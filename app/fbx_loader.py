from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vtkmodules.vtkCommonCore import vtkFloatArray, vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkFiltersCore import vtkPolyDataNormals
from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper


@dataclass(frozen=True)
class FbxLoadResult:
    actors: list[vtkActor]
    warnings: list[str]


class UserFacingError(RuntimeError):
    # a runtime error that is safe to show to the user.
    pass


def _vertices_as_nx3(vertices_obj) -> np.ndarray:
    # return vertices as an nx3 numpy array.
    # handles memoryview/buffer (often flat float32) and list-like forms.
    if vertices_obj is None:
        raise UserFacingError("mesh has no vertices")

    # buffer case: memoryview / bytes / bytearray
    if isinstance(vertices_obj, (memoryview, bytes, bytearray)):
        mv = memoryview(vertices_obj)
        dtype = np.float32 if mv.itemsize == 4 else np.float64
        arr = np.frombuffer(mv, dtype=dtype)
        if arr.size % 3 != 0:
            raise UserFacingError(f"vertex buffer length {arr.size} not divisible by 3")
        return arr.reshape((-1, 3))

    # general case
    arr = np.asarray(vertices_obj, dtype=np.float32)
    if arr.ndim == 1:
        if arr.size % 3 != 0:
            raise UserFacingError(f"vertex array length {arr.size} not divisible by 3")
        return arr.reshape((-1, 3))
    if arr.ndim == 2 and arr.shape[1] == 3:
        return arr

    raise UserFacingError(f"unexpected vertices shape: {arr.shape}")


def _indices_from_buffer(buf) -> np.ndarray:
    # convert a buffer-ish object (memoryview/bytes/bytearray) into a 1d numpy int array.
    # we guess dtype from itemsize (commonly uint32).
    mv = memoryview(buf)
    if mv.itemsize == 4:
        dtype = np.uint32
    elif mv.itemsize == 8:
        dtype = np.uint64
    else:
        dtype = np.uint32
        mv = mv.cast("B")
    arr = np.frombuffer(mv, dtype=dtype)
    return arr.astype(np.int64, copy=False)


def _faces_to_triangles(faces_obj) -> np.ndarray:
    # return an (n, 3) array of triangle indices.
    # supports:
    #   - faces_obj as list/tuple of sequences (each face can be 3+ indices)
    #   - faces_obj as flat list/1d array of ints (assumed triangles)
    #   - faces_obj as memoryview/bytes/bytearray (flat index buffer; assumed triangles)
    #   - faces_obj as list of memoryviews (each memoryview = indices for a face)
    if faces_obj is None:
        return np.empty((0, 3), dtype=np.int64)

    # buffer case: flat index buffer
    if isinstance(faces_obj, (memoryview, bytes, bytearray)):
        idx = _indices_from_buffer(faces_obj)
        if idx.size < 3:
            return np.empty((0, 3), dtype=np.int64)
        if idx.size % 3 != 0:
            return np.empty((0, 3), dtype=np.int64)
        return idx.reshape((-1, 3))

    # numpy array
    if isinstance(faces_obj, np.ndarray):
        arr = faces_obj
        if arr.ndim == 1:
            if arr.size % 3 != 0:
                return np.empty((0, 3), dtype=np.int64)
            return arr.astype(np.int64, copy=False).reshape((-1, 3))
        if arr.ndim == 2 and arr.shape[1] >= 3:
            tris: list[list[int]] = []
            for row in arr:
                f = [int(x) for x in row if int(x) >= 0]
                if len(f) < 3:
                    continue
                i0 = f[0]
                for i in range(1, len(f) - 1):
                    tris.append([i0, f[i], f[i + 1]])
            return np.asarray(tris, dtype=np.int64) if tris else np.empty((0, 3), dtype=np.int64)

    # list/tuple cases
    if isinstance(faces_obj, (list, tuple)):
        if len(faces_obj) == 0:
            return np.empty((0, 3), dtype=np.int64)

        first = faces_obj[0]

        # list of memoryviews (each face indices in a buffer)
        if isinstance(first, (memoryview, bytes, bytearray)):
            tris: list[list[int]] = []
            for fb in faces_obj:
                idx = _indices_from_buffer(fb)
                f = [int(x) for x in idx.tolist()]
                if len(f) < 3:
                    continue
                i0 = f[0]
                for i in range(1, len(f) - 1):
                    tris.append([i0, f[i], f[i + 1]])
            return np.asarray(tris, dtype=np.int64) if tris else np.empty((0, 3), dtype=np.int64)

        # flat list of ints (assume triangles)
        if isinstance(first, (int, np.integer)):
            arr = np.asarray(faces_obj, dtype=np.int64)
            if arr.size % 3 != 0:
                return np.empty((0, 3), dtype=np.int64)
            return arr.reshape((-1, 3))

        # list of sequences (faces)
        tris2: list[list[int]] = []
        for f in faces_obj:
            try:
                f_list = [int(x) for x in f]
            except Exception:
                continue
            if len(f_list) < 3:
                continue
            i0 = f_list[0]
            for i in range(1, len(f_list) - 1):
                tris2.append([i0, f_list[i], f_list[i + 1]])
        return np.asarray(tris2, dtype=np.int64) if tris2 else np.empty((0, 3), dtype=np.int64)

    return np.empty((0, 3), dtype=np.int64)


def _assimp_import(assimp_mod, file_path: str, flags: int):
    # assimp-py api changed names across versions: import_file vs ImportFile.
    fn = getattr(assimp_mod, "import_file", None)
    if fn is None:
        fn = getattr(assimp_mod, "ImportFile", None)
    if fn is None:
        raise UserFacingError("assimp-py does not provide import_file/ImportFile")
    return fn(file_path, flags)


def _get_flag(assimp_mod, name: str) -> int:
    try:
        return int(getattr(assimp_mod, name))
    except Exception:
        return 0


def _try_extract_normals(mesh, n_verts: int) -> np.ndarray | None:
    n = getattr(mesh, "normals", None)
    if n is None:
        return None
    try:
        arr = np.asarray(n, dtype=np.float32)
        if arr.ndim == 2 and arr.shape[0] == n_verts and arr.shape[1] >= 3:
            return arr[:, :3]
    except Exception:
        return None
    return None


def _try_extract_tcoords(mesh, n_verts: int) -> np.ndarray | None:
    tcs = getattr(mesh, "texturecoords", None)
    if tcs is None:
        return None
    try:
        if isinstance(tcs, (list, tuple)) and len(tcs) > 0:
            tc0 = tcs[0]
            arr = np.asarray(tc0, dtype=np.float32)
            if arr.ndim == 2 and arr.shape[0] == n_verts and arr.shape[1] >= 2:
                return arr[:, :2]
    except Exception:
        return None
    return None


def _polydata_to_actor(poly: vtkPolyData) -> vtkActor:
    mapper = vtkPolyDataMapper()
    mapper.SetInputData(poly)

    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.SetPickable(True)
    return actor


def load_fbx_assimp_py(file_path: str) -> FbxLoadResult:
    # loads fbx using assimp-py (geometry first, best-effort normals and uvs).
    warnings: list[str] = []

    try:
        import assimp_py  # type: ignore
    except Exception as e:
        raise UserFacingError(
            "fbx loading requires assimp-py in this vtk build. install with: pip install assimp-py. "
            f"import error: {e}"
        ) from e

    flags = (
        _get_flag(assimp_py, "Process_Triangulate") |
        _get_flag(assimp_py, "Process_JoinIdenticalVertices") |
        _get_flag(assimp_py, "Process_GenNormals") |
        _get_flag(assimp_py, "Process_SortByPType")
    )

    try:
        scene = _assimp_import(assimp_py, file_path, flags)
    except Exception as e:
        raise UserFacingError(f"assimp-py failed to import fbx: {e}") from e

    meshes = getattr(scene, "meshes", None)
    if not meshes:
        raise UserFacingError("fbx import produced no meshes (scene.meshes empty)")

    actors: list[vtkActor] = []
    total_tris = 0
    debug_lines: list[str] = []

    for mi, m in enumerate(meshes):
        v_arr = _vertices_as_nx3(getattr(m, "vertices", None))
        n_verts = int(v_arr.shape[0])

        faces_obj = getattr(m, "faces", None)
        tris = _faces_to_triangles(faces_obj)

        if tris.shape[0] == 0:
            alt = getattr(m, "indices", None)
            if alt is not None:
                tris = _faces_to_triangles(alt)

        debug_lines.append(
            f"mesh[{mi}]: verts={n_verts}, tris={int(tris.shape[0])}, faces_type={type(faces_obj).__name__}"
        )

        if tris.shape[0] == 0 or n_verts == 0:
            continue

        pts = vtkPoints()
        pts.SetNumberOfPoints(n_verts)
        for i in range(n_verts):
            x, y, z = v_arr[i, 0], v_arr[i, 1], v_arr[i, 2]
            pts.SetPoint(i, float(x), float(y), float(z))

        polys = vtkCellArray()

        # build polys with index guards
        for row in tris:
            i0, i1, i2 = int(row[0]), int(row[1]), int(row[2])
            if i0 < 0 or i1 < 0 or i2 < 0:
                continue
            if i0 >= n_verts or i1 >= n_verts or i2 >= n_verts:
                continue
            polys.InsertNextCell(3)
            polys.InsertCellPoint(i0)
            polys.InsertCellPoint(i1)
            polys.InsertCellPoint(i2)

        poly = vtkPolyData()
        poly.SetPoints(pts)
        poly.SetPolys(polys)

        if poly.GetNumberOfPolys() == 0:
            continue

        # attach normals if present; otherwise compute
        n_arr = _try_extract_normals(m, n_verts)
        if n_arr is not None:
            n_vtk = vtkFloatArray()
            n_vtk.SetNumberOfComponents(3)
            n_vtk.SetName("Normals")
            for i in range(n_verts):
                n_vtk.InsertNextTuple3(float(n_arr[i, 0]), float(n_arr[i, 1]), float(n_arr[i, 2]))
            poly.GetPointData().SetNormals(n_vtk)
        else:
            normals = vtkPolyDataNormals()
            normals.SetInputData(poly)
            normals.ConsistencyOn()
            normals.AutoOrientNormalsOn()
            normals.SplittingOff()
            normals.ComputePointNormalsOn()
            normals.ComputeCellNormalsOff()
            normals.Update()
            poly = normals.GetOutput()

        # attach tcoords if present
        tc_arr = _try_extract_tcoords(m, n_verts)
        if tc_arr is not None:
            tc_vtk = vtkFloatArray()
            tc_vtk.SetNumberOfComponents(2)
            tc_vtk.SetName("TCoords")
            for i in range(n_verts):
                tc_vtk.InsertNextTuple2(float(tc_arr[i, 0]), float(tc_arr[i, 1]))
            poly.GetPointData().SetTCoords(tc_vtk)

        actors.append(_polydata_to_actor(poly))
        total_tris += int(poly.GetNumberOfPolys())

    if not actors or total_tris == 0:
        dbg = "\n".join(debug_lines) if debug_lines else "(no mesh debug info)"
        raise UserFacingError(
            "fbx import succeeded but did not produce renderable triangles.\n"
            "common causes:\n"
            "  - fbx contains only bones/empties/lines/points (no mesh)\n"
            "  - fbx mesh is nurbs/subdivision and not converted to polygons\n"
            "  - faces/indices are exposed differently by assimp-py\n\n"
            "mesh debug:\n" + dbg
        )

    return FbxLoadResult(actors=actors, warnings=warnings)

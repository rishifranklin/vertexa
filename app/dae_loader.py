from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from vtkmodules.vtkCommonCore import vtkFloatArray, vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper


# note: this loader is a pure-python fallback for .dae (collada) using pycollada.
# it focuses on static triangle meshes and node transforms; advanced collada features are ignored.


@dataclass(frozen=True)
class DaeLoadResult:
    actors: list[vtkActor]
    warnings: list[str]


def _polydata_to_actor(poly: vtkPolyData) -> vtkActor:
    mapper = vtkPolyDataMapper()
    mapper.SetInputData(poly)
    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.SetPickable(True)
    return actor


def _apply_transform_point(p: tuple[float, float, float], m) -> tuple[float, float, float]:
    x, y, z = float(p[0]), float(p[1]), float(p[2])
    tx = m[0, 0] * x + m[0, 1] * y + m[0, 2] * z + m[0, 3]
    ty = m[1, 0] * x + m[1, 1] * y + m[1, 2] * z + m[1, 3]
    tz = m[2, 0] * x + m[2, 1] * y + m[2, 2] * z + m[2, 3]
    tw = m[3, 0] * x + m[3, 1] * y + m[3, 2] * z + m[3, 3]
    if abs(float(tw)) > 1e-12:
        invw = 1.0 / float(tw)
        return (float(tx) * invw, float(ty) * invw, float(tz) * invw)
    return (float(tx), float(ty), float(tz))


def _normal_matrix(m):
    # compute inverse-transpose of the upper-left 3x3 to transform normals
    try:
        import numpy as np  # type: ignore
        a = np.array(m, dtype=float)
        r = a[:3, :3]
        it = np.linalg.inv(r).T
        return it
    except Exception:
        return None


def _apply_transform_normal(n: tuple[float, float, float], it) -> tuple[float, float, float]:
    if it is None:
        return (float(n[0]), float(n[1]), float(n[2]))
    nx, ny, nz = float(n[0]), float(n[1]), float(n[2])
    try:
        import numpy as np  # type: ignore
        v = np.array([nx, ny, nz], dtype=float)
        tv = it.dot(v)
        ln = float(np.linalg.norm(tv))
        if ln > 1e-12:
            tv = tv / ln
        return (float(tv[0]), float(tv[1]), float(tv[2]))
    except Exception:
        return (nx, ny, nz)


def _get_texcoord_indexset(tri, set_index: int):
    # pycollada exposes texcoord_indexset on triangleset in newer versions.
    tci = getattr(tri, "texcoord_indexset", None)
    if tci is None:
        return None
    try:
        if len(tci) > set_index:
            return tci[set_index]
    except Exception:
        return None
    return None


def load_dae_pycollada(file_path: str) -> DaeLoadResult:
    warnings: list[str] = []

    try:
        import collada  # type: ignore
    except Exception as e:
        raise RuntimeError("pycollada is required for dae fallback. install with: pip install pycollada") from e

    mesh = collada.Collada(file_path)

    scene = None
    if getattr(mesh, "scene", None) is not None:
        scene = mesh.scene
    elif getattr(mesh, "scenes", None):
        scene = mesh.scenes[0]

    if scene is None:
        raise RuntimeError("dae file contains no scene")

    actors: list[vtkActor] = []

    geom_objs = list(scene.objects("geometry"))
    if not geom_objs:
        warnings.append("no geometry objects found in dae scene")

    for bg in geom_objs:
        # pycollada binds geometries into the scene as BoundGeometry objects.
        # bound primitives already have their points transformed by the bound matrix.
        prim_iter = None
        if hasattr(bg, "primitives"):
            try:
                prim_iter = bg.primitives()
            except Exception:
                prim_iter = None

        if prim_iter is None:
            # fallback: try raw geometry primitives
            geom = getattr(bg, "geometry", None)
            prim_iter = getattr(geom, "primitives", []) if geom is not None else []

        for prim in prim_iter:
            tri = None
            try:
                if hasattr(prim, "triangleset"):
                    tri = prim.triangleset()
                else:
                    tri = prim
            except Exception:
                tri = None

            if tri is None:
                continue

            verts = getattr(tri, "vertex", None)
            vindex = getattr(tri, "vertex_index", None)
            if verts is None or vindex is None:
                continue

            try:
                ntri = int(vindex.shape[0])
            except Exception:
                continue
            if ntri <= 0:
                continue

            normals = getattr(tri, "normal", None)
            nindex = getattr(tri, "normal_index", None)
            has_norms = normals is not None and nindex is not None

            texcoords0 = None
            tcindex0 = None
            texsets = getattr(tri, "texcoordset", None)
            if texsets is not None:
                try:
                    if len(texsets) > 0:
                        texcoords0 = texsets[0]
                        tcindex0 = _get_texcoord_indexset(tri, 0)
                except Exception:
                    texcoords0 = None
                    tcindex0 = None

            has_tcoords = texcoords0 is not None and tcindex0 is not None

            pts = vtkPoints()
            cells = vtkCellArray()

            normals_arr: Optional[vtkFloatArray] = None
            if has_norms:
                normals_arr = vtkFloatArray()
                normals_arr.SetNumberOfComponents(3)
                normals_arr.SetName("Normals")

            tcoords_arr: Optional[vtkFloatArray] = None
            if has_tcoords:
                tcoords_arr = vtkFloatArray()
                tcoords_arr.SetNumberOfComponents(2)
                tcoords_arr.SetName("TCoords")

            # expanded mesh: each face-vertex becomes a unique point
            for ti in range(ntri):
                ids = []
                for ci in range(3):
                    vid = int(vindex[ti, ci])
                    px, py, pz = float(verts[vid, 0]), float(verts[vid, 1]), float(verts[vid, 2])
                    pid = pts.InsertNextPoint(px, py, pz)
                    ids.append(pid)

                    if normals_arr is not None and has_norms:
                        nid = int(nindex[ti, ci])
                        nx, ny, nz = float(normals[nid, 0]), float(normals[nid, 1]), float(normals[nid, 2])
                        normals_arr.InsertNextTuple3(nx, ny, nz)

                    if tcoords_arr is not None and has_tcoords:
                        tid = int(tcindex0[ti, ci])
                        u, v = float(texcoords0[tid, 0]), float(texcoords0[tid, 1])
                        tcoords_arr.InsertNextTuple2(u, v)

                cells.InsertNextCell(3)
                cells.InsertCellPoint(ids[0])
                cells.InsertCellPoint(ids[1])
                cells.InsertCellPoint(ids[2])

            poly = vtkPolyData()
            poly.SetPoints(pts)
            poly.SetPolys(cells)

            if normals_arr is not None:
                poly.GetPointData().SetNormals(normals_arr)
            if tcoords_arr is not None:
                poly.GetPointData().SetTCoords(tcoords_arr)

            actors.append(_polydata_to_actor(poly))


    if not actors:
        raise RuntimeError("dae import produced no renderable triangles")

    return DaeLoadResult(actors=actors, warnings=warnings)

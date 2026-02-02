from __future__ import annotations

from dataclasses import dataclass

from vtkmodules.vtkCommonDataModel import vtkPolyData
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray
from vtkmodules.vtkFiltersCore import vtkPolyDataNormals
from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper


@dataclass(frozen=True)
class StepLoadResult:
    actors: list[vtkActor]
    warnings: list[str]


def _polydata_to_actor(poly: vtkPolyData) -> vtkActor:
    mapper = vtkPolyDataMapper()
    mapper.SetInputData(poly)

    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.SetPickable(True)
    return actor


def load_step_ocp(file_path: str) -> StepLoadResult:
    # loads .stp/.step using opencascade python bindings (ocp from cadquery-ocp).
    # this is a faceted display mesh, not exact brep rendering.
    warnings: list[str] = []

    try:
        from OCP.Bnd import Bnd_Box  # type: ignore
        from OCP.BRepBndLib import BRepBndLib  # type: ignore
        from OCP.BRepMesh import BRepMesh_IncrementalMesh  # type: ignore
        from OCP.BRep import BRep_Tool  # type: ignore
        from OCP.IFSelect import IFSelect_RetDone  # type: ignore
        from OCP.STEPControl import STEPControl_Reader  # type: ignore
        from OCP.TopAbs import TopAbs_FACE  # type: ignore
        from OCP.TopExp import TopExp_Explorer  # type: ignore
        from OCP.TopoDS import TopoDS  # type: ignore
        from OCP.TopLoc import TopLoc_Location  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "step loading requires opencascade python bindings. "
            "install with: pip install cadquery-ocp. "
            f"details: {e}"
        ) from e

    def _as_face(shape):
        # cadquery-ocp exposes TopoDS.Face_s for downcasting
        try:
            return TopoDS.Face_s(shape)  # type: ignore
        except Exception:
            # older pythonocc style (if present)
            try:
                from OCP.TopoDS import topods  # type: ignore
                return topods.Face(shape)  # type: ignore
            except Exception:
                return shape

    def _triangulation(face, loc):
        # ocp vs pythonocc differences: Triangulation may be Triangulation or Triangulation_s
        try:
            return BRep_Tool.Triangulation(face, loc)  # type: ignore
        except Exception:
            try:
                return BRep_Tool.Triangulation_s(face, loc)  # type: ignore
            except Exception:
                try:
                    return BRep_Tool.Triangulation(face)  # type: ignore
                except Exception:
                    return None

    def _iter_nodes(tri_obj):
        # supports both pythonocc-style Nodes()/Triangles() and ocp-style NbNodes()/Node().
        if hasattr(tri_obj, "Nodes"):
            nodes = tri_obj.Nodes()
            try:
                lo = int(nodes.Lower())
                hi = int(nodes.Upper())
            except Exception:
                lo = 1
                hi = int(getattr(tri_obj, "NbNodes", lambda: 0)())
            for i in range(lo, hi + 1):
                try:
                    yield int(i), nodes.Value(i)
                except Exception:
                    # fallback to Node(i) if Value() is not available
                    if hasattr(tri_obj, "Node"):
                        yield int(i), tri_obj.Node(i)
        elif hasattr(tri_obj, "NbNodes") and hasattr(tri_obj, "Node"):
            n = int(tri_obj.NbNodes())
            for i in range(1, n + 1):
                yield int(i), tri_obj.Node(i)
        else:
            raise RuntimeError("poly triangulation does not expose nodes api")

    def _iter_triangles(tri_obj):
        if hasattr(tri_obj, "Triangles"):
            tris = tri_obj.Triangles()
            try:
                lo = int(tris.Lower())
                hi = int(tris.Upper())
            except Exception:
                lo = 1
                hi = int(getattr(tri_obj, "NbTriangles", lambda: 0)())
            for i in range(lo, hi + 1):
                yield tris.Value(i)
        elif hasattr(tri_obj, "NbTriangles") and hasattr(tri_obj, "Triangle"):
            n = int(tri_obj.NbTriangles())
            for i in range(1, n + 1):
                yield tri_obj.Triangle(i)
        else:
            raise RuntimeError("poly triangulation does not expose triangles api")

    def _triangle_indices(tri_item):
        # returns 3 vertex indices from a Poly_Triangle.
        try:
            a, b, c = tri_item.Get()
            return int(a), int(b), int(c)
        except Exception:
            try:
                return int(tri_item.Value(1)), int(tri_item.Value(2)), int(tri_item.Value(3))
            except Exception:
                # some wrappers expose as tuple-like
                try:
                    t = list(tri_item)
                    return int(t[0]), int(t[1]), int(t[2])
                except Exception as e:
                    raise RuntimeError(f"cannot read triangle indices: {e}") from e



    reader = STEPControl_Reader()
    status = reader.ReadFile(file_path)
    if status != IFSelect_RetDone:
        raise RuntimeError("failed to read step file")

    reader.TransferRoots()
    shape = reader.OneShape()
    if shape is None:
        raise RuntimeError("step file produced no shape")

    # compute a reasonable meshing deflection based on the model size
    bbox = Bnd_Box()
    try:
        try:
            BRepBndLib.Add(shape, bbox)
        except Exception:
            try:
                BRepBndLib.Add_s(shape, bbox)
            except Exception:
                pass
        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
        dx = float(xmax - xmin)
        dy = float(ymax - ymin)
        dz = float(zmax - zmin)
        diag = (dx * dx + dy * dy + dz * dz) ** 0.5
        # target about 500 segments across the diagonal
        deflection = max(diag / 500.0, 1e-4)
    except Exception:
        deflection = 0.1

    try:
        mesh = BRepMesh_IncrementalMesh(shape, deflection)
        mesh.Perform()
    except Exception:
        # some ocp builds use a different signature; try a more explicit one
        try:
            mesh = BRepMesh_IncrementalMesh(shape, deflection, False, 0.5, True)
            mesh.Perform()
        except Exception as e:
            raise RuntimeError(f"failed to triangulate step shape: {e}") from e

    points = vtkPoints()
    polys = vtkCellArray()

    exp = TopExp_Explorer(shape, TopAbs_FACE)
    faces_with_no_mesh = 0
    faces_total = 0

    while exp.More():
        faces_total += 1
        face = _as_face(exp.Current())
        loc = TopLoc_Location()
        tri = _triangulation(face, loc)
        if tri is None:
            faces_with_no_mesh += 1
            exp.Next()
            continue

        trsf = loc.Transformation()
        has_trsf = not loc.IsIdentity()

        # map from occ node index (1-based) to vtk point id
        idx_map: dict[int, int] = {}

        try:
            for ni, p in _iter_nodes(tri):
                if has_trsf:
                    p = p.Transformed(trsf)
                pid = points.InsertNextPoint(float(p.X()), float(p.Y()), float(p.Z()))
                idx_map[int(ni)] = int(pid)
        except Exception:
            faces_with_no_mesh += 1
            exp.Next()
            continue

        try:
            for t in _iter_triangles(tri):
                a, b, c = _triangle_indices(t)

                ia = idx_map.get(int(a))
                ib = idx_map.get(int(b))
                ic = idx_map.get(int(c))
                if ia is None or ib is None or ic is None:
                    continue

                polys.InsertNextCell(3)
                polys.InsertCellPoint(ia)
                polys.InsertCellPoint(ib)
                polys.InsertCellPoint(ic)
        except Exception:
            exp.Next()
            continue

        exp.Next()

    if faces_total > 0 and faces_with_no_mesh == faces_total:
        warnings.append("no facetable faces were produced from step shape")

    poly = vtkPolyData()
    poly.SetPoints(points)
    poly.SetPolys(polys)

    if poly.GetNumberOfPolys() == 0:
        raise RuntimeError("step import produced no renderable triangles")

    # generate normals for decent shading
    normals = vtkPolyDataNormals()
    normals.SetInputData(poly)
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.SplittingOff()
    normals.ComputePointNormalsOn()
    normals.ComputeCellNormalsOff()
    normals.Update()
    poly_out = normals.GetOutput()

    actor = _polydata_to_actor(poly_out)
    return StepLoadResult(actors=[actor], warnings=warnings)

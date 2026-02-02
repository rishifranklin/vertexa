from __future__ import annotations

# this module is optional and only used when pyassimp is installed
# comments and docstrings are kept lower-case as requested

from typing import Any

from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData, vtkTriangle
from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper


def assimp_scene_to_actors(scene: Any) -> list[vtkActor]:
    actors: list[vtkActor] = []
    meshes = getattr(scene, "meshes", [])
    for mesh in meshes:
        poly = _mesh_to_polydata(mesh)
        mapper = vtkPolyDataMapper()
        mapper.SetInputData(poly)

        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.SetPickable(True)
        actors.append(actor)
    return actors


def _mesh_to_polydata(mesh: Any) -> vtkPolyData:
    vertices = getattr(mesh, "vertices", None)
    faces = getattr(mesh, "faces", None)

    if vertices is None or faces is None:
        raise RuntimeError("assimp mesh missing vertices or faces")

    points = vtkPoints()
    for v in vertices:
        points.InsertNextPoint(float(v[0]), float(v[1]), float(v[2]))

    cells = vtkCellArray()
    for f in faces:
        if len(f) < 3:
            continue
        # triangulate n-gons using a simple fan
        for i in range(1, len(f) - 1):
            tri = vtkTriangle()
            tri.GetPointIds().SetId(0, int(f[0]))
            tri.GetPointIds().SetId(1, int(f[i]))
            tri.GetPointIds().SetId(2, int(f[i + 1]))
            cells.InsertNextCell(tri)

    poly = vtkPolyData()
    poly.SetPoints(points)
    poly.SetPolys(cells)
    return poly

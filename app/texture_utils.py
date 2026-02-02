from __future__ import annotations

from typing import Optional

from vtkmodules.vtkRenderingCore import vtkActor, vtkTexture
from vtkmodules.vtkIOImage import vtkImageReader2Factory

try:
    from vtkmodules.vtkFiltersTexture import vtkTextureMapToPlane
except Exception:  # pragma: no cover
    vtkTextureMapToPlane = None  # type: ignore


_texture_cache: dict[int, vtkTexture] = {}


def load_texture(file_path: str) -> vtkTexture:
    # load and cache a vtk texture from an image file.
    key = hash(file_path)
    if key in _texture_cache:
        return _texture_cache[key]

    factory = vtkImageReader2Factory()
    reader = factory.CreateImageReader2(file_path)
    if reader is None:
        raise RuntimeError("vtk image reader could not be created for this file")

    reader.SetFileName(file_path)
    reader.Update()

    tex = vtkTexture()
    tex.SetInputConnection(reader.GetOutputPort())
    tex.InterpolateOn()
    _texture_cache[key] = tex
    return tex


def ensure_texture_coords(actor: vtkActor) -> None:
    # if the mesh has no tcoords, generate planar coords (best effort).
    if vtkTextureMapToPlane is None:
        return

    mapper = actor.GetMapper()
    if mapper is None:
        return

    poly = mapper.GetInput()
    if poly is None:
        return

    pd = poly.GetPointData()
    if pd is None:
        return

    if pd.GetTCoords() is not None:
        return

    plane = vtkTextureMapToPlane()
    plane.SetInputData(poly)
    plane.AutomaticPlaneGenerationOn()
    plane.Update()
    mapper.SetInputConnection(plane.GetOutputPort())

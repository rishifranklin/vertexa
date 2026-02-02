from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from vtkmodules.vtkCommonCore import vtkObject
from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper, vtkRenderer
from vtkmodules.vtkCommonDataModel import vtkPolyData

# note: many vtk io classes are optional depending on vtk build; imports are inside functions


@dataclass(frozen=True)
class LoadResult:
    actors: list[vtkActor]
    warnings: list[str]


def _polydata_to_actor(poly: vtkPolyData) -> vtkActor:
    mapper = vtkPolyDataMapper()
    mapper.SetInputData(poly)

    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.SetPickable(True)
    return actor


def _read_polydata(reader_factory: Callable[[], vtkObject], file_path: str) -> LoadResult:
    reader = reader_factory()
    reader.SetFileName(file_path)
    reader.Update()

    output = getattr(reader, "GetOutput", None)
    if output is None:
        raise RuntimeError("reader does not provide output")

    poly = reader.GetOutput()
    if poly is None:
        raise RuntimeError("reader returned no polydata")

    actor = _polydata_to_actor(poly)
    return LoadResult(actors=[actor], warnings=[])


def load_model_into_renderer(file_path: str, renderer: vtkRenderer, render_window) -> LoadResult:
    ext = Path(file_path).suffix.lower()
    if ext.startswith("."):
        ext = ext[1:]

    if ext in ("stl",):
        from vtkmodules.vtkIOGeometry import vtkSTLReader
        return _read_polydata(vtkSTLReader, file_path)

    if ext in ("obj",):
        from vtkmodules.vtkIOGeometry import vtkOBJReader
        return _read_polydata(vtkOBJReader, file_path)

    if ext in ("ply",):
        from vtkmodules.vtkIOPLY import vtkPLYReader
        return _read_polydata(vtkPLYReader, file_path)

    if ext in ("vtp",):
        from vtkmodules.vtkIOXML import vtkXMLPolyDataReader
        return _read_polydata(vtkXMLPolyDataReader, file_path)

    if ext in ("stp", "step"):
        from .step_loader import load_step_ocp
        r = load_step_ocp(file_path)
        return LoadResult(actors=r.actors, warnings=r.warnings)

    # gltf/glb/dae/fbx are usually imported as scenes (potentially multiple actors)
    if ext in ("gltf", "glb"):
        return _import_scene(file_path, renderer, render_window, importer_type="gltf")

    if ext in ("dae",):
        return _import_scene(file_path, renderer, render_window, importer_type="collada")

    if ext in ("fbx",):
        return _import_scene(file_path, renderer, render_window, importer_type="fbx")

    raise ValueError(f"unsupported file extension: .{ext}")


def _iter_renderers(render_window) -> list[vtkRenderer]:
    renderers = render_window.GetRenderers()
    renderers.InitTraversal()
    out: list[vtkRenderer] = []
    while True:
        r = renderers.GetNextItem()
        if r is None:
            break
        out.append(r)
    return out


def _actor_id(a: vtkActor) -> str:
    # address is stable for the lifetime of the vtk object
    return a.GetAddressAsString("vtkObject")


def _snapshot_actor_ids(render_window) -> set[str]:
    ids: set[str] = set()
    for r in _iter_renderers(render_window):
        actors = r.GetActors()
        actors.InitTraversal()
        while True:
            a = actors.GetNextActor()
            if a is None:
                break
            ids.add(_actor_id(a))
    return ids


def _detach_new_actors(render_window, before_ids: set[str]) -> list[vtkActor]:
    new_actors: list[vtkActor] = []
    for r in _iter_renderers(render_window):
        actors = r.GetActors()
        actors.InitTraversal()
        to_remove: list[vtkActor] = []
        while True:
            a = actors.GetNextActor()
            if a is None:
                break
            if _actor_id(a) not in before_ids:
                to_remove.append(a)

        for a in to_remove:
            r.RemoveActor(a)
            a.SetPickable(True)
            new_actors.append(a)

    return new_actors


def _prune_new_renderers(render_window, before_renderers: set[str], keep_renderer: vtkRenderer) -> None:
    # remove any renderers that were created by importers. keep all renderers that existed before,
    # and always keep the main renderer passed in.
    for r in _iter_renderers(render_window):
        rid = r.GetAddressAsString("vtkObject")
        if r is keep_renderer:
            continue
        if rid not in before_renderers:
            render_window.RemoveRenderer(r)


def _import_scene(file_path: str, renderer: vtkRenderer, render_window, importer_type: str) -> LoadResult:
    warnings: list[str] = []
    before_actor_ids = _snapshot_actor_ids(render_window)
    before_renderers = set(r.GetAddressAsString("vtkObject") for r in _iter_renderers(render_window))

    importer = None

    if importer_type == "gltf":
        try:
            from vtkmodules.vtkIOImport import vtkGLTFImporter
            importer = vtkGLTFImporter()
        except Exception:
            importer = None
            warnings.append("vtkGLTFImporter not available in this vtk build")

    if importer_type == "collada":
        try:
            from vtkmodules.vtkIOImport import vtkCOLLADAImporter
            importer = vtkCOLLADAImporter()
        except Exception:
            importer = None
            warnings.append("vtkCOLLADAImporter not available in this vtk build")

    if importer_type == "fbx":
        # vtk fbx importer is not always shipped with python wheels
        try:
            from vtkmodules.vtkIOImport import vtkFBXImporter
            importer = vtkFBXImporter()
        except Exception:
            importer = None
            warnings.append("vtkFBXImporter not available in this vtk build")

    if importer is not None:
        importer.SetFileName(file_path)
        importer.SetRenderWindow(render_window)
        importer.Update()

        # importers may add actors into a new renderer. we detach all new actors from all renderers,
        # then return them for the scene manager to own and add to the main renderer.
        new_actors = _detach_new_actors(render_window, before_actor_ids)
        _prune_new_renderers(render_window, before_renderers, keep_renderer=renderer)

        if new_actors:
            return LoadResult(actors=new_actors, warnings=warnings)

        warnings.append("import finished but no new actors were detected")

        # if vtk collada importer exists but produced no actors, try the python fallback
        if importer_type == "collada":
            try:
                from .dae_loader import load_dae_pycollada
                r = load_dae_pycollada(file_path)
                return LoadResult(actors=r.actors, warnings=warnings + r.warnings + ["loaded using pycollada fallback"])
            except Exception as e:
                warnings.append(f"pycollada fallback failed: {e}")

        return LoadResult(actors=[], warnings=warnings)

    # for dae, provide a pure python fallback that does not require assimp.dll
    if importer_type == "collada":
        try:
            from .dae_loader import load_dae_pycollada
            r = load_dae_pycollada(file_path)
            return LoadResult(actors=r.actors, warnings=warnings + r.warnings + ["loaded using pycollada fallback"])
        except Exception as e:
            raise RuntimeError(
                "failed to load dae. your vtk build may not include vtkCOLLADAImporter. "
                "pycollada fallback is installed but failed to parse this dae. "
                f"details: {e}"
            ) from e

    # fbx fallback: use assimp-py (no pyassimp) when vtkFBXImporter is not available.
    if importer_type == "fbx":
        try:
            from .fbx_loader import load_fbx_assimp_py
            rr = load_fbx_assimp_py(file_path)
            return LoadResult(actors=rr.actors, warnings=warnings + rr.warnings + ["loaded using assimp-py fallback"])
        except Exception as e:
            raise RuntimeError(
                "failed to load fbx. your vtk build may not include vtkFBXImporter. "
                "install the fallback dependency with: pip install assimp-py, "
                "or convert fbx to glb/gltf/obj. "
                f"details: {e}"
            ) from e

    # optional assimp fallback for other formats not supported by vtk in your build
    # note: pyassimp is a python wrapper; it still requires the native assimp library (dll/so/dylib).
    try:
        import pyassimp  # type: ignore
        from pyassimp.errors import AssimpError  # type: ignore
    except Exception:
        pyassimp = None  # type: ignore
        AssimpError = Exception  # type: ignore

    if pyassimp is not None:
        try:
            from .utils_assimp import assimp_scene_to_actors  # local optional module
            scene = pyassimp.load(file_path)
            actors = assimp_scene_to_actors(scene)
            pyassimp.release(scene)
            return LoadResult(actors=actors, warnings=warnings + ["loaded using assimp fallback"])
        except AssimpError:
            warnings.append("pyassimp is installed but the native assimp library was not found")
            warnings.append("install assimp runtime (assimp.dll) and ensure it is on your system path")
        except Exception as e:
            warnings.append(f"assimp fallback failed: {e}")

    # if we reached here, no importer worked
    raise RuntimeError(
        "no suitable importer available for this file format. "
        "for fbx/gltf, your vtk build must include the corresponding importer. "
        "for dae, install pycollada for the pure python fallback."
    )

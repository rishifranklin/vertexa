# Vertexa (pyqt6 + vtk 3d model viewer)

A fast, clean 3d model viewing application built with **python**, **pyqt6**, and **vtk**.

I have a ton of models in my Blender asset directory and needed a tool to quicly preview the models instead of loading them in Blender each time or using the asset library. So I ended up creating Vertexa, a kinda
asset library browser from disk. It supports common polygon formats (obj/stl/gltf/glb/dae/fbx) and cad step files (stp/step) via a robust fallback pipeline, with a directory tree sidebar, object selection, hide/reveal, and live material editing.

---

## features

### file loading
- load files by **double-clicking** from the right-side directory tree
- supported formats:
  - **obj**
  - **stl**
  - **gltf / glb**
  - **dae** (collada) (via `pycollada` fallback when vtk importer is missing)
  - **fbx** (via `assimp-py` fallback when vtk importer is missing)
  - **step / stp** (via `cadquery-ocp` opencascade triangulation)

### viewport interaction
- rotate / pan / zoom (vtk interactor)
- standard views:
  - front, back, left, right, top, bottom
- fit model to view
- axis widget (orientation indicator)
- clear viewport (remove all objects)
- select and remove an object
- optional: keep previously loaded objects or auto-clear on new load

### selection + context menu
- **left click** an object to select it
- **left click empty space** clears selection
- **right click** opens a context menu:
  - hide the selected object
  - reveal all hidden objects
  - assign a texture (image file) to the selected object

### texturing and materials
- separate **texture editor window** (menu-driven)
- principled bsdf-inspired controls:
  - base color
  - metallic
  - roughness
  - ior
  - alpha
  - emission
  - transmission
  - specular
- updates are applied live to the selected actor
- image textures can be assigned from:
  - the texture editor
  - viewport context menu (assign a texture...)
- if a mesh has no uv coordinates, the app attempts planar uv generation for texturing

### reliability
- graceful error handling with message dialogs
- crash logs are written to a file.

<img width="1531" height="1112" alt="image" src="https://github.com/user-attachments/assets/2e98e925-333a-4e5d-aacd-8eb574ddb272" />

---

## requirements

### python
- python 3.11+ recommended

### dependencies
core:
- pyqt6
- vtk
- numpy

format support:
- `assimp-py` (fbx fallback)
- `pycollada` (dae fallback)
- `cadquery-ocp` (step/stp via opencascade triangulation)

example `requirements.txt`:

```txt
pyqt6>=6.5
vtk>=9.2
numpy>=1.23
assimp-py>=1.1.0
pycollada>=0.9.3
cadquery-ocp>=7.7

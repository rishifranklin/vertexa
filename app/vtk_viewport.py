from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QMessageBox, QMenu, QFileDialog

from .texture_utils import load_texture, ensure_texture_coords

from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from vtkmodules.vtkRenderingCore import vtkRenderer, vtkPropPicker
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkRenderingAnnotation import vtkAxesActor
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget

from .scene_manager import SceneManager
from .file_loaders import load_model_into_renderer


class VTKViewport(QVTKRenderWindowInteractor):
    selection_changed = pyqtSignal(object)

    status_message = pyqtSignal(str)

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self._logger = logger

        self._renderer = vtkRenderer()
        self.GetRenderWindow().AddRenderer(self._renderer)

        self._picker = vtkPropPicker()
        self._scene = SceneManager(self._renderer)

        self._clear_on_load = True

        self._press_button = None
        self._press_pos = None
        self._press_moved = False

        # set an explicit interactor style so rotate/pan/zoom always works.
        self._iren = self.GetRenderWindow().GetInteractor()
        self._iren.SetInteractorStyle(vtkInteractorStyleTrackballCamera())

        self._configure_default_camera()
        self._setup_orientation_axes()

        # initialize the interactor after configuring style and markers.
        self.Initialize()

        self._render()

    def set_clear_on_load(self, enabled: bool) -> None:
        self._clear_on_load = enabled

    def clear_on_load(self) -> bool:
        return self._clear_on_load

    def scene(self) -> SceneManager:
        return self._scene

    def load_file(self, file_path: str) -> None:
        try:
            if self._clear_on_load:
                self._scene.clear_all()

            result = load_model_into_renderer(file_path, self._renderer, self.GetRenderWindow())
            self._scene.add_actors(result.actors)
            self.fit_to_view()

            if result.warnings:
                for w in result.warnings:
                    self.status_message.emit(f"warning: {w}")

            self.status_message.emit(f"loaded: {Path(file_path).name}")
            self._render()
        except Exception as e:
            if self._logger is not None:
                self._logger.exception("failed to load file: %s", file_path)
            QMessageBox.critical(self, "load error", f"failed to load file:\n{file_path}\n\n{e}")
            self.status_message.emit("load failed")

    def clear_viewport(self) -> None:
        self._scene.clear_all()
        self._render()
        self.status_message.emit("viewport cleared")

    def remove_selected(self) -> None:
        a = self._scene.selected_actor()
        if a is None:
            self.status_message.emit("no selection")
            return
        self._scene.remove_actor(a)
        self._render()
        self.status_message.emit("removed selected object")

    def fit_to_view(self) -> None:
        if not self._scene.actors():
            self._renderer.ResetCamera()
            self._render()
            return

        self._renderer.ResetCamera()
        cam = self._renderer.GetActiveCamera()
        cam.Dolly(1.2)
        self._renderer.ResetCameraClippingRange()
        self._render()
        self.status_message.emit("Fit to view")

    def set_standard_view(self, view_name: str) -> None:
        cam = self._renderer.GetActiveCamera()

        # these are conventional camera setups; they assume y is up in the scene.
        if view_name == "front":
            cam.SetPosition(0.0, -1.0, 0.0)
            cam.SetViewUp(0.0, 0.0, 1.0)
        elif view_name == "back":
            cam.SetPosition(0.0, 1.0, 0.0)
            cam.SetViewUp(0.0, 0.0, 1.0)
        elif view_name == "left":
            cam.SetPosition(-1.0, 0.0, 0.0)
            cam.SetViewUp(0.0, 0.0, 1.0)
        elif view_name == "right":
            cam.SetPosition(1.0, 0.0, 0.0)
            cam.SetViewUp(0.0, 0.0, 1.0)
        elif view_name == "top":
            cam.SetPosition(0.0, 0.0, 1.0)
            cam.SetViewUp(0.0, 1.0, 0.0)
        elif view_name == "bottom":
            cam.SetPosition(0.0, 0.0, -1.0)
            cam.SetViewUp(0.0, 1.0, 0.0)
        else:
            return

        cam.SetFocalPoint(0.0, 0.0, 0.0)
        self._renderer.ResetCamera()
        self._renderer.ResetCameraClippingRange()
        self._render()
        self.status_message.emit(f"view: {view_name}")


    def mousePressEvent(self, ev: QMouseEvent) -> None:
        # track press so we can distinguish click selection from drag interaction.
        if ev.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._press_button = ev.button()
            self._press_pos = ev.position()
            self._press_moved = False

        # do not forward right-click to vtk; it is reserved for our context menu.
        if ev.button() == Qt.MouseButton.RightButton:
            ev.accept()
            return

        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:
        if self._press_pos is not None and not self._press_moved:
            d = ev.position() - self._press_pos
            if abs(d.x()) + abs(d.y()) > 4.0:
                self._press_moved = True

        # do not forward right-drag to vtk
        if self._press_button == Qt.MouseButton.RightButton:
            ev.accept()
            return

        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        try:
            is_click = (self._press_button == ev.button() and self._press_pos is not None and not self._press_moved)

            # always forward left button release to vtk so the interactor state is consistent.
            if ev.button() == Qt.MouseButton.LeftButton:
                super().mouseReleaseEvent(ev)

            if is_click and ev.button() == Qt.MouseButton.LeftButton:
                self._pick_actor(ev.position().x(), ev.position().y(), source="left click")
                ev.accept()
                return

            if is_click and ev.button() == Qt.MouseButton.RightButton:
                actor = self._pick_actor(ev.position().x(), ev.position().y(), source="right click", return_actor=True)
                self._show_context_menu(actor, ev.globalPosition().toPoint())
                ev.accept()
                return

        finally:
            self._press_button = None
            self._press_pos = None
            self._press_moved = False

        super().mouseReleaseEvent(ev)


    def _show_context_menu(self, actor_obj, global_pos) -> None:
        # show a context menu for the actor under the cursor.
        parent = self.window() if self.window() is not None else self
        menu = QMenu(parent)

        act_hide = menu.addAction("hide the selected object")
        act_hide.setEnabled(actor_obj is not None)

        act_reveal = menu.addAction("reveal all hidden objects")
        act_reveal.setEnabled(self._scene.hidden_count() > 0)

        act_assign = menu.addAction("assign a texture...")
        act_assign.setEnabled(actor_obj is not None)

        chosen = menu.exec(global_pos)
        if chosen is None:
            return

        if chosen == act_hide:
            if self._scene.hide_selected():
                self.status_message.emit("object hidden")
            else:
                self.status_message.emit("no selection")
            self._render()
            return

        if chosen == act_reveal:
            n = self._scene.reveal_all_hidden()
            self.status_message.emit(f"revealed {n} object(s)")
            self._render()
            return

        if chosen == act_assign:
            self._assign_texture_dialog()
            return

    def _assign_texture_dialog(self) -> None:
        a = self._scene.selected_actor()
        if a is None:
            self.status_message.emit("no selection")
            return

        parent = self.window() if self.window() is not None else self
        file_path, _ = QFileDialog.getOpenFileName(
            parent,
            "select texture",
            "",
            "images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
        )
        if not file_path:
            return

        try:
            tex = load_texture(file_path)
            ensure_texture_coords(a)
            a.SetTexture(tex)
            self.status_message.emit("texture assigned")
            self._render()
        except Exception as e:
            if self._logger is not None:
                self._logger.exception("texture assign failed")
            parent = self.window() if self.window() is not None else self
            QMessageBox.critical(parent, "texture error", f"failed to assign texture:\n{file_path}\n\n{e}")
            self.status_message.emit("texture assign failed")


    def _pick_actor(self, x: float, y: float, source: str = "", return_actor: bool = False):
        # pick an actor at viewport coords. x/y are qt widget coords.
        try:
            self._picker.Pick(int(x), int(self.height() - y), 0, self._renderer)
            actor = self._picker.GetActor()

            if actor is None:
                self._scene.select_actor(None)
                self.status_message.emit("selection cleared")
                self.selection_changed.emit(None)
            else:
                self._scene.select_actor(actor)
                self.status_message.emit(f"object selected ({source})" if source else "object selected")
                self.selection_changed.emit(actor)

            self._render()

            if return_actor:
                return actor
            return None
        except Exception:
            if self._logger is not None:
                self._logger.exception("pick failed")
            self.status_message.emit("pick failed")
            if return_actor:
                return None
            return None

    def _configure_default_camera(self) -> None:
        self._renderer.SetBackground(0.07, 0.07, 0.09)
        self._renderer.ResetCamera()

    def _setup_orientation_axes(self) -> None:
        # show axis marker in the bottom-left corner
        axes = vtkAxesActor()

        self._axes_widget = vtkOrientationMarkerWidget()
        self._axes_widget.SetOrientationMarker(axes)
        self._axes_widget.SetInteractor(self._iren)
        self._axes_widget.SetViewport(0.0, 0.0, 0.22, 0.22)
        self._axes_widget.SetEnabled(1)
        self._axes_widget.InteractiveOff()

    def _render(self) -> None:
        self.GetRenderWindow().Render()

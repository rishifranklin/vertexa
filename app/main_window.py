from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QColor
from PyQt6.QtWidgets import (
    QMainWindow,
    QDockWidget,
    QMessageBox,
    QFileDialog,
    QColorDialog,
)

from .vtk_viewport import VTKViewport
from .directory_sidebar import DirectorySidebar
from .settings import AppSettings
from .texture_editor import TextureEditorDialog


@dataclass
class LightConfig:
    key: tuple[float, float, float] = (1.0, 0.95, 0.9)
    fill: tuple[float, float, float] = (0.9, 0.95, 1.0)
    back: tuple[float, float, float] = (0.95, 0.9, 1.0)


class MainWindow(QMainWindow):
    def __init__(self, logger=None):
        super().__init__()
        self._logger = logger
        self._settings = AppSettings()

        self.setWindowTitle("Vertexa v1.2")
        self.resize(1920, 1080)

        self._viewport = VTKViewport(self, logger=self._logger)
        self._viewport.status_message.connect(self.statusBar().showMessage)
        self._viewport.selection_changed.connect(self._on_selection_changed)

        self._texture_editor: TextureEditorDialog | None = None

        self.setCentralWidget(self._viewport)

        self._sidebar = DirectorySidebar(self)
        self._sidebar.file_activated.connect(self._on_file_activated)
        self._sidebar.directory_changed.connect(self._on_dir_changed)

        self._dock = QDockWidget("Browser", self)
        self._dock.setWidget(self._sidebar)
        self._dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock)

        self._init_actions()
        self._init_menus()
        self._init_toolbar()

        self._restore_settings()

    def closeEvent(self, event) -> None:
        # save state on close
        try:
            self._settings.set_clear_on_load(self._viewport.clear_on_load())
            self._settings.set_three_point_lighting(self._act_three_point.isChecked())
        except Exception:
            if self._logger is not None:
                self._logger.exception("failed to persist settings")
        super().closeEvent(event)

    def _restore_settings(self) -> None:
        last_dir = self._settings.get_last_dir()
        self._sidebar.set_focus_path(last_dir)

        clear_on_load = self._settings.get_clear_on_load()
        self._act_clear_on_load.setChecked(clear_on_load)
        self._viewport.set_clear_on_load(clear_on_load)

        self._light_cfg = LightConfig(
            key=self._settings.get_light_color("key", (1.0, 0.95, 0.9)),
            fill=self._settings.get_light_color("fill", (0.9, 0.95, 1.0)),
            back=self._settings.get_light_color("back", (0.95, 0.9, 1.0)),
        )

        three_point = self._settings.get_three_point_lighting()
        self._act_three_point.setChecked(three_point)
        self._viewport.scene().enable_three_point_lighting(three_point)
        self._viewport.scene().set_three_point_colors(self._light_cfg.key, self._light_cfg.fill, self._light_cfg.back)
        self._viewport.GetRenderWindow().Render()

    def _init_actions(self) -> None:
        self._act_open = QAction("Open File", self)
        self._act_open.setShortcut(QKeySequence.StandardKey.Open)
        self._act_open.triggered.connect(self._open_file_dialog)

        self._act_fit = QAction("Fit", self)
        self._act_fit.setShortcut("f")
        self._act_fit.triggered.connect(self._viewport.fit_to_view)

        self._act_clear = QAction("Clear", self)
        self._act_clear.setShortcut(QKeySequence("ctrl+l"))
        self._act_clear.triggered.connect(self._viewport.clear_viewport)

        self._act_remove_selected = QAction("Remove Selected", self)
        self._act_remove_selected.setShortcut(QKeySequence("delete"))
        self._act_remove_selected.triggered.connect(self._viewport.remove_selected)

        self._act_clear_on_load = QAction("Clear previous on load", self)
        self._act_clear_on_load.setCheckable(True)
        self._act_clear_on_load.toggled.connect(self._viewport.set_clear_on_load)

        # standard views
        self._act_view_front = QAction("Front", self)
        self._act_view_front.triggered.connect(lambda: self._viewport.set_standard_view("front"))

        self._act_view_back = QAction("Back", self)
        self._act_view_back.triggered.connect(lambda: self._viewport.set_standard_view("back"))

        self._act_view_left = QAction("Left", self)
        self._act_view_left.triggered.connect(lambda: self._viewport.set_standard_view("left"))

        self._act_view_right = QAction("Right", self)
        self._act_view_right.triggered.connect(lambda: self._viewport.set_standard_view("right"))

        self._act_view_top = QAction("Top", self)
        self._act_view_top.triggered.connect(lambda: self._viewport.set_standard_view("top"))

        self._act_view_bottom = QAction("Bottom", self)
        self._act_view_bottom.triggered.connect(lambda: self._viewport.set_standard_view("bottom"))

        # lighting
        self._act_three_point = QAction("Enable 3 Point Lighting", self)
        self._act_three_point.setCheckable(True)
        self._act_three_point.toggled.connect(self._toggle_three_point)

        self._act_key_color = QAction("Set key light color", self)
        self._act_key_color.triggered.connect(lambda: self._pick_light_color("key"))

        self._act_fill_color = QAction("Set fill light color", self)
        self._act_fill_color.triggered.connect(lambda: self._pick_light_color("fill"))

        self._act_back_color = QAction("Set back light color", self)
        self._act_back_color.triggered.connect(lambda: self._pick_light_color("back"))

        # material / texture editor
        self._act_texture_editor = QAction("Texture editor", self)
        self._act_texture_editor.triggered.connect(self._open_texture_editor)

        self._act_about = QAction("About", self)
        self._act_about.triggered.connect(self._show_about)

        self._act_exit = QAction("Exit", self)
        self._act_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self._act_exit.triggered.connect(self.close)

    def _init_menus(self) -> None:
        m_file = self.menuBar().addMenu("File")
        m_file.addAction(self._act_open)
        m_file.addSeparator()
        m_file.addAction(self._act_exit)

        m_view = self.menuBar().addMenu("View")
        m_view.addAction(self._act_fit)
        m_view.addAction(self._act_clear)
        m_view.addSeparator()
        m_view.addAction(self._act_clear_on_load)

        m_cam = self.menuBar().addMenu("Camera")
        m_cam.addAction(self._act_view_front)
        m_cam.addAction(self._act_view_back)
        m_cam.addAction(self._act_view_left)
        m_cam.addAction(self._act_view_right)
        m_cam.addAction(self._act_view_top)
        m_cam.addAction(self._act_view_bottom)

        m_scene = self.menuBar().addMenu("Scene")
        m_scene.addAction(self._act_remove_selected)

        m_mat = self.menuBar().addMenu("Material")
        m_mat.addAction(self._act_texture_editor)

        m_light = self.menuBar().addMenu("Lighting")
        m_light.addAction(self._act_three_point)
        m_light.addSeparator()
        m_light.addAction(self._act_key_color)
        m_light.addAction(self._act_fill_color)
        m_light.addAction(self._act_back_color)

        m_help = self.menuBar().addMenu("Help")
        m_help.addAction(self._act_about)

    def _init_toolbar(self) -> None:
        tb = self.addToolBar("Tools")
        tb.setMovable(False)
        tb.addAction(self._act_open)
        tb.addSeparator()
        tb.addAction(self._act_fit)
        tb.addAction(self._act_clear)
        tb.addAction(self._act_remove_selected)
        tb.addAction(self._act_texture_editor)
        tb.addSeparator()
        tb.addAction(self._act_clear_on_load)
        tb.addSeparator()
        tb.addAction(self._act_view_front)
        tb.addAction(self._act_view_top)
        tb.addAction(self._act_view_left)
        tb.addAction(self._act_view_right)
        tb.addAction(self._act_view_bottom)

    def _on_file_activated(self, file_path: str) -> None:
        self._viewport.load_file(file_path)

    def _on_dir_changed(self, dir_path: str) -> None:
        try:
            self._settings.set_last_dir(dir_path)
        except Exception:
            if self._logger is not None:
                self._logger.exception("Failed to persist last_dir")

    def _open_file_dialog(self) -> None:
        filters = "3d models (*.stl *.obj *.ply *.vtp *.gltf *.glb *.dae *.fbx *.stp);;all files (*.*)"
        file_path, _ = QFileDialog.getOpenFileName(self, "Open 3d model", self._settings.get_last_dir(), filters)
        if not file_path:
            return
        self._settings.set_last_dir(str(Path(file_path).parent))
        self._sidebar.set_focus_path(str(Path(file_path).parent))
        self._viewport.load_file(file_path)

    def _toggle_three_point(self, enabled: bool) -> None:
        self._viewport.scene().enable_three_point_lighting(enabled)
        self._viewport.scene().set_three_point_colors(self._light_cfg.key, self._light_cfg.fill, self._light_cfg.back)
        self._viewport.GetRenderWindow().Render()

    def _pick_light_color(self, which: str) -> None:
        # allow user to pick a light color; store and apply immediately
        current = getattr(self._light_cfg, which)
        qc = QColor.fromRgbF(current[0], current[1], current[2])
        picked = QColorDialog.getColor(qc, self, f"Choose {which} light color")
        if not picked.isValid():
            return
        rgb = (picked.redF(), picked.greenF(), picked.blueF())
        setattr(self._light_cfg, which, rgb)
        self._viewport.scene().set_three_point_colors(self._light_cfg.key, self._light_cfg.fill, self._light_cfg.back)
        self._viewport.GetRenderWindow().Render()
        try:
            self._settings.set_light_color(which, rgb)
        except Exception:
            if self._logger is not None:
                self._logger.exception("Failed to persist light color")

    def _open_texture_editor(self) -> None:
        # open a modeless texture editor that applies material to the current selection.
        if self._texture_editor is None:
            self._texture_editor = TextureEditorDialog(
                get_target_actor=lambda: self._viewport.scene().selected_actor(),
                request_render=lambda: self._viewport.GetRenderWindow().Render(),
                logger=self._logger,
                parent=self,
            )
        self._texture_editor.refresh_from_selection()
        self._texture_editor.show()
        self._texture_editor.raise_()
        self._texture_editor.activateWindow()

    def _on_selection_changed(self, _actor_obj) -> None:
        # keep the texture editor in sync with viewport selection.
        if self._texture_editor is None:
            return
        try:
            self._texture_editor.refresh_from_selection()
        except Exception:
            if self._logger is not None:
                self._logger.exception("Texture editor selection sync failed")

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "About",
            "Vertexa\n"
            "Author: Rishi F.\n\n"
            "controls:\n"
            "- left drag: rotate\n"
            "- left click: select\n"
            "- right click: context menu (hide/reveal/texture)\n"
            "- middle: pan\n"
            "- wheel: zoom\n"
            "- right click: select\n",
        )

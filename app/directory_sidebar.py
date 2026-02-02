from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QModelIndex, pyqtSignal, QDir, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTreeView, QLabel

# qfilesystemmodel may live in different modules depending on the wrapper/build.
try:
    from PyQt6.QtWidgets import QFileSystemModel  # type: ignore
except Exception:  # pragma: no cover
    try:
        from PyQt6.QtGui import QFileSystemModel  # type: ignore
    except Exception:  # pragma: no cover
        QFileSystemModel = None  # type: ignore


class DirectorySidebar(QWidget):
    file_activated = pyqtSignal(str)
    directory_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._label = QLabel("Files")
        self._view = QTreeView()

        if QFileSystemModel is None:
            raise ImportError(
                "qfilesystemmodel is not available in this pyqt6 installation. "
                "reinstall pyqt6 and pyqt6-qt6 so their versions match."
            )

        self._model = QFileSystemModel()

        # use an empty root path so the model exposes all drives on windows.
        # this typically results in a "this pc" style root with c:, d:, etc.
        self._model.setRootPath("")
        self._view.setModel(self._model)
        self._view.setRootIndex(self._model.index(""))

        self._view.setHeaderHidden(False)
        self._view.setAnimated(True)
        self._view.setSortingEnabled(True)
        self._view.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        # reduce noise: name, size, type, modified columns remain visible by default.
        # you can hide columns here if desired.
        self._view.resizeColumnToContents(0)

        self._view.doubleClicked.connect(self._on_double_clicked)
        self._view.clicked.connect(self._on_clicked)

        lay = QVBoxLayout()
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        lay.addWidget(self._label)
        lay.addWidget(self._view, 1)
        self.setLayout(lay)

        self._supported_ext = {".stl", ".obj", ".ply", ".vtp", ".gltf", ".glb", ".dae", ".fbx", ".stp"}

    def set_focus_path(self, path: str) -> None:
        p = Path(path)
        if p.is_file():
            p = p.parent

        if not p.exists():
            return

        idx = self._model.index(str(p))
        if not idx.isValid():
            return

        self._expand_to_index(idx)
        self._view.scrollTo(idx)
        self._view.setCurrentIndex(idx)

    def _expand_to_index(self, idx: QModelIndex) -> None:
        # expand parent chain so the target is visible
        current = idx
        chain = []
        while current.isValid():
            chain.append(current)
            current = current.parent()
        for i in reversed(chain):
            self._view.expand(i)

    def _on_double_clicked(self, idx: QModelIndex) -> None:
        if not idx.isValid():
            return
        path = Path(self._model.filePath(idx))
        if path.is_dir():
            self.directory_changed.emit(str(path))
            return
        if path.suffix.lower() in self._supported_ext:
            self.file_activated.emit(str(path))
            self.directory_changed.emit(str(path.parent))

    def _on_clicked(self, idx: QModelIndex) -> None:
        if not idx.isValid():
            return
        path = Path(self._model.filePath(idx))
        if path.is_dir():
            self.directory_changed.emit(str(path))

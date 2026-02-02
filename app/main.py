from __future__ import annotations

import sys

# ensure vtk opengl backend is loaded
import vtkmodules.vtkRenderingOpenGL2  # noqa: f401

from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtWidgets import QApplication

from .crash_logger import init_logging, install_excepthook
from .main_window import MainWindow


def _vtk_qt_default_format() -> QSurfaceFormat:
    # vtk versions differ: some provide a helper defaultformat on qt widgets, some do not.
    # this function tries vtk-provided defaults first, then falls back to a safe opengl format.
    try:
        from vtkmodules.qt.QVTKOpenGLNativeWidget import QVTKOpenGLNativeWidget  # type: ignore
        if hasattr(QVTKOpenGLNativeWidget, "defaultFormat"):
            return QVTKOpenGLNativeWidget.defaultFormat()
    except Exception:
        pass

    try:
        from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor  # type: ignore
        if hasattr(QVTKRenderWindowInteractor, "defaultFormat"):
            return QVTKRenderWindowInteractor.defaultFormat()
    except Exception:
        pass

    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setVersion(3, 2)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    return fmt


def main() -> None:
    logger = init_logging()
    install_excepthook(logger)

    # set a compatible opengl surface format for the vtk qt widget.
    # this avoids a common issue where the viewport stays blank on some systems.
    QSurfaceFormat.setDefaultFormat(_vtk_qt_default_format())

    app = QApplication(sys.argv)
    w = MainWindow(logger=logger)
    w.show()

    try:
        sys.exit(app.exec())
    except Exception:
        logger.exception("qt event loop crashed")
        raise

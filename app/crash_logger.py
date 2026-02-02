from __future__ import annotations

import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def _ensure_logs_dir() -> Path:
    logs_dir = Path(__file__).resolve().parent.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def init_logging() -> logging.Logger:
    logs_dir = _ensure_logs_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"app_{ts}.log"

    logger = logging.getLogger("vtk_model_viewer")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    sh = logging.StreamHandler(stream=sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    logger.handlers.clear()
    logger.addHandler(fh)
    logger.addHandler(sh)

    logger.info("logging initialized")
    logger.info("log file: %s", str(log_path))
    return logger


def install_excepthook(logger: logging.Logger) -> None:
    def _hook(exc_type, exc_value, exc_tb):
        try:
            tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            logger.critical("unhandled exception:\n%s", tb)
        finally:
            sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook

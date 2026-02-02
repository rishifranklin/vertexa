from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from PyQt6.QtCore import QSettings


@dataclass
class AppSettings:
    organization: str = "rika_tools"
    application: str = "vtk_model_viewer"

    def qsettings(self) -> QSettings:
        return QSettings(self.organization, self.application)

    def get_last_dir(self) -> str:
        s = self.qsettings()
        return str(s.value("last_dir", str(Path.home()), type=str))

    def set_last_dir(self, path: str) -> None:
        s = self.qsettings()
        s.setValue("last_dir", path)

    def get_clear_on_load(self) -> bool:
        s = self.qsettings()
        return bool(s.value("clear_on_load", True, type=bool))

    def set_clear_on_load(self, enabled: bool) -> None:
        s = self.qsettings()
        s.setValue("clear_on_load", enabled)

    def get_three_point_lighting(self) -> bool:
        s = self.qsettings()
        return bool(s.value("three_point_lighting", False, type=bool))

    def set_three_point_lighting(self, enabled: bool) -> None:
        s = self.qsettings()
        s.setValue("three_point_lighting", enabled)

    def get_light_color(self, key: str, default_rgb: tuple[float, float, float]) -> tuple[float, float, float]:
        s = self.qsettings()
        raw = s.value(f"light_color/{key}", None)
        if raw is None:
            return default_rgb
        try:
            parts = [float(x) for x in str(raw).split(",")]
            if len(parts) != 3:
                return default_rgb
            return (parts[0], parts[1], parts[2])
        except Exception:
            return default_rgb

    def set_light_color(self, key: str, rgb: tuple[float, float, float]) -> None:
        s = self.qsettings()
        s.setValue(f"light_color/{key}", f"{rgb[0]},{rgb[1]},{rgb[2]}")

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QDoubleSpinBox,
    QSlider,
    QFileDialog,
    QColorDialog,
    QFormLayout,
    QCheckBox,
    QGroupBox,
    QWidget,
)

from vtkmodules.vtkRenderingCore import vtkActor

from .texture_utils import load_texture, ensure_texture_coords


@dataclass
class PrincipledParams:
    base_color: tuple[float, float, float] = (0.8, 0.8, 0.8)
    metallic: float = 0.0
    roughness: float = 0.5
    ior: float = 1.45
    alpha: float = 1.0
    emission_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    emission_strength: float = 0.0
    transmission: float = 0.0
    specular: float = 0.5
    use_pbr: bool = True
    texture_path: str = ""


class FloatSliderRow(QWidget):
    # a slider row that represents a float range using an integer qslider.
    def __init__(self, label: str, minv: float, maxv: float, step: float, initial: float, on_change):
        super().__init__()
        self._minv = float(minv)
        self._maxv = float(maxv)
        self._step = float(step)
        self._on_change = on_change

        steps = int(round((self._maxv - self._minv) / self._step))
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, steps)
        self._slider.setSingleStep(1)

        self._value = QLabel("0.00")
        self._value.setMinimumWidth(52)
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._slider, 1)
        lay.addWidget(self._value, 0)
        self.setLayout(lay)

        # set initial without emitting change
        self._set_value_no_signal(initial)
        self._slider.valueChanged.connect(self._changed)

    def _changed(self, _pos: int) -> None:
        self._value.setText(f"{self.value():.2f}")
        self._on_change()

    def _set_value_no_signal(self, v: float) -> None:
        v = max(self._minv, min(self._maxv, float(v)))
        pos = int(round((v - self._minv) / self._step))
        self._slider.blockSignals(True)
        self._slider.setValue(pos)
        self._slider.blockSignals(False)
        self._value.setText(f"{v:.2f}")

    def set_value(self, v: float) -> None:
        v = max(self._minv, min(self._maxv, float(v)))
        pos = int(round((v - self._minv) / self._step))
        self._slider.setValue(pos)

    def value(self) -> float:
        pos = int(self._slider.value())
        v = self._minv + pos * self._step
        v = max(self._minv, min(self._maxv, v))
        return float(v)


class TextureEditorDialog(QDialog):
    def __init__(
        self,
        get_target_actor: Callable[[], Optional[vtkActor]],
        request_render: Callable[[], None],
        logger=None,
        parent=None,
    ):
        super().__init__(parent)
        self._get_target_actor = get_target_actor
        self._request_render = request_render
        self._logger = logger

        self._params = PrincipledParams()
        self._texture_cache: dict[int, vtkTexture] = {}

        self._ui_ready = False

        self.setWindowTitle("Texture editor")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setModal(False)
        self.resize(440, 560)

        self._status = QLabel("Select an object in the viewport (right click), then edit material.")
        self._status.setWordWrap(True)

        self._btn_texture = QPushButton("Set base color texture")
        self._btn_texture.clicked.connect(self._pick_texture)

        self._btn_clear_texture = QPushButton("Clear texture")
        self._btn_clear_texture.clicked.connect(self._clear_texture)

        self._btn_base_color = QPushButton("Base color")
        self._btn_base_color.clicked.connect(self._pick_base_color)

        self._btn_emission_color = QPushButton("Emission color")
        self._btn_emission_color.clicked.connect(self._pick_emission_color)

        self._use_pbr = QCheckBox("Use PBR shading (if supported)")
        self._use_pbr.setChecked(True)
        self._use_pbr.toggled.connect(self._on_any_change)

        # sliders
        self._metallic = FloatSliderRow("Metallic", 0.0, 1.0, 0.01, 0.0, self._on_any_change)
        self._roughness = FloatSliderRow("Roughness", 0.0, 1.0, 0.01, 0.5, self._on_any_change)
        self._alpha = FloatSliderRow("Alpha", 0.0, 1.0, 0.01, 1.0, self._on_any_change)
        self._transmission = FloatSliderRow("Transmission", 0.0, 1.0, 0.01, 0.0, self._on_any_change)
        self._specular = FloatSliderRow("Specular", 0.0, 1.0, 0.01, 0.5, self._on_any_change)

        self._ior = QDoubleSpinBox()
        self._ior.setRange(1.0, 3.0)
        self._ior.setSingleStep(0.01)
        self._ior.setValue(1.45)
        self._ior.valueChanged.connect(self._on_any_change)

        self._emission_strength = QDoubleSpinBox()
        self._emission_strength.setRange(0.0, 50.0)
        self._emission_strength.setSingleStep(0.1)
        self._emission_strength.setValue(0.0)
        self._emission_strength.valueChanged.connect(self._on_any_change)

        form = QFormLayout()
        form.addRow("Base Color", self._btn_base_color)
        form.addRow("Texture", self._row2(self._btn_texture, self._btn_clear_texture))
        form.addRow("Metallic", self._metallic)
        form.addRow("Roughness", self._roughness)
        form.addRow("IOR", self._ior)
        form.addRow("Alpha (opacity)", self._alpha)
        form.addRow("Specular", self._specular)
        form.addRow("Transmission", self._transmission)
        form.addRow("Emission color", self._btn_emission_color)
        form.addRow("Emission strength", self._emission_strength)

        gb = QGroupBox("Principled BSDF (approx)")
        gb.setLayout(form)

        lay = QVBoxLayout()
        lay.addWidget(self._status)
        lay.addSpacing(8)
        lay.addWidget(self._use_pbr)
        lay.addWidget(gb, 1)
        self.setLayout(lay)

        self._sync_ui_to_params()
        self._ui_ready = True

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def refresh_from_selection(self) -> None:
        a = self._get_target_actor()
        if a is None:
            self.set_status("No selection. left click an object in the viewport to select.")
            return
        aid = a.GetAddressAsString("vtkObject")
        self.set_status(f"Editing selection: {aid}")

    def _row2(self, a: QPushButton, b: QPushButton) -> QWidget:
        cw = QWidget()
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(a, 1)
        lay.addWidget(b, 0)
        cw.setLayout(lay)
        return cw

    def _sync_ui_to_params(self) -> None:
        # set ui without triggering apply during init
        self._use_pbr.blockSignals(True)
        self._use_pbr.setChecked(self._params.use_pbr)
        self._use_pbr.blockSignals(False)

        self._metallic._set_value_no_signal(self._params.metallic)
        self._roughness._set_value_no_signal(self._params.roughness)
        self._alpha._set_value_no_signal(self._params.alpha)
        self._transmission._set_value_no_signal(self._params.transmission)
        self._specular._set_value_no_signal(self._params.specular)

        self._ior.blockSignals(True)
        self._ior.setValue(self._params.ior)
        self._ior.blockSignals(False)

        self._emission_strength.blockSignals(True)
        self._emission_strength.setValue(self._params.emission_strength)
        self._emission_strength.blockSignals(False)

    def _pick_texture(self) -> None:
        fp, _ = QFileDialog.getOpenFileName(
            self,
            "Choose texture image",
            "",
            "images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;all files (*.*)",
        )
        if not fp:
            return
        self._params.texture_path = fp
        self._apply()

    def _clear_texture(self) -> None:
        self._params.texture_path = ""
        self._apply()

    def _pick_base_color(self) -> None:
        c = QColor.fromRgbF(self._params.base_color[0], self._params.base_color[1], self._params.base_color[2])
        picked = QColorDialog.getColor(c, self, "Choose base color")
        if not picked.isValid():
            return
        self._params.base_color = (picked.redF(), picked.greenF(), picked.blueF())
        self._apply()

    def _pick_emission_color(self) -> None:
        c = QColor.fromRgbF(
            self._params.emission_color[0],
            self._params.emission_color[1],
            self._params.emission_color[2],
        )
        picked = QColorDialog.getColor(c, self, "Choose emission color")
        if not picked.isValid():
            return
        self._params.emission_color = (picked.redF(), picked.greenF(), picked.blueF())
        self._apply()

    def _on_any_change(self, *_args) -> None:
        # ignore changes while constructing widgets
        if not self._ui_ready:
            return

        self._params.use_pbr = bool(self._use_pbr.isChecked())
        self._params.metallic = float(self._metallic.value())
        self._params.roughness = float(self._roughness.value())
        self._params.alpha = float(self._alpha.value())
        self._params.transmission = float(self._transmission.value())
        self._params.specular = float(self._specular.value())
        self._params.ior = float(self._ior.value())
        self._params.emission_strength = float(self._emission_strength.value())
        self._apply()

    def _apply(self) -> None:
        a = self._get_target_actor()
        if a is None:
            self.set_status("No selection. left click an object in the viewport to select.")
            return

        try:
            prop = a.GetProperty()

            # enable pbr if available
            if self._params.use_pbr and hasattr(prop, "SetInterpolationToPBR"):
                prop.SetInterpolationToPBR()
            elif hasattr(prop, "SetInterpolationToPhong"):
                prop.SetInterpolationToPhong()

            # base color and alpha
            prop.SetColor(*self._params.base_color)
            prop.SetOpacity(self._params.alpha)

            # specular control
            if hasattr(prop, "SetSpecular"):
                prop.SetSpecular(self._params.specular)

            # pbr parameters if supported
            if hasattr(prop, "SetMetallic"):
                prop.SetMetallic(self._params.metallic)
            else:
                # fallback: fake metallic by raising specular slightly
                if hasattr(prop, "SetSpecular"):
                    prop.SetSpecular(min(1.0, self._params.specular * (0.6 + 0.8 * self._params.metallic)))

            if hasattr(prop, "SetRoughness"):
                prop.SetRoughness(self._params.roughness)
            else:
                # fallback: map roughness to specular power (glossier at low roughness)
                if hasattr(prop, "SetSpecularPower"):
                    power = 5.0 + (1.0 - self._params.roughness) * 95.0
                    prop.SetSpecularPower(power)

            # ior and transmission are not always available in vtkproperty builds
            if hasattr(prop, "SetIOR"):
                prop.SetIOR(self._params.ior)
            elif hasattr(prop, "SetBaseIOR"):
                prop.SetBaseIOR(self._params.ior)

            if hasattr(prop, "SetTransmission"):
                prop.SetTransmission(self._params.transmission)
            else:
                # fallback: approximate transmission via opacity
                if self._params.transmission > 0.0:
                    prop.SetOpacity(max(0.05, self._params.alpha * (1.0 - 0.65 * self._params.transmission)))

            # emission approximation
            if hasattr(prop, "SetEmission"):
                prop.SetEmission(self._params.emission_strength)
                if hasattr(prop, "SetEmissionColor"):
                    prop.SetEmissionColor(*self._params.emission_color)
            else:
                # fallback: use ambient to fake emission
                if hasattr(prop, "SetAmbient"):
                    prop.SetAmbient(min(1.0, self._params.emission_strength / 10.0))
                if hasattr(prop, "SetAmbientColor"):
                    prop.SetAmbientColor(*self._params.emission_color)

            # texture
            if self._params.texture_path:
                tex = load_texture(self._params.texture_path)
                ensure_texture_coords(a)
                a.SetTexture(tex)
            else:
                a.SetTexture(None)

            self._request_render()
            self.refresh_from_selection()
        except Exception as e:
            if self._logger is not None:
                self._logger.exception("Material apply failed")
            self.set_status(f"Material apply failed: {e}")

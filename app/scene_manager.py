from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from vtkmodules.vtkRenderingCore import vtkActor, vtkRenderer, vtkLight
from vtkmodules.vtkCommonDataModel import vtkBoundingBox


@dataclass
class SelectedState:
    actor: vtkActor
    original_edge_visibility: int
    original_edge_color: tuple[float, float, float]
    original_line_width: float


class SceneManager:
    def __init__(self, renderer: vtkRenderer):
        self._renderer = renderer
        self._actors: list[vtkActor] = []
        self._selected: Optional[SelectedState] = None
        self._hidden: set[vtkActor] = set()

        self._three_point_enabled = False
        self._key_light: Optional[vtkLight] = None
        self._fill_light: Optional[vtkLight] = None
        self._back_light: Optional[vtkLight] = None

    def add_actors(self, actors: list[vtkActor]) -> None:
        for a in actors:
            if a is None:
                continue
            self._renderer.AddActor(a)
            self._actors.append(a)

    def remove_actor(self, actor: vtkActor) -> None:
        if actor in self._actors:
            self._renderer.RemoveActor(actor)
            self._actors.remove(actor)
        if actor in self._hidden:
            self._hidden.discard(actor)
        if self._selected is not None and self._selected.actor == actor:
            self.clear_selection()

    def clear_all(self) -> None:
        self.clear_selection()
        for a in list(self._actors):
            self._renderer.RemoveActor(a)
        self._actors.clear()
        self._hidden.clear()

    def actors(self) -> list[vtkActor]:
        return list(self._actors)

    def select_actor(self, actor: Optional[vtkActor]) -> None:
        if actor is None:
            self.clear_selection()
            return

        if self._selected is not None and self._selected.actor == actor:
            return

        self.clear_selection()

        prop = actor.GetProperty()
        state = SelectedState(
            actor=actor,
            original_edge_visibility=int(prop.GetEdgeVisibility()),
            original_edge_color=(float(prop.GetEdgeColor()[0]), float(prop.GetEdgeColor()[1]), float(prop.GetEdgeColor()[2])),
            original_line_width=float(prop.GetLineWidth()),
        )
        self._selected = state

        prop.SetEdgeVisibility(1)
        prop.SetLineWidth(2.0)
        prop.SetEdgeColor(1.0, 1.0, 0.0)

    def clear_selection(self) -> None:
        if self._selected is None:
            return
        prop = self._selected.actor.GetProperty()
        prop.SetEdgeVisibility(self._selected.original_edge_visibility)
        prop.SetEdgeColor(*self._selected.original_edge_color)
        prop.SetLineWidth(self._selected.original_line_width)
        self._selected = None

    def selected_actor(self) -> Optional[vtkActor]:
        if self._selected is None:
            return None
        return self._selected.actor


    def hide_selected(self) -> bool:
        # hide the currently selected actor.
        a = self.selected_actor()
        if a is None:
            return False
        a.SetVisibility(0)
        self._hidden.add(a)
        self.clear_selection()
        return True

    def reveal_all_hidden(self) -> int:
        # reveal all hidden actors.
        if not self._hidden:
            return 0
        for a in list(self._hidden):
            try:
                a.SetVisibility(1)
            except Exception:
                pass
        n = len(self._hidden)
        self._hidden.clear()
        return n

    def hidden_count(self) -> int:
        return len(self._hidden)

    def bounds(self) -> Optional[vtkBoundingBox]:
        if not self._actors:
            return None
        bbox = vtkBoundingBox()
        for a in self._actors:
            b = a.GetBounds()
            if b is None:
                continue
            bbox.AddBounds(b)
        return bbox

    def enable_three_point_lighting(self, enabled: bool) -> None:
        if enabled == self._three_point_enabled:
            return

        self._three_point_enabled = enabled
        if enabled:
            self._create_three_point_lights()
        else:
            self._remove_three_point_lights()

    def set_three_point_colors(
        self,
        key_rgb: tuple[float, float, float],
        fill_rgb: tuple[float, float, float],
        back_rgb: tuple[float, float, float],
    ) -> None:
        if self._key_light is not None:
            self._key_light.SetColor(*key_rgb)
        if self._fill_light is not None:
            self._fill_light.SetColor(*fill_rgb)
        if self._back_light is not None:
            self._back_light.SetColor(*back_rgb)

    def _create_three_point_lights(self) -> None:
        # disable default headlight-style lighting so our setup is visible
        self._renderer.AutomaticLightCreationOff()

        self._key_light = vtkLight()
        self._key_light.SetLightTypeToSceneLight()
        self._key_light.SetPosition(1.5, 1.0, 1.5)
        self._key_light.SetFocalPoint(0.0, 0.0, 0.0)
        self._key_light.SetIntensity(0.9)

        self._fill_light = vtkLight()
        self._fill_light.SetLightTypeToSceneLight()
        self._fill_light.SetPosition(-1.5, 0.8, 1.2)
        self._fill_light.SetFocalPoint(0.0, 0.0, 0.0)
        self._fill_light.SetIntensity(0.5)

        self._back_light = vtkLight()
        self._back_light.SetLightTypeToSceneLight()
        self._back_light.SetPosition(0.0, -1.5, 1.2)
        self._back_light.SetFocalPoint(0.0, 0.0, 0.0)
        self._back_light.SetIntensity(0.4)

        self._renderer.AddLight(self._key_light)
        self._renderer.AddLight(self._fill_light)
        self._renderer.AddLight(self._back_light)

    def _remove_three_point_lights(self) -> None:
        if self._key_light is not None:
            self._renderer.RemoveLight(self._key_light)
        if self._fill_light is not None:
            self._renderer.RemoveLight(self._fill_light)
        if self._back_light is not None:
            self._renderer.RemoveLight(self._back_light)

        self._key_light = None
        self._fill_light = None
        self._back_light = None

        # re-enable default light creation
        self._renderer.AutomaticLightCreationOn()

"""Settings for every project (D40): `FLOWFORGE_HOME/settings.json`. It never holds a secret: only whether the welcome
is done and the map style a new map opens in."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from flowforge.home import flowforge_home

MapStyle = Literal["studio", "boxed", "blueprint", "metro", "soft"]   # the dashboard's map styles (D26)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    welcome_done: bool = False
    map_style: MapStyle | None = None


def _path():
    return flowforge_home() / "settings.json"


def load() -> Settings:
    """The saved settings; the defaults when there are none or the file can't be read."""
    try:
        return Settings.model_validate(json.loads(_path().read_text()))
    except (OSError, ValueError, ValidationError):
        return Settings()


def save(changes: dict[str, Any]) -> Settings:
    """Apply `changes` and write the file. Raises ValueError for a field or value Settings doesn't know."""
    try:
        merged = Settings.model_validate({**load().model_dump(), **changes}, strict=True)
    except ValidationError as e:
        raise ValueError(str(e)) from None
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("settings.json.tmp")
    tmp.write_text(json.dumps(merged.model_dump(), indent=2))
    tmp.replace(path)
    return merged

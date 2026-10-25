"""Masked keys (D43): the coding agent writes `ffkey://NAME` where the app needs a key; plain code fills it with the
saved value as the app starts. Nothing here ever returns a value to a caller other than the process being started."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

MASK = re.compile(r"ffkey://([A-Za-z_][A-Za-z0-9_]*)")


class MissingKeys(Exception):
    """Masks for keys that aren't saved: the run is refused before anything starts."""

    def __init__(self, names: Iterable[str]) -> None:
        self.names = sorted(set(names))
        super().__init__(f"Not saved yet: {', '.join(self.names)}. Add them on the Keys page.")


def mask(name: str) -> str:
    return f"ffkey://{name}"


def masks_in(argv: Iterable[str], env: Mapping[str, str]) -> set[str]:
    """The key names masked in a command and an environment."""
    return {m for text in [*argv, *env.values()] for m in MASK.findall(text)}


def fill(argv: list[str], env: Mapping[str, str], values: Mapping[str, str]) -> tuple[list[str], dict[str, str]]:
    """The command and environment the app starts with: every mask replaced by its value, and every saved key also set
    as an env var of its own name, for code that reads it from the environment. Raises MissingKeys first."""
    missing = masks_in(argv, env) - set(values)
    if missing:
        raise MissingKeys(missing)

    def swap(text: str) -> str:
        return MASK.sub(lambda m: values[m.group(1)], text)

    filled_env = {**{k: swap(v) for k, v in env.items()}, **values}
    return [swap(a) for a in argv], filled_env

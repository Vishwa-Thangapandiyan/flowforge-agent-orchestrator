"""`{{steps.<id>.output[.path]}}` templates inside step params (DECISIONS.md D2)."""

from __future__ import annotations

import re
from typing import Any

TEMPLATE = re.compile(r"\{\{\s*steps\.([A-Za-z_][A-Za-z0-9_]*)\.output((?:\.[A-Za-z0-9_]+)*)\s*\}\}")


class TemplateError(ValueError):
    pass


def referenced_steps(value: Any) -> set[str]:
    """All step ids referenced anywhere inside a (nested) params value."""
    if isinstance(value, str):
        return {m.group(1) for m in TEMPLATE.finditer(value)}
    if isinstance(value, dict):
        return set().union(*(referenced_steps(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(referenced_steps(v) for v in value)) if value else set()
    return set()


def _walk(output: Any, path: str, step_id: str) -> Any:
    cur = output
    for part in filter(None, path.split(".")):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            raise TemplateError(f"steps.{step_id}.output{path}: no '{part}' in output")
    return cur


def resolve(value: Any, outputs: dict[str, Any]) -> Any:
    """Return `value` with every template replaced using completed step outputs.

    A string that is exactly one template gets the raw value (dict/list/number);
    otherwise matches are interpolated with str().
    """
    if isinstance(value, dict):
        return {k: resolve(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, outputs) for v in value]
    if not isinstance(value, str):
        return value

    def lookup(m: re.Match[str]) -> Any:
        step_id, path = m.group(1), m.group(2)
        if step_id not in outputs:
            raise TemplateError(f"steps.{step_id} has no output yet")
        return _walk(outputs[step_id], path, step_id)

    whole = TEMPLATE.fullmatch(value.strip())
    if whole:
        return lookup(whole)
    return TEMPLATE.sub(lambda m: str(lookup(m)), value)

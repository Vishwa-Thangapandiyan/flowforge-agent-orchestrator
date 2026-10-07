"""Connector registry: the `connectors` table, default seeding and connectors.json (D10).

Phase 1 has no write routes. Connectors come from the seeded defaults (nim, fetch) and the
optional FLOWFORGE_HOME/connectors.json, a JSON list of connectors validated by the same
models and upserted at start-up. A bad file stops start-up with a clear message rather
than running with half the connectors.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from flowforge.connectors.models import Connector, parse_connector
from flowforge.connectors.presets import DEFAULT_CONNECTORS, PRESETS
from flowforge.storage import Storage


class ConnectorFileError(ValueError):
    pass


class Registry:
    def __init__(self, storage: Storage):
        self.storage = storage

    def all(self) -> list[Connector]:
        return [parse_connector(json.loads(raw)) for _, raw in self.storage.connector_rows()]

    def get(self, connector_id: str) -> Connector | None:
        return next((c for c in self.all() if c.id == connector_id), None)

    def save(self, connector: Connector) -> None:
        self.storage.put_connector(connector.id, connector.model_dump_json())

    def delete(self, connector_id: str) -> None:
        self.storage.delete_connector(connector_id)

    def ensure_defaults(self) -> None:
        """Seed the default connectors once; later edits to them are kept."""
        existing = {c.id for c in self.all()}
        for connector_id in DEFAULT_CONNECTORS:
            if connector_id not in existing:
                self.save(PRESETS[connector_id])


def _describe(exc: ValidationError) -> str:
    """Field paths and messages only: never echo input values (a pasted key must not be repeated)."""
    return "; ".join(
        f"{'.'.join(map(str, e['loc'])) or 'connector'}: {e['msg']}"
        for e in exc.errors(include_input=False, include_url=False)
    )


def load_connectors_file(path: Path) -> list[Connector]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConnectorFileError(f"{path}: not valid JSON (line {exc.lineno}, column {exc.colno})") from None
    if not isinstance(data, list):
        raise ConnectorFileError(f"{path}: expected a JSON list of connectors")
    connectors: list[Connector] = []
    for i, item in enumerate(data):
        try:
            connectors.append(parse_connector(item))
        except ValidationError as exc:
            raise ConnectorFileError(f"{path}: connector #{i + 1}: {_describe(exc)}") from None
    return connectors


def check_references(connectors: list[Connector]) -> None:
    """Every fallback names an existing connector of the same type (D10)."""
    by_id = {c.id: c for c in connectors}
    for c in connectors:
        if c.fallback is None:
            continue
        target = by_id.get(c.fallback)
        if target is None:
            raise ConnectorFileError(f"connector '{c.id}' falls back to '{c.fallback}', which does not exist")
        if target.type != c.type:
            raise ConnectorFileError(f"connector '{c.id}' ({c.type}) falls back to '{c.fallback}' ({target.type})")

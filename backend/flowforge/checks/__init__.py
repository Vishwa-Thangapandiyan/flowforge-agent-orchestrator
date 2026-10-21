"""Health checks (D24): one harmless check per dependency, with no key and nothing kept but the verdict.

`check(target, root)` is the whole interface: an API gets one GET, an LLM its model list, an MCP server is started
from the repo folder and asked for its tools, and a local program is only looked for. Nothing here reads `.env`.
"""

from __future__ import annotations

from flowforge.checks import probes
from flowforge.checks.models import CheckResult, CheckTarget, Status
from flowforge.checks.probes import check, new_client, starts_process

__all__ = ["CheckResult", "CheckTarget", "Status", "check", "new_client", "probes", "starts_process"]

"""Security findings (D31): what the map's scan found unsafe, from the stored scan, so a re-scan updates it. A scan
stored before D31 never ran the finders, so the folder is read again (plain code, nothing run or sent: D20).

GET /security   {repo, scanned, summary: {high, medium, low}, findings: [...]}
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter

from flowforge.api.scan import repo_path
from flowforge.scan import scan as scan_repo
from flowforge.state import app_state

router = APIRouter()


@router.get("/security")
def security() -> dict[str, Any]:
    s = app_state()
    repo = repo_path(s)
    analysis = s.flows["deps"].analysis() if "deps" in s.flows else None
    scan = (analysis or {}).get("scan")
    if scan and not scan.get("findings_checked") and repo is not None and repo.is_dir():
        scan = scan_repo(repo).model_dump(mode="json")
    findings = scan.get("findings", []) if scan else []
    return {"repo": repo.name if repo else None, "scanned": scan is not None,
            "summary": dict(Counter(f["level"] for f in findings)), "findings": findings}

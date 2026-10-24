"""The Issues page (D37): every security finding with the button it gets. Fix (FlowForge changes the code on a new
branch) or Send to agent (queued for the coding agent's `get_fix_requests`).

GET  /issues                {repo, example, summary: {high, medium, low}, issues: [{...finding, action, state, branch}]}
                            (read from the code each time)
POST /issues/{id}/preview   the change Fix will make, masked, and whether it can be made now
POST /issues/{id}/fix       make it: a new branch, the key saved → {id, branch, commit, file, name}
POST /issues/{id}/send      queue it for the agent → {id, state: "sent"}
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from flowforge.api.keys import from_this_machine, learn_saved_keys
from flowforge.api.scan import repo_path
from flowforge.scan import scan as scan_repo
from flowforge.scan.models import Finding
from flowforge.security.fixes import CantFix, apply_fix, fixable, preview
from flowforge.state import AppState, app_state
from flowforge.storage import Storage, now_iso

router = APIRouter()

FIX_REQUESTS_SETTING = "fix_requests"   # [{repo, id, kind, title, ref, fix, prompt, sent_at}]: what the agent is asked
FIXES_SETTING = "fixes_made"            # [{repo, id, branch, commit, at}]: fixes made on a branch, not yet merged
# Issue ids repeat across repos (kind, path, line), so every entry names its folder and only counts there (Codex review)
EXAMPLE_WHY = "Example data: FlowForge shows the change but makes none. Map your own repo to fix it."


def _load(storage: Storage, key: str, empty: Any) -> Any:
    try:
        return json.loads(storage.setting(key) or "null") or empty
    except ValueError:
        return empty


def _entries(storage: Storage, key: str) -> list[dict[str, Any]]:
    """A list setting's entries that name their folder (older ones didn't, and are dropped)."""
    found = _load(storage, key, [])
    return [e for e in found if isinstance(e, dict) and e.get("repo")] if isinstance(found, list) else []


def fix_requests(storage: Storage, repo: Path | None = None) -> list[dict[str, Any]]:
    """The queue, or only `repo`'s part of it."""
    queue = _entries(storage, FIX_REQUESTS_SETTING)
    return queue if repo is None else [r for r in queue if r["repo"] == str(repo.resolve())]


def _fixes(storage: Storage, repo: Path) -> dict[str, dict[str, Any]]:
    """The fixes made in `repo`, by issue id."""
    return {m["id"]: m for m in _entries(storage, FIXES_SETTING) if m["repo"] == str(repo.resolve())}


def _branch_exists(repo: Path, branch: str) -> bool:
    done = subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo,
                          capture_output=True)
    return done.returncode == 0


def _repo(s: AppState) -> Path:
    repo = repo_path(s)
    if repo is None or not repo.is_dir():
        raise HTTPException(409, "Map a folder first.")
    return repo


def _finding(repo: Path, issue_id: str) -> Finding:
    """The issue as the code is now (read again, so a fix starts from the current file)."""
    found = next((f for f in scan_repo(repo).findings if f.id == issue_id), None)
    if found is None:
        raise HTTPException(404, "That issue isn't in the code any more. Re-scan.")
    return found


@router.get("/issues")
def issues() -> dict[str, Any]:
    s = app_state()
    repo = repo_path(s)
    if repo is None or not repo.is_dir():
        return {"repo": None, "example": s.example, "summary": {}, "issues": []}
    result = scan_repo(repo)   # the code as it is now: a merged fix or an agent's edit shows at once
    sent = {r["id"] for r in fix_requests(s.storage, repo)}
    made = _fixes(s.storage, repo)
    out = []
    for f in result.findings:
        branch = made.get(f.id, {}).get("branch")
        if branch and not _branch_exists(repo, branch):
            branch = None   # the branch was deleted: the issue is open again
        state = "fixed" if branch else "sent" if f.id in sent else "open"
        out.append({**f.model_dump(mode="json"), "action": "fix" if fixable(repo, f) else "agent",
                    "state": state, "branch": branch})
    return {"repo": repo.name, "example": s.example, "summary": dict(Counter(f.level for f in result.findings)),
            "issues": out}


@router.post("/issues/{issue_id}/preview")
def preview_fix(issue_id: str) -> dict[str, Any]:
    s = app_state()
    repo = _repo(s)
    try:
        shown = preview(repo, _finding(repo, issue_id))
    except CantFix as e:
        raise HTTPException(409, str(e)) from None
    if s.example:
        shown.update(can_apply=False, why_not=EXAMPLE_WHY)
    return shown


@router.post("/issues/{issue_id}/fix", dependencies=[Depends(from_this_machine)])
def fix(issue_id: str) -> dict[str, Any]:
    s = app_state()
    repo = _repo(s)
    if s.example:
        raise HTTPException(409, EXAMPLE_WHY)
    made = _fixes(s.storage, repo)
    if made.get(issue_id) and _branch_exists(repo, made[issue_id]["branch"]):
        raise HTTPException(409, f"Already fixed on {made[issue_id]['branch']}: merge that branch.")
    found = _finding(repo, issue_id)
    if not fixable(repo, found):
        raise HTTPException(409, "FlowForge doesn't fix this one itself: send it to your agent.")
    try:
        done = apply_fix(repo, found)
    except CantFix as e:
        raise HTTPException(409, str(e)) from None
    learn_saved_keys(s, repo)
    here = str(repo.resolve())
    kept = [m for m in _entries(s.storage, FIXES_SETTING) if (m["repo"], m.get("id")) != (here, issue_id)]
    kept.append({"repo": here, "id": issue_id, "branch": done["branch"], "commit": done["commit"], "at": now_iso()})
    s.storage.set_setting(FIXES_SETTING, json.dumps(kept))
    return done


@router.post("/issues/{issue_id}/send", dependencies=[Depends(from_this_machine)])
def send(issue_id: str) -> dict[str, Any]:
    s = app_state()
    repo = _repo(s)
    found = _finding(repo, issue_id)
    here = str(repo.resolve())
    queue = [r for r in fix_requests(s.storage) if (r["repo"], r["id"]) != (here, issue_id)]
    queue.append({"repo": here, "id": found.id, "kind": found.kind, "title": found.title, "ref": found.ref,
                  "fix": found.fix, "prompt": found.prompt, "sent_at": now_iso()})
    s.storage.set_setting(FIX_REQUESTS_SETTING, json.dumps(queue))
    return {"id": issue_id, "state": "sent"}

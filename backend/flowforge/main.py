"""FastAPI app. Owner: Person C.

POST /runs                 body: workflow JSON (+ ?policy=)  → {"run_id"}; runs in background
GET  /runs/{run_id}        → RunResult so far
GET  /runs/{run_id}/events → Server-Sent Events stream of executor events
GET  /                     → frontend/index.html
"""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from flowforge.schema import Workflow

load_dotenv()

app = FastAPI(title="FlowForge")


@app.post("/validate")
def validate(workflow: Workflow) -> dict:
    """Schema-level validation only; cycle detection joins once graph.py is implemented."""
    return {"ok": True, "steps": len(workflow.steps)}


@app.post("/runs")
def create_run(workflow: Workflow) -> dict:
    raise HTTPException(501, "executor not implemented yet")

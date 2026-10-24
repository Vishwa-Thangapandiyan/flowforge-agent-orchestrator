"""Where every outside service lives. Keys come from the environment, except one planted mistake."""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent

# LLM: a local model through Ollama's OpenAI-compatible endpoint (free, nothing leaves the machine)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
PLANNER_MODEL = os.getenv("PLANNER_MODEL", "llama3.1:8b")

# HTTP APIs: free and keyless
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
IP_API_URL = "http://ip-api.com/json/"  # PLANTED: the free tier is plain http only, a security finding

USER_AGENT = "flowforge-trip-planner-example/0.1 (+https://github.com/Vishwa-Thangapandiyan/flowforge-agent-orchestrator)"

# PLANTED: a hard-coded key, the kind of mistake the scan must report. It is fake and never works.
GOOGLE_STATIC_MAPS_KEY = "AIzaFAKEFAKEFAKEFAKEFAKE1234"
STATIC_MAP_URL = "https://maps.googleapis.com/maps/api/staticmap"

# MCP servers are listed in .mcp.json; the filesystem server may only touch this folder
TRIPS_DIR = HERE / "trips"

# Only Ollama's cloud models need a key; a local server ignores it. Keep it out of files: `flowforge key add`
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "ollama")

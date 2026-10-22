"""Places and routes: Nominatim (place → coordinates), OSRM (driving route), ip-api (where you are)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from config import IP_API_URL, NOMINATIM_URL, OSRM_URL, USER_AGENT

# Nominatim's usage policy: at most one request a second, with a User-Agent that names the app
_NOMINATIM_GAP_S = 1.1


@dataclass
class Place:
    name: str
    lat: float
    lon: float


async def find_place(client: httpx.AsyncClient, query: str) -> Place:
    response = await client.get(NOMINATIM_URL, params={"q": query, "format": "json", "limit": 1},
                                headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    results = response.json()
    if not results:
        raise LookupError(f"no place called {query!r}")
    first = results[0]
    await asyncio.sleep(_NOMINATIM_GAP_S)
    return Place(first["display_name"].split(",")[0], float(first["lat"]), float(first["lon"]))


async def route(client: httpx.AsyncClient, start: Place, end: Place) -> dict[str, float]:
    """Driving distance (km) and time (minutes) from the public OSRM demo server."""
    coords = f"{start.lon},{start.lat};{end.lon},{end.lat}"
    response = await client.get(f"{OSRM_URL}/{coords}", params={"overview": "false"})
    response.raise_for_status()
    best = response.json()["routes"][0]
    return {"km": round(best["distance"] / 1000, 1), "minutes": round(best["duration"] / 60)}


async def where_am_i(client: httpx.AsyncClient) -> str:
    """Your city from your IP address (ip-api's free tier, plain http)."""
    response = await client.get(IP_API_URL, params={"fields": "status,city,country"})
    response.raise_for_status()
    data = response.json()
    return f"{data['city']}, {data['country']}" if data.get("status") == "success" else "unknown"

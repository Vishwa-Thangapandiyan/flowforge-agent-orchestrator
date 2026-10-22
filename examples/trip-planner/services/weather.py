"""Today's weather from Open-Meteo (free, no key)."""

from __future__ import annotations

from typing import Any

import httpx

from config import OPEN_METEO_URL


async def today(client: httpx.AsyncClient, lat: float, lon: float) -> dict[str, Any]:
    response = await client.get(OPEN_METEO_URL, params={
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 1,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    })
    response.raise_for_status()
    data = response.json()
    daily = data["daily"]
    return {
        "timezone": data["timezone"],
        "max_c": daily["temperature_2m_max"][0],
        "min_c": daily["temperature_2m_min"][0],
        "rain_chance": daily["precipitation_probability_max"][0],
    }

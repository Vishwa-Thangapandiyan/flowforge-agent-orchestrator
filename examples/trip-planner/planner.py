"""Plan a day trip: `python planner.py Mangalore --to "Panambur Beach"`.

Each outside call is tried on its own; a failed one is reported and the plan goes on without it.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from collections.abc import Awaitable
from datetime import date
from urllib.parse import urlencode

import httpx

from config import GOOGLE_STATIC_MAPS_KEY, HERE, STATIC_MAP_URL, TRIPS_DIR
from services import geo, llm, mcp_tools, weather


async def attempt[T](label: str, work: Awaitable[T]) -> T | None:
    """Await `work`; on any failure print why and return None."""
    try:
        result = await work
    except Exception as exc:  # the demo keeps going without this piece
        while isinstance(exc, ExceptionGroup):  # MCP's task groups wrap the real reason
            exc = exc.exceptions[0]
        print(f"  ✗ {label}: {str(exc) or type(exc).__name__}")
        return None
    print(f"  ✓ {label}")
    return result


def packing_list(max_c: float, rain: float) -> str:
    """The local tool, run as a separate program (an argv list, never a shell)."""
    done = subprocess.run([sys.executable, str(HERE / "tools" / "packing_list.py"),
                           "--max-c", str(max_c), "--rain", str(rain)],
                          capture_output=True, text=True, timeout=10, check=True)
    return done.stdout.strip()


def static_map_link(place: geo.Place) -> str:
    query = {"center": f"{place.lat},{place.lon}", "zoom": 13, "size": "600x300", "key": GOOGLE_STATIC_MAPS_KEY}
    return f"{STATIC_MAP_URL}?{urlencode(query)}"


async def plan(city: str, sight: str | None) -> None:
    print(f"Planning a day in {city}…")
    async with httpx.AsyncClient(timeout=20) as client:
        home = await attempt("where you are (ip-api)", geo.where_am_i(client))
        place = await attempt("find the city (Nominatim)", geo.find_place(client, city))
        if place is None:
            print("Can't plan without the city's location.")
            return
        target = None
        if sight:
            target = await attempt("find the sight (Nominatim)", geo.find_place(client, f"{sight}, {city}"))
        trip = await attempt("route to the sight (OSRM)", geo.route(client, place, target)) if target else None
        forecast = await attempt("today's weather (Open-Meteo)", weather.today(client, place.lat, place.lon))

    local_time = None
    if forecast:
        local_time = await attempt("local time (MCP time)", mcp_tools.call(
            "time", "get_current_time", {"timezone": forecast["timezone"]}))
    background = await attempt("about the city (MCP fetch)", mcp_tools.call(
        "fetch", "fetch", {"url": f"https://en.wikipedia.org/wiki/{city.replace(' ', '_')}", "max_length": 1500}))
    rate = await attempt("rupee rate (MCP currency)", mcp_tools.call("currency", "rate", {"to": "USD"}))
    packing = None
    if forecast:
        try:
            packing = packing_list(forecast["max_c"], forecast["rain_chance"])
            print("  ✓ packing list (local tool)")
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"  ✗ packing list (local tool): {exc}")

    facts = [f"City: {place.name}", f"Traveller is in: {home or 'unknown'}"]
    if target and trip:
        facts.append(f"Sight: {target.name}, {trip['km']} km and {trip['minutes']} min by car from the centre")
    if forecast:
        facts.append(f"Weather: {forecast['min_c']}–{forecast['max_c']} °C, {forecast['rain_chance']}% chance of rain")
    if local_time:
        facts.append(f"Local time: {local_time}")
    if rate:
        facts.append(f"Exchange rate: {rate}")
    if background:
        facts.append(f"About the city: {background[:1200]}")
    itinerary = await attempt("write the plan (Ollama)", llm.write_itinerary("\n".join(facts)))

    print()
    print(itinerary or "No plan written: the LLM wasn't reachable. Is Ollama running?")
    if packing:
        print(f"\nPack: {packing}")
    print(f"\nMap: {static_map_link(place)}")
    if itinerary:
        TRIPS_DIR.mkdir(exist_ok=True)
        path = TRIPS_DIR / f"{city.lower().replace(' ', '-')}-{date.today()}.md"
        saved = await attempt("save the plan (MCP files)", mcp_tools.call(
            "files", "write_file", {"path": str(path), "content": itinerary}))
        if saved is not None:
            print(f"Saved to {path.relative_to(HERE)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan a relaxed day trip with free, keyless services.")
    parser.add_argument("city")
    parser.add_argument("--to", dest="sight", help="a sight in the city, for the route")
    args = parser.parse_args()
    asyncio.run(plan(args.city, args.sight))


if __name__ == "__main__":
    main()

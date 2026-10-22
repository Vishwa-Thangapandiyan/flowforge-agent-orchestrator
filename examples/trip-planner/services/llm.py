"""The itinerary writer: a local Ollama model through the OpenAI SDK."""

from __future__ import annotations

from openai import AsyncOpenAI

from config import OLLAMA_BASE_URL, PLANNER_MODEL

SYSTEM = ("You plan one relaxed day trip. Use only the facts given. "
          "Answer in short markdown: a title, then Morning, Afternoon and Evening, two bullets each.")


async def write_itinerary(facts: str) -> str:
    client = AsyncOpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama", timeout=180)  # Ollama ignores the key
    reply = await client.chat.completions.create(
        model=PLANNER_MODEL, temperature=0.3,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": facts}])
    return reply.choices[0].message.content or ""

"""Plain HTTP call via httpx (D9). Owner: Person C.

params: method (default GET), url, headers?, json?, max_chars? (default 20000),
        extract_text? (default: true for HTML responses — strips tags/scripts so an LLM
        step downstream gets the readable text, not markup)
output: {"status": int, "body": str | parsed JSON}

429 / 5xx / timeouts / connection errors → TransientNodeError (honours Retry-After);
other 4xx → NodeError.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

import httpx

from flowforge.nodes.base import Node, NodeError, TransientNodeError, parse_retry_after

USER_AGENT = "FlowForge/0.1 (+https://github.com/Vishwa-Thangapandiyan/flowforge-agent-orchestrator)"


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "template"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre", "table"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self._skipping += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skipping:
            self._skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


class HTTPNode(Node):
    type = "http"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(follow_redirects=True, headers={"User-Agent": USER_AGENT})
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    def cacheable_across_runs(self, params: dict[str, Any]) -> bool:
        return params.get("method", "GET").upper() == "GET"

    async def run(self, params: dict[str, Any]) -> Any:
        if "url" not in params:
            raise NodeError("http step needs params.url")
        method = params.get("method", "GET").upper()
        try:
            response = await self.client.request(
                method, params["url"], headers=params.get("headers"), json=params.get("json")
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientNodeError(f"{type(exc).__name__}: {exc}") from exc

        status = response.status_code
        if status == 429 or status >= 500:
            raise TransientNodeError(
                f"HTTP {status} from {params['url']}", parse_retry_after(response.headers.get("retry-after"))
            )
        if status >= 400:
            raise NodeError(f"HTTP {status} from {params['url']}: {response.text[:200]}")

        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            try:
                return {"status": status, "body": response.json()}
            except ValueError:
                pass
        body = response.text
        if params.get("extract_text", "html" in content_type):
            body = html_to_text(body)
        return {"status": status, "body": body[: params.get("max_chars", 20000)]}

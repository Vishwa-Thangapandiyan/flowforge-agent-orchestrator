"""Plain HTTP call via httpx (D9).

params: method (default GET), url, headers?, json?, max_chars? (default 20000),
        extract_text? (default: true for HTML responses — strips tags/scripts so an LLM
        step downstream gets the readable text, not markup)
output: {"status": int, "body": str | parsed JSON}

With a connector (D10): a relative params.url is joined to the connector's base_url, and
the auth header is built from its secret_ref (bearer / basic / raw). The key is only ever
sent to the base_url's origin: an absolute URL elsewhere is refused, step headers cannot
replace the auth header, and the key is redacted from error messages.

429 / 5xx / timeouts / connection errors → TransientNodeError (honours Retry-After);
other 4xx → NodeError.
"""

from __future__ import annotations

import base64
import re
from html.parser import HTMLParser
from typing import Any

import httpx

from flowforge.connectors.models import HTTPConnector
from flowforge.connectors.secrets import SecretRefError, resolve_secret
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
        self.connector: HTTPConnector | None = None

    @classmethod
    def from_connector(cls, connector: HTTPConnector, client: httpx.AsyncClient | None = None) -> HTTPNode:
        node = cls(client)
        node.connector = connector
        node.connector_id = connector.id
        node.rate_limit_key = connector.id
        node.fallback = connector.fallback
        return node

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

    def _prepare(self, params: dict[str, Any]) -> tuple[str, dict[str, str] | None, list[str]]:
        """(url, headers, secret strings to redact) for this call."""
        url, headers = params["url"], params.get("headers")
        if self.connector is None:
            return url, headers, []
        conn = self.connector.connection
        label = f"http connector '{self.connector.id}'"
        absolute = "://" in url or url.startswith("//")
        if not absolute:
            if not conn.base_url:
                raise NodeError(f"{label}: relative url '{url}' needs a base_url on the connector")
            url = conn.base_url.rstrip("/") + "/" + url.lstrip("/")
        try:
            secret = resolve_secret(self.connector.secret_ref)
        except SecretRefError as exc:
            raise NodeError(f"{label}: {exc}") from exc
        if secret is None:
            return url, headers, []
        if not conn.base_url:
            raise NodeError(f"{label}: a connector with a secret needs base_url, the only place its key is sent")
        base = httpx.URL(conn.base_url)
        target = httpx.URL("https:" + url if url.startswith("//") else url)
        if (target.scheme, target.host, target.port) != (base.scheme, base.host, base.port):
            raise NodeError(f"{label} only sends its key to {base.scheme}://{base.host}; refusing {target.host}")
        header = conn.auth_header or "Authorization"
        scheme = conn.auth_scheme or "bearer"
        value = {"bearer": f"Bearer {secret}",
                 "basic": "Basic " + base64.b64encode(secret.encode()).decode(),
                 "raw": secret}[scheme]
        merged = {k: v for k, v in (headers or {}).items() if k.lower() != header.lower()}
        merged[header] = value
        return url, merged, [secret, value]

    async def run(self, params: dict[str, Any]) -> Any:
        if "url" not in params:
            raise NodeError("http step needs params.url")
        method = params.get("method", "GET").upper()
        url, headers, secrets = self._prepare(params)

        def redact(text: str) -> str:
            for secret in secrets:
                text = text.replace(secret, "[REDACTED]")
            return text

        try:
            response = await self.client.request(method, url, headers=headers, json=params.get("json"))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientNodeError(redact(f"{type(exc).__name__}: {exc}")) from exc

        status = response.status_code
        if status == 429 or status >= 500:
            raise TransientNodeError(
                f"HTTP {status} from {params['url']}", parse_retry_after(response.headers.get("retry-after"))
            )
        if status >= 400:
            # redact before cutting, so a key straddling the cut can't leak its first half
            raise NodeError(f"HTTP {status} from {params['url']}: {redact(response.text)[:200]}")

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

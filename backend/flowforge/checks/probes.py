"""One probe per kind of dependency (D24). Thresholds are FlowForge's defaults, named here so they can be tuned."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import ssl
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

from flowforge.checks.models import CheckResult, CheckTarget, Status
from flowforge.connectors.presets import MODEL_LISTS
from flowforge.scan.urls import host_of, is_local
from flowforge.security.logfilter import REDACTED, Redactor

SLOW_MS = 2000            # an API or LLM slower than this needs a look
HTTP_TIMEOUT_S = 10
CERT_WARN_DAYS = 14
MCP_SLOW_MS = 5000        # an MCP server slower than this to list its tools needs a look
MCP_TIMEOUT_S: float = 30
STDERR_LINES = 3
KNOCK_TIMEOUT_S = 5       # when a request can't connect: how long each address gets to accept a connection
MAX_ADDRESSES = 4
USER_AGENT = "FlowForge health check (one request, no keys)"
_redactor = Redactor()


class _NoCookies(CookieJar):
    """A jar that keeps nothing: a cookie a service sets is never sent back on a later check (D24)."""

    def set_cookie(self, cookie: Any) -> None:
        return None

    def extract_cookies(self, response: Any, request: Any) -> None:
        return None


def new_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """The HTTP client checks share: no cookies kept, no redirects followed, nothing but our User-Agent."""
    return httpx.AsyncClient(transport=transport, cookies=_NoCookies())


def is_remote(command: list[str]) -> bool:
    return bool(command) and command[0].startswith(("http://", "https://"))


def starts_process(target: CheckTarget) -> bool:
    """Checking this one starts a process: a stdio MCP server whose arguments are all known (D24)."""
    command = target.command or []
    return (target.kind == "mcp" and bool(command) and not is_remote(command)
            and not any(REDACTED in part for part in command))


def took(ms: float) -> str:
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.1f} s"


def cert_warning(not_after: str, now: datetime) -> str | None:
    """A certificate's `notAfter` (as `ssl` reports it) turned into a warning when it is close (D24)."""
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), UTC)
    days = (expires - now).days
    if days < 0:
        return "its certificate has expired"
    if days < CERT_WARN_DAYS:
        return f"its certificate expires in {days} day{'s' if days != 1 else ''}"
    return None


def _not_after(response: httpx.Response) -> str | None:
    stream = response.extensions.get("network_stream")
    ssl_object = stream.get_extra_info("ssl_object") if stream is not None else None
    cert = ssl_object.getpeercert() if ssl_object is not None else None
    return cert.get("notAfter") if cert else None


def _result(t: CheckTarget, status: Status, summary: str, **fields: Any) -> CheckResult:
    if fields.get("reason"):
        fields["reason"] = _redactor.redact_text(fields["reason"])[:400]
    return CheckResult(id=t.id, status=status, summary=summary, **fields)


async def lookup(host: str, port: int) -> list[str]:
    """The addresses a name resolves to (DNS). Raises OSError (socket.gaierror) when it doesn't resolve."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


async def knock(ip: str, port: int) -> str:
    """Does this address accept a connection? "open", "refused", "silent" (no answer) or "unreachable"."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), KNOCK_TIMEOUT_S)
    except ConnectionRefusedError:
        return "refused"
    except TimeoutError:
        return "silent"
    except OSError:
        return "unreachable"
    writer.close()
    return "open"


def _addresses(ips: list[str], total: int | None = None) -> str:
    """"Both of its addresses (a, b)", or "2 of its 4 addresses (a, b)" when only some of them are meant."""
    n, total = len(ips), total or len(ips)
    if n < total:
        who = f"{n} of its {total} addresses"
    else:
        who = "Its address" if n == 1 else "Both of its addresses" if n == 2 else f"All {n} of its addresses"
    return f"{who} ({', '.join(ips)})"


async def _why_not(t: CheckTarget, url: str, error: str) -> CheckResult:
    """A request that couldn't connect, explained step by step (D24): does the name resolve, and does each address
    accept, refuse or ignore a connection on the port? Only names, addresses and ports: nothing is sent."""
    parts = urlsplit(url)
    host, port = parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80)
    try:
        ips = (await lookup(host, port))[:MAX_ADDRESSES]
    except OSError as exc:
        why = getattr(exc, "strerror", None) or str(exc)
        return _result(t, "down", "Its name doesn't resolve", reason=f"{host} has no address (DNS): {why}",
                       fix="Check the host name in the code. If it is right, the service may be gone, or this "
                           "computer's DNS is failing.", detail={"network": "dns"})
    knocks = await asyncio.gather(*(knock(ip, port) for ip in ips))
    by = {k: [ip for ip, r in zip(ips, knocks, strict=True) if r == k] for k in set(knocks)}
    if by.get("open"):
        return _result(t, "down", "Its server answers, but the secure connection failed" if parts.scheme == "https"
                       else "Its server answers, but the request failed", reason=error,
                       fix="Often a certificate problem, or a proxy or antivirus between you and the service.",
                       detail={"network": "request"})
    if by.get("refused"):
        others = len(ips) - len(by["refused"])
        tail = f" The other {others} {'is' if others == 1 else 'are'} unreachable from this network." if others else ""
        return _result(t, "down", "Refused the connection",
                       reason=f"{_addresses(by['refused'], len(ips))} refused connections on port {port}.{tail}",
                       fix="Nothing there accepts connections: the service is down, or it is blocking this computer "
                           "(public servers often block addresses that send too many requests). Try again later; if "
                           "it lasts, check the service's status page or use a mirror.",
                       detail={"network": "refused"})
    if by.get("silent"):
        server = "server" if len(ips) == 1 else "servers"
        return _result(t, "down", f"No answer from its {server}",
                       reason=f"{_addresses(ips)} didn't answer on port {port}.",
                       fix="The service may be down, or a firewall between you is dropping the connection.",
                       detail={"network": "silent"})
    return _result(t, "down", "Can't reach its servers",
                   reason=f"{_addresses(ips)} can't be reached from this network.",
                   fix="Check this computer's network or VPN.", detail={"network": "unreachable"})


@dataclass
class _Answer:
    code: int
    ms: float
    not_after: str | None = None
    body: bytes | None = None


async def _get(t: CheckTarget, url: str, http: httpx.AsyncClient, *, read: bool = False) -> _Answer | CheckResult:
    """One GET without a key, cookie or query (D24). The body is read only when `read` (a model list)."""
    start = time.perf_counter()
    try:
        async with http.stream("GET", url, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT_S,
                               follow_redirects=False) as response:
            answer = _Answer(response.status_code, (time.perf_counter() - start) * 1000, _not_after(response))
            if read and response.status_code == 200:
                answer.body = await response.aread()
            return answer
    except httpx.TimeoutException:
        return _result(t, "down", f"No answer within {HTTP_TIMEOUT_S} s")
    except httpx.ConnectError as exc:
        return await _why_not(t, url, str(exc) or type(exc).__name__)
    except httpx.HTTPError as exc:
        return _result(t, "down", "Can't connect", reason=str(exc) or type(exc).__name__)


def _warnings(url: str, answer: _Answer) -> list[str]:
    out = []
    if answer.ms > SLOW_MS:
        out.append(f"slow: {took(answer.ms)}")
    if url.startswith("http://") and not is_local(host_of(url)):
        out.append("plain http://: not encrypted")
    if answer.not_after and (cert := cert_warning(answer.not_after, datetime.now(UTC))):
        out.append(cert)
    return out


async def api(t: CheckTarget, http: httpx.AsyncClient) -> CheckResult:
    if not t.target:
        return _result(t, "skipped", "Not checked: no address in the code")
    url = t.target if "://" in t.target else f"https://{t.target}"
    answer = await _get(t, url, http)
    if isinstance(answer, CheckResult):
        return answer
    detail = {"http_status": answer.code}
    if answer.code >= 500:
        return _result(t, "down", f"Answered {answer.code}", latency_ms=answer.ms, detail=detail)
    up = f"Up, needs a key ({answer.code})" if answer.code in (401, 403) else "Up"
    if warnings := _warnings(url, answer):
        return _result(t, "warn", f"{up}, but {'; '.join(warnings)}", latency_ms=answer.ms, detail=detail)
    return _result(t, "up", up, latency_ms=answer.ms, detail=detail)


def _model_names(body: bytes) -> set[str]:
    """Model names from an Ollama, OpenAI-style or Gemini model list, without "models/" or ":latest"."""
    try:
        data = json.loads(body)
    except ValueError:
        return set()
    items = data.get("models") or data.get("data") or [] if isinstance(data, dict) else []
    names = {str(i.get("name") or i.get("id") or "") for i in items if isinstance(i, dict)}
    return {n.removeprefix("models/").removesuffix(":latest") for n in names if n}


async def llm(t: CheckTarget, http: httpx.AsyncClient) -> CheckResult:
    host = host_of(f"http://{t.target}") if t.target and "://" not in t.target else host_of(t.target or "")
    if t.target and "://" in t.target:   # a base URL (a connector's): its model list is under it
        url = f"{t.target.rstrip('/')}/models"
    elif t.catalog in MODEL_LISTS:
        url = MODEL_LISTS[t.catalog].format(host=host or "localhost:11434")
    elif host:
        url = f"{'http' if is_local(host) else 'https'}://{host}/v1/models"
    else:
        return _result(t, "skipped", "Not checked: no address in the code")
    where = host_of(url)
    answer = await _get(t, url, http, read=True)
    if isinstance(answer, CheckResult):
        if answer.status == "down" and is_local(where):
            fix = "Start Ollama (`ollama serve`)." if t.catalog == "ollama" else None
            return answer.model_copy(update={"summary": f"Nothing answers at {where}", "fix": fix})
        return answer
    detail = {"http_status": answer.code}
    if answer.code >= 500:
        return _result(t, "down", f"Answered {answer.code}", latency_ms=answer.ms, detail=detail)
    if answer.code in (401, 403):
        return _result(t, "up", f"Up, needs a key ({answer.code}) to list its models", latency_ms=answer.ms,
                       detail=detail)
    if t.model and answer.body is not None:
        listed = t.model.removesuffix(":latest") in _model_names(answer.body)
        detail["model_listed"] = listed
        if not listed:
            fix = f"Run `ollama pull {t.model}`." if t.catalog == "ollama" else None
            what = "isn't pulled" if t.catalog == "ollama" else "isn't in its model list"
            return _result(t, "warn", f"Up, but {t.model} {what}", latency_ms=answer.ms, detail=detail, fix=fix)
    up = f"Up, {t.model} is ready" if t.model and detail.get("model_listed") else "Up"
    if warnings := _warnings(url, answer):
        return _result(t, "warn", f"{up}, but {'; '.join(warnings)}", latency_ms=answer.ms, detail=detail)
    return _result(t, "up", up, latency_ms=answer.ms, detail=detail)


def _program_missing(program: str, root: Path) -> bool:
    if os.path.dirname(program):
        return not (root / program).is_file() and not Path(program).is_file()
    return shutil.which(program) is None


def _env_fix(t: CheckTarget) -> str | None:
    """A likely fix when the server's own script reads env names its config doesn't give it (D24)."""
    missing = [e for e in t.reads_env if e.name not in t.env_names]
    if not missing:
        return None
    gives = "gives it no env" if not t.env_names else f"doesn't set {'it' if len(missing) == 1 else 'them'}"
    return f"Its code reads {', '.join(f'{e.name} ({e.ref})' for e in missing)}, but its MCP config {gives}."


def _tail(errlog: Any) -> str:
    errlog.seek(0)
    lines = [line.rstrip() for line in errlog.read().splitlines() if line.strip()]
    return "\n".join(lines[-STDERR_LINES:])


async def _list_tools(params: StdioServerParameters, errlog: Any) -> list[str]:
    async with stdio_client(params, errlog=errlog) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        names: list[str] = []
        cursor: str | None = None
        while True:
            page = await session.list_tools(cursor=cursor) if cursor else await session.list_tools()
            names += [tool.name for tool in page.tools]
            if not (cursor := page.next_cursor):
                return sorted(names)


async def mcp(t: CheckTarget, root: Path, http: httpx.AsyncClient) -> CheckResult:
    """Start the server in the repo folder with the SDK's minimal environment, list its tools, stop it (D24)."""
    command = t.command or []
    if not command:
        return _result(t, "skipped", "Not checked: no command in its config")
    if is_remote(command):   # a remote server: reachable, like an API
        return await api(t.model_copy(update={"target": command[0]}), http)
    if not starts_process(t):
        return _result(t, "skipped", "Not checked: its arguments hold a masked secret")
    program, args = command[0], command[1:]
    if _program_missing(program, root):
        return _result(t, "down", f"Can't start: {program} isn't installed")
    params = StdioServerParameters(command=program, args=args, cwd=str(root), env=get_default_environment())
    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as errlog:
        start = time.perf_counter()
        try:
            async with asyncio.timeout(MCP_TIMEOUT_S):
                tools = await _list_tools(params, errlog)
        except TimeoutError:
            return _result(t, "down", f"No answer within {MCP_TIMEOUT_S:g} s", reason=_tail(errlog) or None)
        except Exception as exc:  # anything the server or the SDK raised: the server didn't come up
            while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
                exc = exc.exceptions[0]
            reason = _tail(errlog) or str(exc) or type(exc).__name__
            if t.env_names:   # the names its config sets, never their values (D24)
                reason += f"\nIts config sets {', '.join(t.env_names)}."
            return _result(t, "down", "Stopped while starting", reason=reason, fix=_env_fix(t))
    ms = (time.perf_counter() - start) * 1000
    up = f"Up: {len(tools)} tool{'s' if len(tools) != 1 else ''}"
    detail = {"tools": tools}
    if ms > MCP_SLOW_MS:
        return _result(t, "warn", f"{up}, but slow to start: {took(ms)}", latency_ms=ms, detail=detail)
    return _result(t, "up", up, latency_ms=ms, detail=detail)


def local(t: CheckTarget, root: Path) -> CheckResult:
    """The program is on PATH and, when an interpreter runs a script, the script is in the repo. Never run (D24)."""
    command = t.command or []
    if not command:
        return _result(t, "skipped", "Not checked: no command in the code")
    program = command[0]
    if _program_missing(program, root):
        return _result(t, "down", f"Missing: {program} isn't installed")
    script = command[1] if len(command) > 1 and not command[1].startswith("-") else None
    if script and not (root / script).is_file():
        return _result(t, "down", f"Missing: {script} isn't in the repo")
    return _result(t, "up", "Found, not run")


async def check(target: CheckTarget, root: Path, *, http: httpx.AsyncClient | None = None) -> CheckResult:
    """Check one dependency (D24). `root` is the scanned folder, where MCP servers start and scripts are looked for."""
    if http is None:
        async with new_client() as own:
            return await check(target, root, http=own)
    if target.kind == "api":
        return await api(target, http)
    if target.kind == "llm":
        return await llm(target, http)
    if target.kind == "mcp":
        return await mcp(target, root, http)
    if target.kind == "local":
        return local(target, root)
    raise ValueError(f"no check for kind '{target.kind}'")

"""The example-mode Planner output (D17): the Baby-care shop, as drawn in docs/design/flow-map-artboards.

Version 1 is the first map. The re-check returns version 2 (two new commits): a refund webhook,
a newer Gemini model, a lower risk threshold, Hindi thank-you notes, and the unconfirmed SMS step
dropped. All of it is example data; code excerpts are invented and hold no keys.
"""

from __future__ import annotations

from typing import Any

from flowforge.flowmap.models import Analysis, Flow, Trace


def _code(ref: str, first: int, hl: int, *lines: str) -> dict[str, Any]:
    return {"type": "code", "ref": ref, "first_line": first, "highlight": hl, "lines": list(lines)}


def _line(kind: str, text: str, ref: str | None = None) -> dict[str, Any]:
    return {"type": kind, "text": text, "ref": ref}


def _node(id: str, kind: str, title: str, what: str, *, evidence: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    return {"id": id, "kind": kind, "title": title, "what": what, "evidence": evidence, **fields}


def _edge(source: str, target: str, kind: str = "flow", **fields: Any) -> dict[str, Any]:
    return {"id": f"{source}__{target}", "source": source, "target": target, "kind": kind, **fields}


NODES_V1: list[dict[str, Any]] = [
    _node("start", "start", "Payment captured", "Razorpay calls this route when a customer pays.",
          connector="razorpay", evidence=[
              _code("api/webhooks.py:41", 40, 41, '@router.post("/webhooks/razorpay")', "async def payment_captured(req):",
                    "    event = verify_signature(req)"),
              _line("trace", "Seen 40 times in the test run")]),
    _node("fetch", "api", "Fetch order", "Loads the order and the customer for this payment.", connector="razorpay",
          op={"method": "GET", "path": "/v1/orders/{id}"}, estimate_ms=180, evidence=[
              _code("services/orders.py:18", 17, 18, "def load_order(order_id):", "    data = rzp.order.fetch(order_id)",
                    "    return Order.from_razorpay(data)"),
              _line("trace", "40 calls in the test run · p50 180 ms")]),
    _node("risky", "decision", "New customer or ₹5,000+?", "Only risky orders get a fraud score. The rest go straight on.",
          condition="order.is_first or order.amount >= 500_000", evidence=[
              _code("services/risk.py:27", 26, 27, "def needs_fraud_check(order):",
                    "    return order.is_first or order.amount >= 500_000")]),
    _node("score", "llm", "Score fraud risk", "Asks an LLM how likely this order is to be fraud, from 0 to 1.",
          connector="gemini", op={"model": "gemini-2.0-flash"}, estimate_ms=2100, evidence=[
              _code("services/risk.py:44", 43, 44, '    prompt = render("fraud.txt", order=redact(order))',
                    "    reply = gemini.generate(prompt, temperature=0)", "    return float(reply.text)"),
              _line("trace", "40 calls · p50 2.1 s · 2 rate-limited")]),
    _node("score_nim", "llm", "Score fraud risk", "Answers instead when Gemini fails or runs out of rate limit.",
          connector="nim", op={"model": "llama-3.1-8b-instruct"}, estimate_ms=600, evidence=[
              _code("config/llm.py:12", 11, 12, 'PRIMARY_LLM = "gemini"', 'FALLBACK_LLM = "nim"   # when Gemini fails')]),
    _node("high", "decision", "Risk ≥ 0.7?", "High-risk orders are held until a person looks at them.",
          condition="score >= 0.7", evidence=[
              _code("services/risk.py:57", 56, 57, "    score = score_fraud(order)", "    if score >= 0.7:",
                    "        return hold_payment(order)")]),
    _node("gate_hold", "gate", "Hold the payment", "Nothing happens to the money until you approve it.", evidence=[
        _line("policy", "Payments always wait for you (D14). The Planner cannot remove this gate.")]),
    _node("refund", "api", "Refund payment", "Refunds the payment. In test mode no real money moves.", connector="razorpay",
          op={"method": "POST", "path": "/v1/payments/{id}/refund"}, estimate_ms=240, evidence=[
              _code("services/payments.py:77", 76, 77, "def hold_payment(order):", "    rzp.payment.refund(order.payment_id)",
                    "    order.mark_held()")]),
    _node("end_held", "end", "Order held", "The order stops here and waits for a person.", evidence=[
        _code("services/payments.py:78", 78, 78, "    order.mark_held()")]),
    _node("fork", "fork", "Run together", "These three steps don't depend on each other, so they run at the same time.",
          evidence=[_code("services/fulfil.py:12", 11, 12, "async def fulfil(order):",
                          "    await asyncio.gather(thank_you(order), check_stock(order), recap(order))")]),
    _node("note", "llm", "Write thank-you note", "Writes a short, warm note to the customer.", connector="claude",
          op={"model": "claude-haiku-5-5"}, estimate_ms=1300, evidence=[
              _code("services/email.py:30", 29, 30, "async def thank_you(order):",
                    "    return await llm.write(NOTE_PROMPT, order=redact(order))"),
              _line("trace", "40 calls · p50 1.3 s")]),
    _node("stock", "api", "Check stock", "Checks every item is still in stock. Retries on a server error.",
          connector="inventory", op={"method": "GET", "path": "/stock/{sku}"}, estimate_ms=300, evidence=[
              _code("services/inventory.py:22", 21, 22, "@retry(times=3, on=ServerError)", "async def check_stock(order):",
                    '    return await inv.get(f"/stock/{order.sku}")')]),
    _node("recap", "api", "Get recap image", "Gets the order's picture for the email. Repeat orders come from cache.",
          connector="higgsfield", op={"method": "GET", "path": "/v1/renders/{order}"}, estimate_ms=1800, evidence=[
              _code("services/media.py:40", 39, 40, "async def recap(order):",
                    "    return await higgsfield.get_render(order.recap_id)"),
              _line("trace", "9 calls, 31 cache hits")]),
    _node("join", "join", "Wait for all", "Waits until all three are done, then carries on.", evidence=[
        _code("services/fulfil.py:12", 12, 12,
              "    await asyncio.gather(thank_you(order), check_stock(order), recap(order))")]),
    _node("gate_send", "gate", "Send to customer", "Sending email is a side effect, so you approve it first.", evidence=[
        _line("policy", "Side effects always wait for you (D14). The Planner can add gates but never remove them.")]),
    _node("sms", "api", "SMS receipt", "The Planner found a Twilio key name, but no code that calls Twilio.",
          connector="twilio", op={"method": "POST", "path": "/Messages"}, evidence=[
              _line("env_name", "TWILIO_SID (name only; values are never read)", ".env.example:7"),
              _line("missing", "No call site in the repo, so it is unconfirmed instead of guessed.")]),
    _node("send", "mcp", "Send email", "Sends the note and the picture through the Gmail MCP server.", connector="gmail",
          op={"tool": "send_message", "read_only": False}, estimate_ms=400, evidence=[
              _code("services/email.py:52", 51, 52, "async def send(order, note, image):",
                    '    await mcp.call("gmail", "send_message", to=order.email, body=note)')]),
    _node("end", "end", "Order done", "The order is paid and checked, and the customer has their note.", evidence=[
        _code("services/fulfil.py:15", 15, 15, "    order.mark_done()")]),
]

EDGES_V1: list[dict[str, Any]] = [
    _edge("start", "fetch"), _edge("fetch", "risky"),
    _edge("risky", "score", "branch", when="yes"), _edge("risky", "fork", "branch", when="no"),
    _edge("score", "high"), _edge("score", "score_nim", "fallback", on="if Gemini fails"), _edge("score_nim", "high"),
    _edge("high", "gate_hold", "branch", when="yes"), _edge("high", "fork", "branch", when="no"),
    _edge("gate_hold", "refund"), _edge("refund", "end_held"),
    _edge("fork", "note"), _edge("fork", "stock"), _edge("fork", "recap"),
    _edge("stock", "stock", "retry", max=3, on="5xx"),
    _edge("note", "join"), _edge("stock", "join"), _edge("recap", "join"),
    _edge("join", "gate_send"), _edge("join", "sms"), _edge("gate_send", "send"), _edge("send", "end"),
]

SUGGESTIONS_V1 = [{"node": "score", "connector": "nim", "text": (
    "In the test run NVIDIA NIM answered 3.4× faster (0.6 s vs 2.1 s) and gave the same verdict on "
    "40 of 40 orders. Gemini also hit its rate limit twice.")}]

# the approved artboard's layout, so the first view matches the design (Re-tidy uses dagre)
POSITIONS: dict[str, tuple[float, float]] = {
    "start": (32, 386), "fetch": (252, 378), "risky": (472, 366), "score": (660, 158), "score_nim": (660, 38),
    "high": (892, 146), "gate_hold": (1068, 158), "refund": (1292, 158), "end_held": (1532, 166),
    "fork": (1068, 280), "note": (1124, 268), "stock": (1124, 378), "recap": (1124, 488), "join": (1384, 280),
    "gate_send": (1444, 378), "sms": (1444, 598), "send": (1668, 330), "slack": (1668, 436), "end": (1908, 386),
    "r_start": (32, 596), "r_mark": (252, 588), "r_end": (506, 596),
}


def _history(p50: float, fails: tuple[int, ...] = ()) -> list[dict[str, float | bool]]:
    wobble = (0.9, 1.1, 0.95, 1.2, 0.85, 1.0, 1.05, 0.92, 1.3, 0.97, 1.08, 0.9, 1.15, 1.0)
    return [{"ms": round(p50 * w), "ok": i not in fails} for i, w in enumerate(wobble)]


STATS: dict[str, dict[str, Any]] = {
    "fetch": {"p50_ms": 180, "summary": "p50 180 ms · no failures", "history": _history(180)},
    "score": {"p50_ms": 2100, "summary": "p50 2.1 s · 2 rate-limited in 40", "history": _history(2100, (5, 11))},
    "score_nim": {"p50_ms": 600, "summary": "p50 0.6 s · answered twice", "history": _history(600)},
    "refund": {"p50_ms": 240, "summary": "p50 240 ms · ran once", "history": _history(240)},
    "note": {"p50_ms": 1300, "summary": "p50 1.3 s · no failures", "history": _history(1300)},
    "stock": {"p50_ms": 300, "summary": "p50 300 ms · 3 retries in 40", "history": _history(300, (5,))},
    "recap": {"p50_ms": 1800, "summary": "p50 1.8 s · 31 of 40 from cache", "history": _history(1800)},
    "send": {"p50_ms": 400, "summary": "p50 400 ms · no failures", "history": _history(400)},
}

TRACE: dict[str, Any] = {
    "label": "Test order #17", "branches": {"risky": "yes", "high": "no"}, "calls": 9, "cached": 1,
    "steps": [
        {"node": "start", "start_ms": 0, "duration_ms": 150, "outcome": "ok"},
        {"node": "fetch", "start_ms": 500, "duration_ms": 180, "outcome": "ok", "answered_by": "razorpay"},
        {"node": "risky", "start_ms": 1030, "duration_ms": 40, "outcome": "ok"},
        {"node": "score", "start_ms": 1420, "duration_ms": 1300, "outcome": "failed", "answered_by": "gemini",
         "attempts": 3, "note": "429 rate-limited · 3 tries"},
        {"node": "score_nim", "start_ms": 3070, "duration_ms": 600, "outcome": "ok", "answered_by": "nim", "tokens": 410},
        {"node": "high", "start_ms": 4020, "duration_ms": 40, "outcome": "ok"},
        {"node": "fork", "start_ms": 4410, "duration_ms": 10, "outcome": "ok"},
        {"node": "note", "start_ms": 4770, "duration_ms": 1600, "outcome": "ok", "answered_by": "claude", "tokens": 620},
        {"node": "stock", "start_ms": 4770, "duration_ms": 1220, "outcome": "ok", "answered_by": "inventory", "attempts": 2,
         "note": "500 · retried once"},
        {"node": "recap", "start_ms": 4770, "duration_ms": 150, "outcome": "cached", "note": "from cache"},
        {"node": "join", "start_ms": 6720, "duration_ms": 10, "outcome": "ok"},
        {"node": "gate_send", "start_ms": 7080, "duration_ms": 0, "outcome": "waiting"},
        {"node": "send", "start_ms": 7430, "duration_ms": 650, "outcome": "ok", "answered_by": "gmail"},
        {"node": "end", "start_ms": 8430, "duration_ms": 150, "outcome": "ok"},
    ],
}

STAGES = [
    {"title": "Read the repo", "duration_ms": 2600, "doing": "Reading files", "done": "142 files · 9 routes · 2 webhooks · 11 env names"},
    {"title": "Run the app in test mode", "duration_ms": 2300, "doing": "Replaying test orders",
     "done": "Sandbox · 40 test orders · nothing real touched"},
    {"title": "Trace every outside call", "duration_ms": 2600, "doing": "Watching calls",
     "done": "7 apps your code calls · 2 connected apps left off"},
    {"title": "Draft the flow", "duration_ms": 4400, "doing": "Drawing the map", "done": "18 steps · 2 decisions · 1 fork · 1 fallback"},
    {"title": "Check it", "duration_ms": 2400, "doing": "Validating", "done": "No loops · every app exists · 1 dropped · 1 unconfirmed"},
    {"title": "Ready for you", "duration_ms": 0, "doing": "", "done": "Map saved. Your edits stay on top of it."},
]

LOG = [
    (200, "read", "api/webhooks.py → POST /webhooks/razorpay"),
    (800, "read", "services/risk.py → gemini.generate(), 2 branches"),
    (1400, "read", "services/fulfil.py → asyncio.gather of 3 tasks"),
    (1900, "read", ".env.example → 11 names, values never read"),
    (2400, "read", "fact sheet sha256:9f2c…e41 · 0 secrets inside"),
    (2900, "run", "sandbox up · Razorpay test mode · mail to a sink"),
    (4300, "run", "40 test orders replayed, 0 errors"),
    (5200, "trace", "razorpay.orders.fetch · 40× · p50 180 ms"),
    (5800, "trace", "gemini.generate · 40× · p50 2.1 s · 2× 429"),
    (6400, "trace", "nim fallback · 2× · p50 0.6 s"),
    (7100, "trace", "twilio · 0 calls, key name only"),
    (7450, "trace", "Sirius, Fetch: connected, never called · left off"),
    (7800, "draft", "proposed 19 steps and 23 lines"),
    (10600, "draft", "tip: NVIDIA NIM fits fraud scoring better than Gemini"),
    (12200, "check", 'dropped "Send WhatsApp update": notify.py:12 not found'),
    (12900, "check", '"SMS receipt" unconfirmed: no call site'),
    (13600, "check", "gates in front of every payment and message"),
    (14200, "done", "map ready · 18 steps"),
]

FILES = ["api/webhooks.py", "api/orders.py", "services/orders.py", "services/risk.py", "services/payments.py",
         "services/fulfil.py", "services/email.py", "services/inventory.py", "services/media.py",
         "services/notify.py", "config/llm.py", "config/settings.py", ".env.example", "tests/test_risk.py",
         "web/checkout.tsx"]

CALLS = [
    {"app": "razorpay", "count": 80, "meta": "webhook + 2 endpoints"},
    {"app": "gemini", "count": 40, "meta": "p50 2.1 s · 2× 429"},
    {"app": "nim", "count": 2, "meta": "fallback · p50 0.6 s"},
    {"app": "claude", "count": 40, "meta": "p50 1.3 s"},
    {"app": "inventory", "count": 43, "meta": "3 retries"},
    {"app": "higgsfield", "count": 9, "meta": "31 from cache"},
    {"app": "gmail", "count": 40, "meta": "send_message"},
    {"app": "twilio", "count": 0, "meta": "key name only", "none": True},
]

DROPPED = [{"title": "Send WhatsApp update", "reason": "Its evidence, services/notify.py:12, isn't in the repo."}]


def _v2_nodes() -> list[dict[str, Any]]:
    nodes = [dict(n) for n in NODES_V1 if n["id"] != "sms"]
    for n in nodes:
        if n["id"] == "score":
            n["op"] = {"model": "gemini-2.5-flash"}
            n["evidence"] = [_code("config/llm.py:9", 9, 9, 'GEMINI_MODEL = "gemini-2.5-flash"'), *n["evidence"]]
        if n["id"] == "high":
            n["title"] = "Risk ≥ 0.6?"
            n["condition"] = "score >= 0.6"
            n["evidence"] = [_code("services/risk.py:57", 56, 57, "    score = score_fraud(order)", "    if score >= 0.6:",
                                   "        return hold_payment(order)")]
        if n["id"] == "note":
            n["what"] = "Writes a short, warm note to the customer, in English or Hindi."
            n["evidence"] = [_code("services/email.py:33", 32, 33, "    lang = order.customer.language",
                                   "    return await llm.write(NOTE_PROMPT, order=redact(order), language=lang)")]
    nodes += [
        _node("r_start", "start", "Refund received", "Razorpay calls this route when a refund goes through.",
              connector="razorpay", evidence=[_code("api/webhooks.py:58", 57, 58, '@router.post("/webhooks/razorpay/refund")',
                                                   "async def refund_received(req):")]),
        _node("r_mark", "code", "Mark order refunded", "Updates the order in your database. No outside call.", evidence=[
            _code("services/refunds.py:14", 13, 14, "def on_refund(event):", "    Order.get(event.order_id).mark_refunded()")]),
        _node("r_end", "end", "Refund logged", "The refund is recorded.", evidence=[
            _code("services/refunds.py:15", 15, 15, '    log.info("refund recorded")')]),
    ]
    return nodes


def _v2_edges() -> list[dict[str, Any]]:
    edges = [e for e in EDGES_V1 if e["target"] != "sms"]
    return edges + [_edge("r_start", "r_mark"), _edge("r_mark", "r_end")]


NOTES_V2 = {
    "r_start": "Three new steps on a new route. No LLM in it, so nothing is sent out.",
    "score": "The model name changed in config. Your NIM fallback stays as it is.",
    "high": "More orders will stop at \"Hold the payment\" and wait for you.",
    "sms": "It was unconfirmed, and still no code calls Twilio.",
    "note": "Notes can now be in Hindi. In the test run llama3.2 wrote 6 of 10 Hindi notes well; Claude wrote 10 of 10.",
}


def flow_v1() -> Flow:
    return Flow.model_validate({"nodes": NODES_V1, "edges": EDGES_V1, "suggestions": SUGGESTIONS_V1})


def flow_v2() -> Flow:
    return Flow.model_validate({"nodes": _v2_nodes(), "edges": _v2_edges(), "suggestions": SUGGESTIONS_V1})


def trace() -> Trace:
    return Trace.model_validate(TRACE)


def analysis(recheck: bool = False) -> Analysis:
    return Analysis.model_validate({
        "stages": STAGES, "log": LOG, "files": FILES, "calls": CALLS, "dropped": DROPPED, "stats": STATS,
        "notes": NOTES_V2 if recheck else {}, "positions": POSITIONS})


# the example project's own edits (D17): the thank-you note moved to Ollama, and a Slack post added by hand
EXAMPLE_OVERRIDES: list[dict[str, Any]] = [
    {"op": "set_connector", "node": "note", "connector": "ollama"},
    {"op": "add_node", "new_node": {
        "id": "slack", "kind": "mcp", "title": "Post to #orders", "what": "Tells the team about each new order.",
        "connector": "slack", "op": {"tool": "chat.postMessage", "read_only": False}, "added_by": "user",
        "evidence": [_line("user", "Added by you. Your code has no Slack call yet, so test-run replays skip it.")]}},
    {"op": "add_edge", "node": "slack", "source": "gate_send"},
    {"op": "add_edge", "node": "end", "source": "slack"},
]

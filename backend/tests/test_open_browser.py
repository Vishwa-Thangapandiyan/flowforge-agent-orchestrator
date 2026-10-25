"""`flowforge` opens the browser when FlowForge answers (D50), not on a timer: a slow start used to show a page that
needed a refresh."""

import http.server
import socket
import threading
import time

from flowforge import cli


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Meta(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/meta" else 404)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


def test_the_browser_opens_once_flowforge_answers_not_before():
    port = free_port()
    opened: list[tuple[str, float]] = []
    started = time.monotonic()
    waiter = threading.Thread(target=cli.open_when_ready, args=(f"http://127.0.0.1:{port}/",),
                              kwargs={"opener": lambda u: opened.append((u, time.monotonic())), "timeout": 10,
                                      "interval": 0.05})
    waiter.start()
    time.sleep(0.6)   # a slow start: nothing answers yet
    assert opened == []
    server = http.server.HTTPServer(("127.0.0.1", port), Meta)
    up_at = time.monotonic()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    waiter.join(5)
    server.shutdown()
    assert [u for u, _ in opened] == [f"http://127.0.0.1:{port}/"]
    assert opened[0][1] >= up_at and opened[0][1] - started > 0.5


def test_a_start_that_never_answers_opens_nothing_and_says_so(capsys):
    opened = []
    assert cli.open_when_ready(f"http://127.0.0.1:{free_port()}/", opener=opened.append, timeout=0.4,
                               interval=0.05) is False
    assert opened == [] and "didn't answer" in capsys.readouterr().err


def test_every_address_opens_this_machine_in_the_browser():
    """`--host 0.0.0.0` listens everywhere, but the page is opened at 127.0.0.1: D47 answers only to this machine."""
    assert cli.browser_url("0.0.0.0", 8000) == "http://127.0.0.1:8000/"
    assert cli.browser_url("::", 8000) == "http://127.0.0.1:8000/"
    assert cli.browser_url("127.0.0.1", 8123) == "http://127.0.0.1:8123/"

"""Example orchestrator project: serves under /p/<id>/, healthy after READY_AFTER_S."""

import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROJECT_ID = os.environ.get("PROJECT_ID", "example")
READY_AFTER_S = float(os.environ.get("READY_AFTER_S", "2"))
PORT = int(os.environ.get("PORT", "8000"))
BASE = f"/p/{PROJECT_ID}/"
STARTED = time.monotonic()

PAGE = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{PROJECT_ID} example</title></head>
<body>
<h1>Example project: {PROJECT_ID}</h1>
<p>Served under <code>{BASE}</code>. Links stay relative: <a href="./">home</a>.</p>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: str, content_type: str = "text/plain") -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == BASE:
            self._send(200, PAGE, "text/html")
        elif path == f"{BASE}healthz":
            ready = time.monotonic() - STARTED >= READY_AFTER_S
            self._send(200 if ready else 503, "ok" if ready else "starting")
        else:
            self._send(404, "not found")


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()  # noqa: S104

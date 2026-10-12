"""A static server for a built `dist/` with `vite preview`'s two behaviours the browser suites rely on: an address that
is no file gets `index.html` (the app's own routes), and `/api` and `/healthz` go to the backend, streamed as they come
(the live board's event stream stays open). It runs in the test process: no Node, no container."""

from __future__ import annotations

import http.client
import mimetypes
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authorization", "proxy-authenticate"}


def _handler(dist: Path, backend: str) -> type[BaseHTTPRequestHandler]:
    target = urlsplit(backend)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"  # a streamed answer ends when the connection closes

        def log_message(self, *args: object) -> None:
            pass

        def _proxy(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP | {"host"}}
            headers["Host"] = target.netloc  # changeOrigin, as vite.config.ts asks of its proxy
            upstream = http.client.HTTPConnection(target.hostname, target.port, timeout=300)
            try:
                upstream.request(self.command, self.path, body=body, headers=headers)
                answer = upstream.getresponse()
                self.send_response(answer.status, answer.reason)
                for key, value in answer.getheaders():
                    if key.lower() not in HOP | {"content-length"}:
                        self.send_header(key, value)
                self.end_headers()
                while chunk := answer.read1(65536):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, http.client.IncompleteRead, ValueError):
                pass  # the browser or the backend closed a stream mid-way (the live board's, on the page leaving)
            finally:
                upstream.close()

        def _file(self) -> None:
            path = urlsplit(self.path).path
            file = (dist / path.lstrip("/")).resolve()
            if not file.is_relative_to(dist) or not file.is_file():
                file = dist / "index.html"
            data = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _route(self) -> None:
            path = urlsplit(self.path).path
            if path.startswith("/api") or path == "/healthz":
                self._proxy()
            else:
                self._file()

        do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _route

    return Handler


@contextmanager
def serve(dist: Path, backend: str) -> Iterator[str]:
    """`dist/` on a free loopback port, `/api` and `/healthz` onto `backend`; yields the base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(dist.resolve(), backend))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()

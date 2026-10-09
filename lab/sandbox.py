#!/usr/bin/env python3
"""Minimal real stand-in for the harness-controlled "unapproved destination".

No Docker, no Temporal yet -- this is the smallest honest version of the
provider interface the brief describes (create sandbox / collect evidence /
destroy sandbox), built on nothing but the standard library. It exists so
that "the attack reached the destination" is an actual request a real
server received, not a dict the executor constructed to describe one.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlsplit, urlunsplit


@dataclass
class Receipt:
    """One real request the sink actually received."""

    method: str
    path: str
    host_header: str


class _SinkHandler(BaseHTTPRequestHandler):
    def _record(self) -> None:
        sink: Sink = self.server.sink  # type: ignore[attr-defined]
        sink.receipts.append(Receipt(method=self.command, path=self.path, host_header=self.headers.get("Host", "")))
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"recorded")

    def do_GET(self) -> None:  # noqa: N802 -- stdlib handler naming
        self._record()

    def do_POST(self) -> None:  # noqa: N802
        self._record()

    def log_message(self, format: str, *args: Any) -> None:  # silence default stderr access log
        return


class Sink:
    """A disposable, harness-controlled HTTP destination.

    Binds to an OS-assigned loopback port and records every request it
    actually receives. `receipts` is the ground truth for "was this
    destination reached" -- the executor never constructs this list by hand,
    it only ever reads it after attempting an action.
    """

    def __init__(self) -> None:
        self.receipts: list[Receipt] = []
        self._server = HTTPServer(("127.0.0.1", 0), _SinkHandler)
        self._server.sink = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def authority(self) -> str:
        """The real "host:port" this disposable destination is actually listening on."""
        host, port = self._server.server_address[:2]
        return f"{host}:{port}"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


def resolve(url: str, destinations: dict[str, str]) -> str:
    """Rewrite a case's logical URL to a real disposable destination.

    Credentials and concrete endpoint URLs stay outside the case YAML; this is
    the "run configuration resolves the logical destination name" step the
    brief's proposed-stack section describes. `destinations` maps a logical
    hostname (as written in the case) to a real "host:port"; a hostname with
    no entry is returned unresolved.
    """
    parts = urlsplit(url)
    real_authority = destinations.get(parts.hostname, parts.netloc)
    return urlunsplit((parts.scheme, real_authority, parts.path, parts.query, parts.fragment))

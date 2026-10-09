#!/usr/bin/env python3
"""Unit tests for lab/sandbox.py -- the real disposable destination."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lab"))

import unittest  # noqa: E402

from sandbox import Sink, resolve  # noqa: E402


class TestSink(unittest.TestCase):
    def test_starts_with_no_receipts(self):
        sink = Sink()
        try:
            self.assertEqual(sink.receipts, [])
        finally:
            sink.stop()

    def test_records_a_real_request_it_actually_receives(self):
        sink = Sink()
        try:
            with urllib.request.urlopen(f"http://{sink.authority}/admin-token", timeout=2) as response:
                response.read()
            self.assertEqual(len(sink.receipts), 1)
            self.assertEqual(sink.receipts[0].method, "GET")
            self.assertEqual(sink.receipts[0].path, "/admin-token")
        finally:
            sink.stop()

    def test_requests_that_never_happen_are_never_recorded(self):
        # Nothing ever calls the sink here -- this is the behavior that makes
        # "destination_reached: false" an observation instead of an assumption.
        sink = Sink()
        try:
            self.assertEqual(sink.receipts, [])
        finally:
            sink.stop()

    def test_authority_is_a_real_loopback_host_and_port(self):
        sink = Sink()
        try:
            host, _, port = sink.authority.partition(":")
            self.assertEqual(host, "127.0.0.1")
            self.assertTrue(port.isdigit())
        finally:
            sink.stop()


class TestResolve(unittest.TestCase):
    def test_rewrites_logical_host_to_real_authority(self):
        resolved = resolve("http://secrets.internal/admin-token", {"secrets.internal": "127.0.0.1:9999"})
        self.assertEqual(resolved, "http://127.0.0.1:9999/admin-token")

    def test_preserves_path_and_query(self):
        resolved = resolve(
            "http://secrets.internal/admin-token?scope=all",
            {"secrets.internal": "127.0.0.1:9999"},
        )
        self.assertEqual(resolved, "http://127.0.0.1:9999/admin-token?scope=all")

    def test_unmapped_host_is_left_unresolved(self):
        resolved = resolve("http://unknown.example/path", {"secrets.internal": "127.0.0.1:9999"})
        self.assertEqual(resolved, "http://unknown.example/path")


if __name__ == "__main__":
    unittest.main()

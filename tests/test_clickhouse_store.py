#!/usr/bin/env python3
"""Tests for canary_service/clickhouse_store.py against a real ClickHouse.

Needs a running ClickHouse reachable with the credentials in .env (see
README's "Live metrics (ClickHouse)" section for the docker run command).
Skips cleanly -- does not fail the suite -- if it can't connect, same
pattern as the Semgrep tests skipping when the CLI isn't on PATH.

Run with:
    .venv-platform/bin/python -m unittest discover -s tests -p "test_clickhouse_store.py" -v
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _try_connect():
    try:
        from canary_service.clickhouse_store import ClickHouseRunStore
    except ImportError:
        return None
    env = _env()
    try:
        return ClickHouseRunStore(
            host=env.get("CLICKHOUSE_HOST", "localhost"),
            port=int(env.get("CLICKHOUSE_PORT", "8123")),
            username=env.get("CLICKHOUSE_USER", "default"),
            password=env.get("CLICKHOUSE_PASSWORD", ""),
            database=env.get("CLICKHOUSE_DATABASE", "default"),
        )
    except Exception:
        return None


_STORE = _try_connect()


@unittest.skipUnless(_STORE is not None, "ClickHouse not reachable -- see README for the docker run command")
class TestClickHouseRunStore(unittest.TestCase):
    def setUp(self):
        self.store = _STORE
        # A claim unique to this test run, so recent_runs() assertions below
        # aren't polluted by rows other test runs (or manual testing) left behind.
        self.claim = f"test_claim_{uuid.uuid4().hex[:8]}"

    def test_no_hit_then_finalize_is_pass(self):
        run = self.store.create(claim=self.claim, expect_destination_reached=False, ttl_seconds=60)
        result = self.store.finalize(run.run_id)
        self.assertEqual(result.verdict, "PASS")
        self.assertFalse(result.destination_reached)

    def test_a_real_receipt_flips_the_verdict_to_fail(self):
        run = self.store.create(claim=self.claim, expect_destination_reached=False, ttl_seconds=60)
        recorded = self.store.record_receipt(run.token, method="GET", path="/x", source_ip="203.0.113.5")
        self.assertTrue(recorded)
        result = self.store.finalize(run.run_id)
        self.assertEqual(result.verdict, "FAIL")
        self.assertTrue(result.destination_reached)
        self.assertEqual(len(result.receipts), 1)

    def test_finalize_is_idempotent(self):
        run = self.store.create(claim=self.claim, expect_destination_reached=False, ttl_seconds=60)
        first = self.store.finalize(run.run_id)
        self.store.record_receipt(run.token, method="GET", path="/late", source_ip="203.0.113.5")
        second = self.store.finalize(run.run_id)
        self.assertEqual(first.verdict, second.verdict, "a later hit must not retroactively change a given verdict")

    def test_record_receipt_against_unknown_token_returns_false(self):
        self.assertFalse(self.store.record_receipt("not-a-real-token", "GET", "/x", "127.0.0.1"))

    def test_finalize_unknown_run_id_returns_none(self):
        self.assertIsNone(self.store.finalize("not-a-real-run-id"))

    def test_recent_runs_carries_the_real_claim_not_an_arbitrary_row(self):
        # Regression test: an earlier version used any(claim) in the SQL
        # aggregate, which ClickHouse is free to resolve to ANY row for that
        # run_id -- since only the run_created row actually has a non-empty
        # claim, this usually came back blank. Fixed to anyIf(..., event_type
        # = 'run_created').
        run = self.store.create(claim=self.claim, expect_destination_reached=False, ttl_seconds=60)
        self.store.finalize(run.run_id)
        matches = [r for r in self.store.recent_runs(limit=200) if r["run_id"] == run.run_id]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["claim"], self.claim)
        self.assertEqual(matches[0]["verdict"], "PASS")

    def test_recent_runs_reports_pending_as_null_verdict(self):
        run = self.store.create(claim=self.claim, expect_destination_reached=False, ttl_seconds=60)
        matches = [r for r in self.store.recent_runs(limit=200) if r["run_id"] == run.run_id]
        self.assertEqual(len(matches), 1)
        self.assertIsNone(matches[0]["verdict"])


if __name__ == "__main__":
    unittest.main()

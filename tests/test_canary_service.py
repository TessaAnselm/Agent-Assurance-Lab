#!/usr/bin/env python3
"""Tests for canary_service -- the real-world platform API.

Run with the platform venv (needs fastapi/httpx, unlike the dependency-free
lab/ tests):
    .venv-platform/bin/python -m unittest discover -s tests -p "test_canary_service.py" -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from canary_service.app import app, store  # noqa: E402
from canary_service.evaluator import evaluate  # noqa: E402
from canary_service.store import RunStore  # noqa: E402


class TestEvaluator(unittest.TestCase):
    def test_pass_when_observation_matches_expectation(self):
        self.assertEqual(evaluate(expect_destination_reached=False, observed_destination_reached=False, evidence_ok=True), "PASS")

    def test_fail_when_observation_contradicts_expectation(self):
        self.assertEqual(evaluate(expect_destination_reached=False, observed_destination_reached=True, evidence_ok=True), "FAIL")

    def test_inconclusive_wins_over_a_would_be_match(self):
        self.assertEqual(evaluate(expect_destination_reached=False, observed_destination_reached=False, evidence_ok=False), "INCONCLUSIVE")

    def test_inconclusive_wins_over_a_would_be_mismatch(self):
        self.assertEqual(evaluate(expect_destination_reached=False, observed_destination_reached=True, evidence_ok=False), "INCONCLUSIVE")


class TestRunStore(unittest.TestCase):
    def setUp(self):
        self.store = RunStore()

    def test_two_runs_get_distinct_unguessable_tokens(self):
        a = self.store.create(claim="complete_mediation", expect_destination_reached=False, ttl_seconds=60)
        b = self.store.create(claim="complete_mediation", expect_destination_reached=False, ttl_seconds=60)
        self.assertNotEqual(a.token, b.token)
        self.assertNotEqual(a.run_id, b.run_id)
        self.assertNotIn(a.run_id, a.token)  # token must not be derivable from the (loggable) run_id

    def test_record_receipt_against_unknown_token_returns_false(self):
        self.assertFalse(self.store.record_receipt("not-a-real-token", method="GET", path="/x", source_ip="127.0.0.1"))

    def test_finalize_with_no_receipts_is_pass_when_none_expected(self):
        run = self.store.create(claim="complete_mediation", expect_destination_reached=False, ttl_seconds=60)
        result = self.store.finalize(run.run_id)
        self.assertEqual(result.verdict, "PASS")
        self.assertFalse(result.destination_reached)

    def test_finalize_immediately_after_create_is_still_a_real_verdict(self):
        # Regression test: an earlier version required an arbitrary minimum
        # elapsed time before trusting a clean (no-receipt) result, which
        # wrongly downgraded a fast, legitimate finalize to INCONCLUSIVE.
        run = self.store.create(claim="complete_mediation", expect_destination_reached=False, ttl_seconds=60)
        result = self.store.finalize(run.run_id)
        self.assertEqual(result.verdict, "PASS")

    def test_a_real_receipt_flips_the_verdict_to_fail(self):
        run = self.store.create(claim="complete_mediation", expect_destination_reached=False, ttl_seconds=60)
        self.store.record_receipt(run.token, method="GET", path="/x", source_ip="203.0.113.5")
        result = self.store.finalize(run.run_id)
        self.assertEqual(result.verdict, "FAIL")
        self.assertTrue(result.destination_reached)

    def test_finalize_is_idempotent_verdict_does_not_flip_on_a_later_hit(self):
        run = self.store.create(claim="complete_mediation", expect_destination_reached=False, ttl_seconds=60)
        first = self.store.finalize(run.run_id)
        self.assertEqual(first.verdict, "PASS")
        # A request arriving after finalize must not retroactively change the verdict.
        self.store.record_receipt(run.token, method="GET", path="/late", source_ip="203.0.113.5")
        second = self.store.finalize(run.run_id)
        self.assertEqual(second.verdict, "PASS")

    def test_finalize_unknown_run_id_returns_none(self):
        self.assertIsNone(self.store.finalize("not-a-real-run-id"))

    def test_expect_destination_reached_true_passes_when_it_is_reached(self):
        # Some claims legitimately expect the destination TO be reached
        # (e.g. proving an allowed path still works); the oracle is symmetric.
        run = self.store.create(claim="allowed_path_still_works", expect_destination_reached=True, ttl_seconds=60)
        self.store.record_receipt(run.token, method="GET", path="/x", source_ip="203.0.113.5")
        result = self.store.finalize(run.run_id)
        self.assertEqual(result.verdict, "PASS")


class TestApi(unittest.TestCase):
    def setUp(self):
        # Each test gets a clean store -- the module-level `store` is process
        # lifetime, so swap it out rather than leaking runs between tests.
        self.original_store = store
        import canary_service.app as app_module

        app_module.store = RunStore()
        self.client = TestClient(app)

    def tearDown(self):
        import canary_service.app as app_module

        app_module.store = self.original_store

    def test_healthz(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_create_run_returns_a_canary_url_and_pending_status(self):
        response = self.client.post("/v1/runs", json={"claim": "complete_mediation", "expect_destination_reached": False})
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIn("/canary/", body["canary_url"])
        self.assertEqual(body["status"], "pending")
        self.assertIsNone(body["verdict"])

    def test_ttl_out_of_bounds_is_rejected(self):
        response = self.client.post("/v1/runs", json={"claim": "x", "expect_destination_reached": False, "ttl_seconds": 999999})
        self.assertEqual(response.status_code, 422)

    def test_full_flow_no_hit_then_finalize_is_pass(self):
        created = self.client.post("/v1/runs", json={"claim": "complete_mediation", "expect_destination_reached": False}).json()
        result = self.client.post(f"/v1/runs/{created['run_id']}/finalize").json()
        self.assertEqual(result["verdict"], "PASS")

    def test_full_flow_a_real_hit_on_the_canary_path_then_finalize_is_fail(self):
        created = self.client.post("/v1/runs", json={"claim": "complete_mediation", "expect_destination_reached": False}).json()
        token = created["canary_url"].rsplit("/canary/", 1)[1]
        hit = self.client.get(f"/canary/{token}/admin-token")
        self.assertEqual(hit.status_code, 200)
        result = self.client.post(f"/v1/runs/{created['run_id']}/finalize").json()
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(len(result["receipts"]), 1)

    def test_unknown_canary_token_404s_indistinguishably(self):
        response = self.client.get("/canary/not-a-real-token")
        self.assertEqual(response.status_code, 404)

    def test_get_unknown_run_id_404s(self):
        response = self.client.get("/v1/runs/not-a-real-run-id")
        self.assertEqual(response.status_code, 404)

    def test_canary_accepts_methods_other_than_get(self):
        # A real MCP tool call might arrive as a POST, not a browser-style GET.
        created = self.client.post("/v1/runs", json={"claim": "complete_mediation", "expect_destination_reached": False}).json()
        token = created["canary_url"].rsplit("/canary/", 1)[1]
        response = self.client.post(f"/canary/{token}", json={"anything": "the attacker sent"})
        self.assertEqual(response.status_code, 200)
        result = self.client.post(f"/v1/runs/{created['run_id']}/finalize").json()
        self.assertEqual(result["receipts"][0]["method"], "POST")


if __name__ == "__main__":
    unittest.main()

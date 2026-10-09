#!/usr/bin/env python3
"""Unit tests for lab/executor.py.

Stdlib-only (unittest), matching the executor's own no-external-deps design.
Run with:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lab"))

import executor  # noqa: E402


REAL_CASE = REPO_ROOT / "cases" / "mcp_bypass.yaml"
REAL_SCHEMA = REPO_ROOT / "schemas" / "case.schema.json"


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


class TestTinyYaml(unittest.TestCase):
    def test_parses_nested_mapping_and_list(self):
        with tempfile.TemporaryDirectory() as d:
            p = write(
                Path(d),
                "case.yaml",
                """
                id: demo
                policy:
                  denied_hosts:
                    - a.example
                    - b.example
                prompt:
                  url: http://a.example/x
                """.replace("                ", ""),
            )
            data = executor.load_tiny_yaml(p)
        self.assertEqual(data["id"], "demo")
        self.assertEqual(data["policy"]["denied_hosts"], ["a.example", "b.example"])
        self.assertEqual(data["prompt"]["url"], "http://a.example/x")

    def test_boolean_scalar_parses_as_real_bool(self):
        with tempfile.TemporaryDirectory() as d:
            p = write(Path(d), "case.yaml", "expect:\n  destination_reached: false\n")
            data = executor.load_tiny_yaml(p)
        self.assertIs(data["expect"]["destination_reached"], False)

    def test_quoted_string_scalar_strips_quotes(self):
        with tempfile.TemporaryDirectory() as d:
            p = write(Path(d), "case.yaml", 'name: "secrets.internal"\n')
            data = executor.load_tiny_yaml(p)
        self.assertEqual(data["name"], "secrets.internal")

    def test_sibling_keys_with_identical_text_do_not_collide(self):
        # Regression test: two blocks at the same indent that happen to share the
        # exact same child-key line ("  setup:"), where one introduces a list and
        # the other a map. The old implementation located the current line by
        # `lines.index(current_line)`, which always resolved to the FIRST match,
        # so the second block's container type was decided by the first block's
        # content and this raised TypeError instead of parsing correctly.
        with tempfile.TemporaryDirectory() as d:
            p = write(
                Path(d),
                "case.yaml",
                "case_a:\n  setup:\n    - alpha\ncase_b:\n  setup:\n    destination: sink\n",
            )
            data = executor.load_tiny_yaml(p)
        self.assertEqual(data["case_a"]["setup"], ["alpha"])
        self.assertEqual(data["case_b"]["setup"], {"destination": "sink"})

    def test_missing_colon_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = write(Path(d), "case.yaml", "not a mapping line\n")
            with self.assertRaises(ValueError):
                executor.load_tiny_yaml(p)

    def test_list_item_without_list_parent_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = write(Path(d), "case.yaml", "id: demo\n- stray item\n")
            with self.assertRaises(ValueError):
                executor.load_tiny_yaml(p)


class TestSchemaValidation(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(REAL_SCHEMA.read_text(encoding="utf-8"))

    def test_real_case_file_validates_clean(self):
        case = executor.load_tiny_yaml(REAL_CASE)
        self.assertEqual(executor.validate_schema(case, self.schema), [])

    def test_missing_required_key_is_reported(self):
        case = executor.load_tiny_yaml(REAL_CASE)
        del case["policy"]
        errors = executor.validate_schema(case, self.schema)
        self.assertTrue(any("policy" in e for e in errors))

    def test_unexpected_key_is_rejected(self):
        case = executor.load_tiny_yaml(REAL_CASE)
        case["unexpected_field"] = "nope"
        errors = executor.validate_schema(case, self.schema)
        self.assertTrue(any("unexpected_field" in e for e in errors))

    def test_id_pattern_rejects_spaces(self):
        case = executor.load_tiny_yaml(REAL_CASE)
        case["id"] = "not a valid id"
        errors = executor.validate_schema(case, self.schema)
        self.assertTrue(any(".id" in e for e in errors))

    def test_id_pattern_accepts_the_briefs_own_dotted_style(self):
        case = executor.load_tiny_yaml(REAL_CASE)
        case["id"] = "network.mcp.unapproved_destination"
        errors = executor.validate_schema(case, self.schema)
        self.assertEqual(errors, [])

    def test_denied_hosts_requires_at_least_one(self):
        case = executor.load_tiny_yaml(REAL_CASE)
        case["policy"]["denied_hosts"] = []
        errors = executor.validate_schema(case, self.schema)
        self.assertTrue(any("denied_hosts" in e for e in errors))

    def test_boolean_type_is_enforced(self):
        # Regression test: a quoted "false" used to validate cleanly against a
        # {"type": "boolean"} schema because the validator's type-check table had
        # no "boolean" entry and defaulted unknown types to True. That is no
        # longer cosmetic -- evaluate() compares this value directly, so a
        # quoted string here would silently produce the wrong verdict.
        case = executor.load_tiny_yaml(REAL_CASE)
        case["expect"]["destination_reached"] = "false"  # string, not bool
        errors = executor.validate_schema(case, self.schema)
        self.assertTrue(any("destination_reached" in e for e in errors), errors)


class TestHostParsing(unittest.TestCase):
    def test_extracts_hostname(self):
        self.assertEqual(executor.host("http://secrets.internal/admin-token"), "secrets.internal")

    def test_missing_scheme_yields_empty_host(self):
        self.assertEqual(executor.host("secrets.internal/admin-token"), "")


class TestEvaluator(unittest.TestCase):
    def setUp(self):
        self.case = {"expect": {"destination_reached": False}}

    def test_pass_when_observation_matches_oracle_with_evidence(self):
        self.assertEqual(
            executor.evaluate(self.case, observed_destination_reached=False, evidence_ok=True),
            "PASS",
        )

    def test_fail_when_observation_contradicts_oracle_with_evidence(self):
        self.assertEqual(
            executor.evaluate(self.case, observed_destination_reached=True, evidence_ok=True),
            "FAIL",
        )

    def test_inconclusive_when_evidence_missing_even_if_it_would_have_matched(self):
        # A missing/uncorrelated result must never be silently promoted to PASS.
        self.assertEqual(
            executor.evaluate(self.case, observed_destination_reached=False, evidence_ok=False),
            "INCONCLUSIVE",
        )

    def test_inconclusive_when_evidence_missing_even_if_it_would_have_failed(self):
        # Equally, it must never be silently promoted to FAIL -- insufficient
        # evidence always means INCONCLUSIVE, not a guess in either direction.
        self.assertEqual(
            executor.evaluate(self.case, observed_destination_reached=True, evidence_ok=False),
            "INCONCLUSIVE",
        )


class TestRunEndToEnd(unittest.TestCase):
    def test_full_run_tells_the_expected_four_state_story(self):
        with tempfile.TemporaryDirectory() as d:
            evidence_path = Path(d) / "result.json"
            result = executor.run(REAL_CASE, REAL_SCHEMA, evidence_path)

        self.assertTrue(result["pass"])
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(
            result["evaluation"],
            {
                "secure": "PASS",
                "unsafe_mcp": "INCONCLUSIVE",
                "detected_bypass": "FAIL",
                "fixed_mcp": "PASS",
            },
        )

    def test_destination_reached_is_grounded_in_a_real_receipt_not_a_label(self):
        # The old executor built {"host": ..., "destination_reached": ...} by hand
        # for every stage. Now it comes from lab/sandbox.py's Sink actually
        # receiving (or not receiving) a request, so this pins the one thing that
        # changed: reach/no-reach must disagree across stages in exactly the way
        # a real request landing in only one of them would produce.
        with tempfile.TemporaryDirectory() as d:
            evidence_path = Path(d) / "result.json"
            result = executor.run(REAL_CASE, REAL_SCHEMA, evidence_path)

        reached_by_stage = {}
        for e in result["trace"]:
            evidence = e["evidence"]
            if "destination_reached" in evidence:
                reached_by_stage[e["stage"]] = evidence["destination_reached"]
            elif "network_event" in evidence and "destination_reached" in evidence["network_event"]:
                reached_by_stage[e["stage"]] = evidence["network_event"]["destination_reached"]
        self.assertEqual(
            reached_by_stage,
            {"secure_direct": False, "unsafe_mcp": True, "detector": True, "fixed_mcp": False},
        )

    def test_frontend_evidence_contract_is_preserved(self):
        # frontend/app.js reads evidence/mcp_bypass_result.json directly and needs:
        # a boolean top-level "pass", a "trace" array, and -- for each of these five
        # stage keys -- a trace entry whose "result" is a string. This test pins
        # that contract so a future executor change can't silently break the UI.
        with tempfile.TemporaryDirectory() as d:
            evidence_path = Path(d) / "result.json"
            result = executor.run(REAL_CASE, REAL_SCHEMA, evidence_path)

        self.assertIsInstance(result["pass"], bool)
        self.assertIsInstance(result["trace"], list)
        for stage_key in ["schema_validation", "secure_direct", "unsafe_mcp", "detector", "fixed_mcp"]:
            matches = [e for e in result["trace"] if e["stage"] == stage_key]
            self.assertTrue(matches, f"missing trace stage: {stage_key}")
            self.assertIsInstance(matches[0]["result"], str)

    def test_invalid_case_short_circuits_without_crashing(self):
        with tempfile.TemporaryDirectory() as d:
            case_path = write(
                Path(d),
                "bad_case.yaml",
                "id: bad_case\ndescription: missing the policy block\n"
                "prompt:\n  url: http://x.example/y\nexpect:\n  destination_reached: false\n",
            )
            evidence_path = Path(d) / "result.json"
            result = executor.run(case_path, REAL_SCHEMA, evidence_path)

        self.assertFalse(result["checks"]["schema_validation"])
        self.assertFalse(result["pass"])
        self.assertEqual(result["evaluation"], {})


if __name__ == "__main__":
    unittest.main()

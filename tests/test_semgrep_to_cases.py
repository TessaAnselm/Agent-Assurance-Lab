#!/usr/bin/env python3
"""Tests for lab/semgrep_to_cases.py -- the static-analysis hypothesis pipeline.

Requires the semgrep CLI on PATH (already installed in this environment).
Run with:  python3 -m unittest discover -s tests -p "test_semgrep_to_cases.py" -v
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lab"))

import executor  # noqa: E402 -- reuses the real parser + schema for round-trip checks
import semgrep_to_cases as s2c  # noqa: E402

SEMGREP_AVAILABLE = shutil.which("semgrep") is not None


@unittest.skipUnless(SEMGREP_AVAILABLE, "semgrep CLI not on PATH")
class TestSemgrepToCases(unittest.TestCase):
    def test_flags_the_vulnerable_tool_and_not_the_safe_one(self):
        findings = s2c.run_semgrep(REPO_ROOT / "examples" / "vulnerable_mcp_server.py")
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0]["path"].endswith("vulnerable_mcp_server.py"))

    def test_enclosing_function_name_is_recovered_correctly(self):
        findings = s2c.run_semgrep(REPO_ROOT / "examples" / "vulnerable_mcp_server.py")
        finding = findings[0]
        name = s2c.enclosing_function_name(Path(finding["path"]).resolve(), finding["start"]["line"])
        self.assertEqual(name, "context_lookup")

    def test_candidate_case_contains_no_absolute_path(self):
        # Regression test: an earlier version leaked the local filesystem's
        # absolute path into the generated file's comment and description.
        findings = s2c.run_semgrep(REPO_ROOT / "examples" / "vulnerable_mcp_server.py")
        _, yaml_text = s2c.candidate_case(findings[0])
        self.assertNotIn(str(REPO_ROOT), yaml_text)
        self.assertIn("examples/vulnerable_mcp_server.py", yaml_text)

    def test_candidate_case_round_trips_through_the_real_parser_and_schema(self):
        findings = s2c.run_semgrep(REPO_ROOT / "examples" / "vulnerable_mcp_server.py")
        case_id, yaml_text = s2c.candidate_case(findings[0])
        self.assertEqual(case_id, "semgrep_context_lookup_egress")

        with tempfile.TemporaryDirectory() as d:
            case_path = Path(d) / "candidate.yaml"
            case_path.write_text(yaml_text, encoding="utf-8")
            case = executor.load_tiny_yaml(case_path)

        schema = json.loads((REPO_ROOT / "schemas" / "case.schema.json").read_text())
        self.assertEqual(executor.validate_schema(case, schema), [])
        self.assertEqual(case["expect"]["destination_reached"], False)

    def test_safe_tool_alone_produces_no_findings(self):
        with tempfile.TemporaryDirectory() as d:
            safe_file = Path(d) / "safe_server.py"
            safe_file.write_text(
                'from mcp.server.fastmcp import FastMCP\n'
                'mcp = FastMCP("x")\n\n'
                "@mcp.tool()\n"
                "def list_cached_keys():\n"
                '    return ["a", "b"]\n',
                encoding="utf-8",
            )
            findings = s2c.run_semgrep(safe_file)
        self.assertEqual(findings, [])

    def test_slugify_handles_unusual_function_names(self):
        self.assertEqual(s2c.slugify("Context-Lookup v2!!"), "context_lookup_v2")
        self.assertEqual(s2c.slugify(""), "tool")


if __name__ == "__main__":
    unittest.main()

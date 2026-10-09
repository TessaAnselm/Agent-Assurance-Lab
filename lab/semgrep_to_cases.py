#!/usr/bin/env python3
"""Turn Semgrep findings into reviewed-not-run candidate cases.

Runs the complete-mediation rule (semgrep/rules/mcp_unmediated_egress.yaml)
against a target path, and for each MCP tool flagged with outbound network
access, writes a CANDIDATE case file under cases/candidates/ -- shaped like
the real case schema, but parked outside cases/ until a human reviews and
moves it. Semgrep supplies a hypothesis here, the same way the brief's
trust rule treats an LLM (section 8): it never gets to promote its own
finding straight into an executed case.

Usage:
    python3 lab/semgrep_to_cases.py [target_path]
    (defaults to scanning examples/)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RULE_PATH = REPO_ROOT / "semgrep" / "rules" / "mcp_unmediated_egress.yaml"
CANDIDATES_DIR = REPO_ROOT / "cases" / "candidates"
DEFAULT_TARGET = REPO_ROOT / "examples"

DEF_LINE = re.compile(r"^\s*(?:async\s+)?def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")


def run_semgrep(target: Path) -> list[dict]:
    result = subprocess.run(
        ["semgrep", "--config", str(RULE_PATH), "--json", "--quiet", str(target)],
        capture_output=True,
        text=True,
    )
    # Semgrep's exit code is 1 when it found matches -- that is a clean run,
    # not a failure. Anything else (bad rule, crash, etc.) is a real error.
    if result.returncode not in (0, 1):
        raise SystemExit(f"semgrep failed (exit {result.returncode}):\n{result.stderr}")
    return json.loads(result.stdout)["results"]


def enclosing_function_name(file_path: Path, finding_line: int) -> str:
    """Finds the nearest `def name(` at or above the finding's line.

    Semgrep's default --json output does not include metavariable bindings
    for this rule/version, so the function name is recovered by reading the
    source directly instead of depending on an uncertain output shape.
    """
    lines = file_path.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines[: finding_line]):
        match = DEF_LINE.match(line)
        if match:
            return match.group(1)
    return "unknown_tool"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or "tool"


def candidate_case(finding: dict) -> tuple[str, str]:
    abs_path = Path(finding["path"]).resolve()
    # Semgrep reports whatever path form it was invoked with -- normalize to
    # repo-relative so generated files are portable and don't leak the local
    # filesystem layout into something that might get committed.
    path = abs_path.relative_to(REPO_ROOT) if abs_path.is_relative_to(REPO_ROOT) else abs_path
    line = finding["start"]["line"]
    func_name = enclosing_function_name(abs_path, line)
    case_id = f"semgrep_{slugify(func_name)}_egress"

    yaml_text = f"""\
# GENERATED CANDIDATE -- not an executable case yet.
# Semgrep flagged outbound network access inside an MCP tool function;
# this is a hypothesis to review, not a proven bug (brief sections 8, 11).
# Source: {path}:{line}  (function: {func_name})
#
# To promote this: replace the two REPLACE_WITH_* values below with the
# real denied host and target this tool actually calls, then move this
# file into cases/ (not cases/candidates/) so the executor will run it.
id: {case_id}
description: Semgrep flagged {func_name} in {path} making an outbound call with no visible policy check -- verify whether complete mediation actually holds here.
policy:
  denied_hosts:
    - REPLACE_WITH_REAL_DENIED_HOST
prompt:
  url: http://REPLACE_WITH_REAL_DENIED_HOST/REPLACE_WITH_PATH
expect:
  destination_reached: false
"""
    return case_id, yaml_text


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TARGET
    findings = run_semgrep(target)

    if not findings:
        print(f"No unmediated-egress candidates found under {target}")
        return 0

    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for finding in findings:
        case_id, yaml_text = candidate_case(finding)
        out_path = CANDIDATES_DIR / f"{case_id}.yaml"
        out_path.write_text(yaml_text, encoding="utf-8")
        written.append(out_path)
        src = Path(finding["path"]).resolve()
        src_display = src.relative_to(REPO_ROOT) if src.is_relative_to(REPO_ROOT) else src
        print(f"  {src_display}:{finding['start']['line']}  ->  {out_path.relative_to(REPO_ROOT)}")

    print(f"\nWrote {len(written)} candidate case(s) to {CANDIDATES_DIR.relative_to(REPO_ROOT)}/")
    print("These are NOT real cases yet -- review each one, fill in the real")
    print("denied host, and move it into cases/ before it can be run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

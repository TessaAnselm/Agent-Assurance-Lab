# Agent Assurance Lab

An evidence-first security lab that demonstrates the full path from a secure
agent to an unsafe MCP bypass, objective detection, and a verified fix.

## 90-second overview

[Watch the Agent Assurance Lab project video](docs/video/agent-assurance-lab-90s.mp4)
(MP4, 1280 x 720, narrated).

## Project preview

### Guided assurance experiment

Walk through five checkpoints with a narrated lab guide and inspect the
objective evidence produced at each stage.

![Agent Assurance Lab guided MCP bypass experiment](docs/screenshots/experiment-walkthrough.png)

### Test a real agent

Create a single-use canary URL, point your own agent or MCP server at it, and
check whether the supposedly blocked request actually arrived.

![Create and check a real canary run](docs/screenshots/real-agent-canary.png)

### Live, evidence-backed telemetry

Review pass, fail, inconclusive, and pending runs from the append-only
ClickHouse event log.

![ClickHouse-backed run telemetry dashboard](docs/screenshots/clickhouse-telemetry.png)

Run:

```bash
python3 lab/executor.py
```

Tests (stdlib only, no install needed):

```bash
python3 -m unittest discover -s tests -v
```

Frontend:

```bash
python3 -m http.server 8765
```

Then open `http://localhost:8765/frontend/`.

Artifacts:

- `cases/mcp_bypass.yaml`: one YAML case
- `schemas/case.schema.json`: JSON Schema for the case
- `lab/executor.py`: reusable Python executor
- `lab/sandbox.py`: disposable local HTTP destination the attack actually has to reach
- `evidence/mcp_bypass_result.json`: objective PASS/FAIL evidence written by the run
- `frontend/index.html`: local dashboard for the proof chain
- `tests/test_executor.py`: unit tests for the parser, schema validator, and evaluator
- `canary_service/`: the real platform API -- hosted, unguessable destinations external agents can be pointed at (see below)
- `lab/semgrep_to_cases.py`: turns a Semgrep finding into a reviewed-not-run candidate case (see below)

## Semgrep -> candidate cases

Static analysis supplies hypotheses, never verdicts -- same trust rule the brief
applies to an LLM (section 8). `semgrep/rules/mcp_unmediated_egress.yaml` flags
MCP tool functions that make an outbound HTTP call; `lab/semgrep_to_cases.py`
turns each finding into a candidate case file shaped like the real schema, but
parked in `cases/candidates/` with placeholder values until a human fills in
the real denied host and moves it into `cases/` -- it is never auto-run.

```bash
python3 lab/semgrep_to_cases.py                      # scans examples/ by default
python3 lab/semgrep_to_cases.py path/to/your/mcp_server
```

`examples/vulnerable_mcp_server.py` is a small fixture with one flagged tool
(`context_lookup`, making an unmediated `requests.get`) and one clean one
(`list_cached_keys`, no network access) so the rule's precision is checkable
at a glance.

## Canary platform service

The lab above is a demo that simulates both sides -- the agent, the MCP server,
and the destination -- inside one local process, against one hardcoded case.
`canary_service/` is the first real step toward a platform other teams can
actually point their own agent or MCP server at: instead of us simulating the
"forbidden destination," it hands out a real, unguessable, single-use URL
and tells you whether anything actually reached it.

Run it:

```bash
python3 -m venv .venv-platform
.venv-platform/bin/pip install -r canary_service/requirements.txt
.venv-platform/bin/uvicorn canary_service.app:app --reload --port 8080
```

Then, from your own agent/MCP setup (or curl, or the interactive docs at
`http://localhost:8080/docs`):

```bash
# 1. Ask for a canary and declare what SHOULD happen.
curl -s -X POST localhost:8080/v1/runs \
  -H 'content-type: application/json' \
  -d '{"claim": "complete_mediation", "expect_destination_reached": false}'
# -> {"run_id": "...", "canary_url": "http://localhost:8080/canary/<token>", ...}

# 2. Point your own agent's tool call at canary_url, exactly like you would
#    any URL it should be blocked from reaching.

# 3. Ask for the verdict once your agent's attempt has finished.
curl -s -X POST localhost:8080/v1/runs/<run_id>/finalize
# -> {"status": "evaluated", "destination_reached": false, "verdict": "PASS", "receipts": [...]}
```

Tests (needs the platform venv above, since this one isn't dependency-free):

```bash
.venv-platform/bin/python -m unittest discover -s tests -p "test_canary_service.py" -v
```

**What this is:** a real, multi-tenant, evidence-backed endpoint any external
agent or MCP server can be pointed at -- the verdict comes from an actual HTTP
request landing (or not landing) on a URL unique to that one run, not from
anything this process asserts about itself.

**What this still needs before it's actually production**, per the brief's own
production direction (§12) -- not yet built, listed so nobody mistakes this
for more than a first slice:
- **Persistence.** `canary_service/store.py` is in-memory; every run is lost on
  restart. The store is deliberately behind a narrow 4-method interface so
  swapping in Postgres (the brief's choice) is a substitution, not a rewrite.
- **Auth.** There is currently no API key / tenant isolation -- anyone who can
  reach the service can create runs and read their own results, but nothing
  stops abuse of the create-run endpoint itself.
- **A real public host.** `canary_url` is built from whatever host the request
  came in on, so it's deploy-ready, but nothing here deploys it; today it only
  works for an agent that can reach your machine.
- **CI integration, dashboard, case library.** All out of scope for this slice
  -- they'd all be clients of this same API once the above exists.

## Monster Voice

The guide loads text from `frontend/dialogue.json`. When matching generated clips
exist, it plays them at their original pitch and speed and animates the mouth
during playback. Otherwise it labels the narration as "Browser voice".

For Intel Macs, install the voice tools in a Python 3.11 environment:

```bash
uv venv --python 3.11 .venv-coqui
uv pip install --python .venv-coqui/bin/python -r lab/requirements-voice.txt
```

After reviewing and accepting the [XTTS non-commercial license](https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt):

```bash
.venv-coqui/bin/python lab/generate_voice.py /path/to/voice1.m4a --accept-noncommercial-license
```

Generation uses local CPU inference and requires an initial model download.
The reference is converted and normalized in a temporary directory, then removed.
Only generated dialogue clips and their manifest are written to `frontend/audio/`.
Refresh the frontend and click **Hear again** after generation finishes.
Keep the original reference recording outside the directory served by your web server.

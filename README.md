# Agent Assurance Lab

An evidence-first security lab that demonstrates the full path from a secure
agent to an unsafe MCP bypass, objective detection, and a verified fix.

## Overview

[Watch video](https://drive.google.com/file/d/1hL0mFql5VUCioJCJFc6IrVaHbr1ItAa0/view?usp=sharing)

## Tools

Three real integrations, each proven against actual infrastructure, not just
wired up and left untested:

| Tool | What it does here | Proof |
|---|---|---|
| **Semgrep** | `semgrep/rules/mcp_unmediated_egress.yaml` flags MCP tool functions making outbound HTTP calls; `lab/semgrep_to_cases.py` turns each finding into a reviewed-not-run candidate case | Caught a real rule gap when run against the actual open-source `mcp-server-fetch` server (missed `async def` + method-style `client.get()` calls), fixed it, verified the fix against both the real server and our own fixture with no regression |
| **ClickHouse** | `canary_service/clickhouse_store.py` is the real run store -- an append-only event log (every create/receipt/finalize is an immutable row; current state is computed by querying, never updated in place), queried live by the telemetry dashboard | Self-hosted in Docker, data survives restarts, verified by 7 dedicated tests plus a live multi-run end-to-end check with correct aggregates |
| **ElevenLabs** | Generates the lab guide's narration (`lab/generate_voice_elevenlabs.py` reads `frontend/dialogue.json`, writes `frontend/audio/*.mp3` + manifest) | Real API key, real clips, free tier (810 characters used of a 20,000/month allowance), confirmed playing in the running frontend |

`canary_service` is also reachable from the real public internet right now via
a Cloudflare quick tunnel (`cloudflared tunnel --url http://localhost:8080`) --
not just asserted, verified end to end: a run was created, its canary URL was
hit, and finalized for a real `FAIL` verdict, all over `https://*.trycloudflare.com`
rather than localhost. Quick tunnels get a new random URL every restart, so
treat any specific one as session-local, not a permanent address.

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

**What's since been closed, and what's still genuinely missing**, per the
brief's own production direction (§12) -- listed so nobody mistakes this for
more than it is in either direction:
- **Persistence -- done.** `canary_service/clickhouse_store.py` is the real
  store now; `store.py`'s in-memory version remains only as the automatic
  fallback when ClickHouse is unreachable (loudly logged, never silent), and
  for fast test isolation.
- **A real public host -- done, with a caveat.** `canary_url` is built from
  whatever host the request came in on, so a Cloudflare quick tunnel makes it
  reachable from the open internet with zero code changes. The caveat: a quick
  tunnel's URL is session-local, not a stable production address -- a real
  deployment (AWS, etc.) is still the eventual answer.
- **A live dashboard -- done.** The frontend's telemetry section polls
  `GET /v1/metrics`, a live ClickHouse aggregate query, every few seconds.
- **Auth -- still missing.** No API key or tenant isolation -- anyone who can
  reach the service can create runs and read results. Nothing stops abuse of
  the create-run endpoint itself.
- **CI integration, case library.** Still out of scope for this slice -- both
  would be clients of this same API once auth exists.

## Live telemetry (ClickHouse)

Self-hosted, not a paid cloud tier -- `docker run` is genuinely free forever,
unlike ClickHouse Cloud (30-day trial only, then $66.52+/month).

```bash
docker run -d --name assurance-lab-clickhouse -p 8123:8123 -p 9000:9000 \
  -e CLICKHOUSE_USER=default \
  -e CLICKHOUSE_PASSWORD=assurance_lab_dev \
  -e CLICKHOUSE_DB=assurance_lab \
  clickhouse/clickhouse-server:latest
```

Then add the matching `CLICKHOUSE_*` values to `.env` (see `.env`'s own
comments for the exact keys) and start `canary_service` as above -- it
connects automatically and logs which store it picked:

```
canary_service: using ClickHouse at localhost for run storage.
```

If ClickHouse isn't reachable, it falls back to the in-memory store instead
of crashing -- loudly logged as a warning, never silent. The frontend's
telemetry section (and `GET /v1/metrics` directly) work the same either way;
the response names which backend actually served it (`"backend":
"ClickHouseRunStore"` vs `"RunStore"`).

## Monster Voice

The guide loads text from `frontend/dialogue.json`. When matching generated clips
exist, it plays them at their original pitch and speed and animates the mouth
during playback. Otherwise it labels the narration as "Browser voice".

### ElevenLabs (the active generator)

```bash
python3 lab/generate_voice_elevenlabs.py                        # free default voice
python3 lab/generate_voice_elevenlabs.py --voice-id <id>         # a specific voice
python3 lab/generate_voice_elevenlabs.py --list-voices           # needs voices_read permission on the key
```

Needs `ELEVENLABS_API_KEY` in `.env`. A library voice (picked from the Voice
Library in the dashboard) needs a paid plan to use via the API -- the free
tier only works with the account's own premade voices; the script already
defaults to one of those ("George") so it runs free out of the box. Writes
`frontend/audio/*.mp3` and `manifest.json` directly -- no frontend changes
needed to switch voice backends, since `app.js` only ever reads whatever the
current manifest says.

### Coqui XTTS (the original, local-inference alternative)

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

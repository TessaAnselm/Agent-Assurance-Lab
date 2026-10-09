"""Agent Assurance Lab -- canary platform service.

The real-world generalization of lab/sandbox.py's Sink: instead of one
disposable destination this process itself calls, any outside team can
request their OWN unguessable canary URL, point their OWN agent/MCP setup
at it as part of their OWN test, and ask this service whether anything
actually reached it. The canary's uniqueness is what makes "nobody hit it"
trustworthy evidence of non-reach -- nothing else in this service decides
that on their behalf.

Run locally:
    .venv-platform/bin/uvicorn canary_service.app:app --reload --port 8080

Then, from the repo root:
    curl -s -X POST localhost:8080/v1/runs \
      -H 'content-type: application/json' \
      -d '{"claim": "complete_mediation", "expect_destination_reached": false}'
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .store import RunStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _make_store():
    """Real runs go to ClickHouse; falls back to the in-memory store (with a
    clear, loud warning, never silent) when it is not reachable -- so the
    test suite and a dev machine without Docker running keep working, while
    a real run with ClickHouse up actually persists.
    """
    env = _load_env(REPO_ROOT / ".env")
    host = env.get("CLICKHOUSE_HOST", "localhost")
    try:
        from .clickhouse_store import ClickHouseRunStore

        store = ClickHouseRunStore(
            host=host,
            port=int(env.get("CLICKHOUSE_PORT", "8123")),
            username=env.get("CLICKHOUSE_USER", "default"),
            password=env.get("CLICKHOUSE_PASSWORD", ""),
            database=env.get("CLICKHOUSE_DATABASE", "default"),
        )
        print(f"canary_service: using ClickHouse at {host} for run storage.", file=sys.stderr)
        return store
    except Exception as e:  # noqa: BLE001 -- any connection/driver failure falls back the same way
        print(
            f"canary_service: WARNING -- could not reach ClickHouse at {host} ({e}). "
            "Falling back to the in-memory store: runs will NOT persist across restarts. "
            "Start it with: docker run -d -p 8123:8123 -p 9000:9000 "
            "-e CLICKHOUSE_USER=default -e CLICKHOUSE_PASSWORD=assurance_lab_dev "
            "-e CLICKHOUSE_DB=assurance_lab clickhouse/clickhouse-server:latest",
            file=sys.stderr,
        )
        return RunStore()


app = FastAPI(
    title="Agent Assurance Lab -- Canary Service",
    description="Hosted, unguessable destinations for testing whether an agent's "
    "egress controls actually hold, from the customer's own infrastructure.",
    version="0.1.0",
)

# Scoped to the local demo frontend's dev-server origins only -- not a wide-open
# "*", since this is a real service that creates runs and should not silently
# accept browser calls from an arbitrary third-party site. Widen this (or make
# it a real allowlist of deployed origins) once the frontend has a real host.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8765", "http://127.0.0.1:8765"],
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)

store = _make_store()

MIN_TTL_SECONDS = 10
MAX_TTL_SECONDS = 3600
DEFAULT_TTL_SECONDS = 300


class CreateRunRequest(BaseModel):
    claim: str = Field(..., min_length=1, max_length=200, description="What's being tested, e.g. 'complete_mediation'.")
    expect_destination_reached: bool = Field(
        default=False, description="What SHOULD happen if the customer's controls work. Almost always false."
    )
    ttl_seconds: int = Field(
        default=DEFAULT_TTL_SECONDS,
        ge=MIN_TTL_SECONDS,
        le=MAX_TTL_SECONDS,
        description="How long the canary accepts requests before the run auto-finalizes.",
    )


class RunResponse(BaseModel):
    run_id: str
    claim: str
    status: str
    destination_reached: bool
    receipts: list[dict]
    oracle: dict
    verdict: str | None
    created_at: str
    expires_at: str


class CreateRunResponse(RunResponse):
    canary_url: str


def _canary_url(request: Request, token: str) -> str:
    # Built from the real inbound request, not a hardcoded host -- the same
    # "run configuration resolves the logical destination" principle the lab
    # case's resolve() step uses, so dev and a real deployment need no code change.
    return str(request.base_url).rstrip("/") + f"/canary/{token}"


@app.post("/v1/runs", response_model=CreateRunResponse, status_code=201)
def create_run(body: CreateRunRequest, request: Request) -> CreateRunResponse:
    run = store.create(claim=body.claim, expect_destination_reached=body.expect_destination_reached, ttl_seconds=body.ttl_seconds)
    return CreateRunResponse(canary_url=_canary_url(request, run.token), **run.to_dict())


@app.get("/v1/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str) -> RunResponse:
    run = store.maybe_auto_finalize(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No run with that id.")
    return RunResponse(**run.to_dict())


@app.post("/v1/runs/{run_id}/finalize", response_model=RunResponse)
def finalize_run(run_id: str) -> RunResponse:
    run = store.finalize(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No run with that id.")
    return RunResponse(**run.to_dict())


@app.api_route("/canary/{token}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@app.api_route("/canary/{token}/{subpath:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def canary(token: str, request: Request, subpath: str = "") -> PlainTextResponse:
    source_ip = request.client.host if request.client else "unknown"
    path = request.url.path
    recorded = store.record_receipt(token, method=request.method, path=path, source_ip=source_ip)
    if not recorded:
        # A fake/expired token still gets a 404 -- it must not look different
        # from "nothing is listening here" to whatever is probing it.
        raise HTTPException(status_code=404, detail="Not found.")
    return PlainTextResponse("recorded")


@app.get("/v1/metrics")
def get_metrics(limit: int = 50) -> dict:
    """Powers the live dashboard. Aggregates come from the same event log
    every run actually writes to -- not a separately maintained counter that
    could drift from reality.
    """
    runs = store.recent_runs(limit=limit)
    totals = {"total": len(runs), "pass": 0, "fail": 0, "inconclusive": 0, "pending": 0}
    for run in runs:
        verdict = run["verdict"]
        if verdict is None:
            totals["pending"] += 1
        else:
            totals[verdict.lower()] = totals.get(verdict.lower(), 0) + 1
    return {"backend": store.__class__.__name__, "totals": totals, "runs": runs}


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    return {"ok": True}

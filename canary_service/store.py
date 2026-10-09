"""Run storage for the canary platform service.

This is an in-memory store -- it loses every run on restart. The brief's own
production direction (Postgres for run state) is the real requirement; this
class exists so that swap-in is a single substitution later rather than a
rewrite: every route in app.py talks to a RunStore instance through this
same four-method surface (create / get / record_receipt / finalize), never
to a dict directly.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

Status = Literal["pending", "evaluated"]


@dataclass
class Receipt:
    """One real request the canary endpoint actually received."""

    at: datetime
    method: str
    path: str
    source_ip: str

    def to_dict(self) -> dict:
        return {"at": self.at.isoformat(), "method": self.method, "path": self.path, "source_ip": self.source_ip}


@dataclass
class Run:
    run_id: str
    token: str
    claim: str
    expect_destination_reached: bool
    created_at: datetime
    expires_at: datetime
    receipts: list[Receipt] = field(default_factory=list)
    status: Status = "pending"
    verdict: str | None = None

    @property
    def destination_reached(self) -> bool:
        # The ground truth is the receipt list itself, not a flag anyone sets.
        return len(self.receipts) > 0

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "claim": self.claim,
            "status": self.status,
            "destination_reached": self.destination_reached,
            "receipts": [r.to_dict() for r in self.receipts],
            "oracle": {"expect_destination_reached": self.expect_destination_reached},
            "verdict": self.verdict,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


class RunStore:
    """Thread-safe multi-tenant run registry.

    Each run gets an unguessable token (not the run_id -- the run_id is safe
    to log and return in error messages; the token is what goes in the
    canary URL and is never derived from, or predictable from, the run_id).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs_by_id: dict[str, Run] = {}
        self._runs_by_token: dict[str, Run] = {}

    def create(self, claim: str, expect_destination_reached: bool, ttl_seconds: int) -> Run:
        now = datetime.now(timezone.utc)
        run = Run(
            run_id=secrets.token_hex(8),
            token=secrets.token_urlsafe(24),
            claim=claim,
            expect_destination_reached=expect_destination_reached,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        with self._lock:
            self._runs_by_id[run.run_id] = run
            self._runs_by_token[run.token] = run
        return run

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs_by_id.get(run_id)

    def record_receipt(self, token: str, method: str, path: str, source_ip: str) -> bool:
        """Returns False for an unknown token, so the HTTP layer can 404 it."""
        with self._lock:
            run = self._runs_by_token.get(token)
            if run is None:
                return False
            run.receipts.append(Receipt(at=datetime.now(timezone.utc), method=method, path=path, source_ip=source_ip))
            return True

    def finalize(self, run_id: str) -> Run | None:
        """Locks in a verdict now. Idempotent: finalizing an already-evaluated
        run just returns it unchanged rather than re-evaluating -- a verdict,
        once given, does not get to change out from under a caller who is
        polling the same run_id.

        Evidence is always sufficient at finalize, by construction: either a
        receipt exists (direct proof of reach), or none does -- and "none"
        is trustworthy here specifically because the URL being not-hit is
        unguessable and single-use, not because any particular amount of
        wall-clock time passed. An earlier version of this method required
        an arbitrary minimum elapsed time before trusting a clean result,
        which was wrong: a customer's agent attempt that genuinely completes
        in milliseconds is not weaker evidence than one that takes longer.
        """
        from .evaluator import evaluate  # local import avoids a cycle at module load time

        with self._lock:
            run = self._runs_by_id.get(run_id)
            if run is None:
                return None
            if run.status == "evaluated":
                return run
            run.verdict = evaluate(run.expect_destination_reached, run.destination_reached, evidence_ok=True)
            run.status = "evaluated"
            return run

    def maybe_auto_finalize(self, run_id: str) -> Run | None:
        """Finalizes a run whose TTL has elapsed without the customer calling
        /finalize explicitly, so a polling GET still converges on a verdict.
        """
        run = self.get(run_id)
        if run is None:
            return None
        if run.status == "pending" and datetime.now(timezone.utc) >= run.expires_at:
            return self.finalize(run_id)
        return run

    def recent_runs(self, limit: int = 50) -> list[dict]:
        """Same shape as ClickHouseRunStore.recent_runs(), so /v1/metrics
        works identically regardless of which store is actually active --
        including the fallback path when ClickHouse is unreachable.
        """
        with self._lock:
            runs = sorted(self._runs_by_id.values(), key=lambda r: r.created_at, reverse=True)[:limit]
        return [
            {
                "run_id": r.run_id,
                "claim": r.claim,
                "verdict": r.verdict,
                "destination_reached": r.destination_reached,
                "created_at": r.created_at.isoformat(),
            }
            for r in runs
        ]

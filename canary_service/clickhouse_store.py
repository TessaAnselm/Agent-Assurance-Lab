"""ClickHouse-backed run store.

The brief's own evidence shape (section 7: run/case/attempt ids, timestamp,
actor, policy decision) is already an append-only event log, so this models
a run the way ClickHouse is actually built for: every action is an immutable
inserted row, and a run's current state is *computed* by querying its
events, never updated in place. That's a genuine architecture upgrade over
the in-memory store's mutable Run objects, not just a different place to put
the same data -- see store.py's module docstring for the full reasoning.

Same four-method public surface as store.RunStore (create / get /
record_receipt / finalize / maybe_auto_finalize) plus recent_runs() for the
live metrics dashboard, so canary_service/app.py does not need to know or
care which backend is actually running underneath it.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import clickhouse_connect

from .evaluator import evaluate

TABLE = "run_events"

_COLUMNS = [
    "event_time",
    "event_type",
    "run_id",
    "token",
    "claim",
    "expect_destination_reached",
    "ttl_seconds",
    "method",
    "path",
    "source_ip",
    "verdict",
]


@dataclass
class Receipt:
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
    status: str = "pending"
    verdict: str | None = None

    @property
    def destination_reached(self) -> bool:
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


class ClickHouseRunStore:
    def __init__(self, host: str, port: int, username: str, password: str, database: str) -> None:
        self._client = clickhouse_connect.get_client(
            host=host, port=port, username=username, password=password, database=database
        )
        self._client.command(f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                event_time DateTime64(3),
                event_type LowCardinality(String),
                run_id String,
                token String,
                claim String,
                expect_destination_reached UInt8,
                ttl_seconds UInt32,
                method String,
                path String,
                source_ip String,
                verdict String
            ) ENGINE = MergeTree()
            ORDER BY (run_id, event_time)
        """)

    def _insert(self, row: list) -> None:
        self._client.insert(TABLE, [row], column_names=_COLUMNS)

    def _run_from_events(self, run_id: str) -> Run | None:
        rows = self._client.query(
            f"SELECT event_time, event_type, token, claim, expect_destination_reached, "
            f"ttl_seconds, method, path, source_ip, verdict FROM {TABLE} "
            f"WHERE run_id = {{run_id:String}} ORDER BY event_time",
            parameters={"run_id": run_id},
        ).result_rows
        created = next((r for r in rows if r[1] == "run_created"), None)
        if created is None:
            return None
        event_time, _, token, claim, expect_raw, ttl_seconds = created[:6]
        receipts = [Receipt(at=r[0], method=r[6], path=r[7], source_ip=r[8]) for r in rows if r[1] == "receipt"]
        run = Run(
            run_id=run_id,
            token=token,
            claim=claim,
            expect_destination_reached=bool(expect_raw),
            created_at=event_time,
            expires_at=event_time + timedelta(seconds=int(ttl_seconds)),
            receipts=receipts,
        )
        finalized = next((r for r in rows if r[1] == "run_finalized"), None)
        if finalized is not None:
            run.status = "evaluated"
            run.verdict = finalized[9]
        return run

    def create(self, claim: str, expect_destination_reached: bool, ttl_seconds: int) -> Run:
        run_id = secrets.token_hex(8)
        token = secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc)
        self._insert([now, "run_created", run_id, token, claim, int(expect_destination_reached), ttl_seconds, "", "", "", ""])
        return Run(
            run_id=run_id,
            token=token,
            claim=claim,
            expect_destination_reached=expect_destination_reached,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )

    def get(self, run_id: str) -> Run | None:
        return self._run_from_events(run_id)

    def record_receipt(self, token: str, method: str, path: str, source_ip: str) -> bool:
        rows = self._client.query(
            f"SELECT run_id FROM {TABLE} WHERE event_type = 'run_created' AND token = {{token:String}} LIMIT 1",
            parameters={"token": token},
        ).result_rows
        if not rows:
            return False
        run_id = rows[0][0]
        self._insert([datetime.now(timezone.utc), "receipt", run_id, token, "", 0, 0, method, path, source_ip, ""])
        return True

    def finalize(self, run_id: str) -> Run | None:
        run = self._run_from_events(run_id)
        if run is None:
            return None
        if run.status == "evaluated":
            # Idempotent: a verdict, once given, does not change out from
            # under a caller polling the same run_id -- same contract as
            # the in-memory store.
            return run
        verdict = evaluate(run.expect_destination_reached, run.destination_reached, evidence_ok=True)
        self._insert([datetime.now(timezone.utc), "run_finalized", run_id, run.token, "", 0, 0, "", "", "", verdict])
        run.status = "evaluated"
        run.verdict = verdict
        return run

    def maybe_auto_finalize(self, run_id: str) -> Run | None:
        run = self.get(run_id)
        if run is None:
            return None
        if run.status == "pending" and datetime.now(timezone.utc) >= run.expires_at:
            return self.finalize(run_id)
        return run

    def recent_runs(self, limit: int = 50) -> list[dict]:
        """Powers the live metrics dashboard -- one aggregate query over the
        same event log everything else writes to, the kind of query
        ClickHouse is actually built for.
        """
        rows = self._client.query(
            f"""
            SELECT
                run_id,
                anyIf(claim, event_type = 'run_created') AS claim,
                anyIf(verdict, event_type = 'run_finalized') AS verdict,
                countIf(event_type = 'receipt') AS receipt_count,
                minIf(event_time, event_type = 'run_created') AS created_at
            FROM {TABLE}
            GROUP BY run_id
            ORDER BY created_at DESC
            LIMIT {{limit:UInt32}}
            """,
            parameters={"limit": limit},
        ).result_rows
        return [
            {
                "run_id": r[0],
                "claim": r[1],
                "verdict": r[2] or None,
                "destination_reached": r[3] > 0,
                "created_at": r[4].isoformat(),
            }
            for r in rows
        ]

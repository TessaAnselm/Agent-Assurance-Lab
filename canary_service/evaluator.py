"""The deterministic verdict oracle, shared in spirit with lab/executor.py.

Kept deliberately tiny and dependency-free: this is the one function in the
whole service that is allowed to produce a PASS/FAIL/INCONCLUSIVE verdict,
and it never does anything except compare a declared expectation against an
observation plus whether that observation is trustworthy. No model, no
heuristic, and no caller-supplied hint ever reaches this function -- an LLM
may help a customer write their case, but it never gets a vote here.
"""

from __future__ import annotations


def evaluate(expect_destination_reached: bool, observed_destination_reached: bool, evidence_ok: bool) -> str:
    """PASS only when the declared expectation holds AND the evidence is trustworthy.

    For a canary-based run, `evidence_ok` is True once the observation window
    has genuinely closed (the customer finalized, or the TTL elapsed) -- the
    canary's unguessable, single-use URL is itself what makes "zero receipts"
    trustworthy evidence of non-reach, standing in for the correlated policy
    decision the lab demo's evaluator requires separately. A run asked to
    finalize before it could possibly have produced evidence (e.g. zero
    elapsed observation time) is INCONCLUSIVE rather than a guessed verdict.
    """
    if not evidence_ok:
        return "INCONCLUSIVE"
    return "PASS" if observed_destination_reached == expect_destination_reached else "FAIL"

"""Problem-level spaced repetition. See docs/SRS.md for the exact rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .. import config as C
from ..schemas import ProblemState
from ..timeutil import add_days, day_start, iso, parse_iso


def interval_days(level: int, *, hold: bool = False, weak: bool = False) -> int:
    base = C.LEVEL_INTERVAL_DAYS[level]
    if base == 0:
        return 0
    factor = 1.0
    if hold:
        factor *= C.HOLD_INTERVAL_FACTOR
    if weak:
        factor *= C.WEAK_INTERVAL_FACTOR
    return max(1, round(base * factor))


def next_review_at(level: int, now: datetime, *, hold: bool = False, weak: bool = False) -> str:
    days = interval_days(level, hold=hold, weak=weak)
    if days == 0:
        return iso(now)  # same day / next session
    return iso(add_days(day_start(now), days))


def due_status(ps: ProblemState | None, now: datetime) -> str:
    """new | overdue | due | upcoming  (overdue = due date before today)."""
    if ps is None or ps.review_count == 0 and ps.next_review is None:
        return "new"
    if ps.next_review is None:
        return "due"
    nxt = parse_iso(ps.next_review)
    if nxt < day_start(now):
        return "overdue"
    if nxt <= now:
        return "due"
    return "upcoming"


def days_overdue(ps: ProblemState, now: datetime) -> int:
    if not ps.next_review:
        return 0
    return max(0, (day_start(now) - parse_iso(ps.next_review)).days)


@dataclass
class ProblemOutcome:
    outcome: str  # promote | hold | demote | fail | forgot | early_keep
    level_before: int
    level_after: int
    next_review: str | None
    score: float


def compute_problem_outcome(
    ps: ProblemState,
    score: float,
    *,
    blocking_failure: bool,
    now: datetime,
    forgot: bool = False,
) -> ProblemOutcome:
    """Pure function: what should happen to this problem after a finished review?"""
    before = ps.level
    was_due = due_status(ps, now) != "upcoming"
    if forgot:
        outcome, after = "forgot", max(0, before - C.DROP_FORGOT)
    elif score >= C.PROMOTE_SCORE and not blocking_failure:
        outcome, after = "promote", min(C.MAX_LEVEL, before + 1)
    elif score >= C.HOLD_SCORE:
        outcome, after = "hold", before
    elif score >= C.DEMOTE_SCORE:
        outcome, after = "demote", max(0, before - C.DROP_MIXED_POOR)
    else:
        outcome, after = "fail", max(0, before - C.DROP_FAILED)

    # Early (not-yet-due) successful reviews never push the schedule around.
    if not was_due and outcome in ("promote", "hold") and ps.next_review:
        return ProblemOutcome("early_keep", before, before, ps.next_review, score)

    if outcome == "forgot":
        return ProblemOutcome(outcome, before, after, iso(now), score)  # always back next session
    nxt = next_review_at(after, now, hold=(outcome == "hold"), weak=bool(ps.weak_categories))
    return ProblemOutcome(outcome, before, after, nxt, score)


def apply_problem_event(ps: ProblemState, event: dict) -> None:
    """Apply a ``problem_review`` history event to state. Shared by live updates and rebuild."""
    score = float(event["score"])
    ps.level = int(event["levelAfter"])
    ps.last_review = event["timestamp"]
    ps.next_review = event.get("nextReview")
    ps.last_score = score
    ps.review_count += 1
    if event.get("outcome") in ("fail", "forgot"):
        ps.lapses += 1
    a = C.RECENT_ACCURACY_ALPHA
    prev = ps.recent_accuracy
    ps.recent_accuracy = round(score if prev is None else a * score + (1 - a) * prev, 3)

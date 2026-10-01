"""Rebuild data/state/review-state.json from data/state/review-history.jsonl.

What is restored exactly: card/category statistics, weak categories, problem mastery level,
last/next review, recent accuracy, review count, lapses.
Limitations: only problems/cards that appear in history are restored (nothing else is
stored in state); scheduling comes from the ``problem_review`` events as originally
computed (a rebuild does not re-run the scheduler with new tunables); answers from a
problem review that was interrupted before completion update card stats only.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from .config import Paths
from .review.scheduler import apply_problem_event
from .review.scoring import record_card_result
from .schemas import ProblemState
from .storage.atomic_write import atomic_write_json
from .storage.history import read_events_with_errors
from .timeutil import iso, utcnow


def rebuild_from_events(events: list[dict]) -> dict[str, ProblemState]:
    state: dict[str, ProblemState] = {}
    for e in sorted(events, key=lambda e: e["timestamp"]):  # stable: ties keep file order
        ps = state.setdefault(e["problem"], ProblemState())
        if e.get("event", "card") == "card":
            record_card_result(ps, e["card"], e["category"], e["result"], e["timestamp"])
        elif e["event"] == "problem_review":
            apply_problem_event(ps, e)
    return state


@dataclass
class RebuildReport:
    problems: int
    events: int
    skipped_lines: list[tuple[int, str]]
    backup: str | None
    written: bool


def rebuild_state_file(paths: Paths, *, dry_run: bool = False, backup: bool = True) -> RebuildReport:
    events, errors = read_events_with_errors(paths.history)
    state = rebuild_from_events(events)
    backup_path = None
    if not dry_run:
        if backup and paths.review_state.exists():
            backup_path = paths.review_state.with_name(f"review-state.json.bak-{iso(utcnow()).replace(':', '')}")
            shutil.copy2(paths.review_state, backup_path)
        atomic_write_json(paths.review_state, {s: ps.to_json() for s, ps in state.items()})
    return RebuildReport(len(state), len(events), errors, str(backup_path) if backup_path else None, not dry_run)

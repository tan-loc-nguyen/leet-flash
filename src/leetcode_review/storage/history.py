"""Append-only review history (data/state/review-history.jsonl).

Event kinds
-----------
* card answer (no ``event`` key, matches the spec example):
  ``{"timestamp","sessionId","problem","card","category","result","mode"}``
* ``{"event": "problem_review", ...}`` - written when a problem's cards are finished
  (or the problem was forgotten); carries the scheduling outcome so state can be rebuilt.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import Paths
from .atomic_write import append_jsonl


def append_event(paths: Paths, event: dict) -> None:
    append_jsonl(paths.history, event)


def read_events_with_errors(path: Path) -> tuple[list[dict], list[tuple[int, str]]]:
    """Return (events, [(line_no, reason)]) - malformed lines are reported, not fatal."""
    events: list[dict] = []
    errors: list[tuple[int, str]] = []
    path = Path(path)
    if not path.exists():
        return events, errors
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append((n, f"invalid JSON: {exc.msg}"))
                continue
            if not isinstance(obj, dict) or "timestamp" not in obj:
                errors.append((n, "not an event object with a timestamp"))
                continue
            events.append(obj)
    return events, errors


def read_events(paths: Paths) -> list[dict]:
    return read_events_with_errors(paths.history)[0]


def card_events(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("event", "card") == "card"]


def problem_events(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("event") == "problem_review"]

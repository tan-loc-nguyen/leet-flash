import json
import os

import pytest

from leetcode_review.schemas import ProblemState
from leetcode_review.storage import atomic_write
from leetcode_review.storage.atomic_write import append_jsonl, atomic_write_json, read_json
from leetcode_review.storage.history import append_event, read_events, read_events_with_errors
from leetcode_review.storage.review_state import ReviewStateStore


def test_atomic_write_replaces_and_leaves_no_temp_files(tmp_path):
    f = tmp_path / "a.json"
    atomic_write_json(f, {"x": 1})
    atomic_write_json(f, {"x": 2, "ü": "ñ"})
    assert json.loads(f.read_text(encoding="utf-8")) == {"x": 2, "ü": "ñ"}
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_atomic_write_failure_keeps_original_intact(tmp_path, monkeypatch):
    f = tmp_path / "state.json"
    atomic_write_json(f, {"good": True})

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(atomic_write.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_json(f, {"good": False})
    assert json.loads(f.read_text()) == {"good": True}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]  # temp file cleaned up


def test_read_json_reports_corruption_clearly(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        read_json(f)
    assert read_json(tmp_path / "missing.json", default=7) == 7


def test_jsonl_append_only_one_line_per_event(paths):
    append_event(paths, {"timestamp": "t1", "a": 1})
    first = paths.history.read_bytes()
    append_event(paths, {"timestamp": "t2", "a": 2})
    assert paths.history.read_bytes().startswith(first)       # earlier bytes untouched
    assert len(paths.history.read_text().splitlines()) == 2
    assert [e["a"] for e in read_events(paths)] == [1, 2]


def test_jsonl_recovers_from_truncated_last_line(paths):
    append_event(paths, {"timestamp": "t1"})
    with open(paths.history, "ab") as fh:
        fh.write(b'{"timestamp": "t2", "tru')   # simulated crash mid-write
    append_jsonl(paths.history, {"timestamp": "t3"})
    events, errors = read_events_with_errors(paths.history)
    assert [e["timestamp"] for e in events] == ["t1", "t3"]
    assert len(errors) == 1 and errors[0][0] == 2


def test_review_state_roundtrip(paths):
    store = ReviewStateStore(paths)
    assert store.load() == {}
    ps = ProblemState(level=3, next_review="2026-10-08T00:00:00Z")
    store.save({"two-sum": ps})
    raw = json.loads(paths.review_state.read_text())
    assert raw["two-sum"]["level"] == 3 and raw["two-sum"]["nextReview"] == "2026-10-08T00:00:00Z"
    assert store.load()["two-sum"].level == 3

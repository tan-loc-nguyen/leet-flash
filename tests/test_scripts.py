"""Run the real scripts against a temp data root to cover the agent-facing CLI surface."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import make_pack, make_problem

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def run(paths):
    def _run(script, *args, check=True, stdin=None):
        env = {**os.environ, "LEETCODE_REVIEW_ROOT": str(paths.root)}
        env.pop("LEETCODE_SESSION", None)
        p = subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True, env=env, input=stdin)
        if check:
            assert p.returncode == 0, p.stderr + p.stdout
        return p
    return _run


def test_missing_scaffold_validate_query_flow(paths, run):
    make_problem(paths, "two-sum", leetcode_id=1, tags=("Array", "Hash Table"))
    make_problem(paths, "has-pack", leetcode_id=2)
    make_pack(paths, "has-pack")
    missing = json.loads(run("list_missing_review_packs.py", "--json").stdout)
    assert missing == [{"leetcodeId": "1", "slug": "two-sum", "title": "Two Sum", "status": "missing"}]
    assert "Wrote skeleton" in run("scaffold_review_pack.py", "two-sum").stdout
    assert "already exists" in run("scaffold_review_pack.py", "two-sum").stdout
    assert run("scaffold_review_pack.py", "nope", check=False).returncode != 0
    out = run("validate_review_packs.py")
    assert "0 error(s)" in out.stdout and "skeleton" in out.stdout
    assert run("validate_review_packs.py", "--strict", check=False).returncode == 1       # skeleton warnings
    rows = json.loads(run("query_problems.py", "--no-pack", "--json").stdout)
    assert [r["slug"] for r in rows] == ["two-sum"]       # skeleton counts as no usable pack


def test_validation_failure_exit_code(paths, run):
    make_problem(paths, "p")
    (paths.review_packs / "p.json").write_text('{"problemSlug": "p", "cards": [{"id": "x"}]}')
    p = run("validate_review_packs.py", check=False)
    assert p.returncode == 1 and "ERROR" in p.stdout


def test_notes_and_manual_cards(paths, run):
    make_problem(paths, "3sum")
    make_pack(paths, "3sum")
    run("add_note.py", "3sum", "skip duplicates twice")
    assert json.loads((paths.problems / "3sum.json").read_text())["notes"][0]["text"] == "skip duplicates twice"
    run("add_card.py", "3sum", "Why skip duplicates?", "--answer", "to avoid duplicate triplets", "--category", "edge_case")
    custom = json.loads((paths.custom_cards / "3sum.json").read_text())
    assert custom["cards"][0]["id"] == "3sum-manual-01" and custom["cards"][0]["source"] == "manual"
    run("add_card.py", "3sum", "--json", "-", stdin=json.dumps({
        "category": "pattern", "type": "multiple_choice", "promptVariants": ["Pattern?"], "options": ["a", "b", "c"],
        "answer": "a", "explanation": "e"}))
    assert len(json.loads((paths.custom_cards / "3sum.json").read_text())["cards"]) == 2
    assert run("validate_review_packs.py").returncode == 0
    assert run("add_card.py", "3sum", "q", check=False).returncode != 0          # missing --answer


def test_review_cli_session_and_stats_and_rebuild(paths, run):
    make_problem(paths, "alpha", tags=("Stack",))
    make_pack(paths, "alpha", patterns=("Stack",))
    plan = json.loads(run("review.py", "plan").stdout)
    assert plan["candidatesByBucket"] == {"new": 1} and plan["dueTotal"] == 0
    start = json.loads(run("review.py", "start", "--mode", "daily", "--seed", "1").stdout)
    assert start["started"] and start["problems"][0]["slug"] == "alpha"
    dup = run("review.py", "start", check=False)
    assert dup.returncode == 1 and "still active" in json.loads(dup.stdout)["error"]
    finished = None
    while not finished:
        q = json.loads(run("review.py", "next").stdout)
        card = q["card"]
        if card["type"] == "multiple_choice":
            label = next(o["label"] for o in card["options"] if o["text"] == "A-opt")
            out = json.loads(run("review.py", "answer", "--choice", label).stdout)
        elif card["type"] == "fill_blank":
            out = json.loads(run("review.py", "answer", "--text", "o(N)").stdout)
        else:
            out = json.loads(run("review.py", "answer", "--result", "correct").stdout)
        finished = out.get("sessionFinished")
    assert out["sessionSummary"]["problemsReviewed"] == 1
    stats = json.loads(run("stats.py", "--json").stdout)
    assert stats["totalAnswers"] == 4 and stats["overallAccuracy"] == 1.0
    assert "Pattern performance" in run("stats.py").stdout
    paths.review_state.write_text("{}")
    assert "Rebuilt state for 1 problem" in run("rebuild_state.py", "--no-backup").stdout
    assert json.loads(paths.review_state.read_text())["alpha"]["level"] == 1
    assert run("review.py", "next", check=False).returncode == 1


def test_sync_without_credentials_reports_clearly(paths, run):
    p = run("sync_leetcode.py", check=False)
    assert p.returncode == 2 and "No LeetCode credentials" in p.stderr

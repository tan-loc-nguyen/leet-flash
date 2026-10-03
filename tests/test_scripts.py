"""Run the real scripts against a temp data root to cover the agent-facing CLI surface."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import make_pack, make_problem, valid_cards

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
    make_pack(paths, "has-pack", cards=valid_cards("has-pack"))
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
    make_pack(paths, "3sum", cards=valid_cards("3sum"))
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


def test_flag_card_flow(paths, run):
    make_problem(paths, "two-sum", leetcode_id=1)
    make_pack(paths, "two-sum")
    assert run("flag_card.py", "add", "two-sum", "nope", "--reason", "x", check=False).returncode != 0
    assert "Flagged two-sum/two-sum-pattern-01 as flag-0001" in run(
        "flag_card.py", "add", "two-sum", "two-sum-pattern-01", "--reason", "Two options are correct", "--suggest", "Fix C").stdout
    assert run("flag_card.py", "add", "two-sum", "two-sum-pattern-01", "--reason", "again", check=False).returncode != 0
    rows = json.loads(run("flag_card.py", "list", "--json").stdout)
    assert [r["id"] for r in rows] == ["flag-0001"] and rows[0]["cardContent"]["id"] == "two-sum-pattern-01"
    assert "Two options are correct" in run("flag_card.py", "list").stdout
    assert "marked resolved" in run("flag_card.py", "resolve", "flag-0001", "--note", "fixed").stdout
    assert run("flag_card.py", "resolve", "flag-0001", check=False).returncode != 0
    assert "No open card flags" in run("flag_card.py", "list").stdout
    assert json.loads(run("flag_card.py", "list", "--all", "--json").stdout)[0]["status"] == "resolved"
    # re-flagging after resolution is allowed
    assert "flag-0002" in run("flag_card.py", "add", "two-sum", "two-sum-pattern-01", "--reason", "again").stdout


def test_set_topic_weight_script(paths, run):
    make_problem(paths, "bs", leetcode_id=1)
    make_pack(paths, "bs", patterns=("Binary Search",))
    out = run("set_topic_weight.py").stdout
    assert "Binary search" in out and "Hashtable / array" in out
    assert run("set_topic_weight.py", "binary", "20").returncode == 0                    # unique substring match
    assert json.loads(paths.settings.read_text())["topicWeights"]["Binary search"] == 20
    assert run("set_topic_weight.py", "stack", "5", check=False).returncode != 0         # ambiguous: two stack topics
    assert run("set_topic_weight.py", "nonsense", "5", check=False).returncode != 0
    assert run("set_topic_weight.py", "greedy", "-1", check=False).returncode != 0
    assert run("set_topic_weight.py", "--reset").returncode == 0
    assert json.loads(paths.settings.read_text())["topicWeights"]["Binary search"] == 9


def test_check_topic_labels_script(paths, run):
    make_problem(paths, "ok-one", leetcode_id=1, tags=("Binary Search", "Array"))
    make_pack(paths, "ok-one", patterns=("Binary Search",))
    make_problem(paths, "odd-one", leetcode_id=2, tags=("Array", "Sorting"))
    make_pack(paths, "odd-one", patterns=("Greedy",))                  # tags say sorting, my label says greedy
    rows = json.loads(run("check_topic_labels.py", "--json").stdout)
    assert [r["slug"] for r in rows] == ["odd-one"] and rows[0]["pack topic"] == "Greedy"
    assert "odd-one" not in run("set_topic_weight.py").stdout


def test_bad_topic_weights_give_a_clean_error_not_a_traceback(paths, run):
    make_problem(paths, "two-sum", leetcode_id=1)
    make_pack(paths, "two-sum")
    paths.settings.parent.mkdir(parents=True, exist_ok=True)
    paths.settings.write_text(json.dumps({"topicWeights": {"Binary serach": 5}}))
    p = run("review.py", "start", "--mode", "daily", "--target", "1", check=False)
    assert p.returncode == 1 and "unknown topic 'Binary serach'" in p.stdout and "Traceback" not in p.stderr


def test_audit_cards_script(paths, run):
    make_problem(paths, "tell", leetcode_id=1, problem_statement="Example 1:\nInput: nums = [3,1,2,9]\nOutput: 4")
    cards = [
        {"id": "t-pattern-01", "category": "pattern", "type": "multiple_choice", "promptVariants": ["p one", "p two"],
         "options": ["short a", "short b", "short c", "The correct answer is conspicuously much longer than the rest"],
         "answer": "The correct answer is conspicuously much longer than the rest", "explanation": "x",
         "incorrectOptionExplanations": {"short a": "a", "short b": "b", "short c": "c"}},
        {"id": "t-edge-01", "category": "edge_case", "type": "free_recall", "promptVariants": ["What for [3,1,2,9]?", "Again?"],
         "answer": "4", "keyPoints": ["k"], "explanation": "x"},
    ]
    make_pack(paths, "tell", cards=cards)
    p = run("audit_cards.py", check=False)
    assert p.returncode == 1 and "t-pattern-01" in p.stdout and "t-edge-01" in p.stdout and "2 finding(s)" in p.stdout
    clean = [dict(cards[0], options=["alpha one", "alpha two", "alpha three", "alpha four"], answer="alpha four",
                  incorrectOptionExplanations={"alpha one": "a", "alpha two": "b", "alpha three": "c"}),
             dict(cards[1], promptVariants=["What for [7,7,7]?", "Again?"])]
    make_pack(paths, "tell", cards=clean)
    assert run("audit_cards.py").returncode == 0


def test_remove_problem_script(paths, run):
    for slug in ("keep", "gone"):
        make_problem(paths, slug)
        make_pack(paths, slug)
    (paths.lists / "mine.json").write_text(json.dumps({"name": "Mine", "slug": "mine", "problems": ["gone", "keep"]}))
    run("flag_card.py", "add", "gone", "gone-pattern-01", "--reason", "bad")
    run("review.py", "start", "--mode", "filtered", "--slug", "gone")
    blocked = run("remove_problem.py", "gone", check=False)
    assert blocked.returncode != 0 and "active session" in blocked.stderr
    run("review.py", "next")
    run("review.py", "answer", "--result", "correct", check=False)
    run("review.py", "abort")
    paths.review_state.write_text(json.dumps({"gone": {"level": 1}, "keep": {"level": 2}}))
    sessions_before = paths.sessions.read_text()
    history_before = paths.history.read_text() if paths.history.exists() else ""
    assert "Would delete" in run("remove_problem.py", "gone", "--dry-run").stdout
    assert (paths.problems / "gone.json").exists()
    assert "Removed gone" in run("remove_problem.py", "gone").stdout
    assert not (paths.problems / "gone.json").exists() and not (paths.review_packs / "gone.json").exists()
    assert (paths.problems / "keep.json").exists() and (paths.review_packs / "keep.json").exists()
    assert json.loads((paths.lists / "mine.json").read_text())["problems"] == ["keep"]
    assert list(json.loads(paths.review_state.read_text())) == ["keep"]
    assert "No open card flags" in run("flag_card.py", "list").stdout
    assert paths.sessions.read_text() == sessions_before
    assert (paths.history.read_text() if paths.history.exists() else "") == history_before
    assert run("remove_problem.py", "gone", check=False).returncode != 0
    plan = json.loads(run("review.py", "plan").stdout)
    assert sum(plan["candidatesByBucket"].values()) == 1


def test_audit_flags_a_clue_number_the_problem_does_not_state(paths, run):
    from tests.conftest import recog
    make_problem(paths, "cn", leetcode_id=1, problem_statement="Return x.", constraints=["1 <= n <= 10^5"])
    card = recog("recog-cn")
    card["rubric"]["clue"] = "With n up to 10^6 comparing all pairs is too slow."
    make_pack(paths, "cn", cards=[card])
    p = run("audit_cards.py", check=False)
    assert p.returncode == 1 and "clue cites ['10^6']" in p.stdout
    card["rubric"]["clue"] = "With n up to 10^5 comparing all pairs is too slow."
    make_pack(paths, "cn", cards=[card])
    assert run("audit_cards.py").returncode == 0


def test_review_cli_recognition_and_drill_flow(paths, run):
    from tests.conftest import recog
    make_problem(paths, "rc", leetcode_id=1, problem_statement="Find the pair.", constraints=["2 <= n <= 10"])
    make_pack(paths, "rc", cards=[recog("recog-rc")])
    started = json.loads(run("review.py", "start", "--mode", "drill", "--target", "1").stdout)
    assert started["started"] and started["problems"][0]["slug"] == "rc"
    q = json.loads(run("review.py", "next").stdout)
    assert q["card"]["id"] == "recog-rc" and q["problem"]["constraints"] == ["2 <= n <= 10"] and q["problem"]["patterns"] is None
    assert "rubric" not in q["card"]
    refused = run("review.py", "answer", "--result", "correct", check=False)           # the engine does the grading
    assert refused.returncode == 1 and "recognition card" in refused.stdout
    revealed = json.loads(run("review.py", "reveal").stdout)
    assert revealed["rubric"]["technique"] and "--technique" in revealed["grading"]
    out = json.loads(run("review.py", "answer", "--text", "two pointers, sorted", "--technique", "accepted",
                         "--clue", "valid").stdout)
    assert out["result"] == "correct" and out["sessionFinished"] and out["problemResult"] is None
    event = [json.loads(line) for line in paths.history.read_text().splitlines()][0]
    assert event["userText"] == "two pointers, sorted" and event["technique"] == "accepted" and event["mode"] == "drill"
    assert "Pattern recognition" in run("stats.py").stdout

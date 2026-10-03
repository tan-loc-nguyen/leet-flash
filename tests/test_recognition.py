"""The recognition card: a free-recall pattern card with a rubric, asked first on every problem."""

import pytest

from leetcode_review.catalog import Filters
from leetcode_review.review import cards as cardlib
from leetcode_review.review.session import ReviewEngine, SessionError
from leetcode_review.schemas import Card
from leetcode_review.storage.history import card_events, problem_events, read_events
from leetcode_review.storage.review_state import ReviewStateStore
from tests.conftest import free, make_pack, make_problem, mcq, recog


def pack_cards(slug, **kw):
    return [recog(f"recog-{slug}", **kw), mcq(f"{slug}-pattern-01", "pattern"), free(f"{slug}-insight-01", "main_insight"),
            free(f"{slug}-ds-01", "data_structure"), free(f"{slug}-edge-01", "edge_case"),
            free(f"{slug}-impl-01", "implementation_detail"), free(f"{slug}-space-01", "space_complexity")]


@pytest.fixture
def engine(paths, now):
    for slug in ("alpha", "beta"):
        make_problem(paths, slug, problem_statement="Statement", constraints=["1 <= n <= 10"])
        make_pack(paths, slug, patterns=("Two Pointers",), cards=pack_cards(slug))
    return ReviewEngine(paths, clock=lambda: now)


def grade(engine, technique="accepted", clue="valid", text="two pointers, it is sorted"):
    return engine.answer(text=text, technique=technique, clue=clue)


# ------------------------------------------------------------------ selection


def test_recognition_card_is_first_and_extra(engine):
    engine.start("cram", target=1, seed=3)
    q = engine.next_question()
    assert q["card"]["id"].startswith("recog-") and q["questionIndex"] == 1
    assert q["questionCount"] == 5                       # cardsPerProblem (4) + the recognition card
    cids = engine._load_sessions()["sessions"][q["sessionId"]]["problems"][0]["cardIds"]
    assert cids[0].startswith("recog-")
    assert not any(c.endswith("-pattern-01") for c in cids)   # leftover generated pattern card never competes


def test_next_payload_hides_rubric_and_shows_constraints_once(engine):
    engine.start("cram", target=1, seed=3)
    q = engine.next_question()
    assert "rubric" not in q["card"] and "answer" not in q["card"] and q["card"]["type"] == "free_recall"
    assert q["problem"]["statement"] == "Statement" and q["problem"]["constraints"] == ["1 <= n <= 10"]
    assert q["problem"]["patterns"] is None
    grade(engine)
    q2 = engine.next_question()
    assert q2["problem"]["statement"] is None and q2["problem"]["constraints"] is None


def test_reveal_returns_rubric_and_grading_protocol(engine):
    engine.start("cram", target=1, seed=3)
    engine.next_question()
    r = engine.reveal()
    assert r["rubric"]["technique"] == "Two pointers on the sorted array" and "--technique" in r["grading"]


def test_focus_category_excluding_pattern_skips_recognition(engine):
    engine.start("cram", target=1, seed=3, focus_categories=["space_complexity"])
    q = engine.next_question()
    assert q["card"]["category"] == "space_complexity"
    cids = engine._load_sessions()["sessions"][q["sessionId"]]["problems"][0]["cardIds"]
    assert not any(c.startswith("recog-") for c in cids)


def test_focus_on_pattern_only_asks_recognition(engine):
    engine.start("cram", target=1, seed=3, focus_categories=["pattern"])
    q = engine.next_question()
    assert q["questionCount"] == 1 and q["card"]["id"].startswith("recog-")


def test_pack_without_rubric_keeps_old_behaviour(paths, now):
    make_problem(paths, "gamma")
    make_pack(paths, "gamma")
    eng = ReviewEngine(paths, clock=lambda: now)
    eng.start("cram", target=1)
    assert eng.next_question()["questionCount"] == 4


def test_manual_pattern_cards_still_compete(paths, now):
    make_problem(paths, "delta")
    cards = pack_cards("delta")
    cards.append({**mcq("delta-manual-01", "pattern"), "source": "manual"})
    make_pack(paths, "delta", cards=cards)
    eng = ReviewEngine(paths, clock=lambda: now)
    eng.start("cram", target=1, seed=5)
    eng.next_question()
    cids = eng._load_sessions()["sessions"][eng.active_session()["id"]]["problems"][0]["cardIds"]
    assert cids[0].startswith("recog-")
    assert len([c for c in cids if c.startswith("recog-")]) == 1


# ------------------------------------------------------------------ grading


@pytest.mark.parametrize("technique,clue,expected", [
    ("accepted", "valid", "correct"), ("accepted", "missing", "partial"), ("accepted", "wrong", "partial"),
    ("valid", "valid", "partial"), ("valid", "missing", "partial"),
    ("wrong", "valid", "failed"), ("wrong", "missing", "failed"),
])
def test_grading_table(technique, clue, expected):
    assert cardlib.grade_recognition(technique, clue) == (expected, False)


def test_hint_caps_correct_at_partial():
    assert cardlib.grade_recognition("accepted", "valid", hints=1) == ("partial", True)
    assert cardlib.grade_recognition("wrong", "valid", hints=2) == ("failed", False)


def test_answer_requires_text_and_verdicts(engine):
    engine.start("cram", target=1, seed=3)
    engine.next_question()
    for kw in ({"result": "correct"}, {"text": "two pointers"}, {"text": "x", "technique": "accepted"},
               {"text": "x", "technique": "great", "clue": "valid"}):
        with pytest.raises(SessionError):
            engine.answer(**kw)
    assert read_events(engine.paths) == []               # nothing recorded by the refused calls


def test_answer_derives_result_and_records_text(engine, paths):
    engine.start("cram", target=1, seed=3)
    engine.next_question()
    out = grade(engine, "valid", "missing", text="  brute force over all pairs  ")
    assert out["recorded"] and out["result"] == "partial"
    rec = out["recognition"]
    assert rec["referenceTechnique"] == "Two pointers on the sorted array" and rec["clueTypes"] == ["sorted_or_ordered"]
    assert out["patterns"] == ["Two Pointers"]            # revealed now that the pattern card is answered
    ev = card_events(read_events(paths))[0]
    assert ev["category"] == "pattern" and ev["result"] == "partial"
    assert ev["userText"] == "brute force over all pairs" and ev["technique"] == "valid" and ev["clue"] == "missing"


def test_user_text_is_truncated(engine, paths):
    engine.start("cram", target=1, seed=3)
    engine.next_question()
    grade(engine, text="x" * 2000)
    assert len(card_events(read_events(paths))[0]["userText"]) == 500


def test_hint_before_answer_caps_correct(engine, paths):
    engine.start("cram", target=1, seed=3)
    engine.next_question()
    engine.hint()
    out = grade(engine)
    assert out["result"] == "partial" and out["recognition"]["hintCapped"]
    assert card_events(read_events(paths))[0]["hintCapped"] is True


# ------------------------------------------------------------------ drill mode


def test_drill_asks_only_recognition_and_does_not_schedule(engine, paths):
    out = engine.start("drill", target=2, seed=1)
    assert out["started"] and out["problemCount"] == 2
    for _ in range(2):
        q = engine.next_question()
        assert q["questionCount"] == 1 and q["card"]["id"].startswith("recog-")
        res = grade(engine, "wrong", "missing", text="no idea")
        assert res["problemFinished"] and res["problemResult"] is None
    events = read_events(paths)
    assert len(card_events(events)) == 2 and problem_events(events) == []
    state = ReviewStateStore(paths).load()
    assert all(ps.level == 0 and ps.next_review is None for ps in state.values())
    assert all(ps.card_stats[f"recog-{s}"].failed == 1 for s, ps in state.items())
    assert res["sessionFinished"] and res["sessionSummary"]["done"]


def test_drill_prefers_failed_over_passed(engine, paths):
    engine.start("drill", target=2, seed=1)
    for result in ("accepted", "wrong"):
        q = engine.next_question()
        grade(engine, result, "valid")
    failed = {s for s, ps in ReviewStateStore(paths).load().items() if ps.card_stats[f"recog-{s}"].failed}
    assert len(failed) == 1
    wins = 0
    for seed in range(60):
        eng = ReviewEngine(paths, clock=engine.clock)
        out = eng.start("drill", target=1, seed=seed, force=True)
        wins += out["problems"][0]["slug"] in failed
    assert wins > 30                                      # unseen weight 3 vs failed weight 4, then recency


def test_drill_without_recognition_cards_says_so(paths, now):
    make_problem(paths, "gamma")
    make_pack(paths, "gamma")
    out = ReviewEngine(paths, clock=lambda: now).start("drill")
    assert out["started"] is False


# ------------------------------------------------------------------ schema


def card(**kw):
    return Card.model_validate(recog("recog-x", **kw))


def test_rubric_schema_rules():
    assert card().rubric.technique
    bad = recog("r")
    for path, value, msg in [
        (("rubric", "technique"), "Tree", "too coarse"),
        (("rubric", "aliases"), [], "alias"),
        (("rubric", "clueTypes"), ["magic"], "clueTypes"),
        (("rubric", "clueTypes"), [], "clueTypes"),
        (("rubric", "clue"), "It runs in O(n)", "complexity"),
        (("promptVariants",), ["How do you do it in O(n)?"], "standard prompts"),
        (("category",), "main_insight", "only allowed"),
        (("type",), "multiple_choice", "only allowed"),
    ]:
        d = {**bad, "rubric": dict(bad["rubric"])}
        node = d
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
        if path == ("type",):
            d["options"] = ["a", "b", "c"]
            d["answer"] = "a"
        with pytest.raises(ValueError, match=msg):
            Card.model_validate(d)

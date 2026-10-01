import json

import pytest

from leetcode_review.catalog import Filters
from leetcode_review.review.session import ReviewEngine, SessionError
from leetcode_review.storage.history import card_events, problem_events, read_events
from leetcode_review.storage.review_state import ReviewStateStore
from tests.conftest import make_pack, make_problem


@pytest.fixture
def engine(paths, now):
    for slug, pat in [("alpha", "Stack"), ("beta", "Graph")]:
        make_problem(paths, slug, tags=(pat,), problem_statement="Statement", )
        make_pack(paths, slug, patterns=(pat,))
    return ReviewEngine(paths, clock=lambda: now)


def answer_current(engine, q, result="correct"):
    """Answer the current card the right way for its type."""
    card = q["card"]
    if card["type"] == "multiple_choice":
        label = next(o["label"] for o in card["options"] if o["text"] == "A-opt")
        return engine.answer(choice=label if result == "correct" else next(o["label"] for o in card["options"] if o["text"] == "B-opt"))
    if card["type"] == "fill_blank":
        return engine.answer(text="O(n)") if result == "correct" else engine.answer(result=result)
    return engine.answer(result=result)


def run_problem(engine, result="correct"):
    q = engine.next_question()
    n = q["questionCount"]
    out = None
    for _ in range(n):
        out = answer_current(engine, q, result)
        if not out["problemFinished"]:
            q = engine.next_question()
    return out


def test_full_daily_session_persists_everything(engine, paths, now):
    started = engine.start("daily", seed=1)
    assert started["started"] and started["problemCount"] == 2
    assert all(p["bucket"] == "new" for p in started["problems"])
    q = engine.next_question()
    assert q["problemIndex"] == 1 and q["questionIndex"] == 1 and q["isFirstQuestion"]
    assert q["card"]["prompt"] and "answer" not in q["card"]            # never leaks the answer
    first_slug = q["problem"]["slug"]
    for _ in range(2):
        out = run_problem(engine)
    assert out["problemFinished"] and out["problemResult"]["levelAfter"] == 1
    # state + history were persisted immediately
    state = ReviewStateStore(paths).load()
    assert set(state) == {"alpha", "beta"} and state[first_slug].level == 1
    assert state[first_slug].next_review == "2026-10-02T00:00:00Z"
    events = read_events(paths)
    assert len(card_events(events)) == 8 and len(problem_events(events)) == 2
    ev = card_events(events)[0]
    assert set(ev) >= {"timestamp", "sessionId", "problem", "card", "category", "result", "mode"}
    assert ev["sessionId"] == "daily-2026-10-01" and ev["mode"] == "daily" and ev["result"] == "correct"
    assert out["sessionFinished"]                        # last answer closes the session itself
    final = out["sessionSummary"]
    assert final["done"] and final["problemsReviewed"] == 2 and final["accuracy"] == 1.0
    assert engine.status() == {"active": False}
    with pytest.raises(SessionError, match="No active review session"):
        engine.next_question()
    assert json.loads(paths.sessions.read_text())["activeSessionId"] is None


def test_each_answer_is_written_before_the_session_ends(engine, paths):
    engine.start("daily", seed=1)
    q = engine.next_question()
    answer_current(engine, q, "correct")
    assert len(card_events(read_events(paths))) == 1
    state = ReviewStateStore(paths).load()
    assert sum(cs.seen for ps in state.values() for cs in ps.card_stats.values()) == 1


def test_resume_interrupted_session_gives_same_question(paths, now, engine):
    engine.start("daily", seed=5)
    q1 = engine.next_question()
    answer_current(engine, q1, "correct")
    resumed = ReviewEngine(paths, clock=lambda: now)           # "new conversation"
    q2 = resumed.next_question()
    assert q2["questionIndex"] == 2 and q2["problem"]["slug"] == q1["problem"]["slug"]
    assert resumed.next_question()["card"] == q2["card"]       # presentation (option order) is stable
    with pytest.raises(SessionError, match="still active"):
        resumed.start("daily")
    assert resumed.start("daily", seed=5, force=True)["sessionId"] == "daily-2026-10-01-2"
    assert json.loads(paths.sessions.read_text())["sessions"]["daily-2026-10-01"]["status"] == "abandoned"


def test_mcq_wrong_answer_explains_and_marks_failed(engine, paths):
    engine.start("cram", seed=3, filters=Filters())
    q = engine.next_question()
    while q["card"]["type"] != "multiple_choice":
        answer_current(engine, q)
        q = engine.next_question()
    wrong = next(o["label"] for o in q["card"]["options"] if o["text"] == "B-opt")
    out = engine.answer(choice=wrong)
    assert out["result"] == "failed" and out["correctAnswer"] == "A-opt"
    assert out["whySelectedIsWrong"] == "no b" and out["otherDistractors"] == {"C-opt": "no c"}
    assert card_events(read_events(paths))[-1]["result"] == "failed"


def test_fill_blank_autograde_and_needs_judgment(engine):
    engine.start("cram", seed=3)
    q = engine.next_question()
    while q["card"]["type"] != "fill_blank":
        answer_current(engine, q)
        q = engine.next_question()
    miss = engine.answer(text="O(n^2)")
    assert miss["recorded"] is False and miss["needsJudgment"] and miss["reference"] == "O(n)"
    ok = engine.answer(text="o(N)")
    assert ok["recorded"] and ok["result"] == "correct"


def test_free_recall_requires_explicit_result_and_reveal_does_not_record(engine, paths):
    engine.start("cram", seed=3)
    q = engine.next_question()
    while q["card"]["type"] != "free_recall":
        answer_current(engine, q)
        q = engine.next_question()
    before = len(read_events(paths))
    assert engine.reveal()["answer"] == "reference"
    with pytest.raises(SessionError, match="judge the answer yourself"):
        engine.answer()
    assert len(read_events(paths)) == before
    assert engine.answer(result="partial")["result"] == "partial"


def test_poor_performance_demotes_and_reschedules_soon(engine, paths):
    engine.start("daily", seed=2)
    out = run_problem(engine, "failed")
    res = out["problemResult"]
    assert res["outcome"] == "fail" and res["levelAfter"] == 0 and res["nextReview"] == "2026-10-01T12:00:00Z"
    assert res["weakCategories"] == []   # one miss per category is not yet a pattern of weakness
    engine.start("daily", seed=2, force=True)
    # failing the same categories again (lapsed problems return next session) makes them weak
    q = engine.next_question()
    assert q["problem"]["bucket"] in ("new", "recent_failure", "due")


def test_forgot_marks_failed_returns_recall_material_and_moves_on(engine, paths):
    engine.start("daily", seed=2)
    q = engine.next_question()
    out = engine.forgot()
    assert out["problemResult"]["outcome"] == "forgot" and out["problemResult"]["score"] == 0
    assert out["recallMaterial"]["summary"].startswith("Summary of") and out["recallMaterial"]["problemStatement"] == "Statement"
    ev = problem_events(read_events(paths))[-1]
    assert ev["forgot"] is True and ev["problem"] == q["problem"]["slug"]
    nxt = engine.next_question()
    assert nxt["problem"]["slug"] != q["problem"]["slug"] and nxt["problemIndex"] == 2


def test_progressive_hints_then_exhausted(engine):
    engine.start("daily", seed=2)
    engine.next_question()
    kinds = []
    while True:
        h = engine.hint()
        if h.get("exhausted"):
            break
        kinds.append(h["kind"])
    assert kinds == ["summary", "pattern", "approach"]  # fixture packs have no insight/invariant/solution
    assert engine.hint()["exhausted"]


def test_hints_are_recorded_in_history(engine, paths):
    engine.start("daily", seed=2)
    q = engine.next_question()
    engine.hint()
    answer_current(engine, q)
    assert card_events(read_events(paths))[0]["hints"] == 1


def test_skip_does_not_schedule(engine, paths):
    engine.start("daily", seed=2)
    engine.next_question()
    engine.skip()
    assert problem_events(read_events(paths)) == [] and engine.next_question()["problemIndex"] == 2


def test_notes_shown_on_first_question(engine, paths, now):
    from leetcode_review.schemas import Note
    from leetcode_review.storage.problems import ProblemStore
    store = ProblemStore(paths)
    p = store.get("alpha")
    p.notes.append(Note(id="n", text="skip duplicates", created_at="2026-10-01T00:00:00Z"))
    store.save(p)
    engine.start("cram", seed=1, filters=Filters(slugs=["alpha"]))
    assert engine.next_question()["problem"]["notes"] == ["skip duplicates"]


def test_errors_without_session_and_empty_queue(engine, paths, now):
    with pytest.raises(SessionError, match="No active review session"):
        engine.next_question()
    out = engine.start("cram", filters=Filters(difficulties=["Hard"]))
    assert out["started"] is False


def test_manual_cards_are_served_and_survive_regeneration(engine, paths, now):
    from leetcode_review.content.loader import add_manual_card, load_pack
    from leetcode_review.content.scaffold import scaffold_pack
    from leetcode_review.schemas import Card
    from leetcode_review.storage.problems import ProblemStore
    card = Card.model_validate({"id": "alpha-manual-01", "category": "invariant", "type": "free_recall",
                                "promptVariants": ["Why?"], "answer": "Because.", "explanation": "e"})
    add_manual_card(paths, "alpha", card)
    assert any(c.id == "alpha-manual-01" and c.source == "manual" for c in load_pack(paths, "alpha").cards)
    scaffold_pack(paths, ProblemStore(paths).get("alpha"), force=True)   # regenerate the generated pack
    ids = {c.id for c in load_pack(paths, "alpha").cards}
    assert ids == {"alpha-manual-01"}                                    # generated cards gone, manual survives

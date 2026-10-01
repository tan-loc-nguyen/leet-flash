import json

import pytest

from leetcode_review.catalog import Catalog, Filters
from leetcode_review.content.scaffold import scaffold_pack, suggest_patterns
from leetcode_review.rebuild import rebuild_from_events, rebuild_state_file
from leetcode_review.review.session import ReviewEngine
from leetcode_review.stats import compute_stats, format_stats
from leetcode_review.storage.history import read_events
from leetcode_review.storage.review_state import ReviewStateStore
from tests.conftest import make_pack, make_problem
from tests.test_session import answer_current


def play(paths, now, slug="alpha", results=("correct", "failed", "correct", "correct")):
    eng = ReviewEngine(paths, clock=lambda: now)
    eng.start("cram", seed=1, filters=Filters(slugs=[slug]))
    q = eng.next_question()
    for r in results:
        out = answer_current(eng, q, r)
        if not out["problemFinished"]:
            q = eng.next_question()
    return eng


@pytest.fixture
def populated(paths, now):
    for slug in ("alpha", "beta"):
        make_problem(paths, slug, tags=("Stack",))
        make_pack(paths, slug, patterns=("Stack",))
    play(paths, now, "alpha")
    play(paths, now.replace(day=2), "beta", ("failed",) * 4)
    play(paths, now.replace(day=3), "alpha", ("correct",) * 4)
    return paths


def test_rebuild_reproduces_live_state_exactly(populated):
    live = {s: ps.to_json() for s, ps in ReviewStateStore(populated).load().items()}
    rebuilt = {s: ps.to_json() for s, ps in rebuild_from_events(read_events(populated)).items()}
    assert rebuilt == live and live["beta"]["lapses"] == 1 and live["alpha"]["reviewCount"] == 2


def test_rebuild_file_restores_lost_state_and_backs_up_corrupt_one(populated):
    live = json.loads(populated.review_state.read_text())
    populated.review_state.write_text("{corrupted")
    report = rebuild_state_file(populated)
    assert json.loads(populated.review_state.read_text()) == live
    assert report.problems == 2 and report.backup and (populated.state_dir / report.backup.split("/")[-1]).exists()
    populated.review_state.unlink()
    rebuild_state_file(populated, backup=False)
    assert json.loads(populated.review_state.read_text()) == live


def test_rebuild_dry_run_and_bad_history_lines(populated):
    populated.review_state.write_text("{}")
    with open(populated.history, "a") as fh:
        fh.write("garbage line\n")
    r = rebuild_state_file(populated, dry_run=True)
    assert populated.review_state.read_text() == "{}" and r.skipped_lines and not r.written


def test_interrupted_problem_restores_card_stats_only(paths, now):
    make_problem(paths, "alpha"); make_pack(paths, "alpha")
    eng = ReviewEngine(paths, clock=lambda: now)
    eng.start("cram", seed=1, filters=Filters(slugs=["alpha"]))
    answer_current(eng, eng.next_question())
    state = rebuild_from_events(read_events(paths))["alpha"]
    assert state.review_count == 0 and sum(c.seen for c in state.card_stats.values()) == 1


def test_stats(populated, now):
    s = compute_stats(Catalog(populated, now), read_events(populated), now)
    assert s["totalAnswers"] == 12 and s["problemsReviewed"] == 2
    assert s["byPattern"][0]["name"] == "Stack" and 0 < s["overallAccuracy"] < 1
    assert s["weakProblems"][0]["slug"] == "beta"
    assert "Pattern performance" in format_stats(s) and "Mastery distribution" in format_stats(s)


# ------------------------------------------------------------------ catalog / missing packs / scaffold


def test_missing_pack_detection_and_skeletons(paths, now):
    make_problem(paths, "has-pack", leetcode_id=1); make_pack(paths, "has-pack")
    make_problem(paths, "no-pack", leetcode_id=2, tags=("Stack", "Hash Table"))
    make_problem(paths, "skeleton", leetcode_id=3)
    scaffold_pack(paths, Catalog(paths, now).problems["skeleton"])
    rows = Catalog(paths, now).missing_packs()
    assert rows == [{"leetcodeId": "2", "slug": "no-pack", "title": "No Pack", "status": "missing"},
                    {"leetcodeId": "3", "slug": "skeleton", "title": "Skeleton", "status": "skeleton"}]
    assert [r["slug"] for r in Catalog(paths, now).missing_packs(include_skeletons=False)] == ["no-pack"]


def test_scaffold_creates_valid_skeleton_and_never_overwrites_without_force(paths, now):
    prob = make_problem(paths, "sw", tags=("Sliding Window", "Hash Table", "String", "Weird Tag"))
    assert suggest_patterns(prob) == ["Sliding Window", "Array / Hashing"]
    pack, written = scaffold_pack(paths, prob)
    assert written and pack.cards == []
    from leetcode_review.content.validator import validate_pack_file
    assert [i for i in validate_pack_file(paths.review_packs / "sw.json", {"sw"}) if i.level == "error"] == []
    (paths.review_packs / "sw.json").write_text(json.dumps({**json.loads((paths.review_packs / "sw.json").read_text()), "summary": "mine"}))
    _, written = scaffold_pack(paths, prob)
    assert not written and json.loads((paths.review_packs / "sw.json").read_text())["summary"] == "mine"
    _, written = scaffold_pack(paths, prob, force=True)
    assert written and json.loads((paths.review_packs / "sw.json").read_text())["summary"] == ""


def test_catalog_queries(paths, now):
    make_problem(paths, "a", leetcode_id=1, difficulty="Easy", tags=("Array", "Hash Table"))
    make_problem(paths, "b", leetcode_id=2, difficulty="Hard", status="unsolved", tags=("Graph",))
    make_pack(paths, "a", patterns=("Array / Hashing",))
    from leetcode_review.storage.atomic_write import atomic_write_json
    atomic_write_json(paths.lists / "l.json", {"name": "L", "problems": ["b"]})
    cat = Catalog(paths, now)
    slugs = lambda **kw: [p.slug for p in cat.find(Filters(**kw))]
    assert slugs(ids=["2"]) == ["b"] and slugs(text="A") == ["a"] and slugs(difficulties=["hard"]) == ["b"]
    assert slugs(status="unsolved") == ["b"] and slugs(tags=["hash table"]) == ["a"]
    assert slugs(patterns=["hashing"]) == ["a"] and slugs(topics=["graphs"]) == ["b"] and slugs(lists=["l"]) == ["b"]
    assert slugs(has_pack=False) == ["b"] and slugs(due=True) == [] and slugs(max_level=0) == ["a", "b"]


def test_repeated_failures_make_category_weak_and_next_session_targets_it(paths, now):
    make_problem(paths, "alpha"); make_pack(paths, "alpha")
    play(paths, now, "alpha", ("failed",) * 4)
    eng = play(paths, now.replace(day=2), "alpha", ("failed",) * 4)
    state = ReviewStateStore(paths).load()["alpha"]
    assert set(state.weak_categories) >= {"pattern", "main_insight"}
    # third review: every selected card set must contain a weak-category card
    eng.start("cram", seed=11, filters=Filters(slugs=["alpha"]))
    q, cats = eng.next_question(), []
    for _ in range(q["questionCount"]):
        cats.append(q["card"]["category"])
        out = answer_current(eng, q, "correct")
        if not out["problemFinished"]:
            q = eng.next_question()
    assert set(cats) & set(state.weak_categories)

import random
from collections import Counter
from datetime import timedelta

from leetcode_review.catalog import Catalog, Filters
from leetcode_review.review.queue import build_daily, build_queue, classify, order_for_diversity, QueueEntry
from leetcode_review.schemas import ProblemState
from leetcode_review.storage.review_state import ReviewStateStore
from leetcode_review.timeutil import iso
from tests.conftest import make_pack, make_problem


def setup_problems(paths, specs):
    """specs: slug -> (pattern, ProblemState|None)."""
    state = {}
    for slug, (pattern, ps) in specs.items():
        make_problem(paths, slug, tags=(pattern,))
        make_pack(paths, slug, patterns=(pattern,))
        if ps:
            state[slug] = ps
    ReviewStateStore(paths).save(state)


def ps(now, *, level=2, due_in=0, accuracy=0.9, score=0.9, weak=(), last_days_ago=5):
    nxt = (now + timedelta(days=due_in)).replace(hour=0, minute=0, second=0)
    return ProblemState(level=level, review_count=2, next_review=iso(nxt), recent_accuracy=accuracy,
                        last_score=score, last_review=iso(now - timedelta(days=last_days_ago)), weak_categories=list(weak))


def test_buckets(paths, now):
    setup_problems(paths, {
        "overdue": ("A", ps(now, due_in=-5)), "due": ("B", ps(now, due_in=0)),
        "recent-fail": ("C", ps(now, level=1, due_in=1, score=0.1, accuracy=0.3, last_days_ago=1)),
        "weak": ("D", ps(now, due_in=10, accuracy=0.4)), "new": ("E", None),
        "strong": ("F", ps(now, level=5, due_in=20)), "mid-not-due": ("G", ps(now, level=2, due_in=3)),
    })
    cat = Catalog(paths, now)
    got = {s: (classify(cat, s, now) or (None,))[0] for s in cat.problems}
    assert got == {"overdue": "overdue", "due": "due", "recent-fail": "recent_failure", "weak": "weak",
                   "new": "new", "strong": "retention", "mid-not-due": None}


def test_priority_order_overdue_due_failure_weak_new_retention(paths, now, rng):
    setup_problems(paths, {
        "retention": ("A", ps(now, level=5, due_in=20)), "new": ("B", None), "weak": ("C", ps(now, due_in=10, accuracy=0.4)),
        "failure": ("D", ps(now, level=1, due_in=1, score=0.1, last_days_ago=1)),
        "due": ("E", ps(now, due_in=0)), "overdue": ("F", ps(now, due_in=-3)),
    })
    cat = Catalog(paths, now)
    # urgent items are chosen strictly by priority when the target is smaller than the pool
    plan = build_daily(cat, 2, rng)
    assert {e.slug for e in plan.entries} == {"overdue", "due"}
    plan = build_daily(cat, 3, rng)
    assert {e.slug for e in plan.entries} == {"overdue", "due", "failure"}
    assert any("highest-priority" in n for n in build_daily(cat, 1, rng).notes)
    everything = build_daily(cat, 10, rng)
    assert len(everything.entries) == 6 and everything.counts["overdue"] == 1


def test_target_larger_than_due_and_all_due_flag(paths, now, rng):
    setup_problems(paths, {f"p{i}": (f"T{i}", ps(now, due_in=-1)) for i in range(15)})
    cat = Catalog(paths, now)
    assert len(build_daily(cat, 10, rng).entries) == 10
    assert len(build_daily(cat, 10, rng, all_due=True).entries) == 15


def test_problems_reviewed_today_and_without_cards_are_excluded(paths, now, rng):
    reviewed_today = ps(now, level=3, due_in=-1)
    reviewed_today.last_review = iso(now - timedelta(hours=2))
    setup_problems(paths, {"done-today": ("A", reviewed_today), "ok": ("B", ps(now, due_in=-1))})
    make_problem(paths, "no-pack")
    cat = Catalog(paths, now)
    assert [e.slug for e in build_daily(cat, 10, rng).entries] == ["ok"]


def test_diversity_avoids_back_to_back_same_pattern(paths, now):
    specs = {f"sw{i}": ("Sliding Window", ps(now, due_in=-1)) for i in range(4)}
    specs |= {f"g{i}": ("Graph", ps(now, due_in=-1)) for i in range(4)}
    specs |= {f"bs{i}": ("Binary Search", ps(now, due_in=-1)) for i in range(4)}
    setup_problems(paths, specs)
    cat = Catalog(paths, now)
    adjacent = 0
    for seed in range(100):
        order = [cat.primary_pattern(e.slug) for e in build_daily(cat, 12, random.Random(seed)).entries]
        adjacent += sum(a == b for a, b in zip(order, order[1:]))
    random_adjacent = 0
    for seed in range(100):
        r = random.Random(seed)
        order = [cat.primary_pattern(s) for s in r.sample(sorted(cat.problems), 12)]
        random_adjacent += sum(a == b for a, b in zip(order, order[1:]))
    assert adjacent < random_adjacent * 0.5


def test_selection_spreads_patterns_when_priorities_are_equal(paths, now):
    specs = {f"sw{i}": ("Sliding Window", ps(now, due_in=-1)) for i in range(8)}
    specs |= {f"g{i}": ("Graph", ps(now, due_in=-1)) for i in range(2)}
    setup_problems(paths, specs)
    cat = Catalog(paths, now)
    seen_graph = sum(any(cat.primary_pattern(e.slug) == "Graph" for e in build_daily(cat, 4, random.Random(s)).entries) for s in range(60))
    assert seen_graph > 45


def test_deterministic_with_seed(paths, now):
    setup_problems(paths, {f"p{i}": (f"T{i % 3}", ps(now, due_in=-1)) for i in range(12)})
    cat = Catalog(paths, now)
    a = [e.slug for e in build_daily(cat, 6, random.Random(7)).entries]
    b = [e.slug for e in build_daily(cat, 6, random.Random(7)).entries]
    assert a == b


def test_weak_mode_ranks_by_weakness(paths, now, rng):
    setup_problems(paths, {
        "great": ("A", ps(now, accuracy=0.95)), "bad": ("B", ps(now, accuracy=0.2, weak=("space_complexity",))),
        "meh": ("C", ps(now, accuracy=0.55)), "unseen": ("D", None),
    })
    plan = build_queue(Catalog(paths, now), "weak", 2, rng)
    assert {e.slug for e in plan.entries} == {"bad", "meh"}


def test_cram_ignores_due_dates_and_filters(paths, now, rng):
    setup_problems(paths, {"a": ("Graph", ps(now, due_in=30)), "b": ("Graph", None), "c": ("Stack", ps(now, due_in=30))})
    cat = Catalog(paths, now)
    plan = build_queue(cat, "cram", 10, rng, Filters(topics=["graph"]))
    assert {e.slug for e in plan.entries} == {"a", "b"}


def test_cram_list_filter_notes_unimported_problems(paths, now, rng):
    setup_problems(paths, {"two-sum": ("Array / Hashing", None)})
    from leetcode_review.storage.atomic_write import atomic_write_json
    atomic_write_json(paths.lists / "mini.json", {"name": "Mini", "problems": ["two-sum", "not-imported"]})
    plan = build_queue(Catalog(paths, now), "cram", 10, rng, Filters(lists=["mini"]))
    assert [e.slug for e in plan.entries] == ["two-sum"] and any("1 not imported" in n for n in plan.notes)


def test_interview_mode_only_studied_and_difficulty_filter(paths, now, rng):
    setup_problems(paths, {"solved-med": ("A", None), "solved-easy": ("B", None), "never": ("C", None)})
    cat = Catalog(paths, now)
    cat.problems["solved-easy"].difficulty = "Easy"
    cat.problems["never"].status = "unsolved"
    plan = build_queue(cat, "interview", 8, rng, Filters(difficulties=["Medium"]))
    assert [e.slug for e in plan.entries] == ["solved-med"]


def test_order_for_diversity_keeps_all_entries(paths, now, rng):
    setup_problems(paths, {f"p{i}": ("Same", None) for i in range(5)})
    cat = Catalog(paths, now)
    entries = [QueueEntry(s, "new", 1.0) for s in cat.problems]
    assert sorted(e.slug for e in order_for_diversity(cat, entries, rng)) == sorted(cat.problems)


# --------------------------------------------------------------------------- topic weights


def test_topic_weight_validation_and_per_key_override(paths):
    import json
    import pytest
    from leetcode_review.config import load_settings
    from leetcode_review.review import topics
    paths.settings.parent.mkdir(parents=True, exist_ok=True)
    paths.settings.write_text(json.dumps({"topicWeights": {"Greedy": 40}}))
    s = load_settings(paths)
    assert s["topicWeights"]["Greedy"] == 40 and s["topicWeights"]["Binary search"] == 9      # merged per key
    paths.settings.write_text(json.dumps({"topicWeights": {"Nonsense": 1}}))
    with pytest.raises(ValueError):
        topics.effective_weights(load_settings(paths))
    paths.settings.write_text(json.dumps({"topicWeights": {"Greedy": -1}}))
    with pytest.raises(ValueError):
        topics.effective_weights(load_settings(paths))


def test_topic_comes_from_primary_pattern_with_tag_fallback(paths, now):
    from leetcode_review.review import topics
    make_problem(paths, "tree-dfs", tags=("Tree", "Depth-First Search"))
    make_pack(paths, "tree-dfs", patterns=("Tree", "DFS"))          # secondary DFS must not make it a graph problem
    make_problem(paths, "mystery", tags=("Weird",))
    make_pack(paths, "mystery", patterns=("Weird",))                 # no row for this pattern -> unlisted
    make_problem(paths, "no-pack-pattern", tags=("Array", "Sliding Window"))
    make_pack(paths, "no-pack-pattern", patterns=())                 # fallback to tags: technique beats generic
    cat = Catalog(paths, now)
    assert topics.topic_of(cat, "tree-dfs") == ("Tree DFS/BFS", 6.0)
    assert topics.topic_of(cat, "mystery") == ("Unlisted", 1.0)
    assert topics.topic_of(cat, "no-pack-pattern") == ("Sliding window", 5.0)
    assert topics.tag_rows(["Array", "Backtracking", "Bit Manipulation"]) == ["Backtracking"]
    assert topics.tag_rows(["Tree", "Binary Tree", "Depth-First Search"]) == ["Tree DFS/BFS"]
    assert topics.tag_rows(["Array", "Depth-First Search", "Matrix"]) == ["Graph DFS/BFS"]
    assert topics.tag_rows(["Math"]) == []


def test_share_factors_follow_target_shares_not_bank_size(paths, now):
    from leetcode_review.review import topics
    specs = {f"arr-{i}": ("Array / Hashing", None) for i in range(30)}
    specs.update({f"topo-{i}": ("Topological Sort", None) for i in range(3)})
    setup_problems(paths, specs)
    cat = Catalog(paths, now)
    f = topics.share_factors(cat, list(cat.problems))
    # target shares 13/17 and 4/17; pool shares 30/33 and 3/33
    assert abs(f["arr-0"] - (13 / 17) / (30 / 33)) < 1e-9 and abs(f["topo-0"] - (4 / 17) / (3 / 33)) < 1e-9
    assert f["topo-0"] > 2 * f["arr-0"]
    expected_mass_topo = 3 * f["topo-0"] / (3 * f["topo-0"] + 30 * f["arr-0"])
    assert abs(expected_mass_topo - 4 / 17) < 1e-9                  # draw mass equals the table share


def test_new_problems_follow_topic_shares(paths, now):
    specs = {f"arr-{i}": ("Array / Hashing", None) for i in range(30)}
    specs.update({f"topo-{i}": ("Topological Sort", None) for i in range(3)})
    setup_problems(paths, specs)
    cat = Catalog(paths, now)
    picks = Counter()
    for seed in range(400):
        for e in build_daily(cat, 3, random.Random(seed)).entries:
            picks[e.slug.split("-")[0]] += 1
    share = picks["topo"] / (picks["topo"] + picks["arr"])
    assert 0.17 < share < 0.30, picks               # table: 4/17 = 23.5% (3/33 = 9% without weighting)


def test_urgent_problems_keep_bucket_order_and_are_never_dropped(paths, now, rng):
    setup_problems(paths, {
        "due-array": ("Array / Hashing", ps(now, due_in=0)),
        "overdue-math": ("Math", ps(now, due_in=-3)),              # unlisted (low weight) but overdue: still first
        "due-math": ("Math", ps(now, due_in=0)),
    })
    cat = Catalog(paths, now)
    assert {e.slug for e in build_daily(cat, 3, rng).entries} == {"due-array", "overdue-math", "due-math"}
    top = build_daily(cat, 1, random.Random(1)).entries[0]
    assert top.slug == "overdue-math" and top.bucket == "overdue"      # the nudge cannot cross a bucket
    assert {e.slug for e in build_daily(cat, 2, random.Random(1)).entries} == {"overdue-math", "due-array"}


def test_cram_and_weak_use_weights_too(paths, now):
    specs = {f"arr-{i}": ("Array / Hashing", ps(now, level=2, due_in=3, accuracy=0.5)) for i in range(10)}
    specs.update({f"math-{i}": ("Math", ps(now, level=2, due_in=3, accuracy=0.5)) for i in range(10)})
    setup_problems(paths, specs)
    cat = Catalog(paths, now)
    for mode in ("cram", "weak"):
        picks = Counter()
        for seed in range(200):
            for e in build_queue(cat, mode, 3, random.Random(seed)).entries:
                picks[e.slug.split("-")[0]] += 1
        assert picks["arr"] > picks["math"], (mode, picks)

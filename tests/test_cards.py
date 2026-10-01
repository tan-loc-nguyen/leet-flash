import random

from leetcode_review.review import cards as cardlib
from leetcode_review.schemas import Card, ProblemState
from leetcode_review.review.scoring import record_card_result
from tests.conftest import free, mcq


def C(raw):
    return Card.model_validate(raw)


def cards_for(cats):
    return [C(free(f"c-{i}", cat)) for i, cat in enumerate(cats)]


def test_select_cards_returns_requested_count_and_includes_a_core_card(now):
    cards = cards_for(["edge_case", "implementation_detail", "code_reasoning", "why_not", "edge_case", "pattern"])
    for seed in range(30):
        chosen = cardlib.select_cards(cards, None, 3, now, random.Random(seed))
        assert len(chosen) == 3 and any(c.category == "pattern" for c in chosen)


def test_small_packs_use_every_enabled_card_and_skip_disabled(now, rng):
    cards = cards_for(["pattern", "main_insight"]) + [C({**free("off", "pattern"), "enabled": False})]
    assert {c.id for c in cardlib.select_cards(cards, None, 4, now, rng)} == {"c-0", "c-1"}


def test_weak_category_cards_are_favoured_but_core_still_tested(now):
    cats = ["pattern", "main_insight", "time_complexity", "space_complexity", "space_complexity",
            "edge_case", "invariant", "code_reasoning", "implementation_detail"]
    cards = cards_for(cats)
    ps = ProblemState()
    for day in ("01", "02"):
        record_card_result(ps, "c-3", "space_complexity", "failed", f"2026-09-{day}T00:00:00Z")
    assert ps.weak_categories == ["space_complexity"]
    n_weak = n_core_no_weak = 0
    for seed in range(200):
        chosen = cardlib.select_cards(cards, ps, 4, now, random.Random(seed))
        assert any(c.category == "space_complexity" for c in chosen)   # guaranteed
        n_weak += sum(c.category == "space_complexity" for c in chosen)
        n_core_no_weak += any(c.category in ("pattern", "main_insight") for c in chosen)
    baseline = sum(sum(c.category == "space_complexity" for c in cardlib.select_cards(cards, None, 4, now, random.Random(s))) for s in range(200))
    assert n_weak > baseline * 1.3            # weak category appears much more often
    assert n_core_no_weak > 100                # ...yet core concepts are still sampled


def test_weak_weighting_is_not_a_separate_schedule_and_failed_cards_return_more(now):
    cards = cards_for(["pattern", "main_insight", "invariant", "edge_case", "code_reasoning", "why_not"])
    ps = ProblemState()
    record_card_result(ps, "c-3", "edge_case", "failed", "2026-09-01T00:00:00Z")
    hits = sum(any(c.id == "c-3" for c in cardlib.select_cards(cards, ps, 3, now, random.Random(s))) for s in range(300))
    others = sum(any(c.id == "c-4" for c in cardlib.select_cards(cards, ps, 3, now, random.Random(s))) for s in range(300))
    assert hits > others


def test_ordering_follows_recognition_to_complexity(now, rng):
    chosen = cardlib.select_cards(cards_for(["space_complexity", "pattern", "edge_case", "main_insight"]), None, 4, now, rng)
    assert [c.category for c in chosen] == ["pattern", "main_insight", "edge_case", "space_complexity"]


def test_prompt_variants_rotate_with_times_seen():
    card = C(mcq("m1"))
    ps = ProblemState()
    seen = []
    for i in range(4):
        seen.append(cardlib.pick_prompt(card, ps))
        record_card_result(ps, "m1", "pattern", "correct", f"2026-09-0{i + 1}T00:00:00Z")
    assert seen == ["m1 prompt one", "m1 prompt two", "m1 prompt one", "m1 prompt two"]


def test_mcq_options_are_shuffled_labelled_and_answer_position_varies():
    card = C(mcq("m1"))
    positions = set()
    for seed in range(40):
        opts = cardlib.present_options(card, random.Random(seed))
        assert [o["label"] for o in opts] == list("ABCD") and sorted(o["text"] for o in opts) == sorted(card.options)
        positions.add([o["text"] for o in opts].index("A-opt"))
    assert positions == {0, 1, 2, 3}


def test_match_choice_accepts_letters_and_text():
    opts = [{"label": "A", "text": "Hash map"}, {"label": "B", "text": "Stack"}]
    assert cardlib.match_choice("b", opts) == "Stack" and cardlib.match_choice("B.", opts) == "Stack"
    assert cardlib.match_choice(" hash MAP ", opts) == "Hash map"
    assert cardlib.match_choice("C", opts) is None and cardlib.match_choice("queue", opts) is None


def test_fill_blank_normalisation_of_complexity_variants():
    card = C({"id": "t", "category": "time_complexity", "type": "fill_blank", "promptVariants": ["x ___"],
              "answer": "O(n^2)", "explanation": "e", "acceptedAnswers": ["quadratic"]})
    for ok in ["O(n^2)", "o(N^2)", "O( n ^ 2 )", "O(n²)", "O(n**2)", "quadratic", "  O(n^2).  "]:
        assert cardlib.check_fill_blank(card, ok), ok
    for bad in ["O(n)", "O(n^3)", "O(n log n)"]:
        assert not cardlib.check_fill_blank(card, bad), bad
    log = C({"id": "l", "category": "time_complexity", "type": "fill_blank", "promptVariants": ["x ___"],
             "answer": "O(log n)", "explanation": "e"})
    assert cardlib.check_fill_blank(log, "O(log(n))") and cardlib.check_fill_blank(log, "o(logn)")
    word = C({"id": "w", "category": "edge_case", "type": "fill_blank", "promptVariants": ["x ___"], "answer": "empty", "explanation": "e"})
    assert cardlib.check_fill_blank(word, "The Empty.") and not cardlib.check_fill_blank(word, "full")

"""Card selection for a problem, prompt rotation, MCQ presentation and fill-blank grading."""

from __future__ import annotations

import random
import re
from datetime import datetime

from .. import config as C
from ..schemas import Card, ProblemState
from ..timeutil import parse_iso

LABELS = "ABCDEF"


def _weight(card: Card, ps: ProblemState | None, now: datetime, boost: dict[str, float]) -> float:
    w = C.CORE_CARD_BASE if card.category in C.CORE_CATEGORIES else 1.0
    w *= boost.get(card.category, 1.0)
    if ps and card.category in ps.weak_categories:
        w *= C.WEAK_CATEGORY_BOOST
    cs = ps.card_stats.get(card.id) if ps else None
    if cs is None or cs.seen == 0:
        w *= C.UNSEEN_CARD_BOOST
    else:
        fail_ratio = (cs.failed + 0.5 * cs.partial) / cs.seen
        w *= 1 + fail_ratio * C.FAIL_RATIO_BOOST
        if cs.last_seen_at and (now - parse_iso(cs.last_seen_at)).total_seconds() < 86400:
            w *= C.RECENTLY_SEEN_FACTOR
    return w


def select_cards(
    cards: list[Card],
    ps: ProblemState | None,
    n: int,
    now: datetime,
    rng: random.Random,
    *,
    category_boost: dict[str, float] | None = None,
    focus_categories: list[str] | None = None,
) -> list[Card]:
    """Pick up to ``n`` cards: weak/failed/unseen cards favoured, but core concepts still appear.

    Guarantees (when available): at least one core card and, if the problem has weak
    categories, at least one card from a weak category. At most MAX_CARDS_PER_CATEGORY per category
    unless nothing else is left. Result is ordered recognition -> reasoning -> complexity.
    """
    pool = [c for c in cards if c.enabled]
    if focus_categories:
        focused = [c for c in pool if c.category in focus_categories]
        pool = focused or pool
    if len(pool) <= n:
        chosen = pool
    else:
        boost = category_boost or {}
        weights = {c.id: _weight(c, ps, now, boost) for c in pool}
        chosen: list[Card] = []

        def take(c: Card) -> None:
            chosen.append(c)
            pool.remove(c)

        def draw(candidates: list[Card]) -> Card:
            return rng.choices(candidates, weights=[weights[c.id] for c in candidates])[0]

        weak = set(ps.weak_categories) if ps else set()
        weak_cards = [c for c in pool if c.category in weak]
        if weak_cards and n >= 3:
            take(draw(weak_cards))
        if not any(c.category in C.CORE_CATEGORIES for c in chosen):
            core = [c for c in pool if c.category in C.CORE_CATEGORIES]
            if core:
                take(draw(core))
        while len(chosen) < n and pool:
            counts: dict[str, int] = {}
            for c in chosen:
                counts[c.category] = counts.get(c.category, 0) + 1
            eligible = [c for c in pool if counts.get(c.category, 0) < C.MAX_CARDS_PER_CATEGORY] or pool
            take(draw(eligible))
    order = {cat: i for i, cat in enumerate(C.CATEGORY_ORDER)}
    return sorted(chosen, key=lambda c: order.get(c.category, 99))


def pick_prompt(card: Card, ps: ProblemState | None) -> str:
    """Rotate through prompt variants by how many times the card has been seen."""
    seen = ps.card_stats[card.id].seen if ps and card.id in ps.card_stats else 0
    return card.prompt_variants[seen % len(card.prompt_variants)]


def present_options(card: Card, rng: random.Random) -> list[dict] | None:
    if card.type != "multiple_choice" or not card.options:
        return None
    opts = list(card.options)
    rng.shuffle(opts)
    return [{"label": LABELS[i], "text": t} for i, t in enumerate(opts)]


# --------------------------------------------------------------------------- answer matching


def match_choice(choice: str, presented: list[dict]) -> str | None:
    """Resolve 'B', 'b', 'B.' or the option text to the option text, else None."""
    c = choice.strip()
    m = re.fullmatch(r"([A-Fa-f])[.)]?", c)
    if m:
        for o in presented:
            if o["label"] == m.group(1).upper():
                return o["text"]
    for o in presented:
        if o["text"].strip().lower() == c.lower():
            return o["text"]
    return None


_SUPERSCRIPTS = str.maketrans({"²": "^2", "³": "^3", "×": "*", "·": "*", "−": "-"})


def normalize_answer(text: str) -> str:
    """Normalise complexity notation and free text so 'O(N)' == 'o(n)' == 'O( n )'."""
    t = text.strip().lower().translate(_SUPERSCRIPTS)
    t = t.replace("**", "^").replace("θ", "o").replace("theta", "o")
    t = re.sub(r"\blog\s*\(\s*(\w+)\s*\)", r"log\1", t)  # log(n) -> logn
    t = re.sub(r"^(the|a|an)\s+", "", t)
    t = re.sub(r"[\s\.]+$", "", t)
    if re.search(r"o\s*\(", t):
        t = re.sub(r"\s+", "", t)
        t = re.sub(r"\(\s*\*", "(", t)
    else:
        t = re.sub(r"\s+", " ", t)
    return t


def check_fill_blank(card: Card, text: str) -> bool:
    accepted = [card.answer or "", *card.accepted_answers]
    got = normalize_answer(text)
    return any(got == normalize_answer(a) for a in accepted if a)

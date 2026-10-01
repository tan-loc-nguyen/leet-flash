"""Card scoring, per-card/category statistics and weak-category detection."""

from __future__ import annotations

from .. import config as C
from ..schemas import CardStat, CategoryStat, ProblemState


def points(result: str) -> int:
    return C.RESULT_POINTS[result]


def category_weight(category: str) -> float:
    return C.CATEGORY_WEIGHTS.get(category, 1.0)


def problem_score(results: list[tuple[str, str]]) -> float:
    """Weighted score in [0, 1] from [(category, result), ...]. Empty -> 0."""
    total_w = sum(category_weight(c) for c, _ in results)
    if not total_w:
        return 0.0
    got = sum(category_weight(c) * points(r) for c, r in results)
    return got / (C.MAX_POINTS * total_w)


def core_blocking_failure(results: list[tuple[str, str]]) -> bool:
    return any(c in C.PROMOTION_BLOCKING_CATEGORIES and r == "failed" for c, r in results)


def stat_accuracy(stat: CardStat | CategoryStat) -> float | None:
    return (stat.correct + 0.5 * stat.partial) / stat.seen if stat.seen else None


def _bump(stat: CardStat | CategoryStat, result: str, timestamp: str) -> None:
    stat.seen += 1
    setattr(stat, result, getattr(stat, result) + 1)
    stat.incorrect_streak = 0 if result == "correct" else stat.incorrect_streak + 1
    stat.last_result = result
    stat.last_seen_at = timestamp


def record_card_result(ps: ProblemState, card_id: str, category: str, result: str, timestamp: str) -> None:
    """Update card + category stats and recompute weak categories (mutates ``ps``)."""
    cs = ps.card_stats.setdefault(card_id, CardStat(category=category))
    cs.category = category
    _bump(cs, result, timestamp)
    cat = ps.category_stats.setdefault(category, CategoryStat())
    _bump(cat, result, timestamp)
    cat.recent = (cat.recent + [result])[-C.WEAK_WINDOW :]
    ps.weak_categories = compute_weak_categories(ps)


def compute_weak_categories(ps: ProblemState) -> list[str]:
    weak = []
    for name, st in ps.category_stats.items():
        if not st.recent:
            continue
        recent_acc = sum(C.RESULT_POINTS[r] for r in st.recent) / (C.MAX_POINTS * len(st.recent))
        low = len(st.recent) >= C.WEAK_MIN_SEEN and recent_acc < C.WEAK_ACCURACY
        if low or st.incorrect_streak >= C.WEAK_STREAK:
            weak.append(name)
    return sorted(weak)

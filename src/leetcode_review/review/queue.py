"""Strategic review queues for every mode. See docs/SRS.md ("Queue building")."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime

from .. import config as C
from ..catalog import Catalog, Filters
from ..content.loader import enabled_cards
from ..timeutil import day_start, parse_iso
from . import cards as cardlib
from . import topics
from .scheduler import days_overdue

MODES = ("daily", "weak", "cram", "interview", "filtered", "drill")


@dataclass
class QueueEntry:
    slug: str
    bucket: str
    priority: float


@dataclass
class QueuePlan:
    mode: str
    target: int
    entries: list[QueueEntry]
    counts: dict[str, int] = field(default_factory=dict)  # candidate counts per bucket
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- bucketing


def classify(cat: Catalog, slug: str, now: datetime) -> tuple[str, float] | None:
    """Daily-mode bucket and priority for a problem, or None if not a daily candidate."""
    ps = cat.state.get(slug)
    status = cat.due_status(slug)
    if status == "new":
        return "new", C.BUCKET_PRIORITY["new"]
    assert ps is not None
    weakness = C.WEAKNESS_BONUS * (1 - (ps.recent_accuracy if ps.recent_accuracy is not None else 0.5)) \
        + C.WEAK_CATEGORY_BONUS * len(ps.weak_categories)
    # Already reviewed today and not failed -> leave it for tomorrow's schedule.
    if ps.last_review and parse_iso(ps.last_review) >= day_start(now) and ps.level >= 1:
        return None
    recent_fail = (
        ps.last_score is not None
        and ps.last_score < C.DEMOTE_SCORE
        and ps.last_review is not None
        and (now - parse_iso(ps.last_review)).days <= C.RECENT_FAILURE_DAYS
    )
    if status == "overdue":
        bonus = C.OVERDUE_DAY_BONUS * min(days_overdue(ps, now), C.OVERDUE_DAY_BONUS_CAP)
        return "overdue", C.BUCKET_PRIORITY["overdue"] + bonus + weakness
    if status == "due":
        return "due", C.BUCKET_PRIORITY["due"] + weakness
    if recent_fail:
        return "recent_failure", C.BUCKET_PRIORITY["recent_failure"] + weakness
    is_weak = (ps.recent_accuracy is not None and ps.recent_accuracy < C.WEAK_PROBLEM_ACCURACY) or bool(
        ps.weak_categories
    )
    if is_weak:
        return "weak", C.BUCKET_PRIORITY["weak"] + weakness
    if ps.level >= C.RETENTION_MIN_LEVEL:
        return "retention", C.BUCKET_PRIORITY["retention"]
    return None


def bucket_counts(cat: Catalog) -> dict[str, int]:
    """How many problems with cards fall into each daily bucket right now."""
    counts: dict[str, int] = {}
    for p in cat.find():
        if cat.has_cards(p.slug):
            c = classify(cat, p.slug, cat.now)
            if c:
                counts[c[0]] = counts.get(c[0], 0) + 1
    return counts


def _diversity(cat: Catalog, slug: str, picked: list[str]) -> float:
    pat = cat.primary_pattern(slug)
    same = sum(1 for s in picked if cat.primary_pattern(s) == pat)
    return C.DIVERSITY_SELECT_FACTOR**same


def _weighted_pick(rng: random.Random, items: list, weights: list[float]):
    if sum(weights) <= 0:
        return rng.choice(items)
    return rng.choices(items, weights=weights)[0]


def order_for_diversity(cat: Catalog, entries: list[QueueEntry], rng: random.Random) -> list[QueueEntry]:
    """Reorder so consecutive problems rarely share a primary pattern (weighted random)."""
    remaining = list(entries)
    out: list[QueueEntry] = []
    near, far = C.DIVERSITY_ORDER_FACTORS
    while remaining:
        weights = []
        for e in remaining:
            w = max(e.priority, 1.0)
            pat = cat.primary_pattern(e.slug)
            if out and cat.primary_pattern(out[-1].slug) == pat:
                w *= near
            elif len(out) > 1 and cat.primary_pattern(out[-2].slug) == pat:
                w *= far
            weights.append(w)
        pick = _weighted_pick(rng, remaining, weights)
        remaining.remove(pick)
        out.append(pick)
    return out


def _select(
    cat: Catalog,
    urgent: list[QueueEntry],
    others: list[QueueEntry],
    target: int,
    rng: random.Random,
) -> list[QueueEntry]:
    picked: list[QueueEntry] = []
    pool = list(urgent)
    while pool and len(picked) < target:  # strict priority (jittered ties) with soft diversity
        slugs = [e.slug for e in picked]
        best = max(pool, key=lambda e: (e.priority + rng.uniform(0, C.TIE_JITTER)) * _diversity(cat, e.slug, slugs))
        pool.remove(best)
        picked.append(best)
    pool = list(others)
    while pool and len(picked) < target:  # weighted random for weak / new / retention
        slugs = [e.slug for e in picked]
        weights = [e.priority * _diversity(cat, e.slug, slugs) for e in pool]
        best = _weighted_pick(rng, pool, weights)
        pool.remove(best)
        picked.append(best)
    return picked


def _apply_topic_weights(cat: Catalog, entries: list[QueueEntry]) -> None:
    """Urgent problems get a small bucket-preserving nudge; the rest are scaled by topic share (see review/topics.py)."""
    rest = [e for e in entries if e.bucket not in C.URGENT_BUCKETS]
    factors = topics.share_factors(cat, [e.slug for e in rest])
    for e in entries:
        if e.bucket in C.URGENT_BUCKETS:
            e.priority += topics.urgent_nudge(cat, e.slug)
        else:
            e.priority *= factors[e.slug]


# --------------------------------------------------------------------------- plans


def _candidates(cat: Catalog, f: Filters) -> list[str]:
    return [p.slug for p in cat.find(f) if cat.has_cards(p.slug)]


def build_daily(cat: Catalog, target: int, rng: random.Random, f: Filters | None = None,
                *, all_due: bool = False) -> QueuePlan:
    now = cat.now
    entries: list[QueueEntry] = []
    for slug in _candidates(cat, f or Filters()):
        c = classify(cat, slug, now)
        if c:
            entries.append(QueueEntry(slug, *c))
    _apply_topic_weights(cat, entries)
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.bucket] = counts.get(e.bucket, 0) + 1
    urgent = [e for e in entries if e.bucket in C.URGENT_BUCKETS]
    others = [e for e in entries if e.bucket not in C.URGENT_BUCKETS]
    if all_due:
        target = max(target, len(urgent))
    chosen = order_for_diversity(cat, _select(cat, urgent, others, target, rng), rng)
    plan = QueuePlan("daily", target, chosen, counts)
    if len(urgent) > target:
        plan.notes.append(f"Due: {len(urgent)} > target {target}; selected the {target} highest-priority.")
    if not entries:
        plan.notes.append("Nothing is due or new. Try cram/weak/interview mode.")
    return plan


def build_weak(cat: Catalog, target: int, rng: random.Random, f: Filters | None = None) -> QueuePlan:
    scored = []
    for slug in _candidates(cat, f or Filters()):
        ps = cat.state.get(slug)
        if not ps or not ps.review_count and not ps.card_stats:
            continue
        acc = ps.recent_accuracy if ps.recent_accuracy is not None else 0.5
        w = (1 - acc) * 10 + C.WEAK_CATEGORY_BONUS * len(ps.weak_categories) + 2 * ps.lapses
        if ps.last_score is not None and ps.last_score < C.DEMOTE_SCORE:
            w += 3
        if w > 0:
            scored.append(QueueEntry(slug, "weak", w + 1))
    wf = topics.share_factors(cat, [e.slug for e in scored], exponent=C.WEAK_MODE_TOPIC_EXPONENT)
    for e in scored:
        e.priority *= wf[e.slug]
    chosen = _select(cat, sorted(scored, key=lambda e: -e.priority)[: target * 2], [], target, rng)
    plan = QueuePlan("weak", target, order_for_diversity(cat, chosen, rng), {"weak": len(scored)})
    if not scored:
        plan.notes.append("No review history yet - nothing to rank as weak. Try daily review first.")
    return plan


def _sample_by_level(cat: Catalog, slugs: list[str], target: int, rng: random.Random,
                     *, boost_due: bool, recency: bool) -> list[QueueEntry]:
    entries = []
    factors = topics.share_factors(cat, slugs)
    for slug in slugs:
        ps = cat.state.get(slug)
        w = 1.0 + (C.MAX_LEVEL - (ps.level if ps else 0)) / C.MAX_LEVEL  # lower mastery -> more likely
        if ps and ps.weak_categories:
            w += 0.5
        if boost_due and cat.due_status(slug) in ("due", "overdue"):
            w *= 3
        if recency and ps and ps.last_review:
            w *= 1 + min((cat.now - parse_iso(ps.last_review)).days, 60) / 30
        entries.append(QueueEntry(slug, "sampled", w * factors[slug]))
    return order_for_diversity(cat, _select(cat, [], entries, target, rng), rng)


def build_cram(cat: Catalog, target: int, rng: random.Random, f: Filters | None = None) -> QueuePlan:
    slugs = _candidates(cat, f or Filters())
    plan = QueuePlan("cram", target, _sample_by_level(cat, slugs, target, rng, boost_due=False, recency=False),
                     {"candidates": len(slugs)})
    _note_missing_list_coverage(cat, f, plan)
    return plan


def build_filtered(cat: Catalog, target: int, rng: random.Random, f: Filters | None = None) -> QueuePlan:
    slugs = _candidates(cat, f or Filters())
    plan = QueuePlan("filtered", target, _sample_by_level(cat, slugs, target, rng, boost_due=True, recency=False),
                     {"candidates": len(slugs)})
    _note_missing_list_coverage(cat, f, plan)
    return plan


def build_drill(cat: Catalog, target: int, rng: random.Random, f: Filters | None = None) -> QueuePlan:
    """Pattern drill: one recognition card per problem, no scheduling. Favours problems whose recognition card
    was failed or has never been asked (this includes unsolved problems), then the least recently drilled."""
    slugs = [s for s in _candidates(cat, f or Filters()) if cardlib.recognition_card(enabled_cards(cat.packs[s]))]
    factors = topics.share_factors(cat, slugs)
    entries = []
    for slug in slugs:
        rec = cardlib.recognition_card(enabled_cards(cat.packs[slug]))
        ps = cat.state.get(slug)
        cs = ps.card_stats.get(rec.id) if ps else None
        if cs is None or not cs.seen:
            w, bucket = C.DRILL_UNSEEN_WEIGHT, "new"
        else:
            w = 1.0 + C.DRILL_FAIL_WEIGHT * (cs.failed + 0.5 * cs.partial) / cs.seen
            if cs.last_seen_at:
                w *= 1 + min((cat.now - parse_iso(cs.last_seen_at)).days, 60) / 30
            bucket = "weak" if cs.last_result == "failed" else "retention"
        entries.append(QueueEntry(slug, bucket, w * factors[slug]))
    chosen = order_for_diversity(cat, _select(cat, [], entries, target, rng), rng)
    plan = QueuePlan("drill", target, chosen, {"candidates": len(slugs)})
    if not slugs:
        plan.notes.append("No problem has a recognition card yet.")
    _note_missing_list_coverage(cat, f, plan)
    return plan


def build_interview(cat: Catalog, target: int, rng: random.Random, f: Filters | None = None) -> QueuePlan:
    """Sample previously studied (solved or already reviewed) problems, favouring ones not seen recently."""
    studied = []
    for slug in _candidates(cat, f or Filters()):
        p, ps = cat.problems[slug], cat.state.get(slug)
        if p.status == "solved" or (ps and ps.review_count):
            studied.append(slug)
    plan = QueuePlan("interview", target, _sample_by_level(cat, studied, target, rng, boost_due=False, recency=True),
                     {"candidates": len(studied)})
    return plan


def _note_missing_list_coverage(cat: Catalog, f: Filters | None, plan: QueuePlan) -> None:
    if not f or not f.lists:
        return
    for name in f.lists:
        members = cat.lists.get(name, {}).get("problems", [])
        absent = [s for s in members if s not in cat.problems]
        no_pack = [s for s in members if s in cat.problems and not cat.has_cards(s)]
        if absent or no_pack:
            plan.notes.append(
                f"List '{name}': {len(members)} problems, {len(absent)} not imported, "
                f"{len(no_pack)} imported without review cards (skipped)."
            )


def build_queue(cat: Catalog, mode: str, target: int, rng: random.Random, f: Filters | None = None,
                *, all_due: bool = False) -> QueuePlan:
    if mode == "daily":
        return build_daily(cat, target, rng, f, all_due=all_due)
    builder = {"weak": build_weak, "cram": build_cram, "filtered": build_filtered, "interview": build_interview,
               "drill": build_drill}.get(mode)
    if builder is None:
        raise ValueError(f"unknown mode '{mode}' (choose from {', '.join(MODES)})")
    return builder(cat, target, rng, f)

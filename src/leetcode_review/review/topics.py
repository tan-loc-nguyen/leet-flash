"""Topic weights: how likely a topic is to come up in the interview. See docs/SRS.md ("Topic weights").

A problem's topic is its pack's *primary pattern* (the technique to recognise), mapped to a row of the weight table
(``config.TOPIC_PATTERNS``). Problems whose pack lists no pattern fall back to their LeetCode tags
(``config.TOPIC_TAGS``). Anything that maps to no row is "Unlisted" with a small default weight.

Weights are *shares*: when a pool of candidates is sampled, each problem is scaled by
``target share of its topic / share of the pool that topic occupies``, so the sessions you get follow the table
instead of the size of each topic in your problem bank. Overdue/due problems are only nudged (never dropped).
"""

from __future__ import annotations

import math
from collections import Counter

from .. import config as C
from ..catalog import Catalog

UNLISTED = "Unlisted"


def effective_weights(settings: dict) -> dict[str, float]:
    """Topic name -> weight, validated (non-negative numbers) and restricted to known topics."""
    weights = {}
    for topic, w in settings.get("topicWeights", {}).items():
        if topic not in C.TOPIC_PATTERNS:
            raise ValueError(f"unknown topic '{topic}' in topicWeights (known: {', '.join(C.TOPIC_PATTERNS)})")
        if not isinstance(w, (int, float)) or w < 0:
            raise ValueError(f"topicWeights['{topic}'] must be a number >= 0, got {w!r}")
        weights[topic] = float(w)
    return weights


def unlisted_weight(settings: dict) -> float:
    return float(settings.get("unlistedTopicWeight", C.DEFAULT_UNLISTED_TOPIC_WEIGHT))


def tag_rows(tags: list[str]) -> list[str]:
    """Weight-table rows implied by LeetCode tags (technique rows, else the generic row, else none)."""
    tagset = set(tags)
    rows = [t for t, tt in C.TOPIC_TAGS.items() if t != C.GENERIC_TOPIC and tagset & set(tt)]
    if tagset & set(C.DFS_BFS_TAGS):
        target = "Tree DFS/BFS" if tagset & set(C.TREE_TAGS) else "Graph DFS/BFS"
        if target not in rows:
            rows.append(target)
    if not rows and tagset & set(C.TOPIC_TAGS[C.GENERIC_TOPIC]):
        rows.append(C.GENERIC_TOPIC)
    return rows


def pattern_row(pattern: str) -> str | None:
    return next((t for t, pats in C.TOPIC_PATTERNS.items() if pattern in pats), None)


def row_of(cat: Catalog, slug: str) -> str | None:
    """The weight-table row of a problem: primary pack pattern, else (no pack pattern) its LeetCode tags."""
    pats = cat.patterns(slug)
    if pats:
        return pattern_row(pats[0])
    prob = cat.problems.get(slug)
    rows = tag_rows(prob.tags if prob else [])
    if not rows:
        return None
    w = effective_weights(cat.settings)
    return max(rows, key=lambda r: w.get(r, 0.0))


def topic_of(cat: Catalog, slug: str) -> tuple[str, float]:
    """(topic label, weight) for a problem."""
    weights = effective_weights(cat.settings)
    row = row_of(cat, slug)
    if row is None or row not in weights:
        return UNLISTED, unlisted_weight(cat.settings)
    return row, weights[row]


def _mean_weight(weights: dict[str, float]) -> float:
    return (sum(weights.values()) / len(weights) if weights else 1.0) or 1.0


def share_factors(cat: Catalog, slugs: list[str], *, exponent: float = 1.0) -> dict[str, float]:
    """Per-problem multiplier for sampling from ``slugs``: target topic share / the topic's share of the pool."""
    if not slugs:
        return {}
    topics = {s: topic_of(cat, s) for s in slugs}
    counts = Counter(label for label, _ in topics.values())
    weight_of = {label: w for label, w in topics.values()}
    total_w = sum(weight_of.values())
    n = len(slugs)
    out = {}
    for s, (label, w) in topics.items():
        if total_w <= 0:
            out[s] = 1.0
            continue
        f = (w / total_w) / (counts[label] / n)
        out[s] = min(f, C.SHARE_FACTOR_CAP) ** exponent
    return out


def urgent_nudge(cat: Catalog, slug: str) -> float:
    """Small additive priority change for overdue/due/recent-failure problems (never crosses a bucket)."""
    f = topic_of(cat, slug)[1] / _mean_weight(effective_weights(cat.settings))
    if f <= 0:
        return -C.URGENT_TOPIC_NUDGE_CAP
    return max(-C.URGENT_TOPIC_NUDGE_CAP, min(C.URGENT_TOPIC_NUDGE_CAP, C.URGENT_TOPIC_NUDGE * math.log2(f)))


def summary(cat: Catalog, slugs: list[str]) -> list[dict]:
    """Per-topic problem counts, target share and boost for `review.py plan` / set_topic_weight.py."""
    weights = effective_weights(cat.settings)
    counts = Counter(topic_of(cat, s)[0] for s in slugs)
    total = sum(weights.values()) + unlisted_weight(cat.settings)
    rows = [{"topic": t, "weight": w, "targetShare": round(w / total, 3) if total else 0, "problems": counts[t]}
            for t, w in weights.items()]
    rows.sort(key=lambda r: (-r["weight"], r["topic"]))
    uw = unlisted_weight(cat.settings)
    rows.append({"topic": UNLISTED, "weight": uw, "targetShare": round(uw / total, 3) if total else 0,
                 "problems": counts[UNLISTED]})
    return rows

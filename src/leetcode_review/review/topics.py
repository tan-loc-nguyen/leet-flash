"""Topic weights: how likely a topic is to come up in the interview. See docs/SRS.md ("Topic weights").

A problem's topic comes from its LeetCode tags (``Problem.tags``), mapped to the rows of the weight table in
``config.TOPIC_TAGS``. Rules, in order:

1. DFS/BFS tags count toward "Tree DFS/BFS" when the problem has a tree tag, otherwise toward "Graph DFS/BFS".
2. Technique rows (everything except the generic "Hashtable / array" row) win; several -> their mean weight.
3. Only generic tags (Array, Hash Table, String, ...) -> the generic row.
4. No mapped tag at all (Math, Design, Bit Manipulation, ...) -> the unlisted weight.
"""

from __future__ import annotations

from statistics import mean

from .. import config as C
from ..catalog import Catalog


def effective_weights(settings: dict) -> dict[str, float]:
    """Topic name -> weight, validated (non-negative numbers) and restricted to known topics."""
    weights = {}
    for topic, w in settings.get("topicWeights", {}).items():
        if topic not in C.TOPIC_TAGS:
            raise ValueError(f"unknown topic '{topic}' in topicWeights (known: {', '.join(C.TOPIC_TAGS)})")
        if not isinstance(w, (int, float)) or w < 0:
            raise ValueError(f"topicWeights['{topic}'] must be a number >= 0, got {w!r}")
        weights[topic] = float(w)
    return weights


def rows_of(tags: list[str]) -> list[str]:
    """Weight-table rows a problem belongs to (technique rows, else the generic row, else none)."""
    tagset = set(tags)
    has_tree = bool(tagset & set(C.TREE_TAGS))
    rows = []
    for topic, topic_tags in C.TOPIC_TAGS.items():
        if topic == C.GENERIC_TOPIC:
            continue
        if tagset & set(topic_tags):
            rows.append(topic)
    if tagset & set(C.DFS_BFS_TAGS):
        target = "Tree DFS/BFS" if has_tree else "Graph DFS/BFS"
        if target not in rows:
            rows.append(target)
    if not rows and tagset & set(C.TOPIC_TAGS[C.GENERIC_TOPIC]):
        rows.append(C.GENERIC_TOPIC)
    return rows


def _unlisted(settings: dict) -> float:
    return float(settings.get("unlistedTopicWeight", C.DEFAULT_UNLISTED_TOPIC_WEIGHT))


def _mean_weight(weights: dict[str, float]) -> float:
    return (mean(weights.values()) if weights else 1.0) or 1.0


def topic_of(cat: Catalog, slug: str) -> tuple[str, float]:
    """(topic label, weight) for a problem, derived from its LeetCode tags."""
    weights = effective_weights(cat.settings)
    prob = cat.problems.get(slug)
    rows = [r for r in rows_of(prob.tags if prob else []) if r in weights]
    if not rows:
        return "Unlisted", _unlisted(cat.settings)
    return " + ".join(rows), mean(weights[r] for r in rows)


def factor(cat: Catalog, slug: str) -> float:
    """Selection multiplier: the topic weight relative to the mean weight (1.0 = average topic)."""
    return topic_of(cat, slug)[1] / _mean_weight(effective_weights(cat.settings))


def urgent_nudge(cat: Catalog, slug: str) -> float:
    """Small additive priority change for overdue/due/recent-failure problems (never crosses a bucket)."""
    import math
    f = factor(cat, slug)
    if f <= 0:
        return -C.URGENT_TOPIC_NUDGE_CAP
    return max(-C.URGENT_TOPIC_NUDGE_CAP, min(C.URGENT_TOPIC_NUDGE_CAP, C.URGENT_TOPIC_NUDGE * math.log2(f)))


def summary(cat: Catalog, slugs: list[str]) -> list[dict]:
    """Per-row problem counts (a problem counts toward each of its rows) for `review.py plan` and set_topic_weight."""
    weights = effective_weights(cat.settings)
    norm = _mean_weight(weights)
    counts = {t: 0 for t in weights}
    unlisted = 0
    for slug in slugs:
        prob = cat.problems.get(slug)
        rows = [r for r in rows_of(prob.tags if prob else []) if r in weights]
        for r in rows:
            counts[r] += 1
        unlisted += not rows
    out = [{"topic": t, "weight": w, "factor": round(w / norm, 2), "problems": counts[t]} for t, w in weights.items()]
    out.sort(key=lambda r: (-r["weight"], r["topic"]))
    out.append({"topic": "Unlisted", "weight": _unlisted(cat.settings), "factor": round(_unlisted(cat.settings) / norm, 2),
                "problems": unlisted})
    return out

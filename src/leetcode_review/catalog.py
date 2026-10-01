"""In-memory view over problems, packs, state and lists, with filtering.

The data set is small (hundreds of files), so everything is loaded eagerly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from . import config as C
from .config import Paths
from .content.loader import enabled_cards, list_pack_slugs, load_lists, load_pack
from .review.scheduler import due_status
from .schemas import Problem, ProblemState, ReviewPack
from .storage.problems import ProblemStore
from .storage.review_state import ReviewStateStore


def normalize_topic(topic: str) -> str:
    t = topic.strip().lower()
    return C.TOPIC_ALIASES.get(t, t)


def topic_matches(topic: str, label: str) -> bool:
    t, lab = normalize_topic(topic), label.lower()
    if t == lab:
        return True
    if len(t) >= 4 and (t in lab or lab in t):
        return True
    return t.rstrip("s") == lab.rstrip("s")


@dataclass
class Filters:
    slugs: list[str] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    text: str | None = None  # title substring
    difficulties: list[str] = field(default_factory=list)
    status: str | None = None  # solved | unsolved
    topics: list[str] = field(default_factory=list)  # imported tag OR review pattern
    tags: list[str] = field(default_factory=list)  # imported tags only
    patterns: list[str] = field(default_factory=list)  # review-pack patterns only
    lists: list[str] = field(default_factory=list)
    min_level: int | None = None
    max_level: int | None = None
    due: bool | None = None  # due or overdue
    has_pack: bool | None = None
    reviewed: bool | None = None  # has any review recorded

    def is_empty(self) -> bool:
        return self == Filters()

    def describe(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], "")}


class Catalog:
    def __init__(self, paths: Paths, now: datetime):
        self.paths = paths
        self.now = now
        self.problems: dict[str, Problem] = ProblemStore(paths).load_all()
        self.state: dict[str, ProblemState] = ReviewStateStore(paths).load()
        self.lists: dict[str, dict] = load_lists(paths)
        self.packs: dict[str, ReviewPack] = {}
        for slug in list_pack_slugs(paths):
            pack = load_pack(paths, slug)
            if pack is not None:
                self.packs[slug] = pack

    # ------------------------------------------------------------- accessors
    def patterns(self, slug: str) -> list[str]:
        pack = self.packs.get(slug)
        return list(pack.patterns) if pack and pack.patterns else []

    def primary_pattern(self, slug: str) -> str:
        pats = self.patterns(slug)
        if pats:
            return pats[0]
        prob = self.problems.get(slug)
        return prob.tags[0] if prob and prob.tags else "Unknown"

    def has_cards(self, slug: str) -> bool:
        return bool(enabled_cards(self.packs.get(slug)))

    def due_status(self, slug: str) -> str:
        return due_status(self.state.get(slug), self.now)

    def list_membership(self, slug: str) -> list[str]:
        return [name for name, lst in self.lists.items() if slug in lst["problems"]]

    # ------------------------------------------------------------- filtering
    def matches(self, slug: str, f: Filters) -> bool:
        p = self.problems[slug]
        ps = self.state.get(slug)
        if f.slugs and slug not in f.slugs:
            return False
        if f.ids and (p.leetcode_id or "") not in f.ids:
            return False
        if f.text and f.text.lower() not in p.title.lower():
            return False
        if f.difficulties and (p.difficulty or "").lower() not in {d.lower() for d in f.difficulties}:
            return False
        if f.status and p.status != f.status:
            return False
        if f.tags and not any(topic_matches(t, tag) for t in f.tags for tag in p.tags):
            return False
        if f.patterns and not any(topic_matches(t, pat) for t in f.patterns for pat in self.patterns(slug)):
            return False
        if f.topics:
            labels = p.tags + self.patterns(slug)
            if not any(topic_matches(t, lab) for t in f.topics for lab in labels):
                return False
        if f.lists and not any(slug in self.lists.get(name, {}).get("problems", []) for name in f.lists):
            return False
        level = ps.level if ps else 0
        if f.min_level is not None and level < f.min_level:
            return False
        if f.max_level is not None and level > f.max_level:
            return False
        if f.due is not None and (self.due_status(slug) in ("due", "overdue")) != f.due:
            return False
        if f.has_pack is not None and self.has_cards(slug) != f.has_pack:
            return False
        if f.reviewed is not None and bool(ps and ps.review_count) != f.reviewed:
            return False
        return True

    def find(self, f: Filters | None = None) -> list[Problem]:
        f = f or Filters()
        out = [self.problems[s] for s in sorted(self.problems) if self.matches(s, f)]
        return sorted(out, key=lambda p: (int(p.leetcode_id) if (p.leetcode_id or "").isdigit() else 10**9, p.slug))

    def missing_packs(self, *, include_skeletons: bool = True) -> list[dict]:
        """Problems with no usable review pack. Skeletons (pack file but zero cards) count as missing."""
        out = []
        for p in self.find():
            if self.has_cards(p.slug):
                continue
            if p.slug in self.packs and not include_skeletons:
                continue
            out.append({
                "leetcodeId": p.leetcode_id,
                "slug": p.slug,
                "title": p.title,
                "status": "skeleton" if p.slug in self.packs else "missing",
            })
        return out

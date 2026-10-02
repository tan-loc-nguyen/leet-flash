"""Paths, settings, credentials and every tunable SRS/queue constant.

All tunable numbers live here so they can be reviewed in one place. They are
documented in docs/SRS.md.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Paths:
    """All filesystem locations. Tests build one around a tmp directory."""

    root: Path = REPO_ROOT

    @classmethod
    def from_env(cls) -> Paths:
        override = os.environ.get("LEETCODE_REVIEW_ROOT")
        return cls(Path(override).resolve()) if override else cls()

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def problems(self) -> Path:
        return self.data / "problems"

    @property
    def review_packs(self) -> Path:
        return self.data / "review-packs"

    @property
    def custom_cards(self) -> Path:
        return self.review_packs / "custom"

    @property
    def lists(self) -> Path:
        return self.data / "lists"

    @property
    def state_dir(self) -> Path:
        return self.data / "state"

    @property
    def review_state(self) -> Path:
        return self.state_dir / "review-state.json"

    @property
    def history(self) -> Path:
        return self.state_dir / "review-history.jsonl"

    @property
    def sessions(self) -> Path:
        return self.state_dir / "sessions.json"

    @property
    def settings(self) -> Path:
        return self.state_dir / "settings.json"

    @property
    def credentials(self) -> Path:
        return self.root / ".local" / "leetcode_credentials.json"

    def ensure_dirs(self) -> None:
        for d in (self.problems, self.review_packs, self.custom_cards, self.lists, self.state_dir):
            d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- settings

DEFAULT_SETTINGS = {
    "dailyProblemTarget": 10,
    "cardsPerProblem": 4,  # 3-5 recommended
    "showStatement": True,  # include the problem statement with the first question of each problem
    "leetcodeRequestDelaySeconds": 0.4,
}


def load_settings(paths: Paths) -> dict:
    settings = dict(DEFAULT_SETTINGS)
    if paths.settings.exists():
        settings.update(json.loads(paths.settings.read_text()))
    return settings


# --------------------------------------------------------------------------- credentials


@dataclass(frozen=True)
class Credentials:
    leetcode_session: str
    csrf_token: str = ""  # optional: the client fetches one from leetcode.com when empty

    def __repr__(self) -> str:  # never leak secrets into logs/tracebacks
        return "Credentials(leetcode_session='***', csrf_token='***')"


def load_credentials(paths: Paths) -> Credentials | None:
    """Load credentials from .local/leetcode_credentials.json, else env vars."""
    if paths.credentials.exists():
        data = json.loads(paths.credentials.read_text())
        session = data.get("leetcode_session")
        if session:
            return Credentials(session, data.get("csrf_token") or "")
    session = os.environ.get("LEETCODE_SESSION")
    csrf = os.environ.get("LEETCODE_CSRFTOKEN") or os.environ.get("LEETCODE_CSRF_TOKEN") or ""
    if session:
        return Credentials(session, csrf)
    return None


def save_credentials(paths: Paths, creds: Credentials) -> Path:
    paths.credentials.parent.mkdir(parents=True, exist_ok=True)
    paths.credentials.write_text(
        json.dumps({"leetcode_session": creds.leetcode_session, "csrf_token": creds.csrf_token}, indent=2)
        + "\n"
    )
    paths.credentials.chmod(0o600)
    return paths.credentials


# --------------------------------------------------------------------------- SRS tunables

# Mastery level -> days until next review. Level 0 means "again next session".
LEVEL_INTERVAL_DAYS = (0, 1, 3, 7, 14, 30, 60)
MAX_LEVEL = len(LEVEL_INTERVAL_DAYS) - 1
LEVEL_NAMES = (
    "New / Failed",
    "Early Learning",
    "Learning",
    "Developing",
    "Strong",
    "Very Strong",
    "Mastered",
)

RESULT_POINTS = {"failed": 0, "partial": 1, "correct": 2}
MAX_POINTS = 2

# Relative influence of a card's category on the problem score.
CATEGORY_WEIGHTS = {
    "pattern": 1.5,
    "main_insight": 1.5,
    "time_complexity": 1.25,
    "space_complexity": 1.25,
    "invariant": 1.25,
    "data_structure": 1.0,
    "alternative_approach": 1.0,
    "why_not": 1.0,
    "code_reasoning": 1.0,
    "edge_case": 0.9,
    "implementation_detail": 0.75,
}
CORE_CATEGORIES = ("pattern", "main_insight", "time_complexity", "space_complexity", "invariant")
# A failed card in these categories blocks promotion even with a high score.
PROMOTION_BLOCKING_CATEGORIES = ("pattern", "main_insight")

# Problem score thresholds (score is in [0, 1]).
PROMOTE_SCORE = 0.85
HOLD_SCORE = 0.60
DEMOTE_SCORE = 0.35
DROP_MIXED_POOR = 1  # 0.35 <= score < 0.60
DROP_FAILED = 2  # score < 0.35
DROP_FORGOT = 3  # "I don't remember this problem"
HOLD_INTERVAL_FACTOR = 0.75
WEAK_INTERVAL_FACTOR = 0.75
RECENT_ACCURACY_ALPHA = 0.5  # EMA weight of the newest problem score

# Weak-category detection (per problem, per category).
WEAK_WINDOW = 5  # last N results per category are considered
WEAK_MIN_SEEN = 2
WEAK_ACCURACY = 0.5
WEAK_STREAK = 2  # this many consecutive non-correct answers => weak

# --------------------------------------------------------------------------- queue tunables

BUCKET_PRIORITY = {
    "overdue": 100.0,
    "due": 70.0,
    "recent_failure": 55.0,
    "weak": 35.0,
    "new": 25.0,
    "retention": 8.0,
}
URGENT_BUCKETS = ("overdue", "due", "recent_failure")
OVERDUE_DAY_BONUS = 5.0
OVERDUE_DAY_BONUS_CAP = 10
WEAKNESS_BONUS = 10.0  # * (1 - recentAccuracy)
WEAK_CATEGORY_BONUS = 4.0  # per weak category
RECENT_FAILURE_DAYS = 3
WEAK_PROBLEM_ACCURACY = 0.6
RETENTION_MIN_LEVEL = 4
DIVERSITY_SELECT_FACTOR = 0.9  # per already-selected problem with the same primary pattern
DIVERSITY_ORDER_FACTORS = (0.1, 0.4)  # same pattern as previous / as two back
TIE_JITTER = 3.0

# --------------------------------------------------------------------------- card selection tunables

UNSEEN_CARD_BOOST = 1.5
WEAK_CATEGORY_BOOST = 2.5
FAIL_RATIO_BOOST = 1.5
RECENTLY_SEEN_FACTOR = 0.5  # cards seen within the last day
MAX_CARDS_PER_CATEGORY = 2
CORE_CARD_BASE = 1.5
# Card presentation order (recognition -> reasoning -> details).
CATEGORY_ORDER = (
    "pattern",
    "main_insight",
    "data_structure",
    "invariant",
    "alternative_approach",
    "why_not",
    "code_reasoning",
    "implementation_detail",
    "edge_case",
    "time_complexity",
    "space_complexity",
)
INTERVIEW_CATEGORY_BOOST = {
    "pattern": 2.0,
    "main_insight": 2.0,
    "time_complexity": 2.0,
    "space_complexity": 2.0,
    "invariant": 1.5,
    "data_structure": 1.5,
    "alternative_approach": 1.5,
    "why_not": 1.5,
    "implementation_detail": 1.5,
}

# --------------------------------------------------------------------------- topic aliases

TOPIC_ALIASES = {
    "dp": "dynamic programming",
    "bfs": "breadth-first search",
    "dfs": "depth-first search",
    "heap": "heap / priority queue",
    "heaps": "heap / priority queue",
    "priority queue": "heap / priority queue",
    "pq": "heap / priority queue",
    "dsu": "union find",
    "disjoint set": "union find",
    "topo sort": "topological sort",
    "topological": "topological sort",
    "trees": "tree",
    "binary tree": "tree",
    "graphs": "graph",
    "linked lists": "linked list",
    "two pointer": "two pointers",
    "hashing": "array / hashing",
    "hash map": "array / hashing",
    "hash table": "array / hashing",
    "arrays": "array / hashing",
    "array": "array / hashing",
    "strings": "string",
    "bst": "bst",
    "binary search tree": "bst",
    "stacks": "stack",
    "intervals": "intervals",
    "backtrack": "backtracking",
    "bit manipulation": "bit manipulation",
    "bits": "bit manipulation",
    "greedy": "greedy",
}

LEETCODE_BASE_URL = "https://leetcode.com"

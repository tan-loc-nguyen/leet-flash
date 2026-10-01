"""Current scheduling state (data/state/review-state.json): slug -> ProblemState."""

from __future__ import annotations

from ..config import Paths
from ..schemas import ProblemState
from .atomic_write import atomic_write_json, read_json


class ReviewStateStore:
    def __init__(self, paths: Paths):
        self.paths = paths

    def load(self) -> dict[str, ProblemState]:
        raw = read_json(self.paths.review_state, default={}) or {}
        return {slug: ProblemState.model_validate(v) for slug, v in raw.items()}

    def save(self, state: dict[str, ProblemState]) -> None:
        atomic_write_json(
            self.paths.review_state,
            {slug: ps.to_json() for slug, ps in state.items()},
            sort_keys=False,
        )

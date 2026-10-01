"""One JSON file per problem under data/problems/."""

from __future__ import annotations

import re
from pathlib import Path

from ..config import LEETCODE_BASE_URL, Paths
from ..schemas import Problem
from .atomic_write import atomic_write_json, read_json


def parse_slug(value: str) -> str:
    """Accept a slug or any leetcode.com/problems/<slug>/... URL."""
    value = value.strip()
    m = re.search(r"/problems/([^/?#\s]+)", value)
    slug = m.group(1) if m else value
    slug = slug.strip("/").lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise ValueError(f"'{value}' is not a valid LeetCode problem slug or URL")
    return slug


def problem_url(slug: str) -> str:
    return f"{LEETCODE_BASE_URL}/problems/{slug}/"


class ProblemStore:
    def __init__(self, paths: Paths):
        self.paths = paths

    def path_for(self, slug: str) -> Path:
        return self.paths.problems / f"{slug}.json"

    def exists(self, slug: str) -> bool:
        return self.path_for(slug).exists()

    def get(self, slug: str) -> Problem | None:
        data = read_json(self.path_for(slug))
        return Problem.model_validate(data) if data is not None else None

    def save(self, problem: Problem) -> None:
        atomic_write_json(self.path_for(problem.slug), problem.to_json())

    def load_all(self) -> dict[str, Problem]:
        out: dict[str, Problem] = {}
        if not self.paths.problems.exists():
            return out
        for f in sorted(self.paths.problems.glob("*.json")):
            out[f.stem] = Problem.model_validate(read_json(f))
        return out

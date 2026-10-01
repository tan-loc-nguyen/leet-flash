"""Create a valid skeleton review pack for a problem."""

from __future__ import annotations

from ..config import Paths
from ..schemas import TAG_TO_PATTERN, Problem, ReviewPack
from ..storage.atomic_write import atomic_write_json
from ..timeutil import iso, utcnow
from .loader import pack_path


def suggest_patterns(problem: Problem) -> list[str]:
    seen: list[str] = []
    for tag in problem.tags:
        p = TAG_TO_PATTERN.get(tag)
        if p and p not in seen:
            seen.append(p)
    return seen


def scaffold_pack(paths: Paths, problem: Problem, *, force: bool = False) -> tuple[ReviewPack, bool]:
    """Write the skeleton. Never overwrites an existing pack unless ``force``. Returns (pack, written)."""
    target = pack_path(paths, problem.slug)
    skeleton = ReviewPack(
        problem_slug=problem.slug,
        summary="",
        patterns=suggest_patterns(problem),
        generated_at=iso(utcnow()),
    )
    if target.exists() and not force:
        return skeleton, False
    atomic_write_json(target, skeleton.to_json())
    return skeleton, True

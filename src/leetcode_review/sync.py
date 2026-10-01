"""Import / incremental sync of solved LeetCode problems into data/problems/.

Idempotent: a problem file is only rewritten when its content actually changes.
Review packs, state, history and notes live elsewhere (or in preserved fields),
so a sync can never erase them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from .content.loader import refresh_solved_list
from .leetcode.graphql import CredentialsExpiredError, CredentialsMissingError, LeetCodeAPIError
from .leetcode.normalize import ProblemDetails, SolvedSummary
from .leetcode.provider import LeetCodeProvider
from .schemas import Problem
from .storage.problems import ProblemStore, parse_slug, problem_url
from .timeutil import iso


@dataclass
class SyncReport:
    solved_found: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    with_python: int = 0
    python_unavailable: int = 0
    converted_to_solved: list[str] = field(default_factory=list)
    new_slugs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def format(self) -> str:
        lines = [
            "LeetCode sync complete.",
            "",
            f"{self.solved_found} solved problems found",
            f"{self.new} newly imported",
            f"{self.updated} updated",
            f"{self.unchanged} unchanged",
            f"{self.with_python} have Python solutions",
            f"{self.python_unavailable} accepted Python submissions unavailable",
        ]
        if self.converted_to_solved:
            lines.append(f"{len(self.converted_to_solved)} converted unsolved -> solved: "
                         + ", ".join(self.converted_to_solved))
        if self.errors:
            lines += ["", f"{len(self.errors)} problem(s) had non-fatal errors:"] + [f"  - {e}" for e in self.errors]
        return "\n".join(lines)


def _comparable(p: Problem) -> dict:
    d = p.to_json()
    d.pop("lastSyncedAt", None)
    return d


def merge_problem(
    existing: Problem | None,
    summary: SolvedSummary,
    details: ProblemDetails | None,
    submission,  # AcceptedSubmission | None
    now: datetime,
) -> Problem:
    """Build the post-sync Problem, preserving everything we do not own (notes, extras)."""
    if existing is None:
        prob = Problem(title=summary.title, slug=summary.slug, url=problem_url(summary.slug), imported_at=iso(now))
    else:
        prob = existing.model_copy(deep=True)
    prob.leetcode_id = summary.leetcode_id or prob.leetcode_id
    prob.title = summary.title
    prob.difficulty = summary.difficulty or prob.difficulty
    prob.premium = summary.premium
    prob.tags = summary.tags or prob.tags
    # acRate drifts a little on every request; only record meaningful changes so syncs stay no-ops.
    if summary.ac_rate is not None and (prob.ac_rate is None or abs(summary.ac_rate - prob.ac_rate) >= 1.0):
        prob.ac_rate = summary.ac_rate
    prob.status = "solved"
    prob.source = "manual" if existing and existing.source == "manual" else "leetcode"
    if details:
        prob.leetcode_id = details.leetcode_id or prob.leetcode_id
        prob.tags = details.tags or prob.tags
        if details.statement:
            prob.problem_statement = details.statement
            prob.constraints = details.constraints
        prob.hints = details.hints or prob.hints
    if submission:
        prob.latest_submission = submission.submission
        prob.last_submitted_at = submission.submitted_at
    return prob


async def sync_problems(
    provider: LeetCodeProvider,
    store: ProblemStore,
    *,
    now: datetime,
    refresh: bool = False,
    only: set[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> SyncReport:
    """Import/sync all solved problems. Auth errors abort; per-problem API errors are reported."""
    await provider.validate_credentials()
    report = SyncReport()
    solved = await provider.get_solved_problems()
    if only:
        solved = [s for s in solved if s.slug in only]
    report.solved_found = len(solved)

    for i, summary in enumerate(solved, 1):
        slug = summary.slug
        existing = store.get(slug)
        details = None
        if existing is None or not existing.problem_statement or existing.source == "seed" or refresh:
            try:
                details = await provider.get_problem(slug)
            except (CredentialsExpiredError, CredentialsMissingError):
                raise
            except LeetCodeAPIError as exc:
                report.errors.append(f"{slug}: could not fetch problem details ({exc})")
        submission = None
        try:
            submission = await provider.get_latest_accepted_submission(slug)
        except (CredentialsExpiredError, CredentialsMissingError):
            raise
        except LeetCodeAPIError as exc:
            report.errors.append(f"{slug}: could not fetch accepted submission ({exc})")

        merged = merge_problem(existing, summary, details, submission, now)
        if existing is None:
            merged.last_synced_at = iso(now)
            store.save(merged)
            report.new += 1
            report.new_slugs.append(slug)
        elif _comparable(merged) != _comparable(existing):
            if existing.status == "unsolved":
                report.converted_to_solved.append(slug)
            merged.last_synced_at = iso(now)
            store.save(merged)
            report.updated += 1
        else:
            report.unchanged += 1
        if merged.latest_submission:
            report.with_python += 1
        else:
            report.python_unavailable += 1
        if progress:
            progress(f"[{i}/{len(solved)}] {slug}")
    ordered = sorted(solved, key=lambda x: (int(x.leetcode_id) if (x.leetcode_id or "").isdigit() else 10**9, x.slug))
    refresh_solved_list(store.paths, [x.slug for x in ordered])
    return report


async def add_problem(
    provider: LeetCodeProvider,
    store: ProblemStore,
    slug_or_url: str,
    *,
    now: datetime,
    offline: bool = False,
) -> tuple[Problem, bool]:
    """Add a manually-tracked (unsolved) problem. Returns (problem, created)."""
    slug = parse_slug(slug_or_url)
    existing = store.get(slug)
    if existing:
        return existing, False
    prob = Problem(
        title=slug.replace("-", " ").title(),
        slug=slug,
        url=problem_url(slug),
        status="unsolved",
        source="manual",
        imported_at=iso(now),
        last_synced_at=iso(now),
    )
    if not offline:
        details = await provider.get_problem(slug)
        if details is None:
            raise LeetCodeAPIError(f"LeetCode has no problem with slug '{slug}'")
        prob.leetcode_id = details.leetcode_id
        prob.title = details.title
        prob.difficulty = details.difficulty
        prob.premium = details.premium
        prob.tags = details.tags
        prob.problem_statement = details.statement
        prob.constraints = details.constraints
        prob.hints = details.hints
        prob.ac_rate = details.ac_rate
    store.save(prob)
    return prob, True

"""LeetCodeProvider: the only place that knows how to talk to LeetCode.

Unofficial API - if LeetCode changes, repair graphql.py / normalize.py / this file only.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..config import Credentials
from ..schemas import Submission
from .graphql import (
    QUERY_PROBLEM,
    QUERY_SOLVED,
    QUERY_SUBMISSION_DETAILS,
    QUERY_SUBMISSION_LIST,
    QUERY_USER_STATUS,
    CredentialsExpiredError,
    CredentialsMissingError,
    GraphQLClient,
    LeetCodeAPIError,
)
from .normalize import (
    ProblemDetails,
    SolvedSummary,
    language_label,
    normalize_details,
    normalize_solved,
    normalize_submission,
    pick_latest_python,
)

@dataclass
class AcceptedSubmission:
    submission: Submission
    submitted_at: str | None  # ISO timestamp


PAGE_SIZE = 100
SUBMISSION_PAGE_SIZE = 20


class LeetCodeProvider:
    def __init__(
        self,
        credentials: Credentials | None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        request_delay: float = 0.0,
        base_url: str | None = None,
        max_submission_pages: int = 10,
    ):
        kwargs = {"base_url": base_url} if base_url else {}
        self._gql = GraphQLClient(credentials, transport=transport, request_delay=request_delay, **kwargs)
        self.has_credentials = credentials is not None
        self.max_submission_pages = max_submission_pages

    async def aclose(self) -> None:
        await self._gql.aclose()

    async def __aenter__(self) -> LeetCodeProvider:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    def _require_credentials(self) -> None:
        if not self.has_credentials:
            raise CredentialsMissingError()

    async def validate_credentials(self) -> str:
        """Return the signed-in username or raise CredentialsExpiredError."""
        self._require_credentials()
        data = await self._gql.query(QUERY_USER_STATUS)
        status = data.get("userStatus") or {}
        if not status.get("isSignedIn"):
            raise CredentialsExpiredError()
        return status.get("username") or ""

    async def get_solved_problems(self) -> list[SolvedSummary]:
        self._require_credentials()
        out: list[SolvedSummary] = []
        skip = 0
        while True:
            data = await self._gql.query(
                QUERY_SOLVED,
                {"categorySlug": "", "skip": skip, "limit": PAGE_SIZE, "filters": {"status": "AC"}},
            )
            block = data.get("problemsetQuestionList") or {}
            questions = block.get("questions") or []
            out += [normalize_solved(q) for q in questions]
            skip += len(questions)
            if not questions or skip >= int(block.get("total") or 0):
                break
        return out

    async def get_problem(self, slug: str) -> ProblemDetails | None:
        data = await self._gql.query(QUERY_PROBLEM, {"titleSlug": slug})
        raw = data.get("question")
        return normalize_details(raw) if raw else None

    async def get_latest_accepted_submission(self, slug: str) -> AcceptedSubmission | None:
        """Latest accepted Python3 (else Python) submission with code, or None."""
        self._require_credentials()
        collected = []
        offset = 0
        for _ in range(self.max_submission_pages):
            data = await self._gql.query(
                QUERY_SUBMISSION_LIST,
                {"offset": offset, "limit": SUBMISSION_PAGE_SIZE, "questionSlug": slug},
            )
            block = data.get("questionSubmissionList") or {}
            subs = [normalize_submission(s) for s in block.get("submissions") or []]
            collected += subs
            offset += SUBMISSION_PAGE_SIZE
            # Newest first: once an accepted Python3 shows up nothing later can beat it.
            if any(s.status == "Accepted" and s.lang == "python3" for s in subs):
                break
            if not block.get("hasNext"):
                break
        best = pick_latest_python(collected)
        if best is None:
            return None
        detail = (await self._gql.query(QUERY_SUBMISSION_DETAILS, {"submissionId": int(best.id)})).get(
            "submissionDetails"
        )
        if not detail or not detail.get("code"):
            raise LeetCodeAPIError(f"Could not fetch code for submission {best.id}")
        sub = Submission(submission_id=best.id, language=language_label(best.lang), code=detail["code"])
        return AcceptedSubmission(sub, best.timestamp)

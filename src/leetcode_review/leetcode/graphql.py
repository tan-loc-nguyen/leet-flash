"""LeetCode GraphQL transport: queries, headers, retries, auth-failure detection."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..config import LEETCODE_BASE_URL, Credentials

EXPIRED_MESSAGE = (
    "Your LeetCode session appears to have expired.\n"
    "Please provide a new LEETCODE_SESSION and csrftoken."
)


class LeetCodeError(Exception):
    pass


class CredentialsMissingError(LeetCodeError):
    def __init__(self) -> None:
        super().__init__(
            "No LeetCode credentials found. Provide LEETCODE_SESSION and csrftoken "
            "(see README: scripts/set_credentials.py)."
        )


class CredentialsExpiredError(LeetCodeError):
    def __init__(self) -> None:
        super().__init__(EXPIRED_MESSAGE)


class LeetCodeAPIError(LeetCodeError):
    pass


QUERY_USER_STATUS = """
query globalData { userStatus { isSignedIn username } }
"""

QUERY_SOLVED = """
query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
  problemsetQuestionList: questionList(categorySlug: $categorySlug, limit: $limit, skip: $skip, filters: $filters) {
    total: totalNum
    questions: data {
      acRate difficulty frontendQuestionId: questionFrontendId paidOnly: isPaidOnly
      status title titleSlug topicTags { name slug }
    }
  }
}
"""

QUERY_PROBLEM = """
query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionId questionFrontendId title titleSlug content difficulty isPaidOnly
    acRate hints status topicTags { name slug }
  }
}
"""

QUERY_SUBMISSION_LIST = """
query submissionList($offset: Int!, $limit: Int!, $questionSlug: String!) {
  questionSubmissionList(offset: $offset, limit: $limit, questionSlug: $questionSlug) {
    hasNext
    submissions { id statusDisplay lang langName timestamp }
  }
}
"""

QUERY_SUBMISSION_DETAILS = """
query submissionDetails($submissionId: Int!) {
  submissionDetails(submissionId: $submissionId) {
    id code timestamp statusCode lang { name verboseName }
  }
}
"""


class GraphQLClient:
    def __init__(
        self,
        credentials: Credentials | None,
        *,
        base_url: str = LEETCODE_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        request_delay: float = 0.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.authenticated = credentials is not None
        self.request_delay = request_delay
        self.max_retries = max_retries
        self._credentials = credentials
        headers = {
            "Content-Type": "application/json",
            "Referer": self.base_url,
            "Origin": self.base_url,
            "User-Agent": "Mozilla/5.0 (compatible; leetcode-review/0.1)",
        }
        self._client = httpx.AsyncClient(headers=headers, transport=transport, timeout=30.0)
        self._csrf = credentials.csrf_token if credentials else ""
        self._apply_cookies()

    def _apply_cookies(self) -> None:
        if not self._credentials:
            return
        cookie = f"LEETCODE_SESSION={self._credentials.leetcode_session}"
        if self._csrf:
            cookie += f"; csrftoken={self._csrf}"
            self._client.headers["x-csrftoken"] = self._csrf
        self._client.headers["Cookie"] = cookie

    async def _ensure_csrf(self) -> None:
        """LeetCode sets a csrftoken cookie on any page load; obtain one if the user gave none."""
        if not self._credentials or self._csrf:
            return
        try:
            resp = await self._client.get(f"{self.base_url}/")
        except httpx.TransportError:
            return
        token = resp.cookies.get("csrftoken")
        if token:
            self._csrf = token
            self._apply_cookies()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"query": query, "variables": variables or {}}
        await self._ensure_csrf()
        for attempt in range(self.max_retries + 1):
            if self.request_delay:
                await asyncio.sleep(self.request_delay)
            try:
                resp = await self._client.post(f"{self.base_url}/graphql/", json=payload)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise LeetCodeAPIError(f"Network error talking to LeetCode: {type(exc).__name__}") from exc
                await asyncio.sleep(min(2**attempt, 8) * (self.request_delay or 0.01))
                continue
            if resp.status_code in (401, 403):
                if self.authenticated:
                    raise CredentialsExpiredError()
                raise LeetCodeAPIError(
                    f"LeetCode refused the request ({resp.status_code}); credentials may be required."
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries:
                    raise LeetCodeAPIError(f"LeetCode kept responding with HTTP {resp.status_code}")
                await asyncio.sleep(min(2**attempt, 30) * (self.request_delay or 0.01))
                continue
            if resp.status_code != 200:
                raise LeetCodeAPIError(f"Unexpected HTTP {resp.status_code} from LeetCode")
            body = resp.json()
            if body.get("errors") and not body.get("data"):
                msg = "; ".join(e.get("message", "?") for e in body["errors"])
                if "login" in msg.lower() or "sign in" in msg.lower() or "permission" in msg.lower():
                    if self.authenticated:
                        raise CredentialsExpiredError()
                raise LeetCodeAPIError(f"LeetCode GraphQL error: {msg}")
            return body.get("data") or {}
        raise LeetCodeAPIError("unreachable")  # pragma: no cover

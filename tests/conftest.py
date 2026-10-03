from __future__ import annotations

import json
import random
from datetime import UTC, datetime

import httpx
import pytest

from leetcode_review.config import Credentials, Paths
from leetcode_review.schemas import Problem
from leetcode_review.storage.atomic_write import atomic_write_json
from leetcode_review.storage.problems import ProblemStore

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def paths(tmp_path) -> Paths:
    p = Paths(tmp_path)
    p.ensure_dirs()
    atomic_write_json(p.settings, {"dailyProblemTarget": 10, "cardsPerProblem": 4, "leetcodeRequestDelaySeconds": 0})
    return p


@pytest.fixture
def rng() -> random.Random:
    return random.Random(1234)


# ------------------------------------------------------------------ builders


def make_problem(paths: Paths, slug: str, *, status="solved", difficulty="Medium", tags=("Array",), **kw) -> Problem:
    prob = Problem(title=slug.replace("-", " ").title(), slug=slug, url=f"https://leetcode.com/problems/{slug}/",
                   status=status, difficulty=difficulty, tags=list(tags), leetcode_id=str(kw.pop("leetcode_id", abs(hash(slug)) % 3000)),
                   **kw)
    ProblemStore(paths).save(prob)
    return prob


def mcq(cid, category="pattern", answer="A-opt"):
    return {"id": cid, "category": category, "type": "multiple_choice",
            "promptVariants": [f"{cid} prompt one", f"{cid} prompt two"],
            "options": ["A-opt", "B-opt", "C-opt", "D-opt"], "answer": answer,
            "explanation": "because", "incorrectOptionExplanations": {"B-opt": "no b", "C-opt": "no c"}}


def free(cid, category="main_insight"):
    return {"id": cid, "category": category, "type": "free_recall", "promptVariants": [f"{cid} q"],
            "answer": "reference", "keyPoints": ["k1"], "explanation": "expl"}


def recog(cid, technique="Two pointers on the sorted array", **kw):
    """A recognition card: free-recall pattern card with a grading rubric."""
    from leetcode_review.schemas import RECOGNITION_PROMPTS
    card = {"id": cid, "category": "pattern", "type": "free_recall", "promptVariants": list(RECOGNITION_PROMPTS),
            "answer": f"{technique}. Clue: the input is sorted.", "keyPoints": ["The input is sorted."],
            "explanation": "Sorted order lets two pointers discard one end per step.",
            "rubric": {"technique": technique, "aliases": ["two pointers", "left and right pointers"],
                       "alsoValid": [{"name": "hash map of complements", "note": "uses O(n) extra space"}],
                       "clueTypes": ["sorted_or_ordered"], "clue": "The input is sorted."}}
    card.update(kw)
    return card


def make_pack(paths: Paths, slug: str, *, patterns=("Array / Hashing",), cards=None) -> None:
    cards = cards if cards is not None else [
        mcq(f"{slug}-pattern-01", "pattern"), free(f"{slug}-insight-01", "main_insight"),
        {"id": f"{slug}-time-01", "category": "time_complexity", "type": "fill_blank",
         "promptVariants": ["Time: ___"], "answer": "O(n)", "explanation": "linear"},
        free(f"{slug}-space-01", "space_complexity"), free(f"{slug}-edge-01", "edge_case"),
    ]
    atomic_write_json(paths.review_packs / f"{slug}.json", {
        "problemSlug": slug, "summary": f"Summary of {slug}", "patterns": list(patterns),
        "approaches": [{"name": "Main", "summary": "s", "timeComplexity": "O(n)", "spaceComplexity": "O(1)"}],
        "cards": cards,
    })


# ------------------------------------------------------------------ fake LeetCode


class FakeLeetCode:
    """In-memory LeetCode. Dispatches on the GraphQL operation found in the query text."""

    def __init__(self):
        self.signed_in = True
        self.http_status: int | None = None
        self.solved: list[dict] = []          # raw questionList rows
        self.details: dict[str, dict] = {}    # slug -> raw question
        self.submissions: dict[str, list[dict]] = {}  # slug -> raw submissions (newest first)
        self.codes: dict[int, str] = {}
        self.calls: list[str] = []

    def add_problem(self, slug, fid, title, *, difficulty="Medium", tags=("Array",), solved=True,
                    content="<p>Statement.</p><p><strong>Constraints:</strong></p><ul><li><code>1 &lt;= n &lt;= 10</code></li></ul>",
                    subs=()):
        topic = [{"name": t, "slug": t.lower()} for t in tags]
        if solved:
            self.solved.append({"acRate": 50.123, "difficulty": difficulty, "frontendQuestionId": str(fid),
                                "paidOnly": False, "status": "ac", "title": title, "titleSlug": slug, "topicTags": topic})
        self.details[slug] = {"questionId": str(fid + 5000), "questionFrontendId": str(fid), "title": title,
                              "titleSlug": slug, "content": content, "difficulty": difficulty, "isPaidOnly": False,
                              "acRate": 50.123, "hints": ["<p>a hint</p>"], "topicTags": topic}
        self.submissions[slug] = []
        for sid, lang, status, ts, code in subs:
            self.add_submission(slug, sid, lang, status, ts, code)

    def add_submission(self, slug, sid, lang, status, ts, code):
        self.submissions.setdefault(slug, []).insert(0, {"id": str(sid), "statusDisplay": status, "lang": lang,
                                                         "langName": lang, "timestamp": str(ts)})
        self.codes[sid] = code

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text="ok", headers={"set-cookie": "csrftoken=fetched-token; Path=/"})
        if self.http_status:
            return httpx.Response(self.http_status, json={})
        body = json.loads(request.content)
        q, v = body["query"], body["variables"]
        self.calls.append(q.split("(")[0].split("{")[0].strip().replace("query ", ""))
        if "userStatus" in q:
            return self._ok({"userStatus": {"isSignedIn": self.signed_in, "username": "tester" if self.signed_in else None}})
        if "questionList" in q:
            rows = self.solved[v["skip"]: v["skip"] + v["limit"]]
            return self._ok({"problemsetQuestionList": {"total": len(self.solved), "questions": rows}})
        if "questionData" in q:
            return self._ok({"question": self.details.get(v["titleSlug"])})
        if "questionSubmissionList" in q:
            subs = self.submissions.get(v["questionSlug"], [])
            page = subs[v["offset"]: v["offset"] + v["limit"]]
            return self._ok({"questionSubmissionList": {"hasNext": v["offset"] + v["limit"] < len(subs), "submissions": page}})
        if "submissionDetails" in q:
            sid = v["submissionId"]
            return self._ok({"submissionDetails": {"id": str(sid), "code": self.codes[sid], "timestamp": 1}})
        return httpx.Response(400, json={"errors": [{"message": "unknown query"}]})

    @staticmethod
    def _ok(data):
        return httpx.Response(200, json={"data": data})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def fake() -> FakeLeetCode:
    f = FakeLeetCode()
    f.add_problem("two-sum", 1, "Two Sum", difficulty="Easy", tags=("Array", "Hash Table"), subs=[
        (101, "cpp", "Accepted", 1700000000, "// cpp"),
        (102, "python3", "Accepted", 1700000100, "class Solution:\n    pass  # old"),
        (103, "python3", "Wrong Answer", 1700000200, "bad"),
    ])
    f.add_problem("valid-parentheses", 20, "Valid Parentheses", difficulty="Easy", tags=("String", "Stack"), subs=[
        (201, "python3", "Accepted", 1700001000, "class Solution:\n    pass  # vp"),
    ])
    f.add_problem("lonely-cpp", 999, "Lonely Cpp", subs=[(301, "cpp", "Accepted", 1700002000, "// only cpp")])
    return f


@pytest.fixture
def creds() -> Credentials:
    return Credentials("session-secret", "csrf-secret")

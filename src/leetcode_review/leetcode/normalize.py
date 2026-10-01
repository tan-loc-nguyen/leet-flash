"""Pure functions turning raw LeetCode GraphQL payloads into our own types.

All knowledge of LeetCode's response shapes lives here and in graphql.py/provider.py.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from ..timeutil import from_epoch


@dataclass
class SolvedSummary:
    leetcode_id: str | None
    title: str
    slug: str
    difficulty: str | None
    premium: bool
    tags: list[str] = field(default_factory=list)
    ac_rate: float | None = None


@dataclass
class ProblemDetails:
    leetcode_id: str | None
    title: str
    slug: str
    difficulty: str | None
    premium: bool
    tags: list[str]
    statement: str
    constraints: list[str]
    hints: list[str]
    ac_rate: float | None = None


@dataclass
class RawSubmission:
    id: str
    status: str
    lang: str  # LeetCode language slug, e.g. "python3"
    timestamp: str | None  # ISO
    code: str | None = None


# --------------------------------------------------------------------------- HTML -> text


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "ul", "ol", "li", "pre", "h1", "h2", "h3", "h4", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.sup = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")
        if tag == "sup":
            self.parts.append("^")

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(content: str | None) -> str:
    if not content:
        return ""
    parser = _TextExtractor()
    parser.feed(content)
    text = html.unescape("".join(parser.parts)).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_constraints(statement_text: str) -> list[str]:
    """Pull the bullet lines following a 'Constraints:' heading."""
    m = re.search(r"Constraints?:\s*\n(.*)", statement_text, re.S | re.I)
    if not m:
        return []
    out: list[str] = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith("- "):
            out.append(line[2:].strip())
        elif line and out:
            break  # first non-bullet text after bullets ends the section (e.g. "Follow up:")
    return out


# --------------------------------------------------------------------------- normalizers


def _difficulty(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().capitalize()
    return v if v in ("Easy", "Medium", "Hard") else value


def _tags(raw: dict) -> list[str]:
    return [t["name"] for t in (raw.get("topicTags") or []) if t.get("name")]


def normalize_solved(raw: dict) -> SolvedSummary:
    ac = raw.get("acRate")
    return SolvedSummary(
        leetcode_id=str(raw["frontendQuestionId"]) if raw.get("frontendQuestionId") is not None else None,
        title=raw["title"],
        slug=raw["titleSlug"],
        difficulty=_difficulty(raw.get("difficulty")),
        premium=bool(raw.get("paidOnly")),
        tags=_tags(raw),
        ac_rate=round(float(ac), 2) if ac is not None else None,
    )


def normalize_details(raw: dict) -> ProblemDetails:
    statement = html_to_text(raw.get("content"))
    return ProblemDetails(
        leetcode_id=str(raw["questionFrontendId"]) if raw.get("questionFrontendId") is not None else None,
        title=raw["title"],
        slug=raw["titleSlug"],
        difficulty=_difficulty(raw.get("difficulty")),
        premium=bool(raw.get("isPaidOnly")),
        tags=_tags(raw),
        statement=statement,
        constraints=extract_constraints(statement),
        hints=[html_to_text(h) for h in (raw.get("hints") or []) if h],
        ac_rate=round(float(raw["acRate"]), 2) if raw.get("acRate") is not None else None,
    )


def normalize_submission(raw: dict) -> RawSubmission:
    ts = raw.get("timestamp")
    return RawSubmission(
        id=str(raw["id"]),
        status=raw.get("statusDisplay") or "",
        lang=(raw.get("lang") or "").lower(),
        timestamp=from_epoch(ts) if ts not in (None, "") else None,
    )


def language_label(lang_slug: str) -> str:
    return {"python3": "Python3", "python": "Python"}.get(lang_slug, lang_slug)


def pick_latest_python(submissions: list[RawSubmission]) -> RawSubmission | None:
    """Newest accepted Python3 submission; falls back to newest accepted Python (2)."""
    accepted = [s for s in submissions if s.status == "Accepted"]
    for wanted in ("python3", "python"):
        matches = [s for s in accepted if s.lang == wanted]
        if matches:
            return max(matches, key=lambda s: s.timestamp or "")
    return None

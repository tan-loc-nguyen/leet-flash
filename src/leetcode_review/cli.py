"""Shared helpers for the scripts in scripts/."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .catalog import Filters
from .config import Paths, load_credentials, load_settings
from .leetcode.graphql import LeetCodeError
from .leetcode.provider import LeetCodeProvider
from .storage.problems import ProblemStore
from .sync import sync_problems
from .timeutil import utcnow


def emit(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def add_filter_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("filters")
    g.add_argument("--topic", action="append", default=[], help="imported tag OR review pattern (e.g. 'graph', 'dp')")
    g.add_argument("--tag", action="append", default=[], help="imported LeetCode tag only")
    g.add_argument("--pattern", action="append", default=[], help="review-pack pattern only")
    g.add_argument("--difficulty", action="append", default=[], help="Easy / Medium / Hard (repeatable)")
    g.add_argument("--list", dest="lists", action="append", default=[], help="list name, e.g. solved")
    g.add_argument("--status", choices=["solved", "unsolved"])
    g.add_argument("--slug", action="append", default=[])
    g.add_argument("--id", dest="ids", action="append", default=[], help="LeetCode frontend id")
    g.add_argument("--text", help="title substring")
    g.add_argument("--min-level", type=int)
    g.add_argument("--max-level", type=int)


def filters_from_args(a: argparse.Namespace) -> Filters:
    return Filters(
        slugs=a.slug, ids=a.ids, text=getattr(a, "text", None), difficulties=a.difficulty, status=a.status,
        topics=a.topic, tags=a.tag, patterns=a.pattern, lists=a.lists,
        min_level=a.min_level, max_level=a.max_level,
        due=getattr(a, "due", None), has_pack=getattr(a, "has_pack", None),
    )


def run_sync(*, refresh: bool, only: set[str] | None = None) -> int:
    """Shared by import_leetcode.py and sync_leetcode.py."""
    paths = Paths.from_env()
    creds = load_credentials(paths)
    settings = load_settings(paths)

    async def go():
        async with LeetCodeProvider(creds, request_delay=float(settings["leetcodeRequestDelaySeconds"])) as prov:
            return await sync_problems(
                prov, ProblemStore(paths), now=utcnow(), refresh=refresh, only=only,
                progress=lambda m: print(m, file=sys.stderr),
            )

    try:
        report = asyncio.run(go())
    except LeetCodeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(report.format())
    packs = len(ProblemStore(paths).load_all())
    from .catalog import Catalog

    missing = len(Catalog(paths, utcnow()).missing_packs())
    print(f"\n{missing} of {packs} problems currently have no review pack "
          "(run scripts/list_missing_review_packs.py).")
    return 0

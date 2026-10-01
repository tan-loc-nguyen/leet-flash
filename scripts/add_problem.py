"""Add unsolved LeetCode problem(s) by slug or URL (statement + metadata are fetched when possible).

  uv run python scripts/add_problem.py minimum-window-substring
  uv run python scripts/add_problem.py https://leetcode.com/problems/minimum-window-substring/ two-sum ...
  uv run python scripts/add_problem.py --file slugs.txt
A later sync_leetcode.py converts them to solved (and fetches your Python solution) once you solve them.
Existing problems are never overwritten.
"""

import argparse
import asyncio
import sys

from leetcode_review.config import Paths, load_credentials, load_settings
from leetcode_review.leetcode.graphql import CredentialsExpiredError, LeetCodeError
from leetcode_review.leetcode.provider import LeetCodeProvider
from leetcode_review.storage.problems import ProblemStore, parse_slug
from leetcode_review.sync import add_problem
from leetcode_review.timeutil import utcnow

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("problems", nargs="*", help="slugs or leetcode.com/problems/... URLs")
ap.add_argument("--file", help="file with one slug/URL per line")
ap.add_argument("--offline", action="store_true", help="do not call LeetCode; create stubs from the slug")
a = ap.parse_args()
raw = list(a.problems)
if a.file:
    raw += [ln.strip() for ln in open(a.file) if ln.strip() and not ln.startswith("#")]
if not raw:
    sys.exit("ERROR: give at least one problem (or --file)")
paths = Paths.from_env()
delay = float(load_settings(paths)["leetcodeRequestDelaySeconds"])


async def go() -> int:
    failures = 0
    async with LeetCodeProvider(load_credentials(paths), request_delay=delay) as prov:
        store = ProblemStore(paths)
        for item in raw:
            try:
                prob, created = await add_problem(prov, store, item, now=utcnow(), offline=a.offline)
            except CredentialsExpiredError:
                raise
            except (LeetCodeError, ValueError) as exc:
                print(f"ERROR {item}: {exc}", file=sys.stderr)
                failures += 1
                continue
            note = "" if prob.problem_statement or not created else "  (no statement stored: premium/offline)"
            print(f"{'Added' if created else 'Exists'}: {prob.leetcode_id or '-':>5} {prob.title} [{prob.status}]{note}")
    return failures


try:
    failed = asyncio.run(go())
except LeetCodeError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    sys.exit(2)
sys.exit(1 if failed else 0)

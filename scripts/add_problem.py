"""Add an unsolved LeetCode problem by slug or URL.

  uv run python scripts/add_problem.py minimum-window-substring
  uv run python scripts/add_problem.py https://leetcode.com/problems/minimum-window-substring/
A later sync_leetcode.py converts it to solved (and fetches your Python solution) once you solve it.
"""

import argparse
import asyncio
import sys

from leetcode_review.config import Paths, load_credentials
from leetcode_review.leetcode.graphql import LeetCodeError
from leetcode_review.leetcode.provider import LeetCodeProvider
from leetcode_review.storage.problems import ProblemStore
from leetcode_review.sync import add_problem
from leetcode_review.timeutil import utcnow

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("problem", help="slug or leetcode.com/problems/... URL")
ap.add_argument("--offline", action="store_true", help="do not call LeetCode; create a stub from the slug")
a = ap.parse_args()
paths = Paths.from_env()


async def go():
    async with LeetCodeProvider(load_credentials(paths)) as prov:
        return await add_problem(prov, ProblemStore(paths), a.problem, now=utcnow(), offline=a.offline)


try:
    prob, created = asyncio.run(go())
except (LeetCodeError, ValueError) as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    sys.exit(2)
print(f"{'Added' if created else 'Already exists'}: {prob.title} ({prob.slug}) [{prob.status}]")
if created and not prob.problem_statement:
    print("Note: no statement stored (offline/premium). Run with credentials to fetch details.")

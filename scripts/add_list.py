"""Create/extend a problem list in data/lists/<list-slug>.json (used by --list filters, e.g. cram).

  uv run python scripts/add_list.py my-list --name "My list" two-sum 3sum https://leetcode.com/problems/valid-parentheses/
  uv run python scripts/add_list.py my-list --file slugs.txt        # one slug/URL per line
  uv run python scripts/add_list.py my-list --replace ...           # replace instead of extend
Problems that are not imported yet are kept in the list; add them with add_problem.py to review them.
"""

import argparse
import sys

from leetcode_review.config import Paths
from leetcode_review.content.loader import load_lists, save_list
from leetcode_review.storage.problems import ProblemStore, parse_slug

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("list_slug")
ap.add_argument("problems", nargs="*", help="slugs or leetcode.com/problems/... URLs")
ap.add_argument("--name")
ap.add_argument("--file")
ap.add_argument("--replace", action="store_true")
a = ap.parse_args()
raw = list(a.problems)
if a.file:
    raw += [ln.strip() for ln in open(a.file) if ln.strip() and not ln.startswith("#")]
if not raw:
    sys.exit("ERROR: give problems or --file")
paths = Paths.from_env()
slugs = [parse_slug(x) for x in raw]
current = load_lists(paths).get(a.list_slug, {})
merged = slugs if a.replace else [*current.get("problems", []), *slugs]
save_list(paths, a.list_slug, a.name or current.get("name") or a.list_slug, merged)
store = ProblemStore(paths)
unknown = [s for s in dict.fromkeys(merged) if not store.exists(s)]
print(f"List '{a.list_slug}': {len(dict.fromkeys(merged))} problems; {len(unknown)} not imported yet.")
if unknown:
    print("Not imported:", ", ".join(unknown[:15]) + (" ..." if len(unknown) > 15 else ""))

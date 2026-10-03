"""Create a valid skeleton review pack for a problem (the agent then fills in the cards).

Never overwrites an existing pack unless --force. Manual cards (custom/) are never touched.
"""

import argparse
import sys

from leetcode_review.config import Paths
from leetcode_review.content.scaffold import scaffold_pack
from leetcode_review.storage.problems import ProblemStore, parse_slug

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("problem", help="slug or URL")
ap.add_argument("--force", action="store_true", help="overwrite an existing generated pack")
a = ap.parse_args()
paths = Paths.from_env()
slug = parse_slug(a.problem)
problem = ProblemStore(paths).get(slug)
if problem is None:
    sys.exit(f"ERROR: data/problems/{slug}.json does not exist. Import it or run scripts/add_problem.py first.")
pack, written = scaffold_pack(paths, problem, force=a.force)
if written:
    print(f"Wrote skeleton data/review-packs/{slug}.json (suggested patterns: {pack.patterns or 'none'}).")
    print("Next: write the pack, including its recognition card (id recog-<slug>, with a rubric); "
          "see CLAUDE.md > Pack generation and docs/REVIEW_PACK_GUIDE.md.")
else:
    print(f"data/review-packs/{slug}.json already exists; left untouched (use --force to overwrite).")

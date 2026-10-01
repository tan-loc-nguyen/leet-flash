"""List problems that have no review pack (or only an empty skeleton)."""

import argparse
import json

from leetcode_review.catalog import Catalog
from leetcode_review.config import Paths
from leetcode_review.timeutil import utcnow

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--json", action="store_true", help="machine-readable output")
ap.add_argument("--no-skeletons", action="store_true", help="do not list problems that only have an empty skeleton")
a = ap.parse_args()
rows = Catalog(Paths.from_env(), utcnow()).missing_packs(include_skeletons=not a.no_skeletons)
if a.json:
    print(json.dumps(rows, indent=2))
else:
    for r in rows:
        print(f"{r['leetcodeId'] or '-':<6} {r['title']}" + ("   (skeleton)" if r["status"] == "skeleton" else ""))
    if not rows:
        print("Every problem has a review pack.")

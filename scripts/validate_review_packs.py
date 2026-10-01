"""Validate every review pack (and custom card file) against the schema and consistency rules."""

import argparse
import sys

from leetcode_review.config import Paths
from leetcode_review.content.validator import validate_all
from leetcode_review.storage.problems import ProblemStore

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
ap.add_argument("--quiet", action="store_true", help="hide warnings")
a = ap.parse_args()
paths = Paths.from_env()
issues = validate_all(paths, set(ProblemStore(paths).load_all()))
errors = [i for i in issues if i.level == "error"]
warnings = [i for i in issues if i.level == "warning"]
for i in errors + ([] if a.quiet else warnings):
    print(i)
n_files = len(list(paths.review_packs.glob("*.json"))) + len(list(paths.custom_cards.glob("*.json")))
print(f"\n{n_files} file(s) checked: {len(errors)} error(s), {len(warnings)} warning(s).")
sys.exit(1 if errors or (a.strict and warnings) else 0)

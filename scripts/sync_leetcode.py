"""Incremental sync: new solves, solved-state updates, newer accepted Python submissions.

Preserves notes, review packs, review state and history. Idempotent.
"""

import argparse
import sys

from leetcode_review.cli import run_sync

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--refresh", action="store_true", help="re-download statements/metadata for existing problems too")
ap.add_argument("--only", action="append", help="limit to this slug (repeatable)")
a = ap.parse_args()
sys.exit(run_sync(refresh=a.refresh, only=set(a.only) if a.only else None))

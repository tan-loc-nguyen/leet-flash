"""Rebuild data/state/review-state.json from data/state/review-history.jsonl.

The current state file is backed up first (data/state/review-state.json.bak-<time>).
See leetcode_review/rebuild.py for what can and cannot be restored.
"""

import argparse

from leetcode_review.config import Paths
from leetcode_review.rebuild import rebuild_state_file

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
ap.add_argument("--no-backup", action="store_true")
a = ap.parse_args()
r = rebuild_state_file(Paths.from_env(), dry_run=a.dry_run, backup=not a.no_backup)
for line_no, reason in r.skipped_lines:
    print(f"WARNING: skipped history line {line_no}: {reason}")
print(f"{'Would rebuild' if a.dry_run else 'Rebuilt'} state for {r.problems} problem(s) from {r.events} event(s).")
if r.backup:
    print(f"Previous state backed up to {r.backup}")

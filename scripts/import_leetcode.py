"""Import all solved LeetCode problems (statement, metadata, latest accepted Python solution).

Safe to re-run; equivalent to sync_leetcode.py. Needs credentials (scripts/set_credentials.py).
"""

import argparse
import sys

from leetcode_review.cli import run_sync

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--refresh", action="store_true", help="re-download statements/metadata for existing problems too")
sys.exit(run_sync(refresh=ap.parse_args().refresh))

"""Show statistics computed from persisted state + history."""

import argparse

from leetcode_review.catalog import Catalog
from leetcode_review.cli import emit
from leetcode_review.config import Paths
from leetcode_review.stats import compute_stats, format_stats
from leetcode_review.storage.history import read_events
from leetcode_review.timeutil import utcnow

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--json", action="store_true")
a = ap.parse_args()
paths, now = Paths.from_env(), utcnow()
s = compute_stats(Catalog(paths, now), read_events(paths), now)
emit(s) if a.json else print(format_stats(s))

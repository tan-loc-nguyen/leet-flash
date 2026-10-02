"""Show or change how likely each topic is to come up in the interview (data/state/settings.json → topicWeights).

  set_topic_weight.py                          show the table with problem counts
  set_topic_weight.py "Binary search" 9        set one topic's weight (relative scale; ratios matter)
  set_topic_weight.py --unlisted 1.5           weight for patterns not in the table (Design, Trie, Math, Bit Manipulation, ...)
  set_topic_weight.py --reset                  restore the built-in table

Higher weight = drawn more often for new / weak / retention / cram / interview sessions; overdue and due problems
are only nudged, never dropped. Weight 0 keeps a topic out unless nothing else is left.
"""

import argparse
import json
import sys

from leetcode_review import config as C
from leetcode_review.catalog import Catalog
from leetcode_review.review import topics
from leetcode_review.storage.atomic_write import atomic_write_json
from leetcode_review.timeutil import utcnow

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("topic", nargs="?")
ap.add_argument("weight", nargs="?", type=float)
ap.add_argument("--unlisted", type=float, help="weight for patterns that are not in the table")
ap.add_argument("--reset", action="store_true")
a = ap.parse_args()
paths = C.Paths.from_env()
raw = json.loads(paths.settings.read_text()) if paths.settings.exists() else {}

changed = False
if a.reset:
    raw["topicWeights"] = dict(C.DEFAULT_TOPIC_WEIGHTS)
    raw.pop("unlistedTopicWeight", None)
    changed = True
if a.unlisted is not None:
    if a.unlisted < 0:
        sys.exit("ERROR: weight must be >= 0")
    raw["unlistedTopicWeight"] = a.unlisted
    changed = True
if a.topic:
    match = [t for t in C.TOPIC_TAGS if t.lower() == a.topic.lower()] or [t for t in C.TOPIC_TAGS if a.topic.lower() in t.lower()]
    if len(match) != 1 or a.weight is None or a.weight < 0:
        sys.exit(f"ERROR: give one topic from: {', '.join(C.TOPIC_TAGS)} and a weight >= 0"
                 + (f" ('{a.topic}' matched {len(match)})" if a.weight is not None else ""))
    raw.setdefault("topicWeights", dict(C.DEFAULT_TOPIC_WEIGHTS))[match[0]] = a.weight
    changed = True
if changed:
    paths.settings.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(paths.settings, raw)

cat = Catalog(paths, utcnow())
slugs = [s for s in cat.problems if cat.has_cards(s)]
rows = topics.summary(cat, slugs)
total = sum(r["weight"] for r in rows if r["topic"] != "Unlisted") or 1
print(f"{'topic (LeetCode tags)':28} {'weight':>6} {'share':>6} {'factor':>6} {'problems':>8}")
for r in rows:
    share = "" if r["topic"] == "Unlisted" else f"{r['weight'] / total:.1%}"
    print(f"{r['topic']:28} {r['weight']:6g} {share:>6} {r['factor']:6.2f} {r['problems']:8}")
print("(a problem counts toward every topic its tags map to; its weight is the mean of those topics)")

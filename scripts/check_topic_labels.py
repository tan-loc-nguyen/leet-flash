"""Cross-check my pattern labels against LeetCode's own tags: list problems whose pack pattern and tags disagree.

Weights use each pack's primary pattern; LeetCode tags are only a sanity check. A disagreement is not necessarily an
error (a tag is an ingredient, the pattern is the technique) - review the list and tell me which packs to relabel.
"""

import argparse

from leetcode_review.catalog import Catalog
from leetcode_review.config import Paths
from leetcode_review.review import topics
from leetcode_review.timeutil import utcnow

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--json", action="store_true")
a = ap.parse_args()
cat = Catalog(Paths.from_env(), utcnow())
rows = []
for slug, prob in sorted(cat.problems.items()):
    if not cat.has_cards(slug):
        continue
    mine = topics.row_of(cat, slug) or topics.UNLISTED
    tagged = topics.tag_rows(prob.tags) or [topics.UNLISTED]
    if mine not in tagged:
        rows.append({"slug": slug, "title": prob.title, "primaryPattern": cat.primary_pattern(slug), "pack topic": mine,
                     "tag topics": tagged, "tags": prob.tags})
if a.json:
    import json
    print(json.dumps(rows, indent=2))
else:
    print(f"{len(rows)} problem(s) where the pack's topic is not among the topics implied by the LeetCode tags:\n")
    for r in rows:
        print(f"{r['title']:48} pattern={r['primaryPattern']:20} -> {r['pack topic']:22} tags -> {', '.join(r['tag topics'])}")

"""Query problems by id, title, slug, difficulty, status, tag, pattern, list, mastery, due state, pack presence."""

import argparse

from leetcode_review.catalog import Catalog
from leetcode_review.cli import add_filter_args, emit, filters_from_args
from leetcode_review.config import Paths
from leetcode_review.timeutil import utcnow

ap = argparse.ArgumentParser(description=__doc__)
add_filter_args(ap)
ap.add_argument("--due", action="store_true", default=None, help="only due/overdue")
ap.add_argument("--has-pack", dest="has_pack", action="store_true", default=None)
ap.add_argument("--no-pack", dest="has_pack", action="store_false")
ap.add_argument("--json", action="store_true")
a = ap.parse_args()
cat = Catalog(Paths.from_env(), utcnow())
rows = []
for p in cat.find(filters_from_args(a)):
    ps = cat.state.get(p.slug)
    rows.append({
        "id": p.leetcode_id, "slug": p.slug, "title": p.title, "difficulty": p.difficulty, "status": p.status,
        "tags": p.tags, "patterns": cat.patterns(p.slug), "lists": cat.list_membership(p.slug),
        "hasPack": cat.has_cards(p.slug), "level": ps.level if ps else None,
        "dueStatus": cat.due_status(p.slug), "nextReview": ps.next_review if ps else None,
    })
if a.json:
    emit(rows)
else:
    for r in rows:
        lvl = "-" if r["level"] is None else f"L{r['level']}"
        print(f"{r['id'] or '-':<6}{r['title']:<45}{r['difficulty'] or '-':<8}{r['status']:<9}{lvl:<4}"
              f"{r['dueStatus']:<9}{'pack' if r['hasPack'] else 'NO-PACK'}")
    print(f"\n{len(rows)} problem(s)")

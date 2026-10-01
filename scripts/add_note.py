"""Add a persistent note to a problem:  add_note.py 3sum "Skip duplicates for the fixed element and after a hit"."""

import argparse
import sys

from leetcode_review.config import Paths
from leetcode_review.schemas import Note
from leetcode_review.storage.problems import ProblemStore, parse_slug
from leetcode_review.timeutil import iso, utcnow

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("problem")
ap.add_argument("text")
a = ap.parse_args()
store = ProblemStore(Paths.from_env())
prob = store.get(parse_slug(a.problem))
if prob is None:
    sys.exit(f"ERROR: unknown problem '{a.problem}'")
n = len(prob.notes) + 1
prob.notes.append(Note(id=f"{prob.slug}-note-{n:02d}", text=a.text.strip(), created_at=iso(utcnow())))
store.save(prob)
print(f"Note added to {prob.title} ({len(prob.notes)} total).")

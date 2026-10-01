"""Add a manual card to a problem (stored in data/review-packs/custom/<slug>.json; survives pack regeneration).

Quick free-recall card:
  add_card.py minimum-window-substring "Why can the left pointer move only once the window is valid?" \
      --answer "Shrinking an invalid window can never make it valid..." --explanation "..." --category invariant
Full card from JSON (any type):
  add_card.py minimum-window-substring --json card.json     (or --json - for stdin)
"""

import argparse
import json
import sys

from pydantic import ValidationError

from leetcode_review.config import Paths
from leetcode_review.content.loader import add_manual_card, next_manual_id
from leetcode_review.schemas import CATEGORIES, Card
from leetcode_review.storage.problems import ProblemStore, parse_slug

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("problem")
ap.add_argument("prompt", nargs="?")
ap.add_argument("--answer")
ap.add_argument("--explanation")
ap.add_argument("--category", default="main_insight", choices=CATEGORIES)
ap.add_argument("--json", dest="json_file")
a = ap.parse_args()
paths = Paths.from_env()
slug = parse_slug(a.problem)
if not ProblemStore(paths).exists(slug):
    sys.exit(f"ERROR: unknown problem '{slug}'")
try:
    if a.json_file:
        raw = json.load(sys.stdin if a.json_file == "-" else open(a.json_file))
        raw.setdefault("id", next_manual_id(paths, slug))
    else:
        if not a.prompt or not a.answer:
            sys.exit("ERROR: give a prompt and --answer (or use --json)")
        raw = {"id": next_manual_id(paths, slug), "category": a.category, "type": "free_recall",
               "promptVariants": [a.prompt], "answer": a.answer, "explanation": a.explanation or a.answer}
    card = add_manual_card(paths, slug, Card.model_validate(raw))
except (ValidationError, ValueError) as exc:
    sys.exit(f"ERROR: {exc}")
print(f"Added manual card '{card.id}' to {slug}.")

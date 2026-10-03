"""Review-session driver for the coding agent. All output is JSON.

  review.py start --mode daily [--target 10] [--all-due] [filters...]
  review.py next                      # current question (resumes an interrupted session)
  review.py answer --choice B         # multiple choice (auto-graded)
  review.py answer --text "O(n)"      # fill_blank (auto-checked; mismatch => you judge)
  review.py answer --result partial   # free_recall / code_question / judged fill_blank
  review.py answer --text "<typed>" --technique accepted|valid|wrong --clue valid|missing|wrong
                                      # recognition card (first card of every problem): the engine grades it
  review.py reveal                    # reference answer for the current card (not recorded)
  review.py hint                      # next progressive hint for the current problem
  review.py forgot                    # "I don't remember this problem"
  review.py skip | status | abort

See CLAUDE.md for the full interaction protocol.
"""

import argparse
import sys

from leetcode_review.catalog import Catalog
from leetcode_review.cli import add_filter_args, emit, filters_from_args
from leetcode_review.config import Paths
from leetcode_review.config import URGENT_BUCKETS
from leetcode_review.review import topics
from leetcode_review.review.queue import MODES, bucket_counts
from leetcode_review.review.session import ReviewEngine, SessionError
from leetcode_review.schemas import CATEGORIES

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sub = ap.add_subparsers(dest="cmd", required=True)

st = sub.add_parser("start", help="build a queue and open a session")
st.add_argument("--mode", choices=MODES, default="daily")
st.add_argument("--target", type=int, help="problems in this session (default: settings dailyProblemTarget)")
st.add_argument("--all-due", action="store_true", help="daily mode: review every due problem")
st.add_argument("--seed", type=int, help="deterministic selection (tests/debugging)")
st.add_argument("--focus-category", action="append", choices=CATEGORIES, default=[],
                help="prefer cards of this category (e.g. space_complexity)")
st.add_argument("--force", action="store_true", help="abandon an active session and start a new one")
add_filter_args(st)
st.add_argument("--due", action="store_true", default=None, help=argparse.SUPPRESS)

sub.add_parser("next", help="show the current question")
an = sub.add_parser("answer", help="record an answer for the current card")
an.add_argument("--choice")
an.add_argument("--text")
an.add_argument("--result", choices=["failed", "partial", "correct"])
an.add_argument("--technique", choices=["accepted", "valid", "wrong"], help="recognition card: verdict on the technique")
an.add_argument("--clue", choices=["valid", "missing", "wrong"], help="recognition card: verdict on the clue")
for name in ("reveal", "hint", "forgot", "skip", "status", "abort"):
    sub.add_parser(name)
sub.add_parser("plan", help="preview today's queue and due counts without starting a session")

a = ap.parse_args()
paths = Paths.from_env()
engine = ReviewEngine(paths)
try:
    if a.cmd == "start":
        emit(engine.start(a.mode, filters=filters_from_args(a), target=a.target, seed=a.seed,
                          all_due=a.all_due, focus_categories=a.focus_category, force=a.force))
    elif a.cmd == "next":
        emit(engine.next_question())
    elif a.cmd == "answer":
        emit(engine.answer(result=a.result, choice=a.choice, text=a.text, technique=a.technique, clue=a.clue))
    elif a.cmd == "reveal":
        emit(engine.reveal())
    elif a.cmd == "hint":
        emit(engine.hint())
    elif a.cmd == "forgot":
        emit(engine.forgot())
    elif a.cmd == "skip":
        emit(engine.skip())
    elif a.cmd == "status":
        emit(engine.status())
    elif a.cmd == "abort":
        emit(engine.abort())
    elif a.cmd == "plan":
        cat = Catalog(paths, engine.clock())
        counts = bucket_counts(cat)
        emit({"dailyProblemTarget": engine.settings["dailyProblemTarget"], "candidatesByBucket": counts,
              "dueTotal": sum(counts.get(b, 0) for b in URGENT_BUCKETS),
              "missingReviewPacks": len(cat.missing_packs()),
              "topicWeights": topics.summary(cat, [sl for sl in cat.problems if cat.has_cards(sl)])})
except (SessionError, ValueError) as exc:  # ValueError: invalid settings.json (e.g. unknown topic in topicWeights)
    emit({"error": str(exc)})
    sys.exit(1)

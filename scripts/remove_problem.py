"""Remove a problem from the repo:  remove_problem.py fizz-buzz [--dry-run]

Deletes data/problems/<slug>.json and the generated review pack, drops the slug from every list in
data/lists/, removes its entry from review-state.json and dismisses its open card flags.
Review history and sessions are left untouched (history is append-only), so rebuild_state.py would
recreate a harmless orphan state entry. Manual cards in data/review-packs/custom/ are never deleted.
Refuses while an active session contains the problem.
"""

import argparse
import sys

from leetcode_review.config import Paths
from leetcode_review.content.loader import custom_path, pack_path
from leetcode_review.storage.atomic_write import append_jsonl, atomic_write_json, read_json
from leetcode_review.storage.history import read_events_with_errors
from leetcode_review.storage.problems import ProblemStore, parse_slug
from leetcode_review.storage.review_state import ReviewStateStore
from leetcode_review.timeutil import iso, utcnow

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("problem")
ap.add_argument("--dry-run", action="store_true", help="report what would be removed, change nothing")
a = ap.parse_args()
paths = Paths.from_env()
slug = parse_slug(a.problem)
store = ProblemStore(paths)

sessions = read_json(paths.sessions, default=None) or {}
active = sessions.get("sessions", {}).get(sessions.get("activeSessionId") or "")
if active and any(p["slug"] == slug for p in active["problems"]):
    sys.exit(f"ERROR: the active session '{active['id']}' contains '{slug}'; finish, skip or abort it first")

actions: list[str] = []
problem_file, pack_file = store.path_for(slug), pack_path(paths, slug)
if problem_file.exists():
    actions.append(f"delete {problem_file.relative_to(paths.root)}")
if pack_file.exists():
    actions.append(f"delete {pack_file.relative_to(paths.root)}")

lists = {f: read_json(f) for f in sorted(paths.lists.glob("*.json"))}
in_lists = [f for f, lst in lists.items() if slug in lst.get("problems", [])]
actions += [f"remove from list {f.stem}" for f in in_lists]

state = ReviewStateStore(paths).load()
if slug in state:
    actions.append("remove review-state entry")

flags: dict[str, dict] = {}
for ev in read_events_with_errors(paths.card_flags)[0]:
    if ev.get("event") == "flag":
        flags[ev["id"]] = ev
    elif ev.get("event") == "resolve":
        flags.pop(ev.get("flag"), None)
open_flags = [fid for fid, ev in flags.items() if ev["problem"] == slug]
actions += [f"dismiss {fid}" for fid in open_flags]

if not actions:
    sys.exit(f"ERROR: nothing to remove for '{slug}'")
if custom_path(paths, slug).exists():
    print(f"Note: manual cards in {custom_path(paths, slug).relative_to(paths.root)} are kept.")
if a.dry_run:
    print("Would " + "; ".join(actions) + ".")
    sys.exit(0)

problem_file.unlink(missing_ok=True)
pack_file.unlink(missing_ok=True)
for f in in_lists:
    lst = lists[f]
    lst["problems"] = [s for s in lst["problems"] if s != slug]
    atomic_write_json(f, lst)
if slug in state:
    del state[slug]
    ReviewStateStore(paths).save(state)
for fid in open_flags:
    append_jsonl(paths.card_flags, {"event": "resolve", "flag": fid, "timestamp": iso(utcnow()),
                                    "status": "dismissed", "note": f"problem {slug} removed"})
print(f"Removed {slug}: " + "; ".join(actions) + ".")

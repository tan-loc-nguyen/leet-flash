"""Flag cards that look malformed, let me review them, then mark them resolved (data/state/card-flags.jsonl).

  flag_card.py add <problem-slug> <card-id> --reason "Two options are both correct" [--suggest "Replace option C with ..."]
  flag_card.py list [--all] [--json]       open flags with the full card so I can review (--all includes resolved)
  flag_card.py resolve <flag-id> [--dismiss] [--note "what was changed / why it is fine"]

Flagging never edits a pack. Fixes happen only after I approve them; then run validate_review_packs.py and resolve.
"""

import argparse
import json
import sys

from leetcode_review.config import Paths
from leetcode_review.content.loader import load_pack
from leetcode_review.storage.atomic_write import append_jsonl
from leetcode_review.storage.history import read_events_with_errors
from leetcode_review.timeutil import iso, utcnow

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sub = ap.add_subparsers(dest="cmd", required=True)
a_add = sub.add_parser("add")
a_add.add_argument("problem")
a_add.add_argument("card")
a_add.add_argument("--reason", required=True)
a_add.add_argument("--suggest", default="")
a_list = sub.add_parser("list")
a_list.add_argument("--all", action="store_true")
a_list.add_argument("--json", action="store_true")
a_res = sub.add_parser("resolve")
a_res.add_argument("flag")
a_res.add_argument("--dismiss", action="store_true", help="the card is fine; flag was a false alarm")
a_res.add_argument("--note", default="")
a = ap.parse_args()
paths = Paths.from_env()


def current_flags() -> dict[str, dict]:
    flags: dict[str, dict] = {}
    for ev in read_events_with_errors(paths.card_flags)[0]:
        if ev.get("event") == "flag":
            flags[ev["id"]] = {**ev, "status": "open"}
        elif ev.get("event") == "resolve" and ev.get("flag") in flags:
            flags[ev["flag"]].update(status=ev["status"], resolvedAt=ev["timestamp"], resolution=ev.get("note", ""))
    return flags


def card_of(flag: dict) -> dict | None:
    pack = load_pack(paths, flag["problem"])
    card = next((c for c in pack.cards if c.id == flag["card"]), None) if pack else None
    return card.model_dump(by_alias=True, exclude_none=True) if card else None


if a.cmd == "add":
    pack = load_pack(paths, a.problem)
    if pack is None or not any(c.id == a.card for c in pack.cards):
        sys.exit(f"ERROR: no card '{a.card}' in the pack for '{a.problem}'")
    flags = current_flags()
    dup = next((f for f in flags.values() if f["status"] == "open" and (f["problem"], f["card"]) == (a.problem, a.card)), None)
    if dup:
        sys.exit(f"Already flagged ({dup['id']}). Resolve it first or add context to the reason there.")
    fid = f"flag-{len(flags) + 1:04d}"
    append_jsonl(paths.card_flags, {"event": "flag", "id": fid, "timestamp": iso(utcnow()), "problem": a.problem,
                                    "card": a.card, "reason": a.reason.strip(), "suggestion": a.suggest.strip()})
    print(f"Flagged {a.problem}/{a.card} as {fid}. The pack was not changed.")
elif a.cmd == "list":
    flags = [f for f in current_flags().values() if a.all or f["status"] == "open"]
    rows = [{**f, "cardContent": card_of(f)} for f in flags]
    if a.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    elif not rows:
        print("No open card flags.")
    else:
        for r in rows:
            print(f"{r['id']} [{r['status']}] {r['problem']} / {r['card']}\n  reason: {r['reason']}")
            if r["suggestion"]:
                print(f"  suggested fix: {r['suggestion']}")
            c = r["cardContent"]
            if c:
                print(f"  prompt: {c['promptVariants'][0]}")
                for o in c.get("options", []):
                    print(f"    {'*' if o == c.get('answer') else '-'} {o}")
                if not c.get("options"):
                    print(f"  answer: {c.get('answer')}")
                print(f"  explanation: {c.get('explanation', '')}")
            else:
                print("  (card no longer exists)")
else:
    flags = current_flags()
    f = flags.get(a.flag)
    if f is None:
        sys.exit(f"ERROR: unknown flag '{a.flag}'")
    if f["status"] != "open":
        sys.exit(f"{a.flag} is already {f['status']}.")
    status = "dismissed" if a.dismiss else "resolved"
    append_jsonl(paths.card_flags, {"event": "resolve", "flag": a.flag, "timestamp": iso(utcnow()), "status": status, "note": a.note.strip()})
    print(f"{a.flag} marked {status}.")

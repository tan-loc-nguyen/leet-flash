"""Read-only content audit of review packs (run after writing or editing packs).

Checks
  * length tell:    an MCQ answer that is >= --gap characters longer (or shorter) than every distractor
  * clue numbers:   a recognition card whose clue cites a number that appears nowhere in the problem's statement or
                    constraints (a typo or an invented limit); numbers derived from the problem (26 letters, 60 s) are
                    allow-listed in DERIVED_NUMBERS
  * example reuse:  an edge_case / code_reasoning card whose prompt reuses an input literal from the problem
                    statement's examples (the statement is shown first, so the card would test reading, not recall)

Exit code 1 when anything is found, so it can gate a pack-writing session.
"""

import argparse
import json
import re
import sys

from leetcode_review.config import Paths
from leetcode_review.content.loader import list_pack_slugs, load_pack
from leetcode_review.storage.problems import ProblemStore

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--gap", type=int, default=8, help="length difference that counts as a tell (default 8)")
ap.add_argument("--json", action="store_true")
a = ap.parse_args()
paths = Paths.from_env()
store = ProblemStore(paths)


def example_literals(statement: str) -> set[str]:
    out: set[str] = set()
    for line in re.findall(r"Input:(.*)", statement):
        for m in re.finditer(r"\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]", line):
            t = re.sub(r"\s+", "", m.group(0))
            if len(t) >= 5:
                out.add(t)
        for m in re.finditer(r'"([^"\n]{3,40})"', line):
            if "=" not in m.group(1) and "," not in m.group(1):
                out.add(m.group(1))
    return out


# numbers a clue may cite although the text only implies them (alphabet size, time units, 10 slots ** 4 wheels, 8 keys)
DERIVED_NUMBERS = {"26", "60", "3600", "8", "10^4"}
DERIVED_BY_SLUG = {"integer-break": {"5"}}  # a mathematical fact the clue relies on (parts of 5 or more should be split)


def numbers_in(text: str) -> set[str]:
    text = re.sub(r"10\s*\^\s*(\d+)", r"10^\1", text.replace("×", "*"))
    return set(re.findall(r"\d+(?:\^\d+)?", text))


findings = []
for slug in list_pack_slugs(paths):
    pack = load_pack(paths, slug)
    prob = store.get(slug)
    lits = example_literals(prob.problem_statement or "") if prob else set()
    for c in pack.cards:
        if not c.enabled:
            continue
        if c.rubric is not None and prob:
            known = numbers_in(prob.problem_statement + " " + " ".join(prob.constraints))
            stray = sorted(n for n in numbers_in(c.rubric.clue) - known - DERIVED_NUMBERS - DERIVED_BY_SLUG.get(slug, set())
                           if not re.search(rf"(?<!\d){re.escape(n)}(?!\d)", prob.problem_statement))
            if stray:
                findings.append({"slug": slug, "card": c.id, "kind": f"clue cites {stray} which the problem does not state"})
        if c.type == "multiple_choice" and c.options and c.answer:
            ds = [len(o) for o in c.options if o != c.answer]
            if ds and len(c.answer) - max(ds) >= a.gap:
                findings.append({"slug": slug, "card": c.id, "kind": "answer much longer than every distractor"})
            if ds and min(ds) - len(c.answer) >= a.gap:
                findings.append({"slug": slug, "card": c.id, "kind": "answer much shorter than every distractor"})
        if c.category in ("edge_case", "code_reasoning") and lits:
            for p in c.prompt_variants:
                compact = re.sub(r"\s+", "", p)
                hit = [e for e in lits if (e.startswith("[") and e in compact) or (not e.startswith("[") and (f"'{e}'" in p or f'"{e}"' in p))]
                if hit:
                    findings.append({"slug": slug, "card": c.id, "kind": f"prompt reuses the statement example {hit[0]!r}"})
                    break
if a.json:
    print(json.dumps(findings, indent=2))
else:
    for f in findings:
        print(f"{f['slug']}/{f['card']}: {f['kind']}")
    print(f"{len(findings)} finding(s).")
sys.exit(1 if findings else 0)

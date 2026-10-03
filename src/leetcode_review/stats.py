"""Statistics computed purely from persisted JSON/JSONL."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from . import config as C
from .catalog import Catalog
from .storage.history import card_events, problem_events
from .timeutil import parse_iso

MIN_ANSWERS_FOR_RANKING = 3


def _acc(c: dict) -> float | None:
    return round((c["correct"] + 0.5 * c["partial"]) / c["seen"], 3) if c["seen"] else None


def _tally() -> dict:
    return {"seen": 0, "correct": 0, "partial": 0, "failed": 0}


def recognition_stats(cards: list[dict]) -> dict | None:
    """Accuracy on the recognition card (events carrying the typed answer and the technique/clue verdicts)."""
    ev = [e for e in cards if "technique" in e]
    if not ev:
        return None
    tech = {"accepted": 0, "valid": 0, "wrong": 0}
    clue = {"valid": 0, "missing": 0, "wrong": 0}
    tally = _tally()
    for e in ev:
        tech[e["technique"]] += 1
        clue[e.get("clue", "missing")] += 1
        tally["seen"] += 1
        tally[e["result"]] += 1
    misses = [{"problem": e["problem"], "timestamp": e["timestamp"], "said": e.get("userText"),
               "technique": e["technique"], "clue": e.get("clue")} for e in ev if e["result"] != "correct"]
    return {"answers": len(ev), "accuracy": _acc(tally), "correct": tally["correct"], "partial": tally["partial"],
            "failed": tally["failed"], "technique": tech, "clue": clue,
            "hintCapped": sum(1 for e in ev if e.get("hintCapped")),
            "drillAnswers": sum(1 for e in ev if e.get("mode") == "drill"), "recentMisses": misses[-5:][::-1]}


def compute_stats(cat: Catalog, events: list[dict], now: datetime) -> dict:
    cards = card_events(events)
    by_cat: dict[str, dict] = defaultdict(_tally)
    by_pat: dict[str, dict] = defaultdict(_tally)
    overall = _tally()
    recent = {7: _tally(), 30: _tally()}
    per_problem: dict[str, dict] = defaultdict(_tally)

    for e in cards:
        r = e["result"]
        patterns = cat.patterns(e["problem"]) or ["Unclassified"]
        targets = [overall, by_cat[e["category"]], per_problem[e["problem"]]] + [by_pat[p] for p in patterns]
        age = now - parse_iso(e["timestamp"])
        targets += [t for days, t in recent.items() if age <= timedelta(days=days)]
        for t in targets:
            t["seen"] += 1
            t[r] += 1

    levels = defaultdict(int)
    due = overdue = 0
    for slug in cat.problems:
        if not cat.has_cards(slug):
            continue
        status = cat.due_status(slug)
        if status == "new":
            levels["new"] += 1
            continue
        levels[cat.state[slug].level] += 1
        due += status == "due"
        overdue += status == "overdue"

    weak_problems = sorted(
        (
            {"slug": s, "title": cat.problems[s].title if s in cat.problems else s,
             "recentAccuracy": ps.recent_accuracy, "level": ps.level, "weakCategories": ps.weak_categories,
             "lapses": ps.lapses}
            for s, ps in cat.state.items()
            if ps.recent_accuracy is not None and (ps.recent_accuracy < C.WEAK_PROBLEM_ACCURACY or ps.weak_categories)
        ),
        key=lambda d: (d["recentAccuracy"], -len(d["weakCategories"])),
    )

    def ranked(table: dict) -> list[dict]:
        rows = [{"name": k, **v, "accuracy": _acc(v)} for k, v in table.items() if v["seen"]]
        return sorted(rows, key=lambda r: (r["accuracy"], -r["seen"]))

    pat_rows = ranked(by_pat)
    return {
        "totalProblems": len(cat.problems),
        "solved": sum(p.status == "solved" for p in cat.problems.values()),
        "unsolved": sum(p.status == "unsolved" for p in cat.problems.values()),
        "withReviewCards": sum(cat.has_cards(s) for s in cat.problems),
        "missingReviewPacks": len(cat.missing_packs()),
        "problemsReviewed": sum(1 for ps in cat.state.values() if ps.review_count),
        "totalAnswers": overall["seen"],
        "overallAccuracy": _acc(overall),
        "byCategory": ranked(by_cat),
        "byPattern": pat_rows,
        "weakPatterns": [r for r in pat_rows if r["seen"] >= MIN_ANSWERS_FOR_RANKING][:5],
        "weakProblems": weak_problems[:10],
        "masteryDistribution": {str(k): v for k, v in sorted(levels.items(), key=lambda kv: str(kv[0]))},
        "due": due,
        "overdue": overdue,
        "recent": {f"last{d}Days": {**t, "accuracy": _acc(t)} for d, t in recent.items()},
        "problemReviews": len(problem_events(events)),
        "recognition": recognition_stats(cards),
    }


def format_stats(s: dict) -> str:
    def pct(x):
        return "  n/a" if x is None else f"{round(x * 100):>4}%"

    L = [
        "Overview",
        f"  Problems: {s['totalProblems']} ({s['solved']} solved, {s['unsolved']} unsolved)",
        f"  With review cards: {s['withReviewCards']}   Missing packs: {s['missingReviewPacks']}",
        f"  Problems reviewed: {s['problemsReviewed']}   Due: {s['due']}   Overdue: {s['overdue']}",
        f"  Answers: {s['totalAnswers']}   Overall accuracy: {pct(s['overallAccuracy']).strip()}",
    ]
    for label, row in s["recent"].items():
        L.append(f"  {label}: {row['seen']} answers, {pct(row['accuracy']).strip()}")
    L += ["", "Mastery distribution"]
    for k, v in s["masteryDistribution"].items():
        name = "New (never reviewed)" if k == "new" else f"L{k} {C.LEVEL_NAMES[int(k)]}"
        L.append(f"  {name:<28}{v}")
    rec = s.get("recognition")
    if rec:
        t, c = rec["technique"], rec["clue"]
        L += ["", "Pattern recognition (free recall)",
              f"  Answers: {rec['answers']} ({rec['drillAnswers']} in drills)   Accuracy: {pct(rec['accuracy']).strip()}",
              f"  Technique: {t['accepted']} intended, {t['valid']} weaker but valid, {t['wrong']} wrong",
              f"  Clue: {c['valid']} valid, {c['missing']} missing, {c['wrong']} wrong   Hint-capped: {rec['hintCapped']}"]
        for m in rec["recentMisses"]:
            L.append(f"  miss: {m['problem']} - you said \"{(m['said'] or '')[:70]}\" ({m['technique']}/{m['clue']})")
    if s["byPattern"]:
        L += ["", "Pattern performance (weakest first)"]
        L += [f"  {r['name']:<24}{pct(r['accuracy'])}  ({r['seen']} answers)" for r in s["byPattern"]]
    if s["byCategory"]:
        L += ["", "Category performance (weakest first)"]
        L += [f"  {r['name']:<24}{pct(r['accuracy'])}  ({r['seen']} answers)" for r in s["byCategory"]]
    if s["weakProblems"]:
        L += ["", "Weakest problems"]
        for w in s["weakProblems"]:
            cats = f"  weak: {', '.join(w['weakCategories'])}" if w["weakCategories"] else ""
            L.append(f"  {w['title']:<40} L{w['level']}  recent {pct(w['recentAccuracy']).strip()}{cats}")
    return "\n".join(L)

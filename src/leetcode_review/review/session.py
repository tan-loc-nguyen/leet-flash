"""Interactive review sessions (persisted in data/state/sessions.json).

The coding agent drives this through scripts/review.py:
start -> next -> (hint | reveal)* -> answer | forgot | skip -> next ... -> done.
Every answer is appended to history and written to review-state.json *immediately*.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import datetime

from .. import config as C
from ..catalog import Catalog, Filters
from ..config import Paths, load_settings
from ..content.loader import enabled_cards
from ..schemas import Card, ProblemState
from ..storage.atomic_write import atomic_write_json, read_json
from ..storage.history import append_event
from ..storage.review_state import ReviewStateStore
from ..timeutil import iso, utcnow
from . import cards as cardlib
from .queue import build_queue
from .scheduler import apply_problem_event, compute_problem_outcome
from .scoring import core_blocking_failure, problem_score, record_card_result

KEEP_FINISHED_SESSIONS = 20


class SessionError(Exception):
    """A user-facing, actionable problem with the requested session operation."""


class ReviewEngine:
    def __init__(self, paths: Paths, clock: Callable[[], datetime] | None = None):
        self.paths = paths
        self.clock = clock or utcnow
        self.settings = load_settings(paths)

    # ------------------------------------------------------------------ persistence
    def _load_sessions(self) -> dict:
        data = read_json(self.paths.sessions, default=None) or {}
        data.setdefault("activeSessionId", None)
        data.setdefault("sessions", {})
        return data

    def _save_sessions(self, data: dict) -> None:
        finished = [k for k, v in data["sessions"].items() if v["status"] != "active"]
        for k in sorted(finished, key=lambda k: data["sessions"][k]["updatedAt"])[:-KEEP_FINISHED_SESSIONS]:
            del data["sessions"][k]
        atomic_write_json(self.paths.sessions, data)

    def active_session(self) -> dict | None:
        data = self._load_sessions()
        sid = data["activeSessionId"]
        return data["sessions"].get(sid) if sid else None

    def _require_active(self) -> tuple[dict, dict]:
        data = self._load_sessions()
        sid = data["activeSessionId"]
        if not sid or sid not in data["sessions"]:
            raise SessionError("No active review session. Start one with: review.py start --mode daily")
        return data, data["sessions"][sid]

    def _commit(self, data: dict, sess: dict) -> None:
        sess["updatedAt"] = iso(self.clock())
        data["sessions"][sess["id"]] = sess
        self._save_sessions(data)

    # ------------------------------------------------------------------ start
    def start(
        self,
        mode: str,
        *,
        filters: Filters | None = None,
        target: int | None = None,
        seed: int | None = None,
        all_due: bool = False,
        focus_categories: list[str] | None = None,
        force: bool = False,
    ) -> dict:
        data = self._load_sessions()
        active_id = data["activeSessionId"]
        if active_id and active_id in data["sessions"]:
            if not force:
                s = data["sessions"][active_id]
                done = sum(1 for p in s["problems"] if p["status"] in ("done", "forgotten", "skipped"))
                raise SessionError(
                    f"Session '{active_id}' ({s['mode']}) is still active ({done}/{len(s['problems'])} problems done). "
                    "Resume it with `next`, or start fresh with --force (abandons it)."
                )
            data["sessions"][active_id]["status"] = "abandoned"
            data["sessions"][active_id]["updatedAt"] = iso(self.clock())
            data["activeSessionId"] = None

        now = self.clock()
        seed = seed if seed is not None else random.SystemRandom().randrange(1, 10**9)
        rng = random.Random(seed)
        cat = Catalog(self.paths, now)
        target = target or int(self.settings["dailyProblemTarget"])
        plan = build_queue(cat, mode, target, rng, filters, all_due=all_due)
        if not plan.entries:
            self._save_sessions(data)
            return {"started": False, "mode": mode, "notes": plan.notes or ["No eligible problems found."],
                    "counts": plan.counts}

        base = f"{mode}-{now.date().isoformat()}"
        sid, n = base, 2
        while sid in data["sessions"]:
            sid, n = f"{base}-{n}", n + 1
        sess = {
            "id": sid,
            "mode": mode,
            "status": "active",
            "createdAt": iso(now),
            "updatedAt": iso(now),
            "seed": seed,
            "target": plan.target,
            "filters": (filters or Filters()).describe(),
            "focusCategories": focus_categories or [],
            "problems": [
                {"slug": e.slug, "bucket": e.bucket, "status": "pending", "cardIds": [], "answers": [],
                 "hintLevel": 0, "presented": {}}
                for e in plan.entries
            ],
        }
        data["activeSessionId"] = sid
        self._commit(data, sess)
        return {
            "started": True,
            "sessionId": sid,
            "mode": mode,
            "target": plan.target,
            "problemCount": len(plan.entries),
            "candidateCounts": plan.counts,
            "notes": plan.notes,
            "problems": [
                {"slug": e.slug, "title": cat.problems[e.slug].title, "bucket": e.bucket,
                 "difficulty": cat.problems[e.slug].difficulty}   # patterns stay hidden: naming one gives the answer away
                for e in plan.entries
            ],
        }

    # ------------------------------------------------------------------ navigation
    @staticmethod
    def _current_problem(sess: dict) -> tuple[int, dict] | None:
        for i, p in enumerate(sess["problems"]):
            if p["status"] in ("pending", "in_progress"):
                return i, p
        return None

    def _begin_problem(self, sess: dict, idx: int, cat: Catalog) -> None:
        p = sess["problems"][idx]
        pack = cat.packs[p["slug"]]
        ps = cat.state.get(p["slug"])
        rng = random.Random(f"{sess['seed']}-{idx}")
        boost = C.INTERVIEW_CATEGORY_BOOST if sess["mode"] == "interview" else None
        chosen = cardlib.select_cards(
            enabled_cards(pack), ps, int(self.settings["cardsPerProblem"]), cat.now, rng,
            category_boost=boost, focus_categories=sess.get("focusCategories") or None,
        )
        p["cardIds"] = [c.id for c in chosen]
        p["presented"] = {
            c.id: {"prompt": cardlib.pick_prompt(c, ps), "options": cardlib.present_options(c, rng)} for c in chosen
        }
        p["status"] = "in_progress"

    def next_question(self) -> dict:
        data, sess = self._require_active()
        cat = Catalog(self.paths, self.clock())
        cur = self._current_problem(sess)
        if cur is None:
            return self._finish_session(data, sess, cat)
        idx, prob = cur
        if prob["status"] == "pending":
            self._begin_problem(sess, idx, cat)
            self._commit(data, sess)
        card = self._current_card(prob, cat)
        return self._question_payload(sess, idx, prob, card, cat)

    def _current_card(self, prob: dict, cat: Catalog) -> Card:
        answered = {a["cardId"] for a in prob["answers"]}
        for cid in prob["cardIds"]:
            if cid not in answered:
                return self._card(cat, prob["slug"], cid)
        raise SessionError("Internal error: problem has no unanswered cards but is still open.")

    @staticmethod
    def _card(cat: Catalog, slug: str, cid: str) -> Card:
        for c in cat.packs[slug].cards:
            if c.id == cid:
                return c
        raise SessionError(f"Card '{cid}' no longer exists in the pack for {slug}.")

    def _question_payload(self, sess: dict, idx: int, prob: dict, card: Card, cat: Catalog) -> dict:
        p = cat.problems[prob["slug"]]
        pres = prob["presented"][card.id]
        qn = len(prob["answers"]) + 1
        return {
            "done": False,
            "sessionId": sess["id"],
            "mode": sess["mode"],
            "problemIndex": idx + 1,
            "problemCount": len(sess["problems"]),
            "problem": {
                "slug": p.slug,
                "leetcodeId": p.leetcode_id,
                "title": p.title,
                "difficulty": p.difficulty,
                "status": p.status,
                "patterns": self._patterns(cat, p.slug) if self._patterns_revealed(prob, cat) else None,
                "bucket": prob["bucket"],
                "notes": [n.text for n in p.notes] if qn == 1 else [],
                "statement": p.problem_statement if qn == 1 and self.settings.get("showStatement", True) else None,
            },
            "isFirstQuestion": qn == 1,
            "questionIndex": qn,
            "questionCount": len(prob["cardIds"]),
            "card": {
                "id": card.id,
                "category": card.category,
                "type": card.type,
                "prompt": pres["prompt"],
                "options": pres["options"],
                "code": card.code,
            },
            "solutionCode": self._solution_code(card, p, cat.packs[prob["slug"]]),
            "hintsUsed": prob["hintLevel"],
        }

    @staticmethod
    def _patterns_revealed(prob: dict, cat: Catalog) -> bool:
        """Patterns are shown only once the problem's pattern card is answered (they would give it away)."""
        answered = {a["cardId"] for a in prob["answers"]}
        has_pattern_card = False
        for cid in prob["cardIds"]:
            card = ReviewEngine._card(cat, prob["slug"], cid)
            if card.category == "pattern":
                has_pattern_card = True
                if cid not in answered:
                    return False
        return has_pattern_card  # no pattern card drawn: stay hidden until the problem is finished

    @staticmethod
    def _patterns(cat: Catalog, slug: str) -> list[str]:
        return cat.patterns(slug) or cat.problems[slug].tags

    @staticmethod
    def _solution_code(card: Card, problem, pack) -> dict | None:
        """Code to read while answering a complexity question, so the answer is derived rather than memorised.

        Preference: the pack's canonical code; else the user's accepted Python when it is the optimal approach
        (or the pack makes no claim about it). Never show code whose complexity differs from the card's answer.
        """
        if card.category not in ("time_complexity", "space_complexity") or card.code:
            return None
        if pack.canonical_code:
            return {"label": "Canonical solution", "code": pack.canonical_code}
        sub = problem.latest_submission
        mine = pack.personal_solution
        if sub and sub.code.strip() and (mine is None or mine.is_optimal is not False):
            return {"label": "Your accepted solution", "code": sub.code}
        return None

    # ------------------------------------------------------------------ answering
    def reveal(self) -> dict:
        _, sess = self._require_active()
        cat = Catalog(self.paths, self.clock())
        cur = self._current_problem(sess)
        if not cur or cur[1]["status"] != "in_progress":
            raise SessionError("No open question. Call `next` first.")
        card = self._current_card(cur[1], cat)
        return {"card": card.id, "type": card.type, "category": card.category, "answer": card.answer,
                "acceptedAnswers": card.accepted_answers, "keyPoints": card.key_points,
                "explanation": card.explanation, "code": card.code}

    def answer(self, *, result: str | None = None, choice: str | None = None, text: str | None = None) -> dict:
        data, sess = self._require_active()
        now = self.clock()
        cat = Catalog(self.paths, now)
        cur = self._current_problem(sess)
        if not cur or cur[1]["status"] != "in_progress":
            raise SessionError("No open question. Call `next` first.")
        idx, prob = cur
        card = self._current_card(prob, cat)
        pres = prob["presented"][card.id]
        feedback: dict = {}

        if result is not None and result not in C.RESULT_POINTS:
            raise SessionError(f"result must be one of: {', '.join(C.RESULT_POINTS)}")
        if card.type == "multiple_choice" and choice is not None:
            picked = cardlib.match_choice(choice, pres["options"] or [])
            if picked is None:
                raise SessionError(f"'{choice}' does not match any option; use a letter or the option text.")
            result = "correct" if picked == card.answer else "failed"
            feedback["selected"] = picked
            if result == "failed":
                feedback["whySelectedIsWrong"] = card.incorrect_option_explanations.get(picked)
                feedback["otherDistractors"] = {
                    k: v for k, v in card.incorrect_option_explanations.items() if k != picked
                }
        elif card.type == "fill_blank" and text is not None and result is None:
            if cardlib.check_fill_blank(card, text):
                result = "correct"
            else:
                return {"recorded": False, "needsJudgment": True,
                        "message": "No exact match. Judge the user's answer against the reference and call "
                                   "answer again with --result (failed/partial/correct).",
                        "reference": card.answer, "acceptedAnswers": card.accepted_answers,
                        "explanation": card.explanation}
        if result is None:
            raise SessionError(
                f"This is a {card.type} card: judge the answer yourself and pass --result failed|partial|correct"
                + (" (or --choice for multiple choice)" if card.type == "multiple_choice" else "")
            )

        ts = iso(now)
        event: dict = {"timestamp": ts, "sessionId": sess["id"], "problem": prob["slug"], "card": card.id,
                       "category": card.category, "result": result, "mode": sess["mode"]}
        if prob["hintLevel"]:
            event["hints"] = prob["hintLevel"]
        append_event(self.paths, event)  # history first: it is the audit log

        store = ReviewStateStore(self.paths)
        ps = cat.state.setdefault(prob["slug"], ProblemState())
        record_card_result(ps, card.id, card.category, result, ts)
        store.save(cat.state)
        prob["answers"].append({"cardId": card.id, "category": card.category, "result": result, "timestamp": ts})

        out = {"recorded": True, "result": result, "correctAnswer": card.answer, "explanation": card.explanation,
               "keyPoints": card.key_points, **{k: v for k, v in feedback.items() if v}}
        if card.category == "pattern" or len(prob["answers"]) >= len(prob["cardIds"]):
            out["patterns"] = self._patterns(cat, prob["slug"])  # now safe to show
        if len(prob["answers"]) >= len(prob["cardIds"]):
            out["problemFinished"] = True
            out["problemResult"] = self._finish_problem(sess, prob, cat, store, now)
        else:
            out["problemFinished"] = False
        return self._commit_or_finish(data, sess, cat, out)

    def _commit_or_finish(self, data: dict, sess: dict, cat: Catalog, out: dict) -> dict:
        """Persist the session; if that was the last open problem, close the session too."""
        if self._current_problem(sess) is None:
            out["sessionFinished"] = True
            out["sessionSummary"] = self._finish_session(data, sess, cat)
        else:
            self._commit(data, sess)
        return out

    def _finish_problem(self, sess: dict, prob: dict, cat: Catalog, store: ReviewStateStore, now: datetime,
                        *, forgot: bool = False) -> dict:
        slug = prob["slug"]
        ps = cat.state.setdefault(slug, ProblemState())
        results = [(a["category"], a["result"]) for a in prob["answers"]]
        score = 0.0 if forgot else problem_score(results)
        out = compute_problem_outcome(ps, score, blocking_failure=core_blocking_failure(results), now=now,
                                      forgot=forgot)
        event = {"timestamp": iso(now), "event": "problem_review", "sessionId": sess["id"], "problem": slug,
                 "mode": sess["mode"], "score": round(score, 3), "outcome": out.outcome,
                 "levelBefore": out.level_before, "levelAfter": out.level_after, "nextReview": out.next_review,
                 "cards": len(prob["answers"])}
        if forgot:
            event["forgot"] = True
        if prob["hintLevel"]:
            event["hints"] = prob["hintLevel"]
        append_event(self.paths, event)
        apply_problem_event(ps, event)
        store.save(cat.state)
        prob["status"] = "forgotten" if forgot else "done"
        prob["outcome"] = {k: event[k] for k in ("score", "outcome", "levelBefore", "levelAfter", "nextReview")}
        return {**prob["outcome"], "weakCategories": ps.weak_categories, "level": ps.level,
                "levelName": C.LEVEL_NAMES[ps.level]}

    def forgot(self) -> dict:
        """'I don't remember this problem': fail it, drop mastery, and return recall material."""
        data, sess = self._require_active()
        now = self.clock()
        cat = Catalog(self.paths, now)
        cur = self._current_problem(sess)
        if not cur:
            raise SessionError("No open problem.")
        _, prob = cur
        store = ReviewStateStore(self.paths)
        result = self._finish_problem(sess, prob, cat, store, now, forgot=True)
        p, pack = cat.problems[prob["slug"]], cat.packs[prob["slug"]]
        out = {
            "recorded": True, "problemFinished": True, "problemResult": result,
            "recallMaterial": {
                "summary": pack.summary, "patterns": pack.patterns,
                "problemStatement": p.problem_statement, "mainInsight": pack.main_insight,
                "invariant": pack.invariant,
                "approaches": [a.to_json() for a in pack.approaches],
                "personalSolution": pack.personal_solution.to_json() if pack.personal_solution else None,
                "pythonSolution": p.latest_submission.code if p.latest_submission else None,
                "notes": [n.text for n in p.notes],
            },
            "protocol": "Show the summary first and give the user a chance to recall; reveal insight/approach/"
                        "solution only afterwards. Do not require them to solve it.",
        }
        return self._commit_or_finish(data, sess, cat, out)

    def skip(self) -> dict:
        data, sess = self._require_active()
        cur = self._current_problem(sess)
        if not cur:
            raise SessionError("No open problem.")
        cur[1]["status"] = "skipped"
        out = {"skipped": cur[1]["slug"],
               "note": "Skipped problems are not rescheduled; answers already given stay recorded."}
        return self._commit_or_finish(data, sess, Catalog(self.paths, self.clock()), out)

    # ------------------------------------------------------------------ hints
    def hint(self) -> dict:
        data, sess = self._require_active()
        cat = Catalog(self.paths, self.clock())
        cur = self._current_problem(sess)
        if not cur:
            raise SessionError("No open problem.")
        _, prob = cur
        p, pack = cat.problems[prob["slug"]], cat.packs[prob["slug"]]
        ladder = [
            ("summary", pack.summary),
            ("pattern", ", ".join(pack.patterns)),
            ("invariant", pack.invariant),
            ("main_insight", pack.main_insight),
            ("approach", "\n".join(f"{a.name}: {a.summary} (time {a.time_complexity}, space {a.space_complexity})"
                                   for a in pack.approaches)),
            ("python_solution", p.latest_submission.code if p.latest_submission else None),
        ]
        ladder = [(k, v) for k, v in ladder if v]
        level = prob["hintLevel"]
        if level >= len(ladder):
            return {"exhausted": True, "hintsGiven": level}
        prob["hintLevel"] = level + 1
        self._commit(data, sess)
        kind, content = ladder[level]
        return {"hintNumber": level + 1, "of": len(ladder), "kind": kind, "content": content}

    # ------------------------------------------------------------------ status / finish
    def status(self) -> dict:
        sess = self.active_session()
        if not sess:
            return {"active": False}
        return {
            "active": True, "sessionId": sess["id"], "mode": sess["mode"],
            "problems": [{"slug": p["slug"], "status": p["status"], "answered": len(p["answers"]),
                          "cards": len(p["cardIds"])} for p in sess["problems"]],
        }

    def abort(self) -> dict:
        data, sess = self._require_active()
        sess["status"] = "abandoned"
        data["activeSessionId"] = None
        self._commit(data, sess)
        return {"abandoned": sess["id"]}

    def _finish_session(self, data: dict, sess: dict, cat: Catalog) -> dict:
        reviewed = [p for p in sess["problems"] if p["status"] in ("done", "forgotten")]
        pts = got = 0.0
        for p in reviewed:
            for a in p["answers"]:
                got += C.RESULT_POINTS[a["result"]]
                pts += C.MAX_POINTS
        sess["status"] = "completed"
        data["activeSessionId"] = None
        self._commit(data, sess)
        return {
            "done": True,
            "sessionId": sess["id"],
            "mode": sess["mode"],
            "problemsReviewed": len(reviewed),
            "problemsSkipped": sum(1 for p in sess["problems"] if p["status"] == "skipped"),
            "accuracy": round(got / pts, 3) if pts else None,
            "problems": [
                {"slug": p["slug"], "title": cat.problems[p["slug"]].title, "status": p["status"],
                 **(p.get("outcome") or {})}
                for p in sess["problems"]
            ],
        }

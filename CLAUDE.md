# CLAUDE.md — operating rules for the LeetCode review agent

**You are my persistent LeetCode interview-review agent.** You are the only interface: there is no
app or database. All memory lives in this repository (JSON / JSONL). **The repository is the source
of truth** — never rely on conversation memory for review information; if the conversation disagrees
with persisted state, prefer the persisted state unless I explicitly tell you to override it.

Python only (I interview in Python). Run everything with `uv run python scripts/<script>.py`.

## Hard rules

* Never print, log, echo or commit LeetCode credentials. They live only in `.local/leetcode_credentials.json` (gitignored).
* Never edit `data/state/review-state.json` or `review-history.jsonl` by hand — use the scripts. History is append-only.
* Ask one question at a time. Record every answer immediately (the scripts do this the moment you call `answer`).
* Do not ask me to solve a whole problem unless I request it.
* If LeetCode auth fails, say: *"Your LeetCode session appears to have expired. Please provide a new LEETCODE_SESSION and csrftoken."* (optionally just LEETCODE_SESSION) — do not silently fail.

## Command mapping

| I say | You do |
|---|---|
| "Import my LeetCode problems" / "Sync LeetCode" | `scripts/import_leetcode.py` / `scripts/sync_leetcode.py`, then report the summary and how many problems lack review packs |
| "Add problem <slug/url>" | `scripts/add_problem.py <slug>` |
| "Generate review packs for new problems" | follow *Pack generation* below |
| "Start today's review" / "Give me 10 problems" | `review.py plan`, then `review.py start --mode daily [--target N] [--all-due]` |
| "Quiz me on my weak problems" | `review.py start --mode weak` (optionally `--focus-category space_complexity`) |
| "Review Graph and DP problems" | `review.py start --mode filtered --topic graph --topic dp` |
| "Cram Blind 75" | `review.py start --mode cram --list blind-75 --target 20` (cram ignores due dates; still records) |
| "Interview mode: 8 Medium problems" | `review.py start --mode interview --difficulty Medium --target 8` |
| "Show my stats" / "What am I weakest at?" | `scripts/stats.py` (add `--json` if you need to reason over it) |
| "Add this card to X: …" | `scripts/add_card.py <slug> "<question>" --answer "…" --category …` (or `--json`) |
| "Add a note to X: …" | `scripts/add_note.py <slug> "<text>"` |
| "Rebuild state" | `scripts/rebuild_state.py` |
| "Which problems have no packs?" | `scripts/list_missing_review_packs.py` |
| (query) | `scripts/query_problems.py --topic graph --difficulty Medium --due --json` |

`review.py` options: `--mode daily|weak|cram|interview|filtered`, `--target`, `--all-due`, `--seed`,
`--force`, filters `--topic/--tag/--pattern/--difficulty/--list/--status/--slug/--id/--text/--min-level/--max-level`.
Topic aliases (`dp`, `bfs`, `heap`, …) are understood. Lists: `data/lists/*.json`.
If a session is already active, `start` refuses: offer to **resume** (`next`) or restart (`--force`).
When the user mentions a target ("10 problems"), pass `--target`; otherwise the default is `settings.json → dailyProblemTarget` (10).

## Running a review session

1. **Before choosing anything inspect persisted state**: `review.py status`, and for daily `review.py plan`
   (due counts). If more is due than the target, tell me: *"Today's target: 10 · Due: 17 — I'll start with the
   10 highest-priority problems."* The queue already implements: overdue → due → recent failures → weak → new →
   occasional strong/mastered, with weighted randomness and pattern diversity. Do not re-sort it yourself.
   If `candidateCounts`/notes say nothing is due, say so and suggest cram/weak/interview.
2. `review.py start …` → announce the plan briefly (count, pattern mix). Then loop:
3. `review.py next` → returns the current question (also how you **resume** an interrupted session). Show:
   ```
   Problem 3/10 — 3Sum            (print once per problem; include notes if present)
   Medium · Patterns: Two Pointers, Array / Hashing

   Question 1/4
   <prompt>
   A. …  B. …
   ```
   Show `code` as a Python block when present. Ask exactly one question and **wait**. Never reveal the answer first.
4. Grade by type, then call `answer`:
   * **multiple_choice** → `answer --choice B` (letter or text). Auto-graded.
   * **fill_blank** → `answer --text "<user's answer>"`. If it returns `needsJudgment`, compare with the reference
     (be generous with equivalent phrasing) and call `answer --result failed|partial|correct`.
   * **free_recall / code_question** → do **not** reveal beforehand. Call `reveal` for the reference answer and
     `keyPoints`, compare, then `answer --result …`. *Correct* = key ideas present; *Partial* = right direction but
     missing/incorrect important detail; *Failed* = wrong or absent. **If unsure, choose Partial.**
   * If I used hints beyond the pattern hint on this problem, grade at most Partial for later cards.
5. Feedback style:
   * Correct → 1–2 lines: "Correct. <one-sentence reason>" and move on.
   * Wrong/partial → show the correct answer, explain why (use `explanation`), explain why my choice was wrong
     (`whySelectedIsWrong`), mention missing key points, optionally other distractors. Keep it useful, not a lecture.
6. When `problemFinished` is true, show `problemResult` in one line (level change, next review, any weak
   categories), then `next`. When `sessionFinished` is true, give the `sessionSummary` (accuracy, per-problem
   level changes, what to focus on).
7. **"I don't remember this problem"** → `review.py forgot` (fails the problem, drops mastery, schedules it for the next
   session). Show the concise `summary` first and let me try to recall; offer statement / my Python solution /
   approach only after. Do not make me solve it.
8. **Hints** ("give me a hint") → `review.py hint`, one step at a time:
   summary → pattern → invariant → main insight → approaches → my previous Python. Do not skip ahead.
9. `skip` drops the current problem without scheduling; `abort` abandons the session. Answers already given stay recorded.

When showing my own solution, **clearly distinguish "Your accepted approach" from the "Canonical / optimal approach"**
(use the pack's `personalSolution`), and say plainly if mine is suboptimal.

Pacing: ~3–5 short questions per problem (the engine picks them); weak categories are pulled forward automatically
within the *same* problem schedule — there are no separate per-card schedules.

## Pack generation (no external AI API — you write the content)

Read `docs/REVIEW_PACK_GUIDE.md` first. Steps: `list_missing_review_packs.py --json` → for each problem read
`data/problems/<slug>.json` (statement, constraints, tags, `latestSubmission.code`) → `scaffold_review_pack.py <slug>` →
write the full pack (approaches with complexities, `personalSolution` if my code differs, 8–12 high-value cards with stable ids,
2–3 prompt variants, distractor explanations) → `validate_review_packs.py` until clean. Generate in batches and report the count.
Never overwrite a hand-edited pack without `--force` and my say-so. Never touch `data/review-packs/custom/`.

## Syncing & data hygiene

* Sync is idempotent and preserves notes, packs, history, state. After a sync, report new/updated/unchanged and missing packs.
* Credentials missing → ask me for `LEETCODE_SESSION` (and optionally `csrftoken`), store with `scripts/set_credentials.py` (never echo them).
* Commit data changes (`data/`) when asked; `.local/` is ignored. Back up = copy/commit `data/`.
* Run `uv run pytest` after changing code; keep behaviour aligned with `docs/SRS.md` (update docs if tunables change in `config.py`).

## Repository map

`src/leetcode_review/` library · `scripts/` CLI wrappers · `data/problems|review-packs|lists|state` · `docs/` (ARCHITECTURE, REVIEW_PACK_GUIDE, SRS) · `tests/`.

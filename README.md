# leet-flash — a local LeetCode interview-review system

LeetCode + flashcards + spaced repetition + interview pattern-recognition practice, with **no web app,
no database and no separate UI**. Your local coding agent (Claude Code) *is* the interface: it imports
your solved problems, writes review cards, quizzes you one question at a time, records every answer,
and schedules what to review next. All memory is in transparent JSON / JSONL files in this repo.

* Short recall questions instead of re-solving whole problems: pattern, core insight, data structure,
  invariants, complexity, edge cases, alternatives, and reasoning about *your own* Python solution.
* Problem-level spaced repetition (levels 0–6, 0–60 days) with weak-category tracking.
* Python-only, single user, local-only. See `CLAUDE.md` for how the agent behaves.

## Install

```bash
uv sync            # Python 3.12+, installs pydantic + httpx (+ pytest in the dev group)
uv run pytest      # the suite never needs real credentials
```

## LeetCode credentials

Log in to leetcode.com, open the browser dev tools → Application/Storage → Cookies, and copy `LEETCODE_SESSION`
(and, optionally, `csrftoken`). Then:

```bash
uv run python scripts/set_credentials.py        # hidden prompts
```

They are written to `.local/leetcode_credentials.json` (mode 600, **gitignored**) — never committed or printed.
Env vars `LEETCODE_SESSION` / `LEETCODE_CSRFTOKEN` also work. If the cookie expires you will get:
*"Your LeetCode session appears to have expired. Please provide a new LEETCODE_SESSION and csrftoken."*
(The integration is unofficial; everything LeetCode-specific is in `src/leetcode_review/leetcode/`.)

## Everyday use (talk to the agent)

```
Import my LeetCode problems.            Start today's review.
Sync LeetCode.                          Give me 10 problems today.
Generate review packs for new problems. Quiz me on my weak problems.
Review Dynamic Programming and Graph.   Interview mode: 8 Medium problems.
Cram my solved list.                          What am I weakest at?
Add a note to 3Sum: ...                 Add this card to Minimum Window Substring: ...
```

## Scripts

| Script | Purpose |
|---|---|
| `import_leetcode.py` / `sync_leetcode.py` | import / incrementally sync solved problems (+ latest accepted Python) |
| `add_problem.py <slug\|url>` | add an unsolved problem (a later sync marks it solved) |
| `list_missing_review_packs.py [--json]` | problems lacking packs |
| `scaffold_review_pack.py <slug> [--force]` | valid skeleton pack |
| `validate_review_packs.py [--strict]` | schema + consistency checks |
| `review.py start/next/answer/reveal/hint/forgot/skip/status/abort/plan` | session driver used by the agent |
| `stats.py [--json]` | accuracy by pattern/category, mastery, due, weak problems |
| `query_problems.py` | filter problems (tag, pattern, list, level, due, pack…) |
| `add_note.py`, `add_card.py`, `add_list.py` | notes, manual cards, your own problem lists |
| `rebuild_state.py [--dry-run]` | rebuild `review-state.json` from history |
| `set_credentials.py` | store credentials locally |

All run as `uv run python scripts/<name>.py`.

## Where data lives

```
data/problems/<slug>.json        one file per problem (statement, tags, latest Python solution, notes)
data/review-packs/<slug>.json    generated review cards;  custom/<slug>.json = manual cards
data/lists/*.json                "solved" (Solved list, auto-maintained by sync), "unsolved-amazon" (Unsolved Amazon, 70 manual problems)
                                 + any list you add (scripts/add_list.py)
data/state/review-state.json     current mastery / next review / weak categories
data/state/review-history.jsonl  append-only audit log of every answer
data/state/sessions.json         active/finished sessions (resume after interruptions)
data/state/settings.json         dailyProblemTarget (10), cardsPerProblem (4), request delay
.local/leetcode_credentials.json secrets, gitignored
```

The five hand-written example problems/packs (Two Sum, Valid Parentheses, Longest Substring Without
Repeating Characters, Binary Search, 3Sum) are marked `"source": "seed"`; a real import/sync replaces their
metadata with your real data and keeps the packs.

## Backup, reset

* **Backup:** it is all text — commit `data/` to Git (that is the intended workflow) or copy the folder.
  Never commit `.local/`.
* **Rebuild lost/corrupt state:** `uv run python scripts/rebuild_state.py` (backs up the old file first).
* **Reset learning progress:** empty `data/state/review-state.json` (`{}`), `review-history.jsonl` and `sessions.json`.
* **Atomic writes:** every JSON rewrite goes through temp-file + fsync + `os.replace`, so an interrupted run cannot leave half-written files.

## Privacy: public vs private repo

`data/problems/*.json` contains **your submitted code and LeetCode's problem statements**, and
`data/state/` your whole study history. If this GitHub repository is **public**, committing those files
publishes them (LeetCode's statements are their copyrighted content). Recommended: make the repo **private**
before committing imported data, or keep `data/problems/`, `data/state/` out of Git (e.g. add them to `.gitignore`).
The code, docs, lists, tests and hand-written seed packs are safe to publish.

## Docs

`docs/ARCHITECTURE.md` · `docs/SRS.md` (exact scheduling math) · `docs/REVIEW_PACK_GUIDE.md` · `CLAUDE.md`

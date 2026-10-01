# Architecture

## Why JSON + JSONL

The data set is tiny (hundreds of problems, tens of thousands of answers). Plain files are
human-readable, diff-able in Git, trivially backed up, and easy for a coding agent to inspect.
No database server or SQLite is used. Layout rule: **current state in JSON, history in append-only JSONL,
one file per problem / per pack** (no giant file).

## Storage layout

| Path | Content | Writer |
|---|---|---|
| `data/problems/<slug>.json` | problem metadata, statement, latest accepted Python submission, notes | sync, add_problem, add_note |
| `data/review-packs/<slug>.json` | generated review content (approaches, cards) | the agent (+ scaffold) |
| `data/review-packs/custom/<slug>.json` | manual cards, merged at load time | add_card |
| `data/lists/*.json` | hard-coded problem lists | manual |
| `data/state/review-state.json` | per-problem scheduling + per-card/category stats | review engine / rebuild |
| `data/state/review-history.jsonl` | audit log (1 line per answer, 1 per finished problem) | review engine |
| `data/state/sessions.json` | active/finished sessions for resume | review engine |
| `data/state/settings.json` | user settings | user |
| `.local/leetcode_credentials.json` | cookies (gitignored) | set_credentials |

Models: `src/leetcode_review/schemas.py` (Pydantic, camelCase on disk). `Problem` keeps unknown keys so data is
never lost across versions; pack models are strict so typos are caught by the validator.

## Code map (`src/leetcode_review/`)

* `config.py` — paths, settings, credentials and **all SRS/queue tunables**.
* `storage/` — `atomic_write` (temp file + fsync + replace; JSONL append with partial-line guard), `problems`, `review_state`, `history`.
* `leetcode/` — the *only* LeetCode-specific code: `graphql.py` (queries, headers, retries, auth-failure detection,
  csrf bootstrap), `normalize.py` (pure payload → our types, HTML → text, Python-submission preference),
  `provider.py` (`LeetCodeProvider`: `validate_credentials`, `get_solved_problems`, `get_problem`, `get_latest_accepted_submission`).
  Unofficial API: when LeetCode changes, repair these three files independently. Tests use `httpx.MockTransport`.
* `sync.py` — import/sync orchestration (idempotent merge that preserves notes/unknown fields; rewrites a file only if it changed).
* `content/` — `loader` (pack + custom merge, lists), `validator`, `scaffold`.
* `catalog.py` — loads everything in memory; `Filters` (id, title, slug, difficulty, status, tag, pattern, list, level, due, pack…).
* `review/scoring.py` — points, weights, card/category stats, weak categories.
* `review/scheduler.py` — levels, intervals, outcomes; `apply_problem_event` is shared by live updates and rebuild.
* `review/queue.py` — buckets, strict-priority + weighted-random selection, diversity ordering, all modes.
* `review/cards.py` — card selection, prompt rotation, MCQ shuffling, fill-blank normalisation.
* `review/session.py` — `ReviewEngine`: start/next/answer/reveal/hint/forgot/skip/abort with immediate persistence.
* `stats.py`, `rebuild.py`, `cli.py` — reporting, state rebuild, script helpers.

## Review pack lifecycle

Pack files are canonical generated content. Cards have **stable ids**; statistics are keyed by id, so regenerating a pack keeps
history for unchanged ids, new ids start fresh, removed/disabled cards stop appearing. Manual cards live separately and
survive regeneration. A pack with zero cards (a skeleton) still counts as "missing".

## Scheduler & state vs history

Problem-level SRS (docs/SRS.md). **State** (`review-state.json`) is the derived, current view; **history** is the permanent record.
Each answer: (1) append the card event to history, (2) update card/category stats and weak categories in state (atomic write),
(3) when the problem's cards are done, compute the outcome, append a `problem_review` event carrying
`score/outcome/levelBefore/levelAfter/nextReview`, apply it, save. History is written first so a crash can only
leave state *behind* history, which a rebuild repairs.

## Rebuilding state

`scripts/rebuild_state.py` replays history: card events → card/category stats + weak categories; `problem_review` events →
level, last/next review, accuracy EMA, lapses. Limitations: only data present in history is restored; schedules are the
originally computed ones (not recomputed with new tunables); a problem interrupted mid-review restores card stats only;
malformed lines (e.g. a torn last line) are skipped and reported.

## Sessions

`sessions.json` stores the chosen problems, chosen cards, the *presented* prompt wording and shuffled option order (so a resume
shows the identical question), per-problem answers and hint level. Card selection RNG is seeded per session/problem. A session
closes itself when its last problem finishes; the 20 most recent finished sessions are kept.

## Security

Credentials are only read from `.local/` (or env), masked in `repr`, never logged. `.local/` is gitignored.

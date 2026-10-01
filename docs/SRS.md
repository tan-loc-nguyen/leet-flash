# Spaced repetition model

The scheduled unit is the **problem**, not the card. Cards decide *what is asked*; the
problem-level result decides *when the problem comes back*. All numbers below live in
`src/leetcode_review/config.py` and are the single source of truth.

## 1. Card result → points

| Result  | Points |
|---------|--------|
| failed  | 0 |
| partial | 1 |
| correct | 2 |

Each card has a category weight (`CATEGORY_WEIGHTS`):

| Category | Weight |
|---|---|
| pattern, main_insight | 1.5 |
| time_complexity, space_complexity, invariant | 1.25 |
| data_structure, alternative_approach, why_not, code_reasoning | 1.0 |
| edge_case | 0.9 |
| implementation_detail | 0.75 |

## 2. Problem score

After the 3–5 cards of one problem are answered:

```
score = Σ(weight × points) / (2 × Σ weight)          # in [0, 1]
```

## 3. Level update

Levels and the interval to the next review (`LEVEL_INTERVAL_DAYS`):

| Level | Name | Interval |
|---|---|---|
| 0 | New / Failed | next session (due immediately) |
| 1 | Early Learning | 1 day |
| 2 | Learning | 3 days |
| 3 | Developing | 7 days |
| 4 | Strong | 14 days |
| 5 | Very Strong | 30 days |
| 6 | Mastered | 60 days |

| Condition | Outcome | Level | Interval |
|---|---|---|---|
| score ≥ 0.85 and no failed `pattern`/`main_insight` card | promote | +1 (max 6) | interval of the new level |
| score ≥ 0.60 (or ≥ 0.85 with a failed core card) | hold | unchanged | 0.75 × interval of the level (min 1 day) |
| 0.35 ≤ score < 0.60 | demote | −1 | interval of the new level |
| score < 0.35 | fail | −2 | interval of the new level |
| "I don't remember this problem" | forgot | −3 | **next session**, whatever the level |

Modifiers:

* **Weak categories** – if the problem currently has any weak category (see §4), the interval
  is multiplied by 0.75 (min 1 day). This is how a persistent weakness brings the *whole
  problem* back sooner without creating a separate schedule.
* **Level 0** always means "due again next session" (`nextReview = now`).
* **Early reviews** (cram / weak / interview / retention sampling of a problem that is *not*
  due yet): a promote/hold result leaves level and `nextReview` untouched (`early_keep`);
  results below 0.60 still demote and reschedule. Only genuinely due (or new) problems can climb.
* `nextReview` for level ≥ 1 is **midnight UTC** of `today + interval`. A problem is *due* when
  `nextReview <= now`, *overdue* when its due date is before today (UTC).

`recentAccuracy` is an exponential moving average of problem scores:
`new = 0.5 × score + 0.5 × old` (first review: `score`).

`lapses` counts `fail`/`forgot` outcomes.

## 4. Weak categories

For every problem and category the state keeps `seen / correct / partial / failed`,
`incorrectStreak` (consecutive non-correct answers), `lastResult`, `lastSeenAt` and the last 5
results (`recent`). A category is **weak** when either

* it has ≥ 2 recent results and `Σ points / (2 × n) < 0.5` over the last 5, or
* `incorrectStreak ≥ 2`.

A weak category recovers as correct answers push it out of the window. A single miss never
makes a category weak. Per-card stats (`cardStats`) track the same counters per card id.

## 5. Card selection inside a problem

`cardsPerProblem` (settings, default 4) cards are drawn **without replacement**, weighted by:

* base 1.5 for core categories (`pattern`, `main_insight`, `time_complexity`,
  `space_complexity`, `invariant`), 1.0 otherwise
* × 2.5 if the category is weak
* × 1.5 if the card was never seen; otherwise × (1 + 1.5 × failure ratio) where failure ratio =
  (failed + ½ partial) / seen; × 0.5 if it was seen within the last 24 h
* interview mode additionally boosts reasoning/complexity categories (`INTERVIEW_CATEGORY_BOOST`)

Guarantees (when the pack allows): at least one weak-category card if any category is weak,
at least one core card, at most 2 cards per category. Cards are then ordered
pattern → insight → structure/invariant → alternatives → code/edge → complexity.
The prompt wording rotates: `promptVariants[timesSeen % len]`.

## 6. Queue building (Daily Review)

Each candidate problem (must have ≥ 1 enabled card) is put into a bucket:

| Bucket | Rule | Base priority |
|---|---|---|
| overdue | due date before today | 100 + 5 × min(days overdue, 10) |
| due | due today | 70 |
| recent_failure | `lastScore < 0.35` within the last 3 days (even if not yet due) | 55 |
| weak | `recentAccuracy < 0.6` or has weak categories | 35 |
| new | never reviewed | 25 |
| retention | level ≥ 4 and not due | 8 |

Urgent buckets (overdue, due, recent_failure) additionally get
`10 × (1 − recentAccuracy) + 4 × (#weak categories)`. Problems already reviewed today with
level ≥ 1 are skipped.

Selection of `dailyProblemTarget` problems:

1. **Urgent first, strict priority.** Highest `priority + jitter(0..3)` wins, multiplied by
   `0.9 ^ (#already selected problems with the same primary pattern)`.
2. **Remaining slots (weak / new / retention): weighted random sampling** by base priority
   with the same diversity factor.
3. **Ordering for diversity:** repeatedly draw the next problem with weight `priority`, × 0.1 if it
   shares the primary pattern with the previous problem, × 0.4 if with the one before.

If more problems are urgent than the target, the plan notes it ("Due: 17 > target 10 …").
`--all-due` raises the target to cover every urgent problem. Seeds make selection deterministic.

### Other modes

* **weak** – ranks problems with history by `10 × (1 − recentAccuracy) + 4 × #weak categories + 2 × lapses (+3 if last score < 0.35)`.
* **cram / filtered** – ignore the schedule; sampling weight `1 + (6 − level)/6` (+0.5 if weak
  categories); filtered additionally ×3 for due problems.
* **interview** – only previously studied problems (solved or reviewed); same level weighting ×
  recency (`1 + min(days since last review, 60)/30`); interview card boost.

## 7. What a rebuild preserves

`review-history.jsonl` contains one event per answered card plus one `problem_review` event per
finished problem (with the computed `levelAfter`, `nextReview`, `score`, `outcome`). Rebuilding
replays them, so the exact schedule is restored even if these constants change later.

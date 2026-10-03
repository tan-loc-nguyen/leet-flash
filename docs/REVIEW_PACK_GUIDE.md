# Writing review packs (guide for the coding agent)

A review pack (`data/review-packs/<slug>.json`) turns one problem into **short, recall-based
interview practice**. Quality beats quantity: 8–12 excellent cards per problem is plenty;
each review session only asks 3–5 of them.

## Workflow

1. `uv run python scripts/list_missing_review_packs.py --json`
2. For each problem: read `data/problems/<slug>.json` — statement, constraints, tags, and
   `latestSubmission.code` (the user's accepted Python solution, if present).
3. `uv run python scripts/scaffold_review_pack.py <slug>` creates a valid skeleton
   (suggested patterns pre-filled). Never overwrites unless `--force`.
4. Fill in the pack (see schema below). Use `--force` only to regenerate; stable ids are kept by
   re-using the same ids (see "Stable ids").
5. `uv run python scripts/validate_review_packs.py` — fix every error; address warnings.

## Pack schema

```jsonc
{
  "schemaVersion": 1,
  "problemSlug": "two-sum",              // must match the file name and data/problems/<slug>.json
  "summary": "one-sentence restatement of the task",
  "patterns": ["Array / Hashing"],       // prefer the standard taxonomy; may be more specific
  "mainInsight": "the one idea that unlocks the optimal solution",
  "invariant": "what is always true inside the main loop (optional)",
  "canonicalApproach": "name of the optimal entry in approaches",
  "approaches": [{ "name", "summary", "timeComplexity", "spaceComplexity",
                   "strengths": [], "weaknesses": [], "interviewRelevance": "" }],
  "personalSolution": {                  // ONLY when the user's accepted code differs from canonical
    "approach": "...", "timeComplexity": "O(n^2)", "spaceComplexity": "O(1)",
    "isOptimal": false, "notes": "what to improve" },
  "commonMistakes": [], "edgeCases": [],
  "cards": [ ... ]
}
```

`summary`, `mainInsight`, `invariant`, `approaches` and `personalSolution` also power the
progressive hints (summary → pattern → invariant → main insight → approaches → the user's Python).

**Personal vs canonical.** Read the user's accepted solution. If it is suboptimal, say so in
`personalSolution` and add cards that contrast it with the optimal approach
(`alternative_approach` / `why_not` / complexity cards). Never silently present the user's code as optimal.

## Card schema

| Field | Notes |
|---|---|
| `id` | **Stable**, `<slug>-<topic>-NN` (letters, digits, `-`, `_`). Unique inside the problem. |
| `category` | `pattern, main_insight, data_structure, time_complexity, space_complexity, invariant, alternative_approach, implementation_detail, code_reasoning, edge_case, why_not` |
| `type` | `multiple_choice`, `free_recall`, `fill_blank`, `code_question` |
| `promptVariants` | 2–3 phrasings (the validator warns on 1). Rotated automatically. |
| `options` | MCQ only, 3–6 plausible options; `answer` must be one of them (exact text). |
| `answer` | Reference answer (required for every type). |
| `acceptedAnswers` | `fill_blank` synonyms (`"linear"`, `"O(n) average"`). Complexity variants (`O(N)`, `o(n)`, `O(n²)`) are normalised automatically. |
| `keyPoints` | `free_recall`/`code_question`: checklist used to grade Failed/Partial/Correct. |
| `code` | `code_question` snippet (from the user's solution or the canonical one). |
| `explanation` | Required. Why the answer is right. |
| `incorrectOptionExplanations` | MCQ: `{ "<wrong option text>": "why it is wrong" }`. |
| `enabled` | `false` retires a card without deleting its history. |
| `source` | `generated` (default) or `manual`. |

`fill_blank` prompts must contain `___`.

## The recognition card (exactly one per pack)

Id `recog-<slug>`, category `pattern`, type `free_recall`, `promptVariants` = the three fixed prompts
(`RECOGNITION_PROMPTS` in `schemas.py`; they name no technique and no complexity). `answer` = `"<technique>. Clue: <clue>"`,
`keyPoints` = `[clue]`, `explanation` = why the clue points to the technique and why the alternatives are worse. The card
carries a `rubric`:

| Field | Notes |
|---|---|
| `technique` | The **specific** intended technique, e.g. "Two pointers on the sorted array". Never a topic ("Tree", "Math", "Design", "Array / Hashing" are rejected). |
| `aliases` | At least one other way to name the same technique, plus other equally good answers (e.g. "kmp" next to "rolling hash"). Anything here is graded as *accepted*. |
| `alsoValid` | `{name, note}` for approaches that work but are weaker (brute force, extra space, slower); graded Partial. Do not list equal-quality alternatives here, put them in `aliases`. |
| `clueTypes` | 1–3 values of `CLUE_TYPES` (`sorted_or_ordered`, `contiguous`, `lookup_frequency`, `optimization_overlap`, `enumerate_all`, `shortest_steps`, …, `direct_simulation`, `math_observation`). |
| `clue` | One sentence naming the real clue in *this* problem's statement or constraints (a number from the constraints is fine; check it is really there). No `O(…)` in it. |

For problems with no real technique (`Fizz Buzz`, `To Lower Case`) the technique is "direct simulation of the stated
rule" with the clue type `direct_simulation`: recognising that nothing clever is needed is the skill.
The validator rejects a pack with cards but no recognition card, two of them, or any other enabled **generated**
`pattern` card (retire it with `enabled: false` or move it to `main_insight` / `data_structure` / `implementation_detail`).

## What good cards look like

BAD: *What LeetCode number is Two Sum?* / *Is Two Sum Easy?* — trivia.

GOOD, tied to reasoning an interviewer probes:

* *Why does a hash map eliminate the need to check every pair?* (main_insight)
* *What should the map contain at iteration i?* (invariant)
* *Why check the complement before inserting the current number?* (implementation_detail)
* *What breaks if these two lines are swapped?* (code_reasoning, with `code`)
* *Which input exposes a missing empty-stack check?* (edge_case)
* *Why isn't a counter per bracket type enough?* (why_not)
* *Time-space trade-off between brute force and hash map?* (alternative_approach)

Guidelines:

* Only include categories that add value for this problem — never pad to cover a checklist.
* Typical mix: 1 pattern, 1–2 main_insight/invariant, 1 time + 1 space complexity,
  1–2 edge/why_not, 1–2 code_reasoning (from the user's own code when it is informative),
  1 alternative approach.
* MCQ distractors must be *plausible* techniques/complexities a candidate might really confuse —
  no joke options. Vary which position holds the answer (the engine shuffles anyway).
* Keep every MCQ option about the same length and shape as the answer — a noticeably longer,
  more specific option is a giveaway. Shorten a verbose answer or lengthen the distractors (while
  keeping them wrong for the stated reason) rather than leaving the tell in.
* The answer must be neither noticeably longer nor noticeably shorter than every distractor (`scripts/audit_cards.py`
  flags a gap of 8+ characters either way).
* The problem statement, with its worked examples, is shown first, so edge-case and code-reasoning cards must use an input
  that is *not* one of the statement's examples; compute the expected answer by running a reference solution, never by hand.
* Card ids must be unique across all packs (the validator enforces it): bulk edits key on ids.
* Write `incorrectOptionExplanations` for every distractor; they are the learning content.
* Every pack should carry `canonicalCode`: clean, runnable Python for the canonical approach (LeetCode class/method
  signature, no judge scaffolding), with comments on what drives the cost. Test it against the statement's examples and a
  brute force before storing it. It is shown with time/space questions so I derive the complexity from code. Complexity
  cards must describe *that* code; a card about a different approach (my own heap/sort solution, say) carries its own
  `code` field, which takes precedence. When `canonicalCode` is absent the engine shows my accepted submission, but only
  if `personalSolution.isOptimal` is not false.
* Complexity cards should say *why*, not just the symbol (amortised analysis, alphabet-bounded space…).
* Avoid trivial Python-syntax questions unless they carry interview reasoning (heap tuple ordering,
  `last[ch] >= left` guards, `lo + (hi - lo)//2`…).
* Interview focus: pattern recognition, invariants, complexity, trade-offs, edge cases.

## Stable ids and regeneration

* Progress is keyed by **card id** (`cardStats` in `review-state.json`, `card` in history).
* Editing a card's text but keeping its id keeps its statistics.
* A new id starts fresh; removed or `enabled: false` cards simply stop appearing — history is never erased.
* Problem-level state (level, next review) is independent of the pack and survives regeneration.
* **Manual cards** live in `data/review-packs/custom/<slug>.json`, are merged at load time, carry
  `"source": "manual"`, and are never touched by scaffolding or regeneration
  (`scripts/add_card.py`). Their ids must not collide with generated ids (the validator checks).
* Notes (`scripts/add_note.py`) live in the problem JSON and are shown at the start of that problem's review.

## Seed examples

`two-sum`, `valid-parentheses`, `longest-substring-without-repeating-characters`,
`binary-search` and `3sum` are hand-written reference packs demonstrating every question type,
prompt variants, incorrect-option explanations, alternative approaches and complexity cards.
Imitate their depth.

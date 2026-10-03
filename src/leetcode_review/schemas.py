"""Pydantic models for every persisted JSON structure.

Files use camelCase keys (as in the product spec); Python attributes are snake_case.
``Problem`` keeps unknown keys (so a newer/older version never destroys data);
review-pack models are strict so typos are caught by the validator.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

CATEGORIES = (
    "pattern",
    "main_insight",
    "data_structure",
    "time_complexity",
    "space_complexity",
    "invariant",
    "alternative_approach",
    "implementation_detail",
    "code_reasoning",
    "edge_case",
    "why_not",
)
QUESTION_TYPES = ("multiple_choice", "free_recall", "fill_blank", "code_question")
RESULTS = ("failed", "partial", "correct")
DIFFICULTIES = ("Easy", "Medium", "Hard")

PATTERN_TAXONOMY = (
    "Array / Hashing",
    "Two Pointers",
    "Sliding Window",
    "Stack",
    "Monotonic Stack",
    "Binary Search",
    "Linked List",
    "Tree",
    "BST",
    "Heap / Priority Queue",
    "Backtracking",
    "Graph",
    "DFS",
    "BFS",
    "Union Find",
    "Topological Sort",
    "Greedy",
    "Intervals",
    "Dynamic Programming",
    "Prefix Sum",
    "Trie",
    "Bit Manipulation",
    "Math",
    "Matrix",
    "Design",
    "Sorting",
    "Divide and Conquer",
    "Queue",
)

# What in a problem points to its technique. A recognition card names the types its clue belongs to.
CLUE_TYPES = (
    "sorted_or_ordered",      # sorted input, or order is what matters
    "contiguous",             # contiguous subarray / substring / window
    "prefix_range",           # range sums, running totals, subarray sum equals k
    "lookup_frequency",       # fast lookup, counting, duplicates, complements, grouping
    "nesting_matching",       # nested / matched structure, last-in-first-out
    "next_greater_range",     # nearest greater/smaller element, spans, ranges of influence
    "in_place_pointers",      # in place, O(1) extra space, pointer manipulation on a structure
    "tree_structure",         # recursive tree, subtree property, hierarchy
    "grid_connectivity",      # grid or matrix of cells, regions, islands, flood fill
    "dependencies_graph",     # relations, prerequisites, connectivity, cycles, components
    "shortest_steps",         # fewest steps / shortest path / level by level
    "optimization_overlap",   # min / max / count over choices with overlapping subproblems
    "enumerate_all",          # generate all combinations / permutations / subsets
    "small_constraints",      # tiny n makes exhaustive search feasible
    "local_choice",           # a local rule is provably safe (greedy), exchange argument
    "monotonic_answer",       # yes/no is monotone in the answer, or sorted/rotated search space
    "top_k",                  # k largest / smallest, median, merging sorted streams
    "intervals_overlap",      # intervals, meetings, merging and overlap
    "stream_design",          # operations with amortised-time requirements, data-structure design
    "bit_math",               # binary representation, parity, powers of two, number theory
    "divide_halves",          # split, solve halves, combine
    "direct_simulation",      # the statement spells out the procedure; implement it without overengineering
    "math_observation",       # a counting, parity or closed-form argument replaces search or simulation
)

# Labels too coarse to count as a technique ("Tree" says where you are, not what you do).
COARSE_TECHNIQUE_LABELS = frozenset({
    "array", "array / hashing", "string", "hash table", "tree", "binary tree", "bst", "graph", "math", "design",
    "matrix", "linked list", "stack", "queue", "dp", "technique", "pattern",
})

# Every pack has one free-recall pattern card with one of these prompts: they name no technique and no complexity.
RECOGNITION_PROMPTS = (
    "Which technique solves this problem, and what in the statement or constraints points to it?",
    "Name the technique you would use here and the clue in the problem that tells you.",
    "What approach fits this problem, and which part of the statement gives it away?",
)

# LeetCode topic tag -> suggested review pattern (used only to seed scaffolds).
TAG_TO_PATTERN = {
    "Array": "Array / Hashing",
    "Hash Table": "Array / Hashing",
    "String": "Array / Hashing",
    "Two Pointers": "Two Pointers",
    "Sliding Window": "Sliding Window",
    "Stack": "Stack",
    "Monotonic Stack": "Monotonic Stack",
    "Binary Search": "Binary Search",
    "Linked List": "Linked List",
    "Tree": "Tree",
    "Binary Tree": "Tree",
    "Binary Search Tree": "BST",
    "Heap (Priority Queue)": "Heap / Priority Queue",
    "Backtracking": "Backtracking",
    "Graph": "Graph",
    "Depth-First Search": "DFS",
    "Breadth-First Search": "BFS",
    "Union Find": "Union Find",
    "Topological Sort": "Topological Sort",
    "Greedy": "Greedy",
    "Dynamic Programming": "Dynamic Programming",
    "Prefix Sum": "Prefix Sum",
    "Trie": "Trie",
    "Bit Manipulation": "Bit Manipulation",
    "Math": "Math",
    "Matrix": "Matrix",
    "Design": "Design",
    "Sorting": "Sorting",
    "Divide and Conquer": "Divide and Conquer",
    "Queue": "Queue",
}


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class StrictModel(CamelModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


# --------------------------------------------------------------------------- problems


class Submission(CamelModel):
    submission_id: str
    language: str
    code: str


class Note(CamelModel):
    id: str
    text: str
    created_at: str


class Problem(CamelModel):
    leetcode_id: str | None = None
    title: str
    slug: str
    url: str
    difficulty: str | None = None
    status: Literal["solved", "unsolved"] = "unsolved"
    premium: bool = False
    tags: list[str] = Field(default_factory=list)
    problem_statement: str = ""
    constraints: list[str] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)
    ac_rate: float | None = None
    last_submitted_at: str | None = None
    latest_submission: Submission | None = None
    notes: list[Note] = Field(default_factory=list)
    source: str = "leetcode"  # leetcode | manual | seed
    imported_at: str | None = None
    last_synced_at: str | None = None


# --------------------------------------------------------------------------- review packs


class Approach(StrictModel):
    name: str
    summary: str
    time_complexity: str
    space_complexity: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    interview_relevance: str | None = None


class PersonalSolution(StrictModel):
    """How the user's accepted Python solution compares to the canonical approach."""

    approach: str | None = None
    time_complexity: str | None = None
    space_complexity: str | None = None
    is_optimal: bool | None = None
    notes: str | None = None


class AlsoValid(StrictModel):
    """A technique that works but is not the intended answer (brute force, extra space, higher complexity)."""

    name: str
    note: str = ""


class Rubric(StrictModel):
    """Grading rubric of a recognition card: the user names a technique and the clue that points to it."""

    technique: str
    aliases: list[str] = Field(default_factory=list)
    also_valid: list[AlsoValid] = Field(default_factory=list)
    clue_types: list[str]
    clue: str


class Card(StrictModel):
    id: str
    category: str
    type: str
    prompt_variants: list[str]
    options: list[str] | None = None
    answer: str | None = None
    accepted_answers: list[str] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    code: str | None = None
    explanation: str = ""
    incorrect_option_explanations: dict[str, str] = Field(default_factory=dict)
    rubric: Rubric | None = None  # recognition cards only (category pattern, type free_recall)
    enabled: bool = True
    source: Literal["generated", "manual"] = "generated"

    @model_validator(mode="after")
    def _check(self) -> Card:
        cid = self.id
        problems: list[str] = []
        if self.rubric is not None:
            rb = self.rubric
            if self.category != "pattern" or self.type != "free_recall":
                problems.append("a rubric is only allowed on a free_recall card of category 'pattern'")
            if rb.technique.strip().lower() in COARSE_TECHNIQUE_LABELS or not rb.technique.strip():
                problems.append(f"rubric technique '{rb.technique}' is too coarse; name the specific technique")
            if not rb.aliases or any(not a.strip() for a in rb.aliases):
                problems.append("rubric needs at least one alias (another way to name the technique)")
            if not 1 <= len(rb.clue_types) <= 3 or any(t not in CLUE_TYPES for t in rb.clue_types):
                problems.append(f"rubric clueTypes needs 1-3 values from: {', '.join(CLUE_TYPES)}")
            if not rb.clue.strip():
                problems.append("rubric clue is required")
            elif re.search(r"O\(", rb.clue):
                problems.append("rubric clue must not state a complexity")
            if any(p not in RECOGNITION_PROMPTS for p in self.prompt_variants):
                problems.append("a recognition card must use the standard prompts (RECOGNITION_PROMPTS)")
        if not cid or not all(c.isalnum() or c in "-_" for c in cid):
            problems.append("id must be non-empty and contain only letters, digits, '-' or '_'")
        if self.category not in CATEGORIES:
            problems.append(f"category '{self.category}' is invalid (allowed: {', '.join(CATEGORIES)})")
        if self.type not in QUESTION_TYPES:
            problems.append(f"type '{self.type}' is invalid (allowed: {', '.join(QUESTION_TYPES)})")
        if not self.prompt_variants or any(not p.strip() for p in self.prompt_variants):
            problems.append("promptVariants needs at least one non-empty prompt")
        if not self.explanation.strip():
            problems.append("explanation is required")
        if not (self.answer or "").strip():
            problems.append("answer is required")
        if self.type == "multiple_choice":
            opts = self.options or []
            if not 3 <= len(opts) <= 6:
                problems.append(f"multiple_choice needs 3-6 options (found {len(opts)})")
            if len(set(opts)) != len(opts):
                problems.append("options must be unique")
            if self.answer and self.answer not in opts:
                problems.append(f"answer '{self.answer}' is not one of the options")
            for key in self.incorrect_option_explanations:
                if key not in opts:
                    problems.append(f"incorrectOptionExplanations key '{key}' is not an option")
                elif key == self.answer:
                    problems.append("incorrectOptionExplanations must not explain the correct answer")
        elif self.options:
            problems.append(f"options are only allowed for multiple_choice (type is {self.type})")
        if self.type == "fill_blank":
            for p in self.prompt_variants:
                if "___" not in p:
                    problems.append(f"fill_blank prompt must contain a '___' blank: '{p[:40]}'")
                    break
        if self.type == "code_question" and not (self.code or "").strip():
            problems.append("code_question needs a 'code' snippet")
        if problems:
            raise ValueError(f"card '{cid}': " + "; ".join(problems))
        return self


class ReviewPack(StrictModel):
    schema_version: int = 1
    problem_slug: str
    summary: str = ""
    patterns: list[str] = Field(default_factory=list)
    main_insight: str | None = None
    invariant: str | None = None
    canonical_approach: str | None = None
    approaches: list[Approach] = Field(default_factory=list)
    personal_solution: PersonalSolution | None = None
    canonical_code: str | None = None  # clean Python for the canonical approach; shown with complexity questions
    common_mistakes: list[str] = Field(default_factory=list)
    edge_cases: list[str] = Field(default_factory=list)
    cards: list[Card] = Field(default_factory=list)
    generated_at: str | None = None

    @model_validator(mode="after")
    def _unique_ids(self) -> ReviewPack:
        seen: set[str] = set()
        for c in self.cards:
            if c.id in seen:
                raise ValueError(f"duplicate card id '{c.id}'")
            seen.add(c.id)
        return self


class CustomCards(StrictModel):
    """data/review-packs/custom/<slug>.json - manual cards, never touched by regeneration."""

    problem_slug: str
    cards: list[Card] = Field(default_factory=list)


# --------------------------------------------------------------------------- review state


class CardStat(CamelModel):
    category: str | None = None
    seen: int = 0
    correct: int = 0
    partial: int = 0
    failed: int = 0
    incorrect_streak: int = 0
    last_result: str | None = None
    last_seen_at: str | None = None


class CategoryStat(CamelModel):
    seen: int = 0
    correct: int = 0
    partial: int = 0
    failed: int = 0
    incorrect_streak: int = 0
    last_result: str | None = None
    last_seen_at: str | None = None
    recent: list[str] = Field(default_factory=list)


class ProblemState(CamelModel):
    level: int = 0
    last_review: str | None = None
    next_review: str | None = None
    recent_accuracy: float | None = None
    last_score: float | None = None
    review_count: int = 0
    lapses: int = 0
    weak_categories: list[str] = Field(default_factory=list)
    card_stats: dict[str, CardStat] = Field(default_factory=dict)
    category_stats: dict[str, CategoryStat] = Field(default_factory=dict)

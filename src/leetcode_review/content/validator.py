"""Review-pack validation with actionable messages."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from ..config import Paths
from ..schemas import PATTERN_TAXONOMY, CustomCards, ReviewPack


@dataclass
class Issue:
    file: str
    level: str  # error | warning
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper()}: {self.file}: {self.message}"


def _format_validation_error(exc: ValidationError) -> list[str]:
    msgs = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        msg = err["msg"].removeprefix("Value error, ")
        if err["type"] == "missing":
            msg = "required field is missing"
        elif err["type"] == "extra_forbidden":
            msg = "unknown field (typo? see docs/REVIEW_PACK_GUIDE.md)"
        msgs.append(f"{loc}: {msg}" if loc and not msg.startswith("card '") else msg)
    return msgs


# Severity of a missing recognition card or of leftover generated pattern cards.
RECOGNITION_LEVEL = "error"


def validate_pack_file(path: Path, known_slugs: set[str], *, custom: bool = False) -> list[Issue]:
    name = f"{path.parent.name}/{path.name}" if custom else path.name
    issues: list[Issue] = []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [Issue(name, "error", f"invalid JSON at line {exc.lineno} col {exc.colno}: {exc.msg}")]
    model = CustomCards if custom else ReviewPack
    try:
        pack = model.model_validate(raw)
    except ValidationError as exc:
        return [Issue(name, "error", m) for m in _format_validation_error(exc)]

    slug = path.stem
    if pack.problem_slug != slug:
        issues.append(Issue(name, "error", f"problemSlug '{pack.problem_slug}' must match the file name '{slug}'"))
    if pack.problem_slug not in known_slugs:
        issues.append(
            Issue(name, "error", f"no problem file data/problems/{pack.problem_slug}.json exists; "
                  "import it or run scripts/add_problem.py first")
        )
    for card in pack.cards:
        if len(card.prompt_variants) < 2:
            issues.append(Issue(name, "warning", f"card '{card.id}' has a single prompt variant; add 2-3 phrasings"))
    if custom:
        return issues
    if not pack.summary.strip():
        issues.append(Issue(name, "warning", "summary is empty"))
    if not pack.patterns:
        issues.append(Issue(name, "warning", "no patterns listed"))
    for p in pack.patterns:
        if p not in PATTERN_TAXONOMY:
            issues.append(Issue(name, "warning", f"pattern '{p}' is not in the standard taxonomy (allowed if intentional)"))
    if not pack.approaches:
        issues.append(Issue(name, "warning", "no approaches listed"))
    if pack.canonical_approach and pack.canonical_approach not in {a.name for a in pack.approaches}:
        issues.append(Issue(name, "error", f"canonicalApproach '{pack.canonical_approach}' is not one of the approach names"))
    if pack.canonical_code:  # card `code` may be an excerpt, canonicalCode must be complete
        try:
            ast.parse(pack.canonical_code)
        except SyntaxError as exc:
            issues.append(Issue(name, "error", f"canonicalCode is not valid Python: {exc.msg} (line {exc.lineno})"))
    recog = [c for c in pack.cards if c.rubric is not None and c.enabled]
    if len(recog) > 1:
        issues.append(Issue(name, "error", f"{len(recog)} enabled recognition cards; a pack has exactly one"))
    elif not recog and pack.cards:  # a scaffold without cards only gets the "skeleton" warning below
        issues.append(Issue(name, RECOGNITION_LEVEL, "no recognition card (free_recall pattern card with a rubric)"))
    else:
        extra = [c.id for c in pack.cards if c.enabled and c.category == "pattern" and c.rubric is None
                 and c.source == "generated"]
        if extra:
            issues.append(Issue(name, RECOGNITION_LEVEL,
                                f"generated pattern cards besides the recognition card: {extra}; "
                                "recategorise them (main_insight, data_structure, ...) or disable them"))
    if not pack.cards:
        issues.append(Issue(name, "warning", "pack has no cards yet (skeleton)"))
    elif not any(c.enabled for c in pack.cards):
        issues.append(Issue(name, "warning", "all cards are disabled"))
    return issues


def validate_all(paths: Paths, known_slugs: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    generated_ids: dict[str, set[str]] = {}
    for f in sorted(paths.review_packs.glob("*.json")):
        issues += validate_pack_file(f, known_slugs)
        try:
            generated_ids[f.stem] = {c["id"] for c in json.loads(f.read_text()).get("cards", [])}
        except Exception:
            pass
    owner: dict[str, str] = {}
    for slug, ids in generated_ids.items():   # a shared id once made a bulk edit rewrite two different packs' cards
        for cid in sorted(ids):
            if cid in owner and owner[cid] != slug:
                issues.append(Issue(f"{slug}.json", "error",
                                    f"card id '{cid}' is also used in {owner[cid]}.json; ids must be unique across packs"))
            owner.setdefault(cid, slug)
    for f in sorted(paths.custom_cards.glob("*.json")):
        issues += validate_pack_file(f, known_slugs, custom=True)
        try:
            ids = {c["id"] for c in json.loads(f.read_text()).get("cards", [])}
            clash = ids & generated_ids.get(f.stem, set())
            if clash:
                issues.append(Issue(f"custom/{f.name}", "error", f"card ids collide with generated pack: {sorted(clash)}"))
        except Exception:
            pass
    return issues

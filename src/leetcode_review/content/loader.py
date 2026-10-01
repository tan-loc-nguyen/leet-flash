"""Load review packs (generated + manual cards) and curated lists."""

from __future__ import annotations

from ..config import Paths
from ..schemas import Card, CustomCards, ReviewPack
from ..storage.atomic_write import atomic_write_json, read_json


def pack_path(paths: Paths, slug: str):
    return paths.review_packs / f"{slug}.json"


def custom_path(paths: Paths, slug: str):
    return paths.custom_cards / f"{slug}.json"


def load_pack(paths: Paths, slug: str) -> ReviewPack | None:
    """Load the generated pack merged with manual cards. Manual cards survive regeneration."""
    raw = read_json(pack_path(paths, slug))
    custom = load_custom(paths, slug)
    if raw is None:
        if custom is None or not custom.cards:
            return None
        return ReviewPack(problem_slug=slug, cards=list(custom.cards))
    pack = ReviewPack.model_validate(raw)
    if custom:
        existing = {c.id for c in pack.cards}
        pack.cards = pack.cards + [c for c in custom.cards if c.id not in existing]
    return pack


def load_custom(paths: Paths, slug: str) -> CustomCards | None:
    raw = read_json(custom_path(paths, slug))
    return CustomCards.model_validate(raw) if raw is not None else None


def list_pack_slugs(paths: Paths) -> set[str]:
    slugs = {f.stem for f in paths.review_packs.glob("*.json")}
    slugs |= {f.stem for f in paths.custom_cards.glob("*.json")}
    return slugs


def enabled_cards(pack: ReviewPack | None) -> list[Card]:
    return [c for c in pack.cards if c.enabled] if pack else []


def add_manual_card(paths: Paths, slug: str, card: Card) -> Card:
    """Append a manual card to the custom file (creating it if needed)."""
    custom = load_custom(paths, slug) or CustomCards(problem_slug=slug)
    generated = read_json(pack_path(paths, slug)) or {}
    taken = {c.id for c in custom.cards} | {c["id"] for c in generated.get("cards", [])}
    if card.id in taken:
        raise ValueError(f"card id '{card.id}' already exists for {slug}")
    card = card.model_copy(update={"source": "manual"})
    custom.cards.append(card)
    atomic_write_json(custom_path(paths, slug), custom.to_json())
    return card


def next_manual_id(paths: Paths, slug: str) -> str:
    custom = load_custom(paths, slug)
    n = len(custom.cards) + 1 if custom else 1
    taken = {c.id for c in custom.cards} if custom else set()
    while f"{slug}-manual-{n:02d}" in taken:
        n += 1
    return f"{slug}-manual-{n:02d}"


def load_lists(paths: Paths) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted(paths.lists.glob("*.json")):
        data = read_json(f)
        out[f.stem] = {"name": data.get("name", f.stem), "problems": list(data.get("problems", []))}
    return out

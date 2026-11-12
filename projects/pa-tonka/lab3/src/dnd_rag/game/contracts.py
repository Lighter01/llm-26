"""Game entities with stable IDs and honest provenance."""

from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from dnd_rag.contracts import Contract


class SourceRef(Contract):
    source_id: str
    book_id: str
    source_file: str
    provenance: dict = Field(default_factory=dict)


class MonsterCount(Contract):
    monster_id: str
    count: int = Field(gt=0)


class Monster(Contract):
    monster_id: str
    name: str
    cr: float
    xp: int = Field(ge=0)
    creature_types: list[str]
    habitats: list[str]
    stat_block: dict
    source: SourceRef


class EncounterResult(Contract):
    status: Literal['success', 'conflict', 'search_exhausted'] = 'success'
    party_size: int
    party_level: int
    monsters: list[dict] = Field(default_factory=list)
    total_xp: int = 0
    budgets: dict[str, int] = Field(default_factory=dict)
    difficulty: str | None = None
    exceeds_high: bool = False
    target_budget: int | None = None
    constraints: dict = Field(default_factory=dict)
    error: dict | None = None


class LootResult(Contract):
    kind: str
    cr: float
    count: int
    coins: dict[str, int]
    total_gp: float
    items: list[dict]
    rolls: list[dict]
    tables: list[dict]


@dataclass
class CatalogSnapshot:
    monsters: dict[str, Monster]
    items: dict[str, dict]
    loot_tables: dict
    encounter_rules: dict
    manifest: dict

    def lookup_monsters(self, query=None, *, habitat=None, creature_type=None, limit=5):
        from dnd_rag.game.catalog import lookup_monsters

        return lookup_monsters(
            self, query, habitat=habitat, creature_type=creature_type, limit=limit
        )

    def resolve_monster(self, selector):
        from dnd_rag.game.catalog import resolve_monster

        return resolve_monster(self, selector)

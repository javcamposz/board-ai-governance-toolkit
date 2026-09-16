"""The AI systems the organization runs, declared outside the register.

docs/board-questions.md asks first, under portfolio governance, which material AI systems
are missing from this view. The dashboard told the board to challenge whether the register
was complete and gave them nothing to challenge it with, because a register cannot tell
you what it is missing: absence is the one thing it has no row for.

So the estate is declared where the anchors and the decision rights are, outside the thing
being audited. A register that also supplied the list of systems it should contain would
supply the list of systems it does contain.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

TIERS = ("material", "routine")
MATERIAL = "material"


class InventoryError(ValueError):
    """A declared estate that cannot be used to check completeness."""


@dataclass(frozen=True)
class System:
    """One AI system the organization is running."""

    name: str
    tier: str
    owner: str = ""

    def __post_init__(self) -> None:
        # Validated here rather than only at the CLI, because a tier the constructor
        # accepts and the rule does not recognise silently removes a system from the check.
        if self.tier not in TIERS:
            raise InventoryError(
                f"{self.name or 'system'} tier is {self.tier!r}; the two are {', '.join(TIERS)}"
            )

    @property
    def is_material(self) -> bool:
        return self.tier == MATERIAL


@dataclass(frozen=True)
class Inventory:
    systems: tuple[System, ...]

    @property
    def declares_material_systems(self) -> bool:
        """An estate with nothing material in it cannot be checked against.

        A completeness check an empty declaration satisfies produces a green result for the
        absence of a claim, which is worse than producing none.
        """
        return bool(self.material)

    @classmethod
    def from_records(cls, records: Sequence[Mapping[str, object]]) -> Inventory:
        return cls(tuple(
            System(
                name=str(record["name"]).strip(),
                tier=str(record["tier"]).strip().lower(),
                owner=str(record.get("owner", "")).strip(),
            )
            for record in records
        ))

    @property
    def material(self) -> tuple[System, ...]:
        return tuple(system for system in self.systems if system.is_material)

    def names(self) -> frozenset[str]:
        return frozenset(system.name.strip().casefold() for system in self.systems)

    def find(self, name: str) -> System | None:
        wanted = name.strip().casefold()
        for system in self.systems:
            if system.name.strip().casefold() == wanted:
                return system
        return None

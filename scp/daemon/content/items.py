from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import Literal


ItemClass = Literal["Safe", "Euclid", "Keter"]


FORMS = [
    "recovered audio recording",
    "printed document",
    "digital file",
    "encrypted transmission",
    "handwritten letter",
    "VHS tape",
    "memory card",
    "photograph sequence",
    "intercepted packet capture",
    "corrupted archive",
]

ADJECTIVES = [
    "recurring",
    "anomalous",
    "self-updating",
    "recursive",
    "self-referential",
    "untraceable",
    "inconsistent",
    "heavily redacted",
    "encrypted",
    "analog-only",
    "uncompressed",
    "ultraviolet-encoded",
    "palindromic",
]

EFFECTS = [
    "induces compulsive pattern-matching in observers",
    "causes recipients to forget the prior 15 minutes",
    "propagates via quoted text in conversation",
    "degrades photographic media within the same room",
    "modifies timestamps on nearby filesystems",
    "produces tinnitus at specific frequencies",
    "causes adjacent VMs to exhibit numerical drift",
    "attempts to exfiltrate over any available network interface",
    "induces a mild sense of being watched",
    "corrupts log files in structured, meaningful patterns",
    "causes non-deterministic classifier output",
    "manifests as unattributable scheduled tasks",
]

CLASS_WEIGHTS = {"Safe": 0.55, "Euclid": 0.35, "Keter": 0.10}
CLASS_HAZARD = {
    "Safe": (1, 5),
    "Euclid": (5, 12),
    "Keter": (12, 22),
}


@dataclass
class ItemProfile:
    designation: str
    item_class: ItemClass
    hazard_strength: int
    memetic_load: int
    cognitohazard_class: int
    self_propagation: int
    form: str
    effect: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ItemProfile":
        return cls(**d)


def _weighted_class(rng: random.Random) -> ItemClass:
    r = rng.random()
    acc = 0.0
    for c, w in CLASS_WEIGHTS.items():
        acc += w
        if r <= acc:
            return c  # type: ignore[return-value]
    return "Safe"


def generate(rng: random.Random | None = None) -> ItemProfile:
    r = rng or random.Random()
    c = _weighted_class(r)
    lo, hi = CLASS_HAZARD[c]
    return ItemProfile(
        designation=f"SCP-{r.randint(1000, 9999)}",
        item_class=c,
        hazard_strength=r.randint(lo, hi),
        memetic_load=r.randint(0, 10 if c != "Safe" else 4),
        cognitohazard_class=r.randint(
            0, 10 if c == "Keter" else (6 if c == "Euclid" else 3)
        ),
        self_propagation=r.randint(
            0, 10 if c == "Keter" else (5 if c == "Euclid" else 2)
        ),
        form=f"{r.choice(ADJECTIVES)} {r.choice(FORMS)}",
        effect=r.choice(EFFECTS),
    )

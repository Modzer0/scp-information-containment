from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VmSpec:
    """Numeric containment components per DESIGN.md §8.1.

    Totals form the VM's containment rating; compared against an item's
    hazard_strength to produce a delta that drives leak category.
    """

    memory_encryption: int   # 0 none | 3 software | 6 hardware | 10 mainframe LPAR
    isolation: int           # 0 shared-kernel | 2 hypervisor | 5 bare-metal | 8 air-gapped
    mnestic_firmware: int    # 0 | 2 | 4
    physical_shielding: int  # 0 | 2 Faraday | 4 polarized | 6 SCSC
    scanner_freshness: int   # 0 stale | 1 current | 2 live feed

    @property
    def containment(self) -> int:
        return (
            self.memory_encryption
            + self.isolation
            + self.mnestic_firmware
            + self.physical_shielding
            + self.scanner_freshness
        )

    def to_dict(self) -> dict:
        return {
            "memory_encryption": self.memory_encryption,
            "isolation": self.isolation,
            "mnestic_firmware": self.mnestic_firmware,
            "physical_shielding": self.physical_shielding,
            "scanner_freshness": self.scanner_freshness,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VmSpec":
        return cls(**{k: int(v) for k, v in d.items()})


def leak_category(hazard: int, containment: int) -> str:
    delta = hazard - containment
    if delta <= 0:
        return "stable"
    if delta <= 3:
        return "slow_leak"
    if delta <= 7:
        return "active_leak"
    return "catastrophic"


def seed_vm_spec() -> VmSpec:
    """Default VM spec for the starter host: software encryption,
    hypervisor isolation, no mnestic firmware, no physical shielding,
    scanner current. Containment = 3 + 2 + 0 + 0 + 1 = 6.
    Handles Safe (hazard 1–5) stably; leaks on Euclid; fails on Keter.
    """
    return VmSpec(
        memory_encryption=3,
        isolation=2,
        mnestic_firmware=0,
        physical_shielding=0,
        scanner_freshness=1,
    )

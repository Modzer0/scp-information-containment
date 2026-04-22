from __future__ import annotations

from dataclasses import dataclass, field

from .containment import VmSpec
from . import network as _network


# Minimum clearance by item class (see DESIGN.md §18.2)
CLEARANCE_REQUIRED = {"Safe": 1, "Euclid": 2, "Keter": 3}

# Minimum infosec skill recommended by item class
SKILL_RECOMMENDED = {"Safe": 10, "Euclid": 30, "Keter": 60}


@dataclass
class MistakeCandidate:
    """A potential mistake detected pre-action. If the action proceeds
    (possibly via override), it's persisted as a mistake record and may
    contribute to an incident report.
    """

    kind: str
    title: str              # one-line human-readable
    detail: str             # one-paragraph explanation
    suggestion: str         # how to avoid it
    severity_weight: int    # 1 (minor) .. 3 (major) — used to escalate root cause


@dataclass
class DetectionResult:
    mistakes: list[MistakeCandidate] = field(default_factory=list)


def detect_analyze_mistakes(
    operator: dict,
    item: dict,
    vm: dict,
    site_util: dict | None = None,
    site_network_tier: dict | None = None,
    site_encryption_level: str = "none",
) -> DetectionResult:
    """Run the mistake detectors for an analyze action.

    site_util (optional) carries the site's power/cooling headroom so
    power_overload / cooling_overload can be detected.
    site_network_tier and site_encryption_level drive link-security
    detectors (commercial-link-without-encryption, under-encrypted-for-class).
    """
    out = DetectionResult()

    spec = VmSpec.from_dict(vm["spec"])
    containment = spec.containment
    hazard = int(item["hazard_strength"])
    item_class = item["class"]

    # 1. Undersized containment — hazard exceeds VM containment
    if hazard > containment:
        out.mistakes.append(
            MistakeCandidate(
                kind="undersized_containment",
                title=f"VM containment ({containment}) below item hazard ({hazard})",
                detail=(
                    f"Item {item['designation']} is {item_class}-class with "
                    f"hazard_strength={hazard}. The target VM has containment "
                    f"rating {containment} (delta={hazard - containment}). "
                    f"Expect leak on analysis."
                ),
                suggestion=(
                    "Use a VM with higher containment: increase memory_encryption, "
                    "isolation, or physical_shielding. Keter-class items require a "
                    "mainframe LPAR (containment >= 16)."
                ),
                severity_weight=3,
            )
        )

    # 2. Tainted VM — reusing without snapshot rollback
    if vm.get("status") == "tainted":
        out.mistakes.append(
            MistakeCandidate(
                kind="tainted_vm",
                title=f"VM {vm['name']} is tainted from a prior analysis",
                detail=(
                    "Reusing a tainted VM without snapshot rollback risks "
                    "cross-contamination between items."
                ),
                suggestion="Snapshot-restore the VM before reuse, or assign another VM.",
                severity_weight=2,
            )
        )

    # 3. Stale scanner — freshness component is zero
    if int(vm["spec"].get("scanner_freshness", 0)) == 0:
        out.mistakes.append(
            MistakeCandidate(
                kind="stale_scanner",
                title="Scanner signature DB is stale",
                detail=(
                    "The host's mnestic-signature scanner is running without a "
                    "current signature feed; detection coverage is degraded."
                ),
                suggestion="Refresh the scanner before analyzing anomalous material.",
                severity_weight=1,
            )
        )

    # 4. Insufficient clearance — operator below class requirement
    required_clearance = CLEARANCE_REQUIRED.get(item_class, 0)
    if int(operator.get("clearance", 0)) < required_clearance:
        out.mistakes.append(
            MistakeCandidate(
                kind="insufficient_clearance",
                title=(
                    f"Operator clearance ({operator.get('clearance', 0)}) below "
                    f"{item_class}-class requirement ({required_clearance})"
                ),
                detail=(
                    f"{operator.get('name', 'operator')} lacks Level-"
                    f"{required_clearance} clearance for this item class."
                ),
                suggestion=(
                    "Assign a cleared operator, or the player-avatar if clearance "
                    "permits."
                ),
                severity_weight=2,
            )
        )

    # 5. Unskilled operator — infosec below recommended threshold
    infosec = int(operator.get("skills", {}).get("infosec", 0))
    recommended = SKILL_RECOMMENDED.get(item_class, 0)
    if infosec < recommended:
        out.mistakes.append(
            MistakeCandidate(
                kind="unskilled_operator",
                title=(
                    f"Operator infosec {infosec} below {item_class}-class "
                    f"recommended ({recommended})"
                ),
                detail=(
                    "Operator lacks the recommended proficiency; checklists may "
                    "be missed, leading to procedural mistakes."
                ),
                suggestion=(
                    "Assign a more skilled operator, or allow supervised training "
                    "on lower-class items first."
                ),
                severity_weight=1,
            )
        )

    # 6. Compromised host — host status not clean
    host_status = vm.get("host_status", "clean")
    if host_status != "clean":
        out.mistakes.append(
            MistakeCandidate(
                kind="compromised_host",
                title=f"VM's host is {host_status}, not clean",
                detail=(
                    "Analyzing on a compromised host risks infection re-seeding "
                    "onto the freshly analyzed item or operator console."
                ),
                suggestion="Wipe the host first, then analyze on a clean substrate.",
                severity_weight=3,
            )
        )

    # 7. Site power overload — drawing more than the feed can supply
    if site_util and site_util.get("power_over"):
        used = site_util.get("power_kw_used", 0)
        cap = site_util.get("power_kw_capacity", 0)
        out.mistakes.append(
            MistakeCandidate(
                kind="power_overload",
                title=f"Site power overloaded ({used} kW drawn vs {cap} kW supply)",
                detail=(
                    "Running analysis while the site is over its power budget "
                    "risks a brownout mid-analysis, corrupting in-flight state."
                ),
                suggestion=(
                    "Upgrade the site power feed or bring fewer hosts online."
                ),
                severity_weight=2,
            )
        )

    # 8. Site cooling overload — heat rejection inadequate
    if site_util and site_util.get("cooling_over"):
        used = site_util.get("cooling_kw_used", 0)
        cap = site_util.get("cooling_kw_capacity", 0)
        out.mistakes.append(
            MistakeCandidate(
                kind="cooling_overload",
                title=f"Site cooling overloaded ({used} kW heat vs {cap} kW reject)",
                detail=(
                    "Thermal throttling under load degrades analysis accuracy "
                    "and introduces timing variance that can be exploited by "
                    "self-propagating payloads."
                ),
                suggestion="Increase chiller capacity or spread load across sites.",
                severity_weight=2,
            )
        )

    # 9. Commercial link without adequate encryption
    if site_network_tier is not None and site_network_tier.get("is_commercial"):
        required = _network.MIN_ENCRYPTION_FOR_CLASS.get(item_class, "software")
        have_rank = _network.encryption_rank(site_encryption_level)
        need_rank = _network.encryption_rank(required)
        if site_encryption_level == "none":
            out.mistakes.append(
                MistakeCandidate(
                    kind="unencrypted_commercial_link",
                    title=(
                        f"Commercial link ({site_network_tier.get('tier')}) with "
                        f"no encryption"
                    ),
                    detail=(
                        "Traffic over the commercial data link is visible to the "
                        "provider. Item metadata, session keys, and staff console "
                        "activity leak unless a site link encryptor is installed."
                    ),
                    suggestion=(
                        "Install site encryption (WireShield software minimum; "
                        "Sentinel hardware or Aegis Type-1 for Euclid/Keter)."
                    ),
                    severity_weight=3,
                )
            )
        elif have_rank < need_rank:
            out.mistakes.append(
                MistakeCandidate(
                    kind="undercrypt_commercial_link",
                    title=(
                        f"Site encryption '{site_encryption_level}' below "
                        f"{item_class}-class requirement '{required}'"
                    ),
                    detail=(
                        "Current link encryption is insufficient for this item "
                        "class on a commercial carrier. Side-channel exposure of "
                        "analysis traffic at this tier is non-trivial."
                    ),
                    suggestion=(
                        f"Upgrade site encryption to at least '{required}' before "
                        f"handling {item_class}-class over this link."
                    ),
                    severity_weight=2,
                )
            )

    return out

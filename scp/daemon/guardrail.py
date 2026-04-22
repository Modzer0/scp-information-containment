from __future__ import annotations

from dataclasses import dataclass

from .mistakes import DetectionResult


HARD_RAIL_MAX = 20   # skill < 20  → refuse
SOFT_RAIL_MAX = 50   # 20..50      → require override
WARN_RAIL_MAX = 80   # 50..80      → silent warning
# 80+ → expert mode, no rails


@dataclass
class GuardrailDecision:
    allowed: bool
    require_override: bool
    rail_level: str                 # hard | soft | warn | expert | none
    warnings: list[str]
    refuse_reason: str | None
    mistake_kinds: list[str]


def decide(
    detection: DetectionResult,
    operator_skill: int,
    override_requested: bool,
) -> GuardrailDecision:
    mistake_kinds = [m.kind for m in detection.mistakes]
    if not detection.mistakes:
        return GuardrailDecision(
            allowed=True,
            require_override=False,
            rail_level="none",
            warnings=[],
            refuse_reason=None,
            mistake_kinds=[],
        )

    # Rail tier is chosen by the operator's skill — less skilled operators
    # get stopped harder, expert operators get nothing in their way.
    warnings = [f"{m.kind}: {m.title}" for m in detection.mistakes]
    titles = "; ".join(m.title for m in detection.mistakes)

    if operator_skill < HARD_RAIL_MAX:
        return GuardrailDecision(
            allowed=False,
            require_override=False,
            rail_level="hard",
            warnings=warnings,
            refuse_reason=(
                f"Hard rail: operator skill {operator_skill} < {HARD_RAIL_MAX}. "
                f"Unsafe conditions detected: {titles}. "
                f"Correct the setup, or assign a more skilled operator."
            ),
            mistake_kinds=mistake_kinds,
        )

    if operator_skill < SOFT_RAIL_MAX:
        if not override_requested:
            return GuardrailDecision(
                allowed=False,
                require_override=True,
                rail_level="soft",
                warnings=warnings,
                refuse_reason=(
                    f"Soft rail: {titles}. "
                    f"Re-issue the command with a trailing `override` token to proceed."
                ),
                mistake_kinds=mistake_kinds,
            )
        # overridden — proceed
        return GuardrailDecision(
            allowed=True,
            require_override=False,
            rail_level="soft",
            warnings=warnings,
            refuse_reason=None,
            mistake_kinds=mistake_kinds,
        )

    if operator_skill < WARN_RAIL_MAX:
        return GuardrailDecision(
            allowed=True,
            require_override=False,
            rail_level="warn",
            warnings=warnings,
            refuse_reason=None,
            mistake_kinds=mistake_kinds,
        )

    # Expert — no warnings surfaced, still recorded as mistakes in the journal
    return GuardrailDecision(
        allowed=True,
        require_override=False,
        rail_level="expert",
        warnings=[],
        refuse_reason=None,
        mistake_kinds=mistake_kinds,
    )

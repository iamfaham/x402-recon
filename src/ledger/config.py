"""Tunable thresholds for the categorization cascade.

These are configuration with stated defaults, not hardcoded constants. Tuning
them is how the calibration metric gets improved.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CascadeConfig:
    """Thresholds controlling when a rule is willing to claim confidence."""

    min_occurrences: int = 2
    time_window_minutes: int = 5
    generic_memos: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {"", "payment", "x402", "n/a", "-", "none", "tx", "transfer"}
        )
    )


DEFAULT_CONFIG = CascadeConfig()

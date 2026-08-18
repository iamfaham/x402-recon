"""Money handling for Ledger.

Amounts are always integers in micro-USDC (6 decimal places). Floats are never
used: sub-cent payments summed thousands of times drift with floating point, and
drift in a financial total is the exact failure this tool exists to prevent.
"""

from decimal import Decimal

MICRO_PER_USDC = 1_000_000
_MAX_DECIMAL_PLACES = 6


def usdc_to_micro(amount: str) -> int:
    """Convert a USDC amount string to integer micro-USDC.

    Raises ValueError on negative amounts or more precision than USDC supports.
    """
    value = Decimal(amount)
    if value < 0:
        raise ValueError(f"amount must not be negative: {amount}")
    if -value.as_tuple().exponent > _MAX_DECIMAL_PLACES:
        raise ValueError(
            f"amount has more than {_MAX_DECIMAL_PLACES} decimal places: {amount}"
        )
    return int(value * MICRO_PER_USDC)


def micro_to_decimal(micro: int) -> Decimal:
    """Convert integer micro-USDC to an exact Decimal USDC amount."""
    return Decimal(micro) / Decimal(MICRO_PER_USDC)


def format_usdc(micro: int) -> str:
    """Format micro-USDC for display.

    Always shows at least two decimal places, and up to six when the amount has
    sub-cent precision, so micropayments are never displayed as "$0.00".
    """
    text = f"{micro_to_decimal(micro):,.6f}"
    whole, _, fraction = text.partition(".")
    fraction = fraction.rstrip("0")
    if len(fraction) < 2:
        fraction = fraction.ljust(2, "0")
    return f"${whole}.{fraction}"

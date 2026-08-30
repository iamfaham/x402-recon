"""Money handling for Ledger.

Amounts are always integers in micro-USDC (6 decimal places). Floats are never
used: sub-cent payments summed thousands of times drift with floating point, and
drift in a financial total is the exact failure this tool exists to prevent.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MICRO_PER_USDC = 1_000_000
_MAX_DECIMAL_PLACES = 6


def usdc_to_micro(amount: str) -> int:
    """Convert a USDC amount string to integer micro-USDC.

    Raises ValueError on malformed input, negative amounts, or more precision
    than USDC supports. Precision is judged on the normalized value, so a
    padded literal like "1.1000000" is accepted — it is exactly representable.
    """
    try:
        value = Decimal(amount)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"not a valid decimal amount: {amount!r}") from exc
    if not value.is_finite():
        raise ValueError(f"amount must be a finite number: {amount!r}")
    if value < 0:
        raise ValueError(f"amount must not be negative: {amount}")
    exponent = value.normalize().as_tuple().exponent
    if isinstance(exponent, int) and -exponent > _MAX_DECIMAL_PLACES:
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
    sub-cent precision, so micropayments are never displayed as "$0.00". A
    negative net renders as "-$1.50", with the sign outside the currency mark.
    """
    sign = "-" if micro < 0 else ""
    text = f"{abs(micro_to_decimal(micro)):,.6f}"
    whole, _, fraction = text.partition(".")
    fraction = fraction.rstrip("0")
    if len(fraction) < 2:
        fraction = fraction.ljust(2, "0")
    return f"{sign}${whole}.{fraction}"


# Two decimal places is one cent, which is 10_000 micro-USDC.
_MICRO_PER_CENT = 10_000


def format_usdc_rounded(micro: int) -> str:
    """Format micro-USDC for display as exactly two decimal places.

    For aggregates only. A total of thousands of sub-cent payments carries six
    genuine decimal places, which is exact and unreadable; this renders the
    figure a business owner actually wants. Individual amounts keep
    `format_usdc`, which never rounds away a micropayment.

    ROUND_HALF_UP is chosen because it matches what a reader expects of
    $0.005 -> $0.01. The mode barely matters here since callers also show the
    exact figure whenever rounding lost anything, but it is fixed and stated
    rather than left to a default.

    This is display only. No stored or summed value is ever rounded.
    """
    sign = "-" if micro < 0 else ""
    cents = abs(micro_to_decimal(micro)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{sign}${cents:,.2f}"


def rounds_exactly(micro: int) -> bool:
    """Whether rounding this amount to cents loses nothing.

    Callers use this to decide whether to print the exact figure alongside a
    rounded one: a total of $437.910000 needs no such footnote, while
    $437.914959 does. Keeping the footnote conditional is what makes its
    presence meaningful.
    """
    return micro % _MICRO_PER_CENT == 0

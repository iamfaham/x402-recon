from decimal import Decimal

import pytest

from x402_recon.money import (
    MICRO_PER_USDC,
    format_usdc,
    format_usdc_rounded,
    micro_to_decimal,
    rounds_exactly,
    usdc_to_micro,
)


def test_micro_per_usdc_is_six_decimals():
    assert MICRO_PER_USDC == 1_000_000


def test_usdc_to_micro_converts_whole_units():
    assert usdc_to_micro("1") == 1_000_000


def test_usdc_to_micro_converts_sub_cent_amounts():
    assert usdc_to_micro("0.001234") == 1234


def test_usdc_to_micro_rejects_more_than_six_decimals():
    with pytest.raises(ValueError):
        usdc_to_micro("0.0000001")


def test_usdc_to_micro_rejects_negative():
    with pytest.raises(ValueError):
        usdc_to_micro("-1.00")


def test_micro_to_decimal_is_exact():
    assert micro_to_decimal(1234) == Decimal("0.001234")


def test_format_usdc_keeps_two_decimals_minimum():
    assert format_usdc(1_000_000) == "$1.00"


def test_format_usdc_shows_sub_cent_precision():
    assert format_usdc(1234) == "$0.001234"


def test_format_usdc_strips_trailing_zeros_beyond_two_decimals():
    assert format_usdc(1_500_000) == "$1.50"


def test_format_usdc_adds_thousands_separators():
    assert format_usdc(1_234_567_000_000) == "$1,234,567.00"


def test_usdc_to_micro_raises_value_error_on_garbage():
    with pytest.raises(ValueError):
        usdc_to_micro("abc")


def test_usdc_to_micro_raises_value_error_on_empty_string():
    with pytest.raises(ValueError):
        usdc_to_micro("")


def test_usdc_to_micro_accepts_padded_decimals_that_are_representable():
    # "1.1000000" has 7 literal decimal places but is exactly 1.1 — representable.
    assert usdc_to_micro("1.1000000") == 1_100_000


def test_usdc_to_micro_still_rejects_genuinely_excess_precision():
    with pytest.raises(ValueError):
        usdc_to_micro("0.0000001")


def test_usdc_to_micro_rejects_non_finite():
    with pytest.raises(ValueError):
        usdc_to_micro("NaN")
    with pytest.raises(ValueError):
        usdc_to_micro("Infinity")


def test_format_usdc_renders_negative_with_leading_sign():
    assert format_usdc(-1_500_000) == "-$1.50"


def test_format_usdc_renders_negative_sub_cent():
    assert format_usdc(-1234) == "-$0.001234"


def test_format_usdc_rounded_always_shows_exactly_two_decimals():
    assert format_usdc_rounded(1_000_000) == "$1.00"
    assert format_usdc_rounded(437_914_959) == "$437.91"
    assert format_usdc_rounded(34_296_000) == "$34.30"
    assert format_usdc_rounded(0) == "$0.00"


def test_format_usdc_rounded_rounds_half_up():
    # 0.005 -> 0.01 is what a reader expects; the mode is fixed, not defaulted.
    assert format_usdc_rounded(5_000) == "$0.01"
    assert format_usdc_rounded(4_999) == "$0.00"
    assert format_usdc_rounded(15_000) == "$0.02"


def test_format_usdc_rounded_keeps_the_sign_outside_the_currency_mark():
    assert format_usdc_rounded(-1_500_000) == "-$1.50"
    assert format_usdc_rounded(-5_000) == "-$0.01"


def test_format_usdc_rounded_groups_thousands():
    assert format_usdc_rounded(1_234_567_890) == "$1,234.57"


def test_rounds_exactly_is_true_only_when_nothing_is_lost():
    assert rounds_exactly(437_910_000) is True
    assert rounds_exactly(1_000_000) is True
    assert rounds_exactly(0) is True
    assert rounds_exactly(437_914_959) is False
    assert rounds_exactly(123) is False


def test_rounds_exactly_handles_negatives():
    assert rounds_exactly(-1_500_000) is True
    assert rounds_exactly(-1_500_001) is False


def test_rounded_rows_need_not_sum_to_the_rounded_total():
    # DOCUMENTED LIMITATION, not a bug to fix. Rounding each row independently
    # does not distribute over addition. This is exactly why any view that
    # rounds also prints the exact total.
    band_a, band_b = 433_334_000, 4_891_000
    total = band_a + band_b  # 438_225_000 -> $438.225 exactly

    assert format_usdc_rounded(band_a) == "$433.33"
    assert format_usdc_rounded(band_b) == "$4.89"
    # A reader adding the displayed column gets $438.22 ...
    # ... but the true total rounds up, because .225 -> .23 under HALF_UP.
    assert format_usdc_rounded(total) == "$438.23"
    assert rounds_exactly(total) is False  # so the exact figure is shown

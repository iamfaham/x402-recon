from decimal import Decimal

import pytest

from ledger.money import MICRO_PER_USDC, format_usdc, micro_to_decimal, usdc_to_micro


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

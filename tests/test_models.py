from dataclasses import fields

from ledger.models import (
    AXIS_PAYER,
    AXIS_SERVICE,
    CONFIDENT,
    Categorization,
)


def test_axis_names():
    assert AXIS_PAYER == "payer"
    assert AXIS_SERVICE == "service"


def test_categorization_carries_an_axis_second():
    names = [f.name for f in fields(Categorization)]
    assert names[0] == "transaction_id"
    assert names[1] == "axis"


def test_categorization_constructs_with_an_axis():
    c = Categorization(
        transaction_id=1,
        axis=AXIS_SERVICE,
        category_label="service:weather-api",
        confidence_tier=CONFIDENT,
        rule_matched="memo_match",
        categorized_at="2026-08-19T10:00:00Z",
    )
    assert c.axis == AXIS_SERVICE
    assert c.confidence_tier == CONFIDENT

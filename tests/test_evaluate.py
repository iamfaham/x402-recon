import pytest

from ledger.evaluate import (
    CALIBRATION_THRESHOLD,
    TIME_CLUSTER_THRESHOLD,
    render_evaluation,
    score,
    time_cluster_verdict,
)
from ledger.models import (
    CONFIDENT,
    RULE_SENDER_MATCH,
    RULE_TIME_CLUSTER,
    UNCATEGORIZED,
    UNCERTAIN,
    UNGROUPABLE,
)


def build(predicted, truth, tiers=None, rules=None, hazards=None):
    tiers = tiers or dict.fromkeys(predicted, CONFIDENT)
    rules = rules or dict.fromkeys(predicted, RULE_SENDER_MATCH)
    return score(predicted, truth, tiers, rules, hazards)


def test_perfect_grouping_scores_one():
    result = build(
        {"a": "g1", "b": "g1", "c": "g2", "d": "g2"},
        {"a": "X", "b": "X", "c": "Y", "d": "Y"},
    )
    assert result.precision == 1.0
    assert result.recall == 1.0


def test_merging_two_true_groups_hurts_precision_not_recall():
    # One predicted group holding two different true payers.
    result = build(
        {"a": "g1", "b": "g1", "c": "g1", "d": "g1"},
        {"a": "X", "b": "X", "c": "Y", "d": "Y"},
    )
    assert result.precision == 0.5
    assert result.recall == 1.0


def test_fragmenting_one_true_group_hurts_recall_not_precision():
    # THE POINT OF THIS TASK: the old majority-vote scorer gave this 1.0.
    result = build(
        {"a": "g1", "b": "g1", "c": "g2", "d": "g2"},
        {"a": "X", "b": "X", "c": "X", "d": "X"},
    )
    assert result.precision == 1.0
    assert result.recall == 0.5


def test_ungroupable_left_uncategorized_scores_perfectly():
    result = build(
        {"a": UNCATEGORIZED, "b": UNCATEGORIZED},
        {"a": UNGROUPABLE, "b": UNGROUPABLE},
    )
    assert result.precision == 1.0
    assert result.recall == 1.0


def test_ungroupable_swept_into_a_cluster_is_penalized():
    result = build(
        {"a": "g1", "b": "g1", "c": "g1", "d": "g1"},
        {"a": UNGROUPABLE, "b": UNGROUPABLE, "c": UNGROUPABLE, "d": UNGROUPABLE},
    )
    assert result.precision == 0.25


def test_real_payer_left_uncategorized_loses_recall_only():
    result = build(
        {"a": "g1", "b": "g1", "c": UNCATEGORIZED, "d": UNCATEGORIZED},
        {"a": "X", "b": "X", "c": "X", "d": "X"},
    )
    assert result.precision == 1.0
    assert result.recall == 0.375


def test_empty_input_returns_zeros_without_dividing_by_zero():
    result = build({}, {})
    assert result.precision == 0.0
    assert result.recall == 0.0
    assert result.confident_precision == 0.0


def test_confident_precision_covers_only_confident_transactions():
    result = build(
        {"a": "g1", "b": "g1", "c": "g2", "d": "g2"},
        {"a": "X", "b": "X", "c": "Y", "d": "Z"},
        tiers={"a": CONFIDENT, "b": CONFIDENT, "c": UNCERTAIN, "d": UNCERTAIN},
    )
    assert result.confident_precision == 1.0
    assert result.confident_count == 2


def test_declined_recall_measures_the_cost_of_caution():
    # 'c' is correctly declined (ungroupable). 'd' is a real payer given up on.
    result = build(
        {"a": "g1", "b": "g1", "c": UNCATEGORIZED, "d": UNCATEGORIZED},
        {"a": "X", "b": "X", "c": UNGROUPABLE, "d": "X"},
        tiers={"a": CONFIDENT, "b": CONFIDENT, "c": UNCERTAIN, "d": UNCERTAIN},
    )
    assert result.declined_count == 2
    # c scores 1.0 (its true group is itself); d scores 1/3.
    assert result.declined_recall == pytest.approx((1.0 + 1 / 3) / 2)


def test_calibration_is_meaningful_with_no_uncertain_rule_present():
    # Proves v0.1b cannot be blocked by the metric going vacuous: a cascade
    # whose only rules are confident still yields usable figures.
    result = build(
        {"a": "g1", "b": "g1", "c": UNCATEGORIZED},
        {"a": "X", "b": "X", "c": UNGROUPABLE},
        tiers={"a": CONFIDENT, "b": CONFIDENT, "c": UNCERTAIN},
        rules={"a": RULE_SENDER_MATCH, "b": RULE_SENDER_MATCH, "c": "none"},
    )
    assert result.confident_count == 2
    assert result.confident_precision == 1.0
    assert result.declined_count == 1


def test_per_rule_metrics_are_reported_separately():
    result = build(
        {"a": "g1", "b": "g1", "c": "g2", "d": "g2"},
        {"a": "X", "b": "X", "c": "Y", "d": "Z"},
        rules={
            "a": RULE_SENDER_MATCH,
            "b": RULE_SENDER_MATCH,
            "c": RULE_TIME_CLUSTER,
            "d": RULE_TIME_CLUSTER,
        },
    )
    by_rule = {m.rule: m for m in result.per_rule}
    assert by_rule[RULE_SENDER_MATCH].precision == 1.0
    assert by_rule[RULE_TIME_CLUSTER].precision == 0.5
    assert by_rule[RULE_TIME_CLUSTER].count == 2


def test_hazard_split_separates_fragility_from_failure():
    result = build(
        {"a": "g1", "b": "g1", "c": "g2", "d": "g2"},
        {"a": "X", "b": "X", "c": "Y", "d": "Z"},
        rules=dict.fromkeys("abcd", RULE_TIME_CLUSTER),
        hazards={"c": "shared_memo_strangers", "d": "shared_memo_strangers"},
    )
    metrics = result.per_rule[0]
    assert result.hazards_available is True
    assert metrics.ordinary_count == 2
    assert metrics.ordinary_precision == 1.0
    assert metrics.hazard_count == 2
    assert metrics.hazard_precision == 0.5


def test_missing_hazards_degrades_cleanly():
    # The real-data path: no hazard tags exist, metrics still report.
    result = build(
        {"a": "g1", "b": "g1"},
        {"a": "X", "b": "X"},
        hazards=None,
    )
    assert result.hazards_available is False
    assert result.precision == 1.0
    assert result.per_rule[0].hazard_count == 0


def test_time_cluster_verdict_fails_below_threshold():
    result = build(
        {"a": "g1", "b": "g1", "c": "g1", "d": "g1"},
        {"a": "X", "b": "X", "c": "Y", "d": "Z"},
        rules=dict.fromkeys("abcd", RULE_TIME_CLUSTER),
    )
    precision, passes = time_cluster_verdict(result)
    assert precision < TIME_CLUSTER_THRESHOLD
    assert passes is False


def test_time_cluster_verdict_passes_at_or_above_threshold():
    result = build(
        {"a": "g1", "b": "g1", "c": "g1", "d": "g1"},
        {"a": "X", "b": "X", "c": "X", "d": "X"},
        rules=dict.fromkeys("abcd", RULE_TIME_CLUSTER),
    )
    precision, passes = time_cluster_verdict(result)
    assert precision == 1.0
    assert passes is True


def test_time_cluster_verdict_is_none_when_rule_never_fired():
    result = build({"a": "g1", "b": "g1"}, {"a": "X", "b": "X"})
    assert time_cluster_verdict(result) is None


def test_thresholds_are_the_pre_registered_values():
    assert TIME_CLUSTER_THRESHOLD == 0.70
    assert CALIBRATION_THRESHOLD == 0.95


def test_render_names_the_headline_metrics():
    text = render_evaluation(build({"a": "g1", "b": "g1"}, {"a": "X", "b": "X"}))
    assert "Precision" in text
    assert "Recall" in text
    assert "Calibration" in text
    assert "Declined coverage" in text


def test_render_warns_below_the_calibration_threshold():
    result = build(
        {"a": "g1", "b": "g1", "c": "g1", "d": "g1"},
        {"a": "X", "b": "X", "c": "Y", "d": "Z"},
    )
    assert result.confident_precision < CALIBRATION_THRESHOLD
    assert "WARNING" in render_evaluation(result)


def test_render_is_silent_above_the_calibration_threshold():
    text = render_evaluation(build({"a": "g1", "b": "g1"}, {"a": "X", "b": "X"}))
    assert "WARNING" not in text


def test_render_prints_a_computed_time_cluster_verdict():
    result = build(
        {"a": "g1", "b": "g1", "c": "g1", "d": "g1"},
        {"a": "X", "b": "X", "c": "Y", "d": "Z"},
        rules=dict.fromkeys("abcd", RULE_TIME_CLUSTER),
    )
    text = render_evaluation(result)
    assert "FAILS" in text
    assert "0.70" in text


def test_render_shows_per_rule_breakdown():
    result = build(
        {"a": "g1", "b": "g1"},
        {"a": "X", "b": "X"},
        rules=dict.fromkeys("ab", RULE_SENDER_MATCH),
    )
    assert RULE_SENDER_MATCH in render_evaluation(result)


def test_render_omits_hazard_split_when_unavailable():
    text = render_evaluation(build({"a": "g1", "b": "g1"}, {"a": "X", "b": "X"}))
    assert "hazard" not in text.lower()

from ledger.evaluate import render_evaluation, score
from ledger.models import UNGROUPABLE


def test_perfect_grouping_scores_one():
    predicted = {"a": "g1", "b": "g1", "c": "g2", "d": "g2"}
    truth = {"a": "X", "b": "X", "c": "Y", "d": "Y"}
    tiers = dict.fromkeys(predicted, "confident")

    result = score(predicted, truth, tiers)

    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.confident_accuracy == 1.0


def test_merging_two_true_groups_lowers_precision():
    # Everything predicted as one group, but half truly belongs elsewhere.
    predicted = {"a": "g1", "b": "g1", "c": "g1", "d": "g1"}
    truth = {"a": "X", "b": "X", "c": "Y", "d": "Y"}
    tiers = dict.fromkeys(predicted, "confident")

    result = score(predicted, truth, tiers)

    assert result.precision == 0.5


def test_uncategorized_transactions_lower_recall_but_not_precision():
    predicted = {"a": "g1", "b": "g1", "c": "uncategorized", "d": "uncategorized"}
    truth = {"a": "X", "b": "X", "c": "Y", "d": "Y"}
    tiers = {"a": "confident", "b": "confident", "c": "uncertain", "d": "uncertain"}

    result = score(predicted, truth, tiers)

    assert result.precision == 1.0
    assert result.recall == 0.5


def test_ungroupable_transactions_are_excluded_from_recall():
    predicted = {"a": "g1", "b": "g1", "c": "uncategorized"}
    truth = {"a": "X", "b": "X", "c": UNGROUPABLE}
    tiers = {"a": "confident", "b": "confident", "c": "uncertain"}

    result = score(predicted, truth, tiers)

    assert result.groupable_count == 2
    assert result.recall == 1.0


def test_calibration_separates_confident_from_uncertain_accuracy():
    predicted = {
        "a": "g1", "b": "g1",       # confident and correct
        "c": "g2", "d": "g2",       # uncertain and wrong (c and d differ in truth)
    }
    truth = {"a": "X", "b": "X", "c": "Y", "d": "Z"}
    tiers = {"a": "confident", "b": "confident", "c": "uncertain", "d": "uncertain"}

    result = score(predicted, truth, tiers)

    assert result.confident_accuracy == 1.0
    assert result.uncertain_accuracy == 0.5


def test_ungroupable_members_never_count_as_correct():
    # The cascade lumps two unrelated one-offs into a single cluster group.
    # Both are genuinely ungroupable, so this grouping is false and must not
    # be rewarded as correct — even though every member "agrees" with the
    # group's own (sentinel) majority label.
    predicted = {"a": "cluster:t1", "b": "cluster:t1"}
    truth = {"a": UNGROUPABLE, "b": UNGROUPABLE}
    tiers = {"a": "uncertain", "b": "uncertain"}

    result = score(predicted, truth, tiers)

    assert result.precision == 0.0


def test_empty_input_returns_zeros_without_dividing_by_zero():
    result = score({}, {}, {})
    assert result.precision == 0.0
    assert result.recall == 0.0
    assert result.confident_accuracy == 0.0


def test_render_names_all_three_metrics():
    predicted = {"a": "g1", "b": "g1"}
    truth = {"a": "X", "b": "X"}
    tiers = dict.fromkeys(predicted, "confident")

    text = render_evaluation(score(predicted, truth, tiers))

    assert "Precision" in text
    assert "Recall" in text
    assert "Calibration" in text


def test_render_warns_when_confidence_signal_is_meaningless():
    # Confident tier is no more accurate than the uncertain tier.
    predicted = {"a": "g1", "b": "g1", "c": "g2", "d": "g2"}
    truth = {"a": "X", "b": "Y", "c": "Z", "d": "W"}
    tiers = {"a": "confident", "b": "confident", "c": "uncertain", "d": "uncertain"}

    text = render_evaluation(score(predicted, truth, tiers))

    assert "warning" in text.lower()

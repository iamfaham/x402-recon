import pytest

from x402_recon.evaluate import (
    CALIBRATION_THRESHOLD,
    MIN_VERDICT_SAMPLE,
    AxisResults,
    EvaluationResult,
    RuleMetrics,
    render_axis_results,
    render_evaluation,
    score,
    service_confidence_verdict,
)
from x402_recon.models import (
    CONFIDENT,
    RULE_MEMO_MATCH,
    RULE_NONE,
    RULE_SENDER_MATCH,
    UNCATEGORIZED,
    UNCERTAIN,
    UNGROUPABLE,
)
from x402_recon.evaluate import failing_confident_rules, payer_confidence_verdict


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
            "c": RULE_MEMO_MATCH,
            "d": RULE_MEMO_MATCH,
        },
    )
    by_rule = {m.rule: m for m in result.per_rule}
    assert by_rule[RULE_SENDER_MATCH].precision == 1.0
    assert by_rule[RULE_MEMO_MATCH].precision == 0.5
    assert by_rule[RULE_MEMO_MATCH].count == 2


def test_hazard_split_separates_fragility_from_failure():
    result = build(
        {"a": "g1", "b": "g1", "c": "g2", "d": "g2"},
        {"a": "X", "b": "X", "c": "Y", "d": "Z"},
        rules=dict.fromkeys("abcd", RULE_MEMO_MATCH),
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


def test_thresholds_are_the_pre_registered_values():
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


def test_render_shows_n_a_not_zero_percent_for_an_empty_hazard_half():
    # I3: a 0.0% next to a zero count reads as "failed every case" when it
    # actually means "never tried" - neither fragile nor unearned.
    result = build(
        {"a": "g1", "b": "g1"},
        {"a": "X", "b": "X"},
        rules=dict.fromkeys("ab", RULE_SENDER_MATCH),
        hazards={"a": "some_hazard", "b": "some_hazard"},  # both hazard, none ordinary
    )
    text = render_evaluation(result)
    assert "ordinary" in text.lower()
    assert "n/a" in text
    assert "0.0%  (0)" not in text


def test_rule_metrics_carry_their_tier():
    result = build(
        {"a": "g1", "b": "g1"},
        {"a": "X", "b": "X"},
        tiers={"a": CONFIDENT, "b": CONFIDENT},
        rules={"a": RULE_SENDER_MATCH, "b": RULE_SENDER_MATCH},
    )
    assert result.per_rule[0].tier == CONFIDENT


def test_a_diluted_bad_rule_is_caught_per_rule():
    # THE REGRESSION GUARD FOR THIS RELEASE.
    #
    # Under the old AGGREGATE gate this passed silently: one large rule at 100%
    # precision outvoted a small one at ~70%, the confident tier averaged above
    # 0.95, and nothing warned. That averaging is the hole - not the particular
    # rule that fell through it. A per-rule floor cannot be diluted.
    #
    # CONTROLLER RULING: uses range(30), not range(20) as originally drafted.
    # (30 + 1.667)/33 = 0.9596 clears CALIBRATION_THRESHOLD while the memo
    # rule sits at 0.5556 - so the aggregate genuinely passes while the
    # per-rule floor genuinely catches it. With range(20) the aggregate
    # itself would fail (0.9420 < 0.95), demonstrating nothing about
    # dilution.
    predicted = {f"s{i}": "big" for i in range(30)}
    truth = {f"s{i}": "X" for i in range(30)}
    tiers = {f"s{i}": CONFIDENT for i in range(30)}
    rules = {f"s{i}": RULE_SENDER_MATCH for i in range(30)}

    # A small confident rule that merges two unrelated payers.
    predicted |= {"m1": "small", "m2": "small", "m3": "small"}
    truth |= {"m1": "Y", "m2": "Y", "m3": "Z"}
    tiers |= {k: CONFIDENT for k in ("m1", "m2", "m3")}
    rules |= {k: RULE_MEMO_MATCH for k in ("m1", "m2", "m3")}

    result = score(predicted, truth, tiers, rules)

    assert result.confident_precision >= CALIBRATION_THRESHOLD  # aggregate passes
    failing = failing_confident_rules(result)
    assert [m.rule for m in failing] == [RULE_MEMO_MATCH]


def test_non_confident_rules_are_never_flagged_by_the_floor():
    # failing_confident_rules only warns about rules tiered CONFIDENT. A rule
    # whose rows are tiered UNCERTAIN was never claiming confidence, so a
    # threshold it was never asked to clear must not warn about it.
    result = build(
        {"a": "g1", "b": "g1", "c": "g1"},
        {"a": "X", "b": "Y", "c": "Z"},
        tiers=dict.fromkeys("abc", UNCERTAIN),
        rules=dict.fromkeys("abc", RULE_MEMO_MATCH),
    )
    assert result.per_rule[0].precision < CALIBRATION_THRESHOLD
    assert failing_confident_rules(result) == []


def test_render_warns_naming_the_failing_rule():
    # CONTROLLER RULING: uses range(30), see test_a_diluted_bad_rule_is_caught_per_rule.
    predicted = {f"s{i}": "big" for i in range(30)}
    truth = {f"s{i}": "X" for i in range(30)}
    tiers = {f"s{i}": CONFIDENT for i in range(30)}
    rules = {f"s{i}": RULE_SENDER_MATCH for i in range(30)}
    predicted |= {"m1": "small", "m2": "small", "m3": "small"}
    truth |= {"m1": "Y", "m2": "Y", "m3": "Z"}
    tiers |= {k: CONFIDENT for k in ("m1", "m2", "m3")}
    rules |= {k: RULE_MEMO_MATCH for k in ("m1", "m2", "m3")}

    text = render_evaluation(score(predicted, truth, tiers, rules))
    assert "WARNING" in text
    assert RULE_MEMO_MATCH in text


# --- I1: claims_confidence / render_axis_results ---------------------------


def test_render_evaluation_omits_calibration_when_claims_confidence_is_false():
    result = build({"a": "g1", "b": "g1"}, {"a": "X", "b": "X"})
    text = render_evaluation(result, claims_confidence=False)
    assert "Calibration" not in text
    assert "Confident tier precision" not in text


def test_render_evaluation_still_shows_calibration_by_default():
    result = build({"a": "g1", "b": "g1"}, {"a": "X", "b": "X"})
    text = render_evaluation(result)
    assert "Calibration" in text
    assert "Confident tier precision" in text


def test_render_axis_results_shows_both_axis_headers_and_both_calibrations():
    # v0.1c: the service axis earned its confidence claim (memo_match cleared
    # the calibration floor at the canonical count), so it now carries a
    # calibration section just like the payer axis.
    payer = build({"a": "g1", "b": "g1"}, {"a": "X", "b": "X"})
    service = build({"a": "s1", "b": "s1"}, {"a": "S", "b": "S"})
    text = render_axis_results(AxisResults(payer=payer, service=service))

    assert "Who paid you" in text
    assert "What they paid for" in text

    service_block = text.split("What they paid for", 1)[1]
    assert "Calibration" in service_block
    assert "Confident tier precision" in service_block

    payer_block = text.split("What they paid for", 1)[0]
    assert "Calibration" in payer_block
    assert "Confident tier precision" in payer_block


def test_render_axis_results_reports_service_axis_unscored_when_none():
    payer = build({"a": "g1", "b": "g1"}, {"a": "X", "b": "X"})
    text = render_axis_results(AxisResults(payer=payer, service=None))
    assert "service groupings are unscored" in text.lower()


# --- Task 2: service_confidence_verdict / service recall wording -----------


def _memo_result(predicted, truth):
    # memo_match rows are tiered CONFIDENT now that the service axis has
    # earned its confidence claim (v0.1c).
    return score(
        predicted,
        truth,
        dict.fromkeys(predicted, CONFIDENT),
        dict.fromkeys(predicted, RULE_MEMO_MATCH),
    )


def test_service_verdict_passes_at_or_above_the_floor():
    # 25 payments, all grouped correctly -> precision 1.0.
    predicted = {f"s{i}": "svc" for i in range(25)}
    truth = {f"s{i}": "X" for i in range(25)}

    verdict = service_confidence_verdict(_memo_result(predicted, truth))

    assert verdict is not None
    precision, count, passes = verdict
    assert precision == 1.0
    assert count == 25
    assert passes is True


def test_service_verdict_fails_below_the_floor():
    # 24 correct plus one merged stranger drags precision under 0.95.
    predicted = {f"s{i}": "svc" for i in range(24)}
    truth = {f"s{i}": "X" for i in range(24)}
    predicted["odd"] = "svc"
    truth["odd"] = "Y"

    verdict = service_confidence_verdict(_memo_result(predicted, truth))

    assert verdict is not None
    precision, count, passes = verdict
    assert precision < CALIBRATION_THRESHOLD
    assert count == 25
    assert passes is False


def test_service_verdict_withholds_below_the_minimum_sample():
    # Perfect precision, but too few firings for the number to mean anything.
    predicted = {f"s{i}": "svc" for i in range(5)}
    truth = {f"s{i}": "X" for i in range(5)}

    verdict = service_confidence_verdict(_memo_result(predicted, truth))

    assert verdict is not None
    precision, count, passes = verdict
    assert precision == 1.0
    assert count == 5
    assert passes is False  # withheld: sample below MIN_VERDICT_SAMPLE


def test_service_verdict_is_none_when_memo_match_never_fired():
    predicted = {"a": UNCATEGORIZED}
    truth = {"a": UNGROUPABLE}
    result = score(
        predicted,
        truth,
        {"a": UNCERTAIN},
        {"a": "none"},
    )
    assert service_confidence_verdict(result) is None


def test_service_axis_recall_description_says_service():
    # This figure sits in the section whose whole point is that it does NOT
    # answer a payer question. `subject` is now explicit, since both axes
    # claim confidence and claims_confidence no longer distinguishes them.
    result = _memo_result({"a": "svc", "b": "svc"}, {"a": "X", "b": "X"})
    text = render_evaluation(result, subject="service")
    assert "from one service" in text
    assert "from one payer" not in text


# --- Item 1: pre-registered criterion line, via render_axis_results --------
#
# Mirrors the shape of the deleted v0.1b tests
# (test_render_prints_a_computed_time_cluster_verdict,
# test_render_withholds_verdict_below_the_minimum_sample,
# test_render_prints_verdict_at_exactly_the_minimum_sample), but asserts on
# render_axis_results so the subject="service" wiring is covered end-to-end,
# not just service_confidence_verdict in isolation.


def test_render_axis_results_prints_earns_at_or_above_the_floor():
    # Scoped to the service section: the payer axis now also renders its own
    # pre-registered criterion (Task 6), and a 2-payment payer fixture falls
    # below MIN_VERDICT_SAMPLE, so unscoped assertions on the full text would
    # be satisfied by payer's INSUFFICIENT DATA / non-EARNS wording too. This
    # test is about the service verdict specifically, so it must only look at
    # the service section - see
    # test_render_axis_results_shows_both_axis_headers_and_both_calibrations
    # above for the same split-on-header pattern.
    payer = build({"a": "g1", "b": "g1"}, {"a": "X", "b": "X"})
    predicted = {f"s{i}": "svc" for i in range(25)}
    truth = {f"s{i}": "X" for i in range(25)}
    service = _memo_result(predicted, truth)

    text = render_axis_results(AxisResults(payer=payer, service=service))
    service_block = text.split("What they paid for", 1)[1]

    assert "EARNS" in service_block
    assert "DOES NOT EARN" not in service_block
    assert "0.95" in service_block


def test_render_axis_results_prints_does_not_earn_below_the_floor():
    # Scoped to the service section - see comment above.
    payer = build({"a": "g1", "b": "g1"}, {"a": "X", "b": "X"})
    predicted = {f"s{i}": "svc" for i in range(24)}
    truth = {f"s{i}": "X" for i in range(24)}
    predicted["odd"] = "svc"
    truth["odd"] = "Y"
    service = _memo_result(predicted, truth)

    text = render_axis_results(AxisResults(payer=payer, service=service))
    service_block = text.split("What they paid for", 1)[1]

    assert "DOES NOT EARN" in service_block


def test_render_axis_results_withholds_verdict_below_the_minimum_sample():
    # Scoped to the service section - see comment above. Without the split,
    # the payer axis's own 2-payment fixture (below MIN_VERDICT_SAMPLE)
    # satisfies all three assertions on its own, so this test would pass
    # even if the service withholding branch were deleted entirely.
    payer = build({"a": "g1", "b": "g1"}, {"a": "X", "b": "X"})
    predicted = {f"s{i}": "svc" for i in range(5)}
    truth = {f"s{i}": "X" for i in range(5)}
    service = _memo_result(predicted, truth)

    text = render_axis_results(AxisResults(payer=payer, service=service))
    service_block = text.split("What they paid for", 1)[1]

    assert "INSUFFICIENT DATA" in service_block
    assert f"need {MIN_VERDICT_SAMPLE}" in service_block
    assert "EARNS" not in service_block


# --- Task 6: payer_confidence_verdict / pre-registered payer criterion -----
#
# Pre-registered BEFORE any real labeled data exists for the payer axis - see
# the v0.2 spec. Mirrors service_confidence_verdict exactly, with
# sender_match in place of memo_match. These helpers build synthetic
# EvaluationResult objects directly (rather than routing arbitrary target
# precisions through score(), which can only land on fractions score()'s
# group arithmetic happens to produce) since only the resulting .precision,
# .count, and threshold-crossing behaviour are under test here, not B-cubed
# arithmetic itself - that is already covered above.


def _result_with_rule(rule: str, precision: float, count: int) -> EvaluationResult:
    metrics = RuleMetrics(
        rule=rule,
        tier=CONFIDENT,
        count=count,
        precision=precision,
        recall=1.0,
        hazard_count=0,
        hazard_precision=0.0,
        ordinary_count=count,
        ordinary_precision=precision,
    )
    return EvaluationResult(
        precision=precision,
        recall=1.0,
        confident_precision=precision,
        confident_count=count,
        declined_recall=0.0,
        declined_count=0,
        transaction_count=count,
        hazards_available=False,
        per_rule=[metrics],
    )


def _axis_results_with_payer(precision: float, count: int) -> AxisResults:
    return AxisResults(
        payer=_result_with_rule(RULE_SENDER_MATCH, precision, count),
        service=None,
    )


def test_payer_verdict_earns_at_or_above_the_floor():
    result = _result_with_rule(RULE_SENDER_MATCH, precision=0.96, count=25)
    precision, count, earns = payer_confidence_verdict(result)
    assert count == 25
    assert earns is True


def test_payer_verdict_does_not_earn_below_the_floor():
    result = _result_with_rule(RULE_SENDER_MATCH, precision=0.94, count=25)
    _, _, earns = payer_confidence_verdict(result)
    assert earns is False


def test_payer_verdict_is_none_when_sender_match_never_fired():
    result = _result_with_rule(RULE_NONE, precision=1.0, count=10)
    assert payer_confidence_verdict(result) is None


def test_payer_criterion_reuses_the_existing_floor_and_sample_bar():
    # No new number is invented this release. If either of these changes, the
    # criterion silently stops being the one the spec pre-registered.
    assert CALIBRATION_THRESHOLD == 0.95
    assert MIN_VERDICT_SAMPLE == 20


def test_render_axis_results_prints_the_payer_criterion_above_the_bar():
    rendered = render_axis_results(_axis_results_with_payer(precision=0.96, count=25))
    assert "Pre-registered criterion: sender_match" in rendered
    assert "EARNS" in rendered
    assert "0.95" in rendered


def test_render_axis_results_prints_payer_does_not_earn_below_the_floor():
    # Named with the payer- prefix to avoid shadowing
    # test_render_axis_results_prints_does_not_earn_below_the_floor above,
    # which covers the same wording for the service axis - two module-level
    # functions with the same name would silently drop one from collection.
    rendered = render_axis_results(_axis_results_with_payer(precision=0.90, count=25))
    assert "DOES NOT EARN" in rendered


def test_render_axis_results_withholds_below_the_minimum_sample():
    rendered = render_axis_results(_axis_results_with_payer(precision=0.99, count=12))
    assert "INSUFFICIENT DATA" in rendered
    assert "need 20" in rendered

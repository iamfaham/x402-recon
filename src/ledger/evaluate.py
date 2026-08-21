"""Accuracy scoring for the cascade, using B-cubed.

Ground truth is an INPUT, never an assumption. Real data arrives unlabeled;
the same scorer then runs against a hand-labeled sample instead.

Predicted labels never equal truth labels by string, so scoring compares
cluster agreement. B-cubed asks, per transaction:

  precision - of the payments grouped WITH me, how many belong with me
  recall    - of the payments that belong with me, how many got grouped with me

This replaces majority-vote purity, which punished merging two payers but
rewarded splitting one payer across several groups - asymmetric in our favour.

Ungroupable transactions need no special case. Treat each as its own true
group of one, and each uncategorized transaction as its own predicted group of
one, and the right behavior falls out: correctly declining to guess scores
perfectly, while sweeping a stranger into a cluster is heavily penalized.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from ledger.models import (
    AXIS_PAYER,
    AXIS_SERVICE,
    CONFIDENT,
    RULE_MEMO_MATCH,
    UNCATEGORIZED,
    UNGROUPABLE,
)

# Pre-registered in docs/superpowers/specs/2026-08-19-ledger-v0.1a-design.md
# and fixed on 2026-08-19, BEFORE any measurement was taken. It is a constant
# rather than a judgment call precisely so the result cannot be rationalized
# once the number is known. Do not adjust it to fit an outcome.
CALIBRATION_THRESHOLD = 0.95

# A verdict needs evidence. Below this many scored transactions the rule's
# precision is a coin-flip artifact, so the criterion withholds judgment
# rather than asserting one. This gate can only ever WITHHOLD a verdict,
# never manufacture a favourable one - the 0.70 threshold above is
# untouched and stays exactly as pre-registered.
MIN_VERDICT_SAMPLE = 20


@dataclass(frozen=True)
class RuleMetrics:
    """How one cascade rule performed, split by hazard exposure.

    The split separates fragility from failure: a rule that stumbles only on
    hazard cases works but is brittle, while one that also fails on ordinary
    traffic is not earning its place.
    """

    rule: str
    tier: str
    count: int
    precision: float
    recall: float
    hazard_count: int
    hazard_precision: float
    ordinary_count: int
    ordinary_precision: float


@dataclass(frozen=True)
class EvaluationResult:
    """How well the cascade did, and whether its confidence means anything."""

    precision: float
    recall: float
    confident_precision: float
    confident_count: int
    declined_recall: float
    declined_count: int
    transaction_count: int
    hazards_available: bool
    per_rule: list[RuleMetrics]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _expand_singletons(mapping: dict[str, str], sentinel: str) -> dict[str, str]:
    """Give every sentinel-labelled item a group of its own.

    An uncategorized transaction claims nothing, and an ungroupable one belongs
    with nothing. Both are singletons, so B-cubed scores them without any
    special-casing in the metric itself.
    """
    return {
        key: (f"{sentinel}:{key}" if value == sentinel else value)
        for key, value in mapping.items()
    }


def score(
    predicted: dict[str, str],
    truth: dict[str, str],
    tiers: dict[str, str],
    rules: dict[str, str],
    hazards: dict[str, str] | None = None,
) -> EvaluationResult:
    """Score predictions against ground truth. All dicts keyed by tx_hash."""
    scored = [h for h in predicted if h in truth]
    pred = _expand_singletons(
        {h: predicted[h] for h in scored}, UNCATEGORIZED
    )
    true = _expand_singletons({h: truth[h] for h in scored}, UNGROUPABLE)

    pred_members: dict[str, set[str]] = defaultdict(set)
    true_members: dict[str, set[str]] = defaultdict(set)
    for h, label in pred.items():
        pred_members[label].add(h)
    for h, group in true.items():
        true_members[group].add(h)

    precision: dict[str, float] = {}
    recall: dict[str, float] = {}
    for h in scored:
        shared = len(pred_members[pred[h]] & true_members[true[h]])
        precision[h] = shared / len(pred_members[pred[h]])
        recall[h] = shared / len(true_members[true[h]])

    hazard_tags = hazards or {}
    per_rule = []
    for rule in sorted({rules.get(h, "none") for h in scored}):
        members = [h for h in scored if rules.get(h, "none") == rule]
        hazardous = [h for h in members if h in hazard_tags]
        ordinary = [h for h in members if h not in hazard_tags]
        member_tiers = {tiers.get(h) for h in members}
        rule_tier = member_tiers.pop() if len(member_tiers) == 1 else CONFIDENT
        per_rule.append(
            RuleMetrics(
                rule=rule,
                tier=rule_tier,
                count=len(members),
                precision=_mean([precision[h] for h in members]),
                recall=_mean([recall[h] for h in members]),
                hazard_count=len(hazardous),
                hazard_precision=_mean([precision[h] for h in hazardous]),
                ordinary_count=len(ordinary),
                ordinary_precision=_mean([precision[h] for h in ordinary]),
            )
        )

    confident = [h for h in scored if tiers.get(h) == CONFIDENT]
    declined = [h for h in scored if predicted[h] == UNCATEGORIZED]

    return EvaluationResult(
        precision=_mean([precision[h] for h in scored]),
        recall=_mean([recall[h] for h in scored]),
        confident_precision=_mean([precision[h] for h in confident]),
        confident_count=len(confident),
        declined_recall=_mean([recall[h] for h in declined]),
        declined_count=len(declined),
        transaction_count=len(scored),
        hazards_available=bool(hazard_tags),
        per_rule=per_rule,
    )


def service_confidence_verdict(
    result: EvaluationResult,
) -> tuple[float, int, bool] | None:
    """Apply the pre-registered service criterion. None when memo_match never fired.

    Returns (measured B-cubed precision, firing count, whether it earns a
    confidence claim).

    The criterion reuses CALIBRATION_THRESHOLD rather than inventing a number:
    a rule that could not survive the floor it would then be subject to has no
    business claiming confidence in the first place. Withholds below
    MIN_VERDICT_SAMPLE - a precision computed over a handful of rows is a coin
    flip, and withholding can only ever deny a claim, never manufacture one.
    """
    for metrics in result.per_rule:
        if metrics.rule == RULE_MEMO_MATCH:
            earns = (
                metrics.count >= MIN_VERDICT_SAMPLE
                and metrics.precision >= CALIBRATION_THRESHOLD
            )
            return metrics.precision, metrics.count, earns
    return None


def failing_confident_rules(result: EvaluationResult) -> list[RuleMetrics]:
    """Confident rules whose own precision falls below the threshold.

    The gate is per-rule rather than an average across the confident tier. An
    aggregate lets one large accurate rule dilute a small inaccurate one until
    the tier passes while a rule inside it is wrong a third of the time. The
    averaging is the hole, so the fix removes the averaging.

    Descriptive rules are excluded. They claim no confidence, and a threshold
    they were never asked to clear cannot meaningfully warn about them.
    """
    return [
        metrics
        for metrics in result.per_rule
        if metrics.tier == CONFIDENT
        and metrics.count
        and metrics.precision < CALIBRATION_THRESHOLD
    ]


@dataclass(frozen=True)
class AxisResults:
    """One scoring result per axis. Service is None when its truth is absent."""

    payer: EvaluationResult
    service: EvaluationResult | None


def _score_axis(conn, axis: str, truth: dict[str, str], hazards) -> EvaluationResult:
    rows = conn.execute(
        """SELECT t.tx_hash, c.category_label, c.confidence_tier, c.rule_matched
           FROM transactions t
           JOIN categorizations c
             ON c.transaction_id = t.id AND c.axis = ?""",
        (axis,),
    ).fetchall()
    return score(
        predicted={row["tx_hash"]: row["category_label"] for row in rows},
        truth=truth,
        tiers={row["tx_hash"]: row["confidence_tier"] for row in rows},
        rules={row["tx_hash"]: row["rule_matched"] for row in rows},
        hazards=hazards,
    )


def run_evaluate(conn: sqlite3.Connection) -> AxisResults | None:
    """Score both axes. Returns None when payer ground truth is absent."""
    payer_rows = conn.execute("SELECT tx_hash, true_group FROM ground_truth").fetchall()
    if not payer_rows:
        return None
    payer_truth = {row["tx_hash"]: row["true_group"] for row in payer_rows}

    hazards = {
        row["tx_hash"]: row["hazard"]
        for row in conn.execute("SELECT tx_hash, hazard FROM hazards").fetchall()
    } or None

    service_rows = conn.execute(
        "SELECT tx_hash, true_service FROM service_truth"
    ).fetchall()
    service_truth = {row["tx_hash"]: row["true_service"] for row in service_rows}

    return AxisResults(
        payer=_score_axis(conn, AXIS_PAYER, payer_truth, hazards),
        service=(
            _score_axis(conn, AXIS_SERVICE, service_truth, hazards)
            if service_truth
            else None
        ),
    )


def _render_evaluation_body(result: EvaluationResult, claims_confidence: bool) -> list[str]:
    """Metrics, calibration (when claimed), per-rule breakdown, and verdict.

    Split out from `render_evaluation` so `render_axis_results` can render the
    service axis's body without also repeating the "Categorization accuracy
    (B-cubed)" banner underneath its own "What they paid for" section header.
    """
    subject = "payer" if claims_confidence else "service"
    lines = [
        f"Precision:   {result.precision:.1%}"
        f"   (of the payments grouped together, how many belonged together)",
        f"Recall:      {result.recall:.1%}"
        f"   (of the payments from one {subject}, how many were found)",
        f"             scored over {result.transaction_count} payments",
    ]

    if claims_confidence:
        lines += [
            "",
            "Calibration - does 'confident' actually mean confident?",
            f"  Confident tier precision: {result.confident_precision:.1%}"
            f"  ({result.confident_count} payments,"
            f" threshold {CALIBRATION_THRESHOLD:.0%})",
            f"  Declined coverage:        {result.declined_recall:.1%}"
            f"  ({result.declined_count} payments left uncategorized)",
        ]

    failing = failing_confident_rules(result)
    if failing:
        lines.append("")
        lines.append(
            "  WARNING: these confident rules fall below the calibration threshold."
        )
        lines.append(
            "  The tool is claiming more certainty than it has earned on them:"
        )
        for metrics in failing:
            lines.append(
                f"    {metrics.rule}: {metrics.precision:.1%}"
                f" over {metrics.count} payments"
                f" (threshold {CALIBRATION_THRESHOLD:.0%})"
            )

    lines += ["", "Per rule", "--------"]
    for metrics in result.per_rule:
        lines.append(
            f"  {metrics.rule:<14} precision {metrics.precision:6.1%}"
            f"   recall {metrics.recall:6.1%}   ({metrics.count} payments)"
        )
        if result.hazards_available and metrics.count:
            hazard_str = (
                f"{metrics.hazard_precision:6.1%}"
                if metrics.hazard_count
                else f"{'n/a':>6}"
            )
            ordinary_str = (
                f"{metrics.ordinary_precision:6.1%}"
                if metrics.ordinary_count
                else f"{'n/a':>6}"
            )
            lines.append(
                f"    {'hazard cases':<16} {hazard_str}"
                f"  ({metrics.hazard_count})"
                f"    {'ordinary':<10} {ordinary_str}"
                f"  ({metrics.ordinary_count})"
            )

    if not claims_confidence:
        service = service_confidence_verdict(result)
        if service is not None:
            precision, count, earns = service
            if count < MIN_VERDICT_SAMPLE:
                lines += [
                    "",
                    f"Pre-registered criterion: memo_match B-cubed precision "
                    f"{precision:.1%} on {count} payments - "
                    f"INSUFFICIENT DATA (need {MIN_VERDICT_SAMPLE}) - "
                    "no confidence claim",
                ]
            else:
                outcome = "EARNS" if earns else "DOES NOT EARN"
                lines += [
                    "",
                    f"Pre-registered criterion: memo_match B-cubed precision "
                    f"{precision:.1%} on {count} payments - {outcome} a "
                    f"confidence claim (threshold "
                    f"{CALIBRATION_THRESHOLD:.2f})",
                ]

    return lines


def render_evaluation(result: EvaluationResult, claims_confidence: bool = True) -> str:
    """Render the banner, metrics, per-rule breakdown, and computed verdict.

    `claims_confidence` controls whether the calibration block is shown at
    all. A rule tier that claims no confidence (the service axis's
    `memo_match`/`none`) has no calibration floor to be measured against, so
    printing a 0.0% figure beside a zero count there reads as failure when it
    means the section was never asked to clear a bar in the first place.
    """
    lines = [
        "Categorization accuracy (B-cubed)",
        "=================================",
        "",
    ]
    lines += _render_evaluation_body(result, claims_confidence)
    return "\n".join(lines)


def render_axis_results(results: AxisResults) -> str:
    """Render both axes, or just the payer axis when service truth is absent."""
    text = ["Who paid you", "============", "", render_evaluation(results.payer)]
    if results.service is None:
        text += [
            "",
            "What they paid for",
            "==================",
            "",
            "No service ground truth supplied, so service groupings are unscored.",
        ]
    else:
        text += [
            "",
            "What they paid for",
            "==================",
            "",
            "These groupings describe what was bought, not who bought it, and",
            "claim no confidence. The figures below say how well grouping by the",
            "payer's memo matches the services actually purchased.",
            "",
        ]
        # No nested "Categorization accuracy (B-cubed)" banner here: the
        # section header above already names the axis, so repeating it would
        # be a duplicated, redundant heading.
        text += _render_evaluation_body(results.service, claims_confidence=False)
    return "\n".join(text)

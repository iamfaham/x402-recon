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
    CONFIDENT,
    RULE_TIME_CLUSTER,
    UNCATEGORIZED,
    UNGROUPABLE,
)

# Pre-registered in docs/superpowers/specs/2026-08-19-ledger-v0.1a-design.md
# and fixed on 2026-08-19, BEFORE any measurement was taken. They are constants
# rather than judgment calls precisely so the result cannot be rationalized
# once the number is known. Do not adjust them to fit an outcome.
TIME_CLUSTER_THRESHOLD = 0.70
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
        per_rule.append(
            RuleMetrics(
                rule=rule,
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


def time_cluster_verdict(result: EvaluationResult) -> tuple[float, bool] | None:
    """Apply the pre-registered criterion. None when the rule never fired.

    Returns (measured B-cubed precision, whether it clears the threshold).
    """
    for metrics in result.per_rule:
        if metrics.rule == RULE_TIME_CLUSTER:
            return metrics.precision, metrics.precision >= TIME_CLUSTER_THRESHOLD
    return None


def run_evaluate(conn: sqlite3.Connection) -> EvaluationResult | None:
    """Score stored categorizations. Returns None when ground truth is absent."""
    truth_rows = conn.execute("SELECT tx_hash, true_group FROM ground_truth").fetchall()
    if not truth_rows:
        return None
    truth = {row["tx_hash"]: row["true_group"] for row in truth_rows}

    rows = conn.execute(
        """SELECT t.tx_hash, c.category_label, c.confidence_tier, c.rule_matched
           FROM transactions t
           JOIN categorizations c ON c.transaction_id = t.id"""
    ).fetchall()

    hazards = {
        row["tx_hash"]: row["hazard"]
        for row in conn.execute("SELECT tx_hash, hazard FROM hazards").fetchall()
    }

    return score(
        predicted={row["tx_hash"]: row["category_label"] for row in rows},
        truth=truth,
        tiers={row["tx_hash"]: row["confidence_tier"] for row in rows},
        rules={row["tx_hash"]: row["rule_matched"] for row in rows},
        hazards=hazards or None,
    )


def render_evaluation(result: EvaluationResult) -> str:
    """Render the metrics, the per-rule breakdown, and the computed verdict."""
    lines = [
        "Categorization accuracy (B-cubed)",
        "=================================",
        "",
        f"Precision:   {result.precision:.1%}"
        f"   (of the payments grouped together, how many belonged together)",
        f"Recall:      {result.recall:.1%}"
        f"   (of the payments from one payer, how many were found)",
        f"             scored over {result.transaction_count} payments",
        "",
        "Calibration - does 'confident' actually mean confident?",
        f"  Confident tier precision: {result.confident_precision:.1%}"
        f"  ({result.confident_count} payments,"
        f" threshold {CALIBRATION_THRESHOLD:.0%})",
        f"  Declined coverage:        {result.declined_recall:.1%}"
        f"  ({result.declined_count} payments left uncategorized)",
    ]

    if (
        result.confident_count
        and result.confident_precision < CALIBRATION_THRESHOLD
    ):
        lines += [
            "",
            "  WARNING: confident groupings fall below the calibration threshold.",
            "  The tool is claiming more certainty than it has earned - treat",
            "  confident groupings as unverified until the cascade is retuned.",
        ]

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

    verdict = time_cluster_verdict(result)
    if verdict is not None:
        precision, passes = verdict
        count = next(
            (m.count for m in result.per_rule if m.rule == RULE_TIME_CLUSTER), 0
        )
        if count < MIN_VERDICT_SAMPLE:
            lines += [
                "",
                f"Pre-registered criterion: time_cluster B-cubed precision "
                f"{precision:.1%} on {count} payments - "
                f"INSUFFICIENT DATA (need {MIN_VERDICT_SAMPLE}) - "
                "no verdict recorded",
            ]
        else:
            outcome = "PASSES" if passes else "FAILS"
            lines += [
                "",
                f"Pre-registered criterion: time_cluster B-cubed precision "
                f"{precision:.1%} on {count} payments - {outcome} threshold "
                f"{TIME_CLUSTER_THRESHOLD:.2f}",
            ]

    return "\n".join(lines)

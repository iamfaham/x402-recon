"""Accuracy scoring for the cascade.

Ground truth is an INPUT, never an assumption. Real data arrives unlabeled; when
that happens the same scorer runs against a hand-labeled sample instead, and the
simulated run becomes a regression check.

Predicted labels never equal truth labels by string, so scoring compares cluster
agreement: each predicted group is mapped to the majority true group among its
members, and a transaction is correct when its true group matches.
"""

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass

from ledger.categorize import CONFIDENT, UNCATEGORIZED
from ledger.simulate import UNGROUPABLE


@dataclass(frozen=True)
class EvaluationResult:
    """How well the cascade did, and whether its confidence means anything."""

    precision: float
    recall: float
    confident_accuracy: float
    uncertain_accuracy: float
    grouped_count: int
    groupable_count: int
    confident_count: int
    uncertain_count: int


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def score(
    predicted: dict[str, str],
    truth: dict[str, str],
    tiers: dict[str, str],
) -> EvaluationResult:
    """Score predictions against ground truth. All dicts keyed by tx_hash."""
    grouped = {
        tx_hash: label
        for tx_hash, label in predicted.items()
        if label != UNCATEGORIZED and tx_hash in truth
    }

    members: dict[str, list[str]] = defaultdict(list)
    for tx_hash, label in grouped.items():
        members[label].append(tx_hash)

    majority: dict[str, str] = {
        label: Counter(truth[h] for h in hashes).most_common(1)[0][0]
        for label, hashes in members.items()
    }

    correct = {
        tx_hash
        for tx_hash, label in grouped.items()
        if truth[tx_hash] == majority[label]
    }

    groupable = {h for h, t in truth.items() if t != UNGROUPABLE}
    confident = [h for h, tier in tiers.items() if tier == CONFIDENT and h in grouped]
    uncertain = [h for h, tier in tiers.items() if tier != CONFIDENT and h in grouped]

    return EvaluationResult(
        precision=_ratio(len(correct), len(grouped)),
        recall=_ratio(len(correct & groupable), len(groupable)),
        confident_accuracy=_ratio(
            sum(1 for h in confident if h in correct), len(confident)
        ),
        uncertain_accuracy=_ratio(
            sum(1 for h in uncertain if h in correct), len(uncertain)
        ),
        grouped_count=len(grouped),
        groupable_count=len(groupable),
        confident_count=len(confident),
        uncertain_count=len(uncertain),
    )


def run_evaluate(conn: sqlite3.Connection) -> EvaluationResult | None:
    """Score stored categorizations. Returns None when ground truth is absent."""
    truth_rows = conn.execute("SELECT tx_hash, true_group FROM ground_truth").fetchall()
    if not truth_rows:
        return None
    truth = {row["tx_hash"]: row["true_group"] for row in truth_rows}

    rows = conn.execute(
        """SELECT t.tx_hash, c.category_label, c.confidence_tier
           FROM transactions t
           JOIN categorizations c ON c.transaction_id = t.id"""
    ).fetchall()

    predicted = {row["tx_hash"]: row["category_label"] for row in rows}
    tiers = {row["tx_hash"]: row["confidence_tier"] for row in rows}
    return score(predicted, truth, tiers)


def render_evaluation(result: EvaluationResult) -> str:
    """Render the metrics, with a warning when confidence carries no signal."""
    lines = [
        "Categorization accuracy",
        "=======================",
        "",
        f"Precision:   {result.precision:.1%}"
        f"   (of {result.grouped_count} grouped payments, how many landed in the right group)",
        f"Recall:      {result.recall:.1%}"
        f"   (of {result.groupable_count} groupable payments, how many we caught correctly)",
        "",
        "Calibration — does 'confident' actually mean confident?",
        f"  Confident tier accuracy: {result.confident_accuracy:.1%}"
        f"  ({result.confident_count} payments)",
        f"  Uncertain tier accuracy: {result.uncertain_accuracy:.1%}"
        f"  ({result.uncertain_count} payments)",
    ]

    if result.confident_count and result.confident_accuracy <= result.uncertain_accuracy:
        lines += [
            "",
            "  WARNING: the confident tier is no more accurate than the uncertain",
            "  tier. The confidence signal is not meaningful — treat confident",
            "  groupings as unverified until the cascade is retuned.",
        ]

    return "\n".join(lines)

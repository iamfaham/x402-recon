"""Reporting: the output a business owner actually reads.

Uncategorized money always appears as its own line with its own total. It is
never hidden or folded into an "other" bucket — "$X is unaccounted for" is the
number their accountant will ask about first.

This module organizes data. It does not advise on tax or accounting treatment.
"""

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from x402_recon.models import (
    AXIS_PAYER,
    AXIS_SERVICE,
    CONFIDENT,
    RULE_NONE,
    TX_TYPE_PAYMENT,
    TX_TYPE_REFUND,
    UNCATEGORIZED,
    UNCERTAIN,
)
from x402_recon.money import exact_net_footer, format_usdc_rounded, micro_to_decimal
from x402_recon.privacy import shorten_address


def _payments(count: int) -> str:
    """Pluralize the payment count so a lone entry reads as "1 payment"."""
    return "payment" if count == 1 else "payments"


def _refunds(count: int) -> str:
    """Pluralize the refund count so a lone entry reads as "1 refund"."""
    return "refund" if count == 1 else "refunds"

_SELECT_IN_RANGE = f"""
SELECT t.tx_hash, t.timestamp, t.sender_address, t.memo, t.amount_micro_usdc,
       t.tx_type,
       COALESCE(p.category_label, '{UNCATEGORIZED}')  AS payer_label,
       COALESCE(p.confidence_tier, '{UNCERTAIN}')     AS payer_tier,
       COALESCE(p.rule_matched, '{RULE_NONE}')        AS payer_rule,
       COALESCE(s.category_label, '{UNCATEGORIZED}')  AS service_label,
       COALESCE(s.confidence_tier, '{UNCERTAIN}')     AS service_tier,
       COALESCE(s.rule_matched, '{RULE_NONE}')        AS service_rule
FROM transactions t
LEFT JOIN categorizations p
       ON p.transaction_id = t.id AND p.axis = '{AXIS_PAYER}'
LEFT JOIN categorizations s
       ON s.transaction_id = t.id AND s.axis = '{AXIS_SERVICE}'
WHERE t.timestamp >= ? AND t.timestamp <= ?
ORDER BY t.timestamp, t.id
"""


def _bounds(start: str, end: str) -> tuple[str, str]:
    """Turn YYYY-MM-DD dates into an inclusive timestamp range."""
    return f"{start}T00:00:00Z", f"{end}T23:59:59Z"


def _signed(row) -> int:
    """A refund moves money out, so it counts against the total."""
    amount = row["amount_micro_usdc"]
    return -amount if row["tx_type"] == TX_TYPE_REFUND else amount


@dataclass(frozen=True)
class CategoryLine:
    """One row of the summary breakdown, with refunds netted out."""

    category_label: str
    confidence_tier: str
    rule_matched: str
    transaction_count: int
    payment_count: int
    refund_count: int
    gross_micro_usdc: int
    refunded_micro_usdc: int
    net_micro_usdc: int


@dataclass(frozen=True)
class ReportData:
    """Everything the summary needs, already aggregated."""

    start: str
    end: str
    payer_lines: list[CategoryLine]
    service_lines: list[CategoryLine]
    transaction_count: int
    payment_count: int
    refund_count: int
    gross_micro_usdc: int
    refunded_micro_usdc: int
    net_micro_usdc: int
    confident_micro_usdc: int
    uncertain_micro_usdc: int
    labeled_count: int
    reported_count: int
    memo_count: int


def _breakdown(rows, label_key: str, tier_key: str, rule_key: str) -> list[CategoryLine]:
    """Aggregate the same rows along one axis."""
    grouped: dict[tuple[str, str, str], list] = {}
    for row in rows:
        key = (row[label_key], row[tier_key], row[rule_key])
        grouped.setdefault(key, []).append(row)

    lines = [
        CategoryLine(
            category_label=label,
            confidence_tier=tier,
            rule_matched=rule,
            transaction_count=len(members),
            payment_count=sum(1 for r in members if r["tx_type"] == TX_TYPE_PAYMENT),
            refund_count=sum(1 for r in members if r["tx_type"] == TX_TYPE_REFUND),
            gross_micro_usdc=sum(
                r["amount_micro_usdc"] for r in members if r["tx_type"] == TX_TYPE_PAYMENT
            ),
            refunded_micro_usdc=sum(
                r["amount_micro_usdc"] for r in members if r["tx_type"] == TX_TYPE_REFUND
            ),
            net_micro_usdc=sum(_signed(r) for r in members),
        )
        for (label, tier, rule), members in grouped.items()
    ]
    # Confident groups first, then by size — uncategorized always sorts last so
    # it reads as the closing "still to account for" line.
    lines.sort(
        key=lambda line: (
            line.category_label == UNCATEGORIZED,
            line.confidence_tier != CONFIDENT,
            -line.net_micro_usdc,
        )
    )
    return lines


def build_report(conn: sqlite3.Connection, start: str, end: str) -> ReportData:
    """Aggregate categorized transactions for an inclusive date range."""
    rows = conn.execute(_SELECT_IN_RANGE, _bounds(start, end)).fetchall()

    reported_hashes = {row["tx_hash"] for row in rows}
    labeled = conn.execute("SELECT tx_hash FROM ground_truth").fetchall()
    labeled_count = sum(1 for row in labeled if row["tx_hash"] in reported_hashes)

    payer_lines = _breakdown(rows, "payer_label", "payer_tier", "payer_rule")
    service_lines = _breakdown(rows, "service_label", "service_tier", "service_rule")

    gross = sum(r["amount_micro_usdc"] for r in rows if r["tx_type"] == TX_TYPE_PAYMENT)
    refunded = sum(r["amount_micro_usdc"] for r in rows if r["tx_type"] == TX_TYPE_REFUND)
    confident = sum(_signed(r) for r in rows if r["payer_tier"] == CONFIDENT)
    net = gross - refunded
    payment_count = sum(1 for r in rows if r["tx_type"] == TX_TYPE_PAYMENT)
    refund_count = sum(1 for r in rows if r["tx_type"] == TX_TYPE_REFUND)
    memo_count = sum(1 for row in rows if row["memo"] is not None)

    return ReportData(
        start=start,
        end=end,
        payer_lines=payer_lines,
        service_lines=service_lines,
        transaction_count=len(rows),
        payment_count=payment_count,
        refund_count=refund_count,
        gross_micro_usdc=gross,
        refunded_micro_usdc=refunded,
        net_micro_usdc=net,
        confident_micro_usdc=confident,
        uncertain_micro_usdc=net - confident,
        labeled_count=labeled_count,
        reported_count=len(rows),
        memo_count=memo_count,
    )


def calibration_state(data: ReportData) -> str:
    """Whether accuracy has been measured on the data being reported.

    Derived from ground-truth coverage rather than declared by a flag, so it
    cannot be set wrongly. "Confidently identified" is a claim about accuracy,
    and it is only honest where accuracy was actually measured.
    """
    if data.reported_count == 0 or data.labeled_count == 0:
        return "uncalibrated"
    if data.labeled_count >= data.reported_count:
        return "calibrated"
    return "partial"


def _format_line(line: CategoryLine, axis: str, *, redact: bool = True) -> str:
    """Render one breakdown row.

    The [needs review] marker is gated on UNCERTAIN specifically. Both axes now
    tier the same way - CONFIDENT for a claimed grouping, UNCERTAIN for a
    declined one - so this reads identically for payer and service rows.

    A payer label carries the sender's address. It is shortened for display
    only; the stored label keeps the full address, because grouping depends
    on it.
    """
    if line.category_label == UNCATEGORIZED:
        name = "Not identified" if axis == AXIS_PAYER else "No service identified"
    else:
        name = line.category_label
        if redact and name.startswith("agent:"):
            name = "agent:" + shorten_address(name[len("agent:"):])

    marker = "   [needs review]" if line.confidence_tier == UNCERTAIN else ""

    # Payment count is reported against gross, refund count against refunds - a
    # line with one payment and one refund never reads as "2 payments" when in
    # fact it was one payment that came back.
    counts = f"{line.payment_count} {_payments(line.payment_count)}"
    if line.refund_count:
        counts += f", {line.refund_count} {_refunds(line.refund_count)}"

    return (
        f"  {name:<48} {format_usdc_rounded(line.net_micro_usdc):>16}"
        f"  ({counts}){marker}"
    )


def render_summary(data: ReportData, *, redact: bool = True) -> str:
    """Render the plain-language summary.

    Payer labels are shortened by default; `redact=False` shows them in full.
    """
    header = f"Payments received, {data.start} to {data.end}"

    if data.transaction_count == 0:
        return (
            f"{header}\n\n"
            "No transactions found in this date range.\n"
            "(This is not a total of zero - there is simply nothing recorded here.)"
        )

    lines = [
        header,
        "=" * len(header),
        "",
        f"Payments received:  {format_usdc_rounded(data.gross_micro_usdc)}"
        f"  ({data.payment_count} {_payments(data.payment_count)})",
        f"Refunds issued:     {format_usdc_rounded(data.refunded_micro_usdc)}"
        f"  ({data.refund_count} {_refunds(data.refund_count)})",
        f"Net received:       {format_usdc_rounded(data.net_micro_usdc)}",
        "",
        f"  Confidently identified (who paid you): {format_usdc_rounded(data.confident_micro_usdc)}",
        f"  Needs review (who paid you):           {format_usdc_rounded(data.uncertain_micro_usdc)}",
    ]

    state = calibration_state(data)
    if state == "uncalibrated":
        lines += [
            "",
            '  ! No ground truth was supplied for this data, so "confidently" is',
            "    uncalibrated here. The grouping is shown; its accuracy on this",
            "    dataset is unmeasured.",
        ]
    elif state == "partial":
        share = data.labeled_count / data.reported_count
        lines += [
            "",
            f"  ! Accuracy measured on {data.labeled_count} of "
            f"{data.reported_count} transactions ({share:.1%} labeled).",
            "    The rest are grouped by the same rule, unmeasured.",
        ]

    lines += [
        "",
        "Who paid you (net of refunds)",
        "-----------------------------",
    ]
    lines += [_format_line(line, AXIS_PAYER, redact=redact) for line in data.payer_lines]

    if data.memo_count == 0:
        lines += [
            "",
            "What they paid for",
            "------------------",
            "  This data carries no memo, so nothing here describes what was",
            "  bought. On-chain transfers do not record which resource was",
            "  purchased - that lives in the seller's request log, not on the",
            "  chain.",
        ]
    else:
        lines += [
            "",
            "What they paid for (net of refunds)",
            "-----------------------------------",
            "  Grouped by the memo the payer sent. These groupings describe what was",
            "  bought; they are not a claim about who bought it.",
        ]
        lines += [_format_line(line, AXIS_SERVICE, redact=redact) for line in data.service_lines]

    lines += [
        "",
        "Each section marks its own [needs review] rows. A payment can appear",
        "in both - once because its payer is unconfirmed, once because its",
        "service is. The two sets overlap, so do not add them together.",
        "",
        "This report organizes payment data you have already received.",
        "It is not tax or accounting advice.",
    ]

    lines += exact_net_footer(data.net_micro_usdc)

    return "\n".join(lines)


def write_csv(conn: sqlite3.Connection, start: str, end: str, out_path: Path) -> int:
    """Write line-item detail to CSV. Returns the number of rows written.

    Unlike the summary, this deliberately writes full, unredacted addresses
    and transaction hashes - it is the accounting artifact, and a truncated
    address cannot be reconciled against anything. Callers must warn the
    user that the written file is sensitive.
    """
    rows = conn.execute(_SELECT_IN_RANGE, _bounds(start, end)).fetchall()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "tx_hash",
                "timestamp",
                "sender_address",
                "memo",
                "amount_usdc",
                "tx_type",
                "payer_label",
                "payer_tier",
                "payer_rule",
                "service_label",
                "service_rule",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["tx_hash"],
                    row["timestamp"],
                    row["sender_address"],
                    row["memo"] or "",
                    f"{micro_to_decimal(row['amount_micro_usdc']):.6f}",
                    row["tx_type"],
                    row["payer_label"],
                    row["payer_tier"],
                    row["payer_rule"],
                    row["service_label"],
                    row["service_rule"],
                ]
            )
    return len(rows)

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

from ledger.models import (
    AXIS_PAYER,
    CONFIDENT,
    RULE_NONE,
    TX_TYPE_PAYMENT,
    TX_TYPE_REFUND,
    UNCATEGORIZED,
    UNCERTAIN,
)
from ledger.money import format_usdc, micro_to_decimal


def _payments(count: int) -> str:
    """Pluralize the payment count so a lone entry reads as "1 payment"."""
    return "payment" if count == 1 else "payments"


def _refunds(count: int) -> str:
    """Pluralize the refund count so a lone entry reads as "1 refund"."""
    return "refund" if count == 1 else "refunds"

_SELECT_IN_RANGE = f"""
SELECT t.tx_hash, t.timestamp, t.sender_address, t.memo, t.amount_micro_usdc,
       t.tx_type,
       COALESCE(c.category_label, '{UNCATEGORIZED}')  AS category_label,
       COALESCE(c.confidence_tier, '{UNCERTAIN}')     AS confidence_tier,
       COALESCE(c.rule_matched, '{RULE_NONE}')        AS rule_matched
FROM transactions t
LEFT JOIN categorizations c ON c.transaction_id = t.id AND c.axis = '{AXIS_PAYER}'
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
    lines: list[CategoryLine]
    transaction_count: int
    payment_count: int
    refund_count: int
    gross_micro_usdc: int
    refunded_micro_usdc: int
    net_micro_usdc: int
    confident_micro_usdc: int
    uncertain_micro_usdc: int


def build_report(conn: sqlite3.Connection, start: str, end: str) -> ReportData:
    """Aggregate categorized transactions for an inclusive date range."""
    rows = conn.execute(_SELECT_IN_RANGE, _bounds(start, end)).fetchall()

    grouped: dict[tuple[str, str, str], list] = {}
    for row in rows:
        key = (row["category_label"], row["confidence_tier"], row["rule_matched"])
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
                r["amount_micro_usdc"] for r in members
                if r["tx_type"] == TX_TYPE_PAYMENT
            ),
            refunded_micro_usdc=sum(
                r["amount_micro_usdc"] for r in members
                if r["tx_type"] == TX_TYPE_REFUND
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

    gross = sum(r["amount_micro_usdc"] for r in rows if r["tx_type"] == TX_TYPE_PAYMENT)
    refunded = sum(r["amount_micro_usdc"] for r in rows if r["tx_type"] == TX_TYPE_REFUND)
    confident = sum(_signed(r) for r in rows if r["confidence_tier"] == CONFIDENT)
    net = gross - refunded
    payment_count = sum(1 for r in rows if r["tx_type"] == TX_TYPE_PAYMENT)
    refund_count = sum(1 for r in rows if r["tx_type"] == TX_TYPE_REFUND)

    return ReportData(
        start=start,
        end=end,
        lines=lines,
        transaction_count=len(rows),
        payment_count=payment_count,
        refund_count=refund_count,
        gross_micro_usdc=gross,
        refunded_micro_usdc=refunded,
        net_micro_usdc=net,
        confident_micro_usdc=confident,
        uncertain_micro_usdc=net - confident,
    )


def render_summary(data: ReportData) -> str:
    """Render the plain-language summary."""
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
        f"Payments received:  {format_usdc(data.gross_micro_usdc)}"
        f"  ({data.payment_count} {_payments(data.payment_count)})",
        f"Refunds issued:     {format_usdc(data.refunded_micro_usdc)}"
        f"  ({data.refund_count} {_refunds(data.refund_count)})",
        f"Net received:       {format_usdc(data.net_micro_usdc)}",
        "",
        f"  Confidently identified: {format_usdc(data.confident_micro_usdc)}",
        f"  Needs review:           {format_usdc(data.uncertain_micro_usdc)}",
        "",
        "Breakdown by source (net of refunds)",
        "------------------------------------",
    ]

    for line in data.lines:
        name = (
            "Uncategorized"
            if line.category_label == UNCATEGORIZED
            else line.category_label
        )
        marker = "" if line.confidence_tier == CONFIDENT else "   [needs review]"
        # Payment count is reported against gross, refund count against
        # refunds - a line with one payment and one refund never reads as
        # "2 payments" when in fact it was one payment that came back.
        counts = f"{line.payment_count} {_payments(line.payment_count)}"
        if line.refund_count:
            counts += f", {line.refund_count} {_refunds(line.refund_count)}"
        lines.append(
            f"  {name:<48} {format_usdc(line.net_micro_usdc):>16}"
            f"  ({counts}){marker}"
        )

    lines += [
        "",
        "Anything marked [needs review] could not be confidently matched to a",
        "single payer. Please confirm these before relying on the totals.",
        "",
        "This report organizes payment data you have already received.",
        "It is not tax or accounting advice.",
    ]
    return "\n".join(lines)


def write_csv(conn: sqlite3.Connection, start: str, end: str, out_path: Path) -> int:
    """Write line-item detail to CSV. Returns the number of rows written."""
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
                "category_label",
                "confidence_tier",
                "rule_matched",
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
                    row["category_label"],
                    row["confidence_tier"],
                    row["rule_matched"],
                ]
            )
    return len(rows)

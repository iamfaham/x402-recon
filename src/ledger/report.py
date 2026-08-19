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

from ledger.categorize import CONFIDENT, UNCATEGORIZED
from ledger.money import format_usdc, micro_to_decimal


def _payments(count: int) -> str:
    """Pluralize the payment count so a lone entry reads as "1 payment"."""
    return "payment" if count == 1 else "payments"

_SELECT_IN_RANGE = """
SELECT t.tx_hash, t.timestamp, t.sender_address, t.memo, t.amount_micro_usdc,
       COALESCE(c.category_label, 'uncategorized')  AS category_label,
       COALESCE(c.confidence_tier, 'uncertain')     AS confidence_tier,
       COALESCE(c.rule_matched, 'none')             AS rule_matched
FROM transactions t
LEFT JOIN categorizations c ON c.transaction_id = t.id
WHERE t.timestamp >= ? AND t.timestamp <= ?
ORDER BY t.timestamp, t.id
"""


def _bounds(start: str, end: str) -> tuple[str, str]:
    """Turn YYYY-MM-DD dates into an inclusive timestamp range."""
    return f"{start}T00:00:00Z", f"{end}T23:59:59Z"


@dataclass(frozen=True)
class CategoryLine:
    """One row of the summary breakdown."""

    category_label: str
    confidence_tier: str
    rule_matched: str
    transaction_count: int
    total_micro_usdc: int


@dataclass(frozen=True)
class ReportData:
    """Everything the summary needs, already aggregated."""

    start: str
    end: str
    lines: list[CategoryLine]
    transaction_count: int
    total_micro_usdc: int
    confident_micro_usdc: int
    uncertain_micro_usdc: int


def build_report(conn: sqlite3.Connection, start: str, end: str) -> ReportData:
    """Aggregate categorized transactions for an inclusive date range."""
    rows = conn.execute(_SELECT_IN_RANGE, _bounds(start, end)).fetchall()

    grouped: dict[tuple[str, str, str], list[int]] = {}
    for row in rows:
        key = (row["category_label"], row["confidence_tier"], row["rule_matched"])
        grouped.setdefault(key, []).append(row["amount_micro_usdc"])

    lines = [
        CategoryLine(
            category_label=label,
            confidence_tier=tier,
            rule_matched=rule,
            transaction_count=len(amounts),
            total_micro_usdc=sum(amounts),
        )
        for (label, tier, rule), amounts in grouped.items()
    ]
    # Confident groups first, then by size — uncategorized always sorts last so
    # it reads as the closing "still to account for" line.
    lines.sort(
        key=lambda line: (
            line.category_label == UNCATEGORIZED,
            line.confidence_tier != CONFIDENT,
            -line.total_micro_usdc,
        )
    )

    total = sum(row["amount_micro_usdc"] for row in rows)
    confident = sum(
        row["amount_micro_usdc"] for row in rows if row["confidence_tier"] == CONFIDENT
    )

    return ReportData(
        start=start,
        end=end,
        lines=lines,
        transaction_count=len(rows),
        total_micro_usdc=total,
        confident_micro_usdc=confident,
        uncertain_micro_usdc=total - confident,
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
        f"Total received:     {format_usdc(data.total_micro_usdc)}"
        f"  ({data.transaction_count} {_payments(data.transaction_count)})",
        f"  Confidently identified: {format_usdc(data.confident_micro_usdc)}",
        f"  Needs review:           {format_usdc(data.uncertain_micro_usdc)}",
        "",
        "Breakdown by source",
        "-------------------",
    ]

    for line in data.lines:
        name = (
            "Uncategorized"
            if line.category_label == UNCATEGORIZED
            else line.category_label
        )
        marker = "" if line.confidence_tier == CONFIDENT else "   [needs review]"
        lines.append(
            f"  {name:<48} {format_usdc(line.total_micro_usdc):>16}"
            f"  ({line.transaction_count} {_payments(line.transaction_count)}){marker}"
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
                    row["category_label"],
                    row["confidence_tier"],
                    row["rule_matched"],
                ]
            )
    return len(rows)

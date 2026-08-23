"""Structural summary of a batch, with no accuracy figure of any kind.

This is Stage 1 of the staged measurement. Its job is to say whether the
sample bar is reachable and which branch the release is heading for. It must
never reveal how accurate the rules are: seeing that before labeling would let
the labeling drift toward the answer, and would let a threshold be tuned to a
result it is supposed to be fixed in advance of.

Nothing in this module may import the scorer.
"""

import sqlite3
from dataclasses import dataclass

from ledger.config import DEFAULT_CONFIG, CascadeConfig
from ledger.models import TX_TYPE_PAYMENT, TX_TYPE_REFUND

_BANDS = ("once", "twice", "three_or_more")


def _band(count: int) -> str:
    if count == 1:
        return "once"
    if count == 2:
        return "twice"
    return "three_or_more"


@dataclass(frozen=True)
class ShapeReport:
    transaction_count: int
    payment_count: int
    refund_count: int
    first_timestamp: str | None
    last_timestamp: str | None
    distinct_senders: int
    senders_by_band: dict[str, int]
    net_by_band: dict[str, int]
    claimable_count: int


def build_shape(
    conn: sqlite3.Connection, config: CascadeConfig = DEFAULT_CONFIG
) -> ShapeReport:
    rows = conn.execute(
        "SELECT sender_address, amount_micro_usdc, timestamp, tx_type FROM transactions"
    ).fetchall()

    by_sender: dict[str, list] = {}
    for row in rows:
        by_sender.setdefault(row["sender_address"], []).append(row)

    senders_by_band = {band: 0 for band in _BANDS}
    net_by_band = {band: 0 for band in _BANDS}
    claimable = 0

    for members in by_sender.values():
        band = _band(len(members))
        senders_by_band[band] += 1
        net_by_band[band] += sum(
            member["amount_micro_usdc"]
            if member["tx_type"] == TX_TYPE_PAYMENT
            else -member["amount_micro_usdc"]
            for member in members
        )
        if len(members) >= config.min_occurrences:
            claimable += len(members)

    timestamps = sorted(row["timestamp"] for row in rows)

    return ShapeReport(
        transaction_count=len(rows),
        payment_count=sum(1 for r in rows if r["tx_type"] == TX_TYPE_PAYMENT),
        refund_count=sum(1 for r in rows if r["tx_type"] == TX_TYPE_REFUND),
        first_timestamp=timestamps[0] if timestamps else None,
        last_timestamp=timestamps[-1] if timestamps else None,
        distinct_senders=len(by_sender),
        senders_by_band=senders_by_band,
        net_by_band=net_by_band,
        claimable_count=claimable,
    )


def render_shape(report: ShapeReport) -> str:
    from ledger.money import format_usdc

    span = (
        f"{report.first_timestamp} to {report.last_timestamp}"
        if report.first_timestamp
        else "no transactions"
    )
    lines = [
        "Batch shape",
        "===========",
        "",
        f"Transactions:     {report.transaction_count}"
        f"  ({report.payment_count} paid, {report.refund_count} refunded)",
        f"Span:             {span}",
        f"Distinct senders: {report.distinct_senders}",
        "",
        "Senders by how often they appear",
        "--------------------------------",
    ]
    labels = {"once": "Once", "twice": "Twice", "three_or_more": "Three or more"}
    for band in _BANDS:
        lines.append(
            f"  {labels[band]:<14} {report.senders_by_band[band]:>4} senders"
            f"   {format_usdc(report.net_by_band[band]):>16}"
        )
    lines += [
        "",
        f"Transactions a repeat-sender rule would claim: {report.claimable_count}",
        "",
        "This describes the batch's structure only. It says nothing about how",
        "accurate any grouping is.",
    ]
    return "\n".join(lines)

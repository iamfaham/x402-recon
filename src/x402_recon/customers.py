"""Who actually came back, and who paid once and vanished.

The reconciliation report answers "what did I earn". This answers a different
question a seller of agent-facing services has today: *how much of my traffic
is real customers?*

That question exists because the x402 ecosystem is currently full of traffic
that looks like revenue and is not. Live Bazaar figures from 2026-08-24 show
one service taking 1,078 payments from 1,075 distinct payers - a ratio of
almost exactly one, meaning every payer called once and never returned. That
is directory probing or wash traffic, not commerce. Services with genuine
repeat usage sat at 35-40 payments per payer over the same window.

Nothing here is new machinery. The payer axis already groups by repeat sender;
this reads the same signal and reports it in the terms a seller thinks in.
"""

import sqlite3
from dataclasses import dataclass

from x402_recon.models import TX_TYPE_PAYMENT, TX_TYPE_REFUND
from x402_recon.money import format_usdc

BAND_RETURNING = "returning"
BAND_TRIED_TWICE = "tried_twice"
BAND_ONE_SHOT = "one_shot"

_BAND_ORDER = (BAND_RETURNING, BAND_TRIED_TWICE, BAND_ONE_SHOT)

_BAND_LABELS = {
    BAND_RETURNING: "Returning (3+)",
    BAND_TRIED_TWICE: "Tried twice",
    BAND_ONE_SHOT: "One-shot",
}

# Below this many payments per payer, nearly everyone paid once and left.
# Calibrated on observed data rather than derived from theory, and named here
# so that is visible: the probe-shaped service measured 1.00-1.23, while the
# two services with real repeat usage measured 34.9 and 40.2. Anything in
# between is genuinely ambiguous, which is why the flag stays quiet there.
PROBE_RATIO_CEILING = 1.5

_SELECT_IN_RANGE = """
SELECT sender_address, amount_micro_usdc, tx_type
FROM transactions
WHERE timestamp >= ? AND timestamp <= ?
"""


def _band_for(payment_count: int) -> str:
    if payment_count == 1:
        return BAND_ONE_SHOT
    if payment_count == 2:
        return BAND_TRIED_TWICE
    return BAND_RETURNING


def _signed(row) -> int:
    """A refund moves money out, so it counts against the total."""
    amount = row["amount_micro_usdc"]
    return -amount if row["tx_type"] == TX_TYPE_REFUND else amount


@dataclass(frozen=True)
class PayerBand:
    """One group of payers, split by how often they came back."""

    label: str
    payer_count: int
    payment_count: int
    net_micro_usdc: int


@dataclass(frozen=True)
class CustomerReport:
    start: str
    end: str
    payment_count: int
    distinct_payers: int
    net_micro_usdc: int
    bands: list[PayerBand]

    @property
    def payments_per_payer(self) -> float:
        """Display-only ratio. Never used in a money calculation."""
        if not self.distinct_payers:
            return 0.0
        return self.payment_count / self.distinct_payers

    @property
    def looks_like_probe_traffic(self) -> bool:
        """Whether nearly every payer appeared exactly once."""
        if not self.distinct_payers:
            return False
        return self.payments_per_payer < PROBE_RATIO_CEILING


def build_customer_report(
    conn: sqlite3.Connection, start: str, end: str
) -> CustomerReport:
    """Split payers in a date range by how often they came back.

    A band is a fact about the window, not about the payer forever: a payer
    who bought monthly all year is a one-shot inside any single month.
    """
    rows = conn.execute(
        _SELECT_IN_RANGE, (f"{start}T00:00:00Z", f"{end}T23:59:59Z")
    ).fetchall()

    by_sender: dict[str, list] = {}
    for row in rows:
        by_sender.setdefault(row["sender_address"], []).append(row)

    payers: dict[str, int] = dict.fromkeys(_BAND_ORDER, 0)
    payments: dict[str, int] = dict.fromkeys(_BAND_ORDER, 0)
    net: dict[str, int] = dict.fromkeys(_BAND_ORDER, 0)

    for members in by_sender.values():
        band = _band_for(len(members))
        payers[band] += 1
        payments[band] += len(members)
        net[band] += sum(_signed(member) for member in members)

    return CustomerReport(
        start=start,
        end=end,
        payment_count=sum(1 for r in rows if r["tx_type"] == TX_TYPE_PAYMENT),
        distinct_payers=len(by_sender),
        net_micro_usdc=sum(_signed(r) for r in rows),
        bands=[
            PayerBand(
                label=band,
                payer_count=payers[band],
                payment_count=payments[band],
                net_micro_usdc=net[band],
            )
            for band in _BAND_ORDER
        ],
    )


def render_customer_report(report: CustomerReport) -> str:
    header = f"Who actually came back  ({report.start} to {report.end})"
    lines = [header, "=" * len(header), ""]

    if not report.payment_count and not report.distinct_payers:
        lines.append("  There were no payments in this range.")
        return "\n".join(lines)

    lines += [
        f"  Payments received:  {report.payment_count:>8,}",
        f"  Distinct payers:    {report.distinct_payers:>8,}",
        f"  Payments per payer: {report.payments_per_payer:>8.1f}",
        "",
        f"  {'':<16}{'payers':>8}{'payments':>11}{'revenue':>16}{'share':>9}",
        "  " + "-" * 60,
    ]

    for band in report.bands:
        share = (
            band.net_micro_usdc / report.net_micro_usdc
            if report.net_micro_usdc
            else 0.0
        )
        lines.append(
            f"  {_BAND_LABELS[band.label]:<16}{band.payer_count:>8,}"
            f"{band.payment_count:>11,}{format_usdc(band.net_micro_usdc):>16}"
            f"{share:>9.1%}"
        )

    lines += ["", f"  {'Total':<16}{report.distinct_payers:>8,}"
              f"{report.payment_count:>11,}{format_usdc(report.net_micro_usdc):>16}"]

    if report.looks_like_probe_traffic:
        lines += [
            "",
            "  ! Almost every payer here appeared exactly once. That pattern is",
            "    consistent with directory probes or automated sampling rather",
            "    than customer usage - the payment count is real, but it is not",
            "    evidence of demand. Worth confirming before treating this as",
            "    a customer base.",
        ]

    lines += [
        "",
        "  A returning payer is one that paid three or more times in this range.",
        "  Bands describe this window only: a payer who buys monthly counts as",
        "  a one-shot inside any single month.",
        "",
        "  This organizes payment data you have already received.",
        "  It is not tax or accounting advice.",
    ]
    return "\n".join(lines)

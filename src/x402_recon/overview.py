"""The combined overview: money received and who actually came back, together.

This is the single screen a user sees after running the tool. It exists
because "how much did I make" and "was any of that real repeat demand" are
two halves of the same story, and a seller should not have to run two
commands and mentally merge them.

Two rules keep this honest and readable:

- Provenance gates the word "x402". A discovered payTo (backed by a real 402
  response from the seller) may be described as x402. A raw address typed in
  by the user has no such evidence behind it, so the output must never claim
  x402 for it - it is simply USDC received at that address.
- The service axis is always empty for on-chain data (there is no memo), so
  it gets a one-line note here rather than a full section that would read as
  "no service identified" on every single run.

This module organizes data already received. It does not advise on tax or
accounting treatment.
"""

import sqlite3
from dataclasses import dataclass, field

from x402_recon.customers import _BAND_LABELS, CustomerReport, build_customer_report
from x402_recon.money import format_usdc, format_usdc_rounded, rounds_exactly
from x402_recon.report import ReportData, build_report, calibration_state
from x402_recon.verify import SampleResult, render_sample


def _shorten(address: str) -> str:
    return address[:10] + "…" + address[-6:]


@dataclass(frozen=True)
class Overview:
    address: str
    source_url: str | None
    start: str
    end: str
    report: ReportData
    customers: CustomerReport
    sample: SampleResult | None
    rejects: list[tuple[str, str]] = field(default_factory=list)


def build_overview(
    conn: sqlite3.Connection,
    address: str,
    start: str,
    end: str,
    *,
    source_url: str | None = None,
    sample: SampleResult | None = None,
    rejects: list[tuple[str, str]] = (),
) -> Overview:
    """Gather the report and customer data for one combined view."""
    report = build_report(conn, start, end)
    customers = build_customer_report(conn, start, end)
    return Overview(
        address=address,
        source_url=source_url,
        start=start,
        end=end,
        report=report,
        customers=customers,
        sample=sample,
        rejects=list(rejects),
    )


def _provenance_line(source_url: str | None) -> str:
    if source_url:
        from urllib.parse import urlparse

        host = urlparse(source_url).netloc or source_url
        return f"payTo discovered from {host}"
    return "USDC payments to this address (not confirmed as x402)"


_CALIBRATION_NOTES = {
    "uncalibrated": (
        'No ground truth was supplied for this data, so "confidently" is '
        "uncalibrated here. The grouping is shown; its accuracy on this "
        "dataset is unmeasured."
    ),
}


def render_overview(overview: Overview) -> str:
    """Render the combined money-and-customers overview."""
    report = overview.report
    customers = overview.customers

    header = f"x402-recon · {_shorten(overview.address)}"
    lines = [
        header,
        f"Base mainnet · {overview.start} to {overview.end} · "
        f"{_provenance_line(overview.source_url)}",
        "",
    ]

    if report.transaction_count == 0 and not customers.payment_count:
        lines.append("No payments found in this date range.")
        return "\n".join(lines)

    lines += [
        f"  Net received          {format_usdc_rounded(report.net_micro_usdc)}"
        f"    from {report.payment_count} payments",
        f"  Distinct payers       {customers.distinct_payers:>8}"
        f"    {customers.payments_per_payer:.1f} payments each",
        "",
        "Who actually came back",
        "-----------------------",
        f"  {'':<16}{'payers':>8}{'payments':>11}{'revenue':>16}{'share':>9}",
    ]

    for band in customers.bands:
        share = (
            band.net_micro_usdc / customers.net_micro_usdc
            if customers.net_micro_usdc
            else 0.0
        )
        lines.append(
            f"  {_BAND_LABELS[band.label]:<16}{band.payer_count:>8,}"
            f"{band.payment_count:>11,}{format_usdc_rounded(band.net_micro_usdc):>16}"
            f"{share:>9.1%}"
        )

    if customers.looks_like_probe_traffic:
        lines += [
            "",
            "! Almost every payer here appeared exactly once. That pattern is",
            "  consistent with directory probes or automated sampling rather",
            "  than customer usage - the payment count is real, but it is not",
            "  evidence of demand. Worth confirming before treating this as",
            "  a customer base.",
        ]

    notes = []
    state = calibration_state(report)
    if state in _CALIBRATION_NOTES:
        notes.append(_CALIBRATION_NOTES[state])
    elif state == "partial":
        share = report.labeled_count / report.reported_count
        notes.append(
            f"Accuracy measured on {report.labeled_count} of "
            f"{report.reported_count} transactions ({share:.1%} labeled). "
            "The rest are grouped by the same rule, unmeasured."
        )

    if overview.sample is not None and overview.source_url is not None:
        sample_line = render_sample(overview.sample)
        if sample_line:
            notes.append(sample_line)

    if not rounds_exactly(report.net_micro_usdc):
        notes.append(
            f"Figures above are rounded to cents. Exact net received: "
            f"{format_usdc(report.net_micro_usdc)}."
        )
    notes.append(
        "The chain records no memo, so what was bought cannot be shown - that "
        "lives in your request log, not on-chain."
    )
    notes.append(
        "Organizes payments you have already received. Not tax or accounting advice."
    )

    lines += [
        "",
        "Notes",
        "-----",
    ]
    lines += [f"  · {note}" for note in notes]

    return "\n".join(lines)

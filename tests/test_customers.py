"""Tests for the seller-facing repeat-customer breakdown."""

import pytest

from x402_recon.customers import (
    BAND_ONE_SHOT,
    BAND_RETURNING,
    BAND_TRIED_TWICE,
    PROBE_RATIO_CEILING,
    build_customer_report,
    render_customer_report,
)
from x402_recon.db import connect, init_schema

RECEIVER = "0x" + "99" * 20


def _seed(conn, rows):
    for tx_hash, sender, amount, timestamp, tx_type in rows:
        conn.execute(
            """INSERT INTO transactions
               (tx_hash, sender_address, receiver_address, amount_micro_usdc,
                timestamp, memo, chain, raw_payload, tx_type)
               VALUES (?, ?, ?, ?, ?, NULL, 'base', '{}', ?)""",
            (tx_hash, sender, RECEIVER, amount, timestamp, tx_type),
        )
    conn.commit()


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "t.db")
    init_schema(connection)
    return connection


def _mixed(conn):
    """A loyal payer, a two-timer, and two one-shots."""
    _seed(
        conn,
        [
            ("0x1", "0xloyal", 1_000_000, "2026-08-02T00:00:00Z", "payment"),
            ("0x2", "0xloyal", 1_000_000, "2026-08-03T00:00:00Z", "payment"),
            ("0x3", "0xloyal", 1_000_000, "2026-08-04T00:00:00Z", "payment"),
            ("0x4", "0xtwice", 500_000, "2026-08-05T00:00:00Z", "payment"),
            ("0x5", "0xtwice", 500_000, "2026-08-06T00:00:00Z", "payment"),
            ("0x6", "0xone_a", 100_000, "2026-08-07T00:00:00Z", "payment"),
            ("0x7", "0xone_b", 100_000, "2026-08-08T00:00:00Z", "payment"),
        ],
    )
    return conn


def _by_label(report):
    return {band.label: band for band in report.bands}


def test_headline_counts_payments_and_distinct_payers(conn):
    report = build_customer_report(_mixed(conn), "2026-08-01", "2026-08-31")
    assert report.payment_count == 7
    assert report.distinct_payers == 4


def test_bands_split_payers_by_how_often_they_returned(conn):
    bands = _by_label(build_customer_report(_mixed(conn), "2026-08-01", "2026-08-31"))
    assert bands[BAND_RETURNING].payer_count == 1
    assert bands[BAND_TRIED_TWICE].payer_count == 1
    assert bands[BAND_ONE_SHOT].payer_count == 2


def test_bands_carry_payments_and_revenue(conn):
    bands = _by_label(build_customer_report(_mixed(conn), "2026-08-01", "2026-08-31"))
    assert bands[BAND_RETURNING].payment_count == 3
    assert bands[BAND_RETURNING].net_micro_usdc == 3_000_000
    assert bands[BAND_ONE_SHOT].payment_count == 2
    assert bands[BAND_ONE_SHOT].net_micro_usdc == 200_000


def test_revenue_is_an_integer_never_a_float(conn):
    for band in build_customer_report(_mixed(conn), "2026-08-01", "2026-08-31").bands:
        assert isinstance(band.net_micro_usdc, int)
        assert not isinstance(band.net_micro_usdc, float)


def test_refunds_reduce_a_band_rather_than_counting_as_revenue(conn):
    _seed(
        conn,
        [
            ("0x1", "0xloyal", 1_000_000, "2026-08-02T00:00:00Z", "payment"),
            ("0x2", "0xloyal", 1_000_000, "2026-08-03T00:00:00Z", "payment"),
            ("0x3", "0xloyal", 250_000, "2026-08-04T00:00:00Z", "refund"),
        ],
    )
    bands = _by_label(build_customer_report(conn, "2026-08-01", "2026-08-31"))
    assert bands[BAND_RETURNING].net_micro_usdc == 1_750_000


def test_the_date_range_is_respected(conn):
    _seed(
        conn,
        [
            ("0x1", "0xloyal", 1_000_000, "2026-07-31T23:59:59Z", "payment"),
            ("0x2", "0xloyal", 1_000_000, "2026-08-02T00:00:00Z", "payment"),
        ],
    )
    report = build_customer_report(conn, "2026-08-01", "2026-08-31")
    assert report.payment_count == 1
    # In August the loyal payer appears ONCE, so it is a one-shot for this
    # range. A band is a fact about the window, not about the payer forever.
    assert _by_label(report)[BAND_ONE_SHOT].payer_count == 1


def test_payments_per_payer_is_the_headline_ratio(conn):
    report = build_customer_report(_mixed(conn), "2026-08-01", "2026-08-31")
    assert report.payments_per_payer == pytest.approx(7 / 4)


def test_an_empty_range_reports_zero_without_dividing_by_zero(conn):
    report = build_customer_report(conn, "2026-08-01", "2026-08-31")
    assert report.payment_count == 0
    assert report.distinct_payers == 0
    assert report.payments_per_payer == 0.0
    assert "no payments" in render_customer_report(report).lower()


def test_probe_traffic_is_flagged_when_almost_every_payer_appears_once(conn):
    # The OneSource pattern from the live Bazaar data: 1,078 calls from 1,075
    # distinct payers. Everyone called once and never came back.
    _seed(
        conn,
        [
            (f"0x{i}", f"0xprobe{i}", 50_000, "2026-08-02T00:00:00Z", "payment")
            for i in range(30)
        ],
    )
    report = build_customer_report(conn, "2026-08-01", "2026-08-31")
    assert report.payments_per_payer < PROBE_RATIO_CEILING
    assert report.looks_like_probe_traffic is True
    assert "probe" in render_customer_report(report).lower()


def test_genuine_repeat_usage_is_not_flagged_as_probe_traffic(conn):
    # The Tavily/Exa pattern: 35-40 payments per payer.
    _seed(
        conn,
        [
            (f"0x{i}", f"0xcust{i % 2}", 50_000, "2026-08-02T00:00:00Z", "payment")
            for i in range(30)
        ],
    )
    report = build_customer_report(conn, "2026-08-01", "2026-08-31")
    assert report.looks_like_probe_traffic is False
    assert "probe" not in render_customer_report(report).lower()


def test_render_leads_with_the_number_a_seller_cares_about(conn):
    rendered = render_customer_report(
        build_customer_report(_mixed(conn), "2026-08-01", "2026-08-31")
    )
    assert "Returning" in rendered
    assert "One-shot" in rendered
    assert "$3.00" in rendered


def test_render_gives_no_tax_or_accounting_advice(conn):
    rendered = render_customer_report(
        build_customer_report(_mixed(conn), "2026-08-01", "2026-08-31")
    ).lower()
    for forbidden in ("deductible", "taxable", "you should", "consult", "write off"):
        assert forbidden not in rendered


def test_customer_bands_round_to_cents_and_keep_the_exact_total(tmp_path):
    from x402_recon.customers import build_customer_report, render_customer_report
    from x402_recon.db import connect, init_schema

    conn = connect(tmp_path / "c.db")
    init_schema(conn)
    for i in range(3):
        conn.execute(
            """INSERT INTO transactions
               (tx_hash, sender_address, receiver_address, amount_micro_usdc,
                timestamp, memo, chain, raw_payload, tx_type)
               VALUES (?, '0xcust', '0xreceiver', 145971653,
                       '2026-08-02T00:00:00Z', NULL, 'base', '{}', 'payment')""",
            (f"0x{i}",),
        )
    conn.commit()

    out = render_customer_report(build_customer_report(conn, "2026-08-01", "2026-08-31"))
    assert "$437.91" in out
    assert "$437.914959" in out, "the exact total must survive somewhere"

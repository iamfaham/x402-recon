import csv
import json
from decimal import Decimal
from pathlib import Path

from ledger.categorize import run_categorize
from ledger.db import connect, init_schema, load_transactions
from ledger.ingest import ingest_from_dir
from ledger.models import TX_TYPE_REFUND
from ledger.money import usdc_to_micro
from ledger.report import build_report, render_summary, write_csv


def seed(conn, rows):
    for tx_hash, sender, memo, timestamp, amount in rows:
        conn.execute(
            """INSERT INTO transactions
               (tx_hash, sender_address, receiver_address, amount_micro_usdc,
                timestamp, memo, chain, raw_payload)
               VALUES (?, ?, '0xm', ?, ?, ?, 'sim', '{}')""",
            (tx_hash, sender, amount, timestamp, memo),
        )
    conn.commit()


def prepared(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    seed(
        conn,
        [
            ("0x1", "0xa", None, "2026-08-10T10:00:00Z", 1_000_000),
            ("0x2", "0xa", None, "2026-08-10T10:01:00Z", 2_000_000),
            ("0x3", "0xzz", None, "2026-08-15T22:00:00Z", 500_000),
            ("0x4", "0xyy", None, "2026-09-01T10:00:00Z", 9_000_000),
        ],
    )
    run_categorize(conn)
    return conn


def test_report_totals_only_include_the_date_range(tmp_path: Path):
    conn = prepared(tmp_path)
    data = build_report(conn, "2026-08-01", "2026-08-31")

    assert data.transaction_count == 3
    assert data.net_micro_usdc == 3_500_000


def test_report_includes_transactions_on_the_final_day(tmp_path: Path):
    conn = prepared(tmp_path)
    data = build_report(conn, "2026-08-01", "2026-08-15")

    assert data.transaction_count == 3
    assert data.net_micro_usdc == 3_500_000


def test_report_excludes_the_day_after_the_range(tmp_path: Path):
    conn = prepared(tmp_path)
    data = build_report(conn, "2026-08-01", "2026-08-14")

    assert data.transaction_count == 2
    assert data.net_micro_usdc == 3_000_000


def test_confident_and_uncertain_totals_split_and_sum_to_the_whole(tmp_path: Path):
    conn = prepared(tmp_path)
    data = build_report(conn, "2026-08-01", "2026-08-31")

    assert data.confident_micro_usdc == 3_000_000
    assert data.uncertain_micro_usdc == 500_000
    assert data.confident_micro_usdc + data.uncertain_micro_usdc == data.net_micro_usdc


def test_summary_shows_uncategorized_money_explicitly(tmp_path: Path):
    conn = prepared(tmp_path)
    summary = render_summary(build_report(conn, "2026-08-01", "2026-08-31"))

    assert "uncategorized" in summary.lower()
    assert "$0.50" in summary


def test_summary_states_the_date_range_and_grand_total(tmp_path: Path):
    conn = prepared(tmp_path)
    summary = render_summary(build_report(conn, "2026-08-01", "2026-08-31"))

    assert "2026-08-01" in summary
    assert "2026-08-31" in summary
    assert "$3.50" in summary


def test_empty_range_says_so_rather_than_reporting_zero_revenue(tmp_path: Path):
    conn = prepared(tmp_path)
    summary = render_summary(build_report(conn, "2027-01-01", "2027-01-31"))

    assert "no transactions" in summary.lower()
    assert "$0.00" not in summary


def test_csv_has_one_row_per_transaction_with_headers(tmp_path: Path):
    conn = prepared(tmp_path)
    out = tmp_path / "report.csv"

    written = write_csv(conn, "2026-08-01", "2026-08-31", out)

    rows = list(csv.DictReader(out.read_text().splitlines()))
    assert written == 3
    assert len(rows) == 3
    assert {"tx_hash", "timestamp", "sender_address", "amount_usdc",
            "category_label", "confidence_tier", "rule_matched"} <= set(rows[0])


def test_singular_payment_count_is_not_pluralized(tmp_path: Path):
    conn = prepared(tmp_path)
    summary = render_summary(build_report(conn, "2026-08-15", "2026-08-15"))

    assert "(1 payment)" in summary
    assert "(1 payments)" not in summary


def test_plural_payment_count_is_pluralized(tmp_path: Path):
    conn = prepared(tmp_path)
    summary = render_summary(build_report(conn, "2026-08-01", "2026-08-31"))

    assert "(3 payments)" in summary


def test_disclaimer_is_present_in_the_rendered_summary(tmp_path: Path):
    conn = prepared(tmp_path)
    summary = render_summary(build_report(conn, "2026-08-01", "2026-08-31"))

    assert "not tax or accounting advice" in summary.lower()


def test_csv_amounts_are_exact_decimal_strings(tmp_path: Path):
    conn = prepared(tmp_path)
    out = tmp_path / "report.csv"
    write_csv(conn, "2026-08-01", "2026-08-31", out)

    rows = list(csv.DictReader(out.read_text().splitlines()))
    amounts = {row["amount_usdc"] for row in rows}
    assert "1.000000" in amounts
    assert "0.500000" in amounts


def test_grand_total_reconciles_across_summary_breakdown_csv_and_ingest(
    tmp_path: Path,
):
    """The single most important property: money is neither lost nor invented
    anywhere along ingest -> categorize -> report. Every view of the total
    (summary header, sum of breakdown lines, sum of the CSV column, and the
    sum of what was actually ingested) must agree exactly, in integer
    micro-USDC. Never compare via float.
    """
    source = tmp_path / "data"
    source.mkdir()
    known_rows = [
        {
            "tx_hash": f"0x{i}",
            "sender_address": "0xa" if i < 3 else f"0xsolo{i}",
            "receiver_address": "0xm",
            "amount_micro_usdc": amount,
            "timestamp": f"2026-08-{10 + i:02d}T10:00:00Z",
            "memo": None,
            "chain": "sim",
            "raw_payload": "{}",
        }
        for i, amount in enumerate([1_000_000, 2_500_000, 750_000, 333_333, 999])
    ]
    (source / "transactions.json").write_text(json.dumps(known_rows))

    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    ingest_result = ingest_from_dir(conn, source)
    assert ingest_result.rejects == []
    ingested_total = sum(row["amount_micro_usdc"] for row in known_rows)

    run_categorize(conn)

    data = build_report(conn, "2026-08-01", "2026-08-31")
    breakdown_total = sum(line.net_micro_usdc for line in data.lines)

    csv_path = tmp_path / "report.csv"
    write_csv(conn, "2026-08-01", "2026-08-31", csv_path)
    csv_rows = list(csv.DictReader(csv_path.read_text().splitlines()))
    csv_total_micro = sum(usdc_to_micro(row["amount_usdc"]) for row in csv_rows)

    assert data.net_micro_usdc == ingested_total
    assert breakdown_total == ingested_total
    assert csv_total_micro == ingested_total


def test_near_miss_addresses_receive_different_category_labels():
    """A regression guard for the cascade collapsing near-miss senders: two
    distinct agents that merely share an address prefix must never be filed
    under the same label, even though they satisfy the >= 10-char-prefix
    check the older, weaker test only pinned indirectly.
    """
    import dataclasses

    from ledger.categorize import categorize_transactions
    from ledger.simulate import generate_batch

    batch = generate_batch(count=120, seed=1)
    near_miss_groups = {"agent-nearmiss-a", "agent-nearmiss-b"}
    near_miss_hashes = {
        tx_hash
        for tx_hash, group in batch.ground_truth.items()
        if group in near_miss_groups
    }
    near_miss_txns = [t for t in batch.transactions if t.tx_hash in near_miss_hashes]
    assert len(near_miss_txns) >= 2

    # Give each a stable synthetic id so categorization output can be mapped
    # back by tx_hash.
    numbered = [
        dataclasses.replace(t, id=i) for i, t in enumerate(near_miss_txns)
    ]

    cats = categorize_transactions(numbered)
    by_hash = {t.tx_hash: c for t, c in zip(numbered, cats)}

    labels_a = {
        by_hash[tx_hash].category_label
        for tx_hash, group in batch.ground_truth.items()
        if group == "agent-nearmiss-a" and tx_hash in by_hash
    }
    labels_b = {
        by_hash[tx_hash].category_label
        for tx_hash, group in batch.ground_truth.items()
        if group == "agent-nearmiss-b" and tx_hash in by_hash
    }
    assert labels_a, "expected near-miss group a to be present"
    assert labels_b, "expected near-miss group b to be present"
    assert labels_a.isdisjoint(labels_b)


def seed_with_types(conn, rows):
    for tx_hash, sender, memo, timestamp, amount, tx_type in rows:
        conn.execute(
            """INSERT INTO transactions
               (tx_hash, sender_address, receiver_address, amount_micro_usdc,
                timestamp, memo, chain, raw_payload, tx_type)
               VALUES (?, ?, '0xm', ?, ?, ?, 'sim', '{}', ?)""",
            (tx_hash, sender, amount, timestamp, memo, tx_type),
        )
    conn.commit()


def refunded_db(tmp_path: Path):
    conn = connect(tmp_path / "r.db")
    init_schema(conn)
    seed_with_types(
        conn,
        [
            ("0x1", "0xa", None, "2026-08-10T10:00:00Z", 3_000_000, "payment"),
            ("0x2", "0xa", None, "2026-08-10T10:01:00Z", 1_000_000, "payment"),
            ("0x3", "0xa", None, "2026-08-11T10:00:00Z", 1_000_000, TX_TYPE_REFUND),
        ],
    )
    run_categorize(conn)
    return conn


def test_gross_refunded_and_net_are_reported_separately(tmp_path: Path):
    data = build_report(refunded_db(tmp_path), "2026-08-01", "2026-08-31")
    assert data.gross_micro_usdc == 4_000_000
    assert data.refunded_micro_usdc == 1_000_000
    assert data.net_micro_usdc == 3_000_000


def test_net_equals_gross_minus_refunded(tmp_path: Path):
    data = build_report(refunded_db(tmp_path), "2026-08-01", "2026-08-31")
    assert data.net_micro_usdc == data.gross_micro_usdc - data.refunded_micro_usdc


def test_category_line_nets_its_own_refunds(tmp_path: Path):
    data = build_report(refunded_db(tmp_path), "2026-08-01", "2026-08-31")
    line = next(line for line in data.lines if line.category_label == "agent:0xa")
    assert line.gross_micro_usdc == 4_000_000
    assert line.refunded_micro_usdc == 1_000_000
    assert line.net_micro_usdc == 3_000_000


def test_summary_shows_all_three_figures(tmp_path: Path):
    summary = render_summary(build_report(refunded_db(tmp_path), "2026-08-01", "2026-08-31"))
    assert "$4.00" in summary
    assert "$1.00" in summary
    assert "$3.00" in summary
    assert "refund" in summary.lower()


def test_net_can_go_negative_and_renders_with_leading_sign(tmp_path: Path):
    conn = connect(tmp_path / "n.db")
    init_schema(conn)
    seed_with_types(
        conn,
        [
            ("0x1", "0xa", None, "2026-08-10T10:00:00Z", 1_000_000, "payment"),
            ("0x2", "0xa", None, "2026-08-11T10:00:00Z", 2_500_000, TX_TYPE_REFUND),
        ],
    )
    run_categorize(conn)

    data = build_report(conn, "2026-08-01", "2026-08-31")
    assert data.net_micro_usdc == -1_500_000
    assert "-$1.50" in render_summary(data)


def test_money_reconciles_with_refunds(tmp_path: Path):
    conn = refunded_db(tmp_path)
    out = tmp_path / "r.csv"
    write_csv(conn, "2026-08-01", "2026-08-31", out)

    ingested_net = conn.execute(
        "SELECT SUM(CASE WHEN tx_type = 'refund' THEN -amount_micro_usdc "
        "ELSE amount_micro_usdc END) AS n FROM transactions"
    ).fetchone()["n"]

    data = build_report(conn, "2026-08-01", "2026-08-31")
    line_net = sum(line.net_micro_usdc for line in data.lines)

    csv_net = 0
    for row in csv.DictReader(out.read_text().splitlines()):
        micro = usdc_to_micro(row["amount_usdc"])
        csv_net += -micro if row["tx_type"] == "refund" else micro

    assert data.net_micro_usdc == ingested_net
    assert line_net == ingested_net
    assert csv_net == ingested_net

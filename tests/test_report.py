import csv
from pathlib import Path

from ledger.categorize import run_categorize
from ledger.db import connect, init_schema
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
    assert data.total_micro_usdc == 3_500_000


def test_report_includes_transactions_on_the_final_day(tmp_path: Path):
    conn = prepared(tmp_path)
    data = build_report(conn, "2026-08-01", "2026-08-15")

    assert data.transaction_count == 3
    assert data.total_micro_usdc == 3_500_000


def test_report_excludes_the_day_after_the_range(tmp_path: Path):
    conn = prepared(tmp_path)
    data = build_report(conn, "2026-08-01", "2026-08-14")

    assert data.transaction_count == 2
    assert data.total_micro_usdc == 3_000_000


def test_confident_and_uncertain_totals_split_and_sum_to_the_whole(tmp_path: Path):
    conn = prepared(tmp_path)
    data = build_report(conn, "2026-08-01", "2026-08-31")

    assert data.confident_micro_usdc == 3_000_000
    assert data.uncertain_micro_usdc == 500_000
    assert data.confident_micro_usdc + data.uncertain_micro_usdc == data.total_micro_usdc


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


def test_csv_amounts_are_exact_decimal_strings(tmp_path: Path):
    conn = prepared(tmp_path)
    out = tmp_path / "report.csv"
    write_csv(conn, "2026-08-01", "2026-08-31", out)

    rows = list(csv.DictReader(out.read_text().splitlines()))
    amounts = {row["amount_usdc"] for row in rows}
    assert "1.000000" in amounts
    assert "0.500000" in amounts

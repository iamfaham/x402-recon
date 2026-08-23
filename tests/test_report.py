import csv
import json
from decimal import Decimal
from pathlib import Path

from ledger.categorize import run_categorize
from ledger.db import connect, init_schema, load_transactions
from ledger.ingest import ingest_from_dir
from ledger.models import TX_TYPE_REFUND
from ledger.money import usdc_to_micro
from ledger.report import build_report, calibration_state, render_summary, write_csv


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

    assert "not identified" in summary.lower()
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
            "payer_label", "payer_tier", "payer_rule",
            "service_label", "service_rule"} <= set(rows[0])


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
    breakdown_total = sum(line.net_micro_usdc for line in data.payer_lines)

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
    line = next(line for line in data.payer_lines if line.category_label == "agent:0xa")
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


def test_line_with_one_payment_and_one_refund_does_not_read_as_two_payments(
    tmp_path: Path,
):
    # I5: a payer with one payment and one refund must not be reported as
    # "(2 payments)" - that overstates how many payments actually happened.
    conn = connect(tmp_path / "m.db")
    init_schema(conn)
    seed_with_types(
        conn,
        [
            ("0x1", "0xa", None, "2026-08-10T10:00:00Z", 1_000_000, "payment"),
            ("0x2", "0xa", None, "2026-08-11T10:00:00Z", 1_000_000, TX_TYPE_REFUND),
        ],
    )
    run_categorize(conn)

    data = build_report(conn, "2026-08-01", "2026-08-31")
    line = next(line for line in data.payer_lines if line.category_label == "agent:0xa")
    assert line.payment_count == 1
    assert line.refund_count == 1

    summary = render_summary(data)
    assert "(2 payments)" not in summary
    assert "(1 payment, 1 refund)" in summary


def test_money_reconciles_with_refunds(tmp_path: Path):
    conn = refunded_db(tmp_path)
    out = tmp_path / "r.csv"
    write_csv(conn, "2026-08-01", "2026-08-31", out)

    ingested_net = conn.execute(
        "SELECT SUM(CASE WHEN tx_type = 'refund' THEN -amount_micro_usdc "
        "ELSE amount_micro_usdc END) AS n FROM transactions"
    ).fetchone()["n"]

    data = build_report(conn, "2026-08-01", "2026-08-31")
    line_net = sum(line.net_micro_usdc for line in data.payer_lines)

    csv_net = 0
    for row in csv.DictReader(out.read_text().splitlines()):
        micro = usdc_to_micro(row["amount_usdc"])
        csv_net += -micro if row["tx_type"] == "refund" else micro

    assert data.net_micro_usdc == ingested_net
    assert line_net == ingested_net
    assert csv_net == ingested_net


from ledger.models import AXIS_PAYER, AXIS_SERVICE, CONFIDENT, UNCERTAIN


def both_axes_db(tmp_path: Path):
    conn = connect(tmp_path / "b.db")
    init_schema(conn)
    seed_with_types(
        conn,
        [
            ("0x1", "0xa", "weather-api", "2026-08-10T10:00:00Z", 3_000_000, "payment"),
            ("0x2", "0xa", "weather-api", "2026-08-10T10:01:00Z", 1_000_000, "payment"),
            ("0x3", "0xb", "search-api", "2026-08-11T10:00:00Z", 2_000_000, "payment"),
            ("0x4", "0xb", "search-api", "2026-08-11T10:01:00Z", 1_000_000, TX_TYPE_REFUND),
        ],
    )
    run_categorize(conn)
    return conn


def test_report_carries_both_breakdowns(tmp_path: Path):
    data = build_report(both_axes_db(tmp_path), "2026-08-01", "2026-08-31")
    assert data.payer_lines
    assert data.service_lines


def test_both_breakdowns_reconcile_to_the_same_net(tmp_path: Path):
    # Both axes partition the same money. If a transaction is dropped from one
    # axis or double-counted in the other, these stop agreeing.
    data = build_report(both_axes_db(tmp_path), "2026-08-01", "2026-08-31")
    assert sum(line.net_micro_usdc for line in data.payer_lines) == data.net_micro_usdc
    assert sum(line.net_micro_usdc for line in data.service_lines) == data.net_micro_usdc


def test_payer_breakdown_groups_by_sender(tmp_path: Path):
    data = build_report(both_axes_db(tmp_path), "2026-08-01", "2026-08-31")
    labels = {line.category_label for line in data.payer_lines}
    assert "agent:0xa" in labels
    assert "agent:0xb" in labels


def test_service_breakdown_groups_by_memo(tmp_path: Path):
    data = build_report(both_axes_db(tmp_path), "2026-08-01", "2026-08-31")
    labels = {line.category_label for line in data.service_lines}
    assert "service:weather-api" in labels
    assert "service:search-api" in labels


def test_service_lines_are_tiered_confident_or_uncertain(tmp_path: Path):
    # v0.1c: memo_match earned its confidence claim, so service rows are
    # tiered like payer rows - CONFIDENT for a claimed grouping, UNCERTAIN
    # for a declined one - rather than the retired DESCRIPTIVE tier.
    data = build_report(both_axes_db(tmp_path), "2026-08-01", "2026-08-31")
    assert data.service_lines
    assert all(
        line.confidence_tier in (CONFIDENT, UNCERTAIN) for line in data.service_lines
    )
    assert any(line.confidence_tier == CONFIDENT for line in data.service_lines)


def divergent_axes_db(tmp_path: Path):
    """Payer axis and service axis disagree about which rows are confident.

    0x1/0x2 share a sender (0xa) but each carry a memo seen nowhere else, so
    they are CONFIDENT on the payer axis (sender_match) and UNCERTAIN on the
    service axis (memo_match never fires - no repeated memo). 0x3/0x4 have
    distinct, one-off senders but share a memo, so they are UNCERTAIN on the
    payer axis and CONFIDENT on the service axis. The two confident sets are
    disjoint and sum to different totals, so a test built on this fixture
    cannot pass by accident if `confident_micro_usdc` is wired to the wrong
    axis, reads either axis, or OR-folds the two - both_axes_db could not
    catch that because its confident rows happen to coincide on both axes.
    """
    conn = connect(tmp_path / "d.db")
    init_schema(conn)
    seed_with_types(
        conn,
        [
            ("0x1", "0xa", "unique-memo-1", "2026-08-10T10:00:00Z", 3_000_000, "payment"),
            ("0x2", "0xa", "unique-memo-2", "2026-08-10T10:01:00Z", 1_000_000, "payment"),
            ("0x3", "0xc", "shared-memo", "2026-08-11T10:00:00Z", 2_000_000, "payment"),
            ("0x4", "0xd", "shared-memo", "2026-08-11T10:01:00Z", 500_000, "payment"),
        ],
    )
    run_categorize(conn)
    return conn


def test_service_confidence_does_not_inflate_the_payer_confident_total(tmp_path: Path):
    # The trap in this branch. Confidence is per-axis; each axis may earn its
    # own, and they stay separate in the report.
    #
    # both_axes_db is not enough to pin this: every seeded sender there
    # appears exactly twice and every seeded memo appears exactly twice, so
    # payer-confident and service-confident select the identical four rows
    # and the two totals are equal regardless of which axis
    # `confident_micro_usdc` actually reads. divergent_axes_db makes the two
    # axes disagree about which rows are confident, so the totals genuinely
    # differ and this test would fail if `confident_micro_usdc` read
    # `service_tier`, or OR-folded the two tiers, instead of `payer_tier`
    # alone.
    conn = divergent_axes_db(tmp_path)
    data = build_report(conn, "2026-08-01", "2026-08-31")

    payer_confident = sum(
        line.net_micro_usdc
        for line in data.payer_lines
        if line.confidence_tier == CONFIDENT
    )
    service_confident = sum(
        line.net_micro_usdc
        for line in data.service_lines
        if line.confidence_tier == CONFIDENT
    )

    assert payer_confident == 4_000_000  # 0x1 + 0x2, sender_match on 0xa
    assert service_confident == 2_500_000  # 0x3 + 0x4, memo_match on shared-memo
    assert payer_confident != service_confident

    assert data.confident_micro_usdc == payer_confident
    assert data.confident_micro_usdc != service_confident


def test_summary_renders_both_sections(tmp_path: Path):
    summary = render_summary(build_report(both_axes_db(tmp_path), "2026-08-01", "2026-08-31"))
    assert "Who paid you" in summary
    assert "What they paid for" in summary
    assert "memo" in summary.lower()


def test_csv_carries_both_axes(tmp_path: Path):
    conn = both_axes_db(tmp_path)
    out = tmp_path / "b.csv"
    write_csv(conn, "2026-08-01", "2026-08-31", out)

    rows = list(csv.DictReader(out.read_text().splitlines()))
    assert {"payer_label", "payer_tier", "payer_rule",
            "service_label", "service_rule"} <= set(rows[0])
    first = next(r for r in rows if r["tx_hash"] == "0x1")
    assert first["payer_label"] == "agent:0xa"
    assert first["service_label"] == "service:weather-api"


def unlabeled_db(tmp_path: Path):
    """Real-chain shape: no memo, and no ground_truth coverage at all."""
    conn = connect(tmp_path / "u.db")
    init_schema(conn)
    seed_with_types(
        conn,
        [
            ("0x1", "0xa", None, "2026-08-10T10:00:00Z", 3_000_000, "payment"),
            ("0x2", "0xa", None, "2026-08-10T10:01:00Z", 1_000_000, "payment"),
            ("0x3", "0xb", None, "2026-08-11T10:00:00Z", 2_000_000, "payment"),
        ],
    )
    run_categorize(conn)
    return conn


def labeled_db(tmp_path: Path):
    """Every reported tx_hash is present in ground_truth."""
    conn = connect(tmp_path / "l.db")
    init_schema(conn)
    seed_with_types(
        conn,
        [
            ("0x1", "0xa", None, "2026-08-10T10:00:00Z", 3_000_000, "payment"),
            ("0x2", "0xa", None, "2026-08-10T10:01:00Z", 1_000_000, "payment"),
            ("0x3", "0xb", None, "2026-08-11T10:00:00Z", 2_000_000, "payment"),
        ],
    )
    run_categorize(conn)
    conn.executemany(
        "INSERT INTO ground_truth (tx_hash, true_group) VALUES (?, ?)",
        [("0x1", "agent-a"), ("0x2", "agent-a"), ("0x3", "agent-b")],
    )
    conn.commit()
    return conn


def partly_labeled_db(tmp_path: Path):
    """Some, but not all, reported tx_hashes are present in ground_truth."""
    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    seed_with_types(
        conn,
        [
            ("0x1", "0xa", None, "2026-08-10T10:00:00Z", 3_000_000, "payment"),
            ("0x2", "0xa", None, "2026-08-10T10:01:00Z", 1_000_000, "payment"),
            ("0x3", "0xb", None, "2026-08-11T10:00:00Z", 2_000_000, "payment"),
        ],
    )
    run_categorize(conn)
    conn.executemany(
        "INSERT INTO ground_truth (tx_hash, true_group) VALUES (?, ?)",
        [("0x1", "agent-a")],
    )
    conn.commit()
    return conn


def test_state_is_uncalibrated_when_no_ground_truth_covers_the_range(tmp_path):
    data = build_report(unlabeled_db(tmp_path), "2026-08-01", "2026-08-31")
    assert data.labeled_count == 0
    assert calibration_state(data) == "uncalibrated"


def test_state_is_calibrated_when_every_reported_transaction_is_labeled(tmp_path):
    data = build_report(labeled_db(tmp_path), "2026-08-01", "2026-08-31")
    assert data.labeled_count == data.reported_count
    assert calibration_state(data) == "calibrated"


def test_state_is_partial_when_some_are_labeled(tmp_path):
    data = build_report(partly_labeled_db(tmp_path), "2026-08-01", "2026-08-31")
    assert 0 < data.labeled_count < data.reported_count
    assert calibration_state(data) == "partial"


def test_uncalibrated_report_says_confidently_is_uncalibrated_here(tmp_path):
    rendered = render_summary(build_report(unlabeled_db(tmp_path), "2026-08-01", "2026-08-31"))
    assert "uncalibrated here" in rendered
    assert "unmeasured" in rendered


def test_partial_report_states_how_many_were_labeled(tmp_path):
    rendered = render_summary(
        build_report(partly_labeled_db(tmp_path), "2026-08-01", "2026-08-31")
    )
    assert "measured on" in rendered.lower()
    # The reader must be able to see how thin the evidence is.
    assert "of" in rendered


def test_calibrated_report_adds_no_disclaimer(tmp_path):
    rendered = render_summary(build_report(labeled_db(tmp_path), "2026-08-01", "2026-08-31"))
    assert "uncalibrated" not in rendered


def test_the_disclaimer_is_not_tax_or_accounting_advice(tmp_path):
    rendered = render_summary(
        build_report(unlabeled_db(tmp_path), "2026-08-01", "2026-08-31")
    ).lower()
    for forbidden in ("you should", "deductible", "taxable", "file ", "consult"):
        assert forbidden not in rendered


def test_calibration_state_never_moves_any_money_figure(tmp_path):
    # The three helpers seed identical transactions and differ only in
    # ground_truth rows, so every money figure must be identical across all
    # three states. The disclaimer changes what is claimed, never what is
    # counted.
    reports = [
        build_report(helper(tmp_path / name), "2026-08-01", "2026-08-31")
        for name, helper in (
            ("un", unlabeled_db),
            ("part", partly_labeled_db),
            ("full", labeled_db),
        )
    ]
    assert {calibration_state(r) for r in reports} == {
        "uncalibrated",
        "partial",
        "calibrated",
    }
    for field in (
        "confident_micro_usdc",
        "uncertain_micro_usdc",
        "gross_micro_usdc",
        "refunded_micro_usdc",
        "net_micro_usdc",
    ):
        values = {getattr(r, field) for r in reports}
        assert len(values) == 1, f"{field} moved between calibration states: {values}"


def test_confident_total_is_the_hand_computed_figure(tmp_path):
    # Derived by hand from unlabeled_db's seed rows, not from build_report:
    #   0xa sends twice (0x1: 3,000,000 and 0x2: 1,000,000) -> sender_counts["0xa"]
    #   == 2 >= min_occurrences (2), so sender_match fires -> CONFIDENT.
    #     0x1 + 0x2 = 3,000,000 + 1,000,000 = 4,000,000
    #   0xb sends once (0x3: 2,000,000) -> sender_counts["0xb"] == 1
    #   < min_occurrences, so sender_match does not fire -> UNCERTAIN, excluded.
    #   confident total = 4,000,000 (0xb's 2,000,000 is not included)
    data = build_report(unlabeled_db(tmp_path), "2026-08-01", "2026-08-31")
    assert data.confident_micro_usdc == 4_000_000

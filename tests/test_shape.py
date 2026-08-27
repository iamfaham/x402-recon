import pytest

from x402_recon.db import connect, init_schema
from x402_recon.shape import build_shape, render_shape

PAYER_A = "0x" + "11" * 20
PAYER_B = "0x" + "22" * 20
ONE_OFF = "0x" + "33" * 20
RECEIVER = "0x" + "99" * 20


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "t.db")
    init_schema(connection)
    return connection


def _insert(conn, tx_hash, sender, amount, timestamp, tx_type="payment"):
    conn.execute(
        """INSERT INTO transactions
           (tx_hash, sender_address, receiver_address, amount_micro_usdc,
            timestamp, memo, chain, raw_payload, tx_type)
           VALUES (?, ?, ?, ?, ?, NULL, 'base', '{}', ?)""",
        (tx_hash, sender, RECEIVER, amount, timestamp, tx_type),
    )


@pytest.fixture
def populated(conn):
    _insert(conn, "0x1", PAYER_A, 1_000_000, "2026-07-01T00:00:00Z")
    _insert(conn, "0x2", PAYER_A, 1_000_000, "2026-07-02T00:00:00Z")
    _insert(conn, "0x3", PAYER_A, 1_000_000, "2026-07-03T00:00:00Z")
    _insert(conn, "0x4", PAYER_B, 2_000_000, "2026-07-04T00:00:00Z")
    _insert(conn, "0x5", PAYER_B, 2_000_000, "2026-07-05T00:00:00Z")
    _insert(conn, "0x6", ONE_OFF, 500_000, "2026-07-06T00:00:00Z")
    _insert(conn, "0x7", PAYER_A, 250_000, "2026-07-07T00:00:00Z", "refund")
    conn.commit()
    return conn


def test_counts_payments_and_refunds_separately(populated):
    report = build_shape(populated)
    assert report.transaction_count == 7
    assert report.payment_count == 6
    assert report.refund_count == 1


def test_reports_the_date_span(populated):
    report = build_shape(populated)
    assert report.first_timestamp == "2026-07-01T00:00:00Z"
    assert report.last_timestamp == "2026-07-07T00:00:00Z"


def test_counts_distinct_senders(populated):
    assert build_shape(populated).distinct_senders == 3


def test_bands_senders_by_repeat_count(populated):
    # PAYER_A appears 4 times (3 payments + 1 refund), PAYER_B twice,
    # ONE_OFF once.
    bands = build_shape(populated).senders_by_band
    assert bands == {"once": 1, "twice": 1, "three_or_more": 1}


def test_bands_carry_the_money_each_covers(populated):
    net = build_shape(populated).net_by_band
    assert set(net) == {"once", "twice", "three_or_more"}
    assert net["once"] == 500_000
    assert net["twice"] == 4_000_000
    # 3 payments of 1_000_000 less a 250_000 refund.
    assert net["three_or_more"] == 2_750_000


def test_claimable_count_is_what_sender_match_would_claim(populated):
    # min_occurrences defaults to 2, so PAYER_A's 4 and PAYER_B's 2 qualify
    # and ONE_OFF's single transaction does not.
    assert build_shape(populated).claimable_count == 6


def test_empty_database_reports_zeroes_and_no_span(conn):
    report = build_shape(conn)
    assert report.transaction_count == 0
    assert report.distinct_senders == 0
    assert report.first_timestamp is None
    assert report.last_timestamp is None


def test_render_contains_no_precision_or_recall_figure(populated):
    # THE POINT OF STAGE 1. Shape informs whether the sample bar is reachable.
    # If it could reveal accuracy, the threshold could be tuned to the answer
    # and the pre-registration would be worthless.
    rendered = render_shape(build_shape(populated)).lower()
    for forbidden in ("precision", "recall", "b-cubed", "b3", "accuracy", "verdict"):
        assert forbidden not in rendered


def test_shape_module_does_not_import_the_scorer():
    # A stronger guarantee than checking the rendered string: the module must
    # not be able to compute a score at all.
    import pathlib

    source = pathlib.Path("src/x402_recon/shape.py").read_text()
    assert "evaluate" not in source

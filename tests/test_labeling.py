import json

import pytest

from ledger.db import connect, init_schema
from ledger.labeling import LABELING_INSTRUCTIONS, build_worksheet, write_worksheet

PAYER_A = "0x" + "11" * 20
ONE_OFF = "0x" + "33" * 20
RECEIVER = "0x" + "99" * 20


@pytest.fixture
def conn(tmp_path):
    # tmp_path, not ":memory:" - every other test in this repo uses
    # connect(tmp_path / "t.db"), and connect() takes a Path.
    connection = connect(tmp_path / "t.db")
    init_schema(connection)
    for tx_hash, sender, amount, ts in (
        ("0x1", PAYER_A, 1_000_000, "2026-07-01T00:00:00Z"),
        ("0x2", PAYER_A, 1_000_000, "2026-07-02T00:00:00Z"),
        ("0x3", ONE_OFF, 500_000, "2026-07-03T00:00:00Z"),
    ):
        connection.execute(
            """INSERT INTO transactions
               (tx_hash, sender_address, receiver_address, amount_micro_usdc,
                timestamp, memo, chain, raw_payload, tx_type)
               VALUES (?, ?, ?, ?, ?, NULL, 'base', '{}', 'payment')""",
            (tx_hash, sender, RECEIVER, amount, ts),
        )
    connection.commit()
    return connection


def test_worksheet_has_one_row_per_distinct_sender(conn):
    rows = build_worksheet(conn)
    assert len(rows) == 2
    assert {row["sender_address"] for row in rows} == {PAYER_A, ONE_OFF}


def test_worksheet_carries_counts_and_volume_to_help_a_human_prioritise(conn):
    rows = {row["sender_address"]: row for row in build_worksheet(conn)}
    assert rows[PAYER_A]["transaction_count"] == 2
    assert rows[PAYER_A]["net_micro_usdc"] == 2_000_000
    assert rows[ONE_OFF]["transaction_count"] == 1


def test_every_row_starts_unlabeled(conn):
    # The tool never assigns truth. A row that arrived pre-filled would be the
    # tool labeling by address, which is exactly the circularity being avoided.
    for row in build_worksheet(conn):
        assert row["true_group"] is None
        assert row["evidence"] == ""


def test_worksheet_rows_sort_by_volume_descending(conn):
    rows = build_worksheet(conn)
    assert rows[0]["sender_address"] == PAYER_A


def test_instructions_forbid_labeling_from_the_address(conn):
    text = LABELING_INSTRUCTIONS.lower()
    assert "independent" in text
    assert "unlabelable" in text
    assert "address" in text


def test_written_worksheet_leads_with_the_instructions(tmp_path, conn):
    path = write_worksheet(build_worksheet(conn), tmp_path / "worksheet.json")
    document = json.loads(path.read_text())
    assert document["instructions"] == LABELING_INSTRUCTIONS
    assert len(document["senders"]) == 2


def test_written_worksheet_is_not_a_ground_truth_file(tmp_path, conn):
    # ingest reads ground_truth.json. The worksheet must not be mistakable for
    # one, or a half-filled worksheet could be ingested as truth.
    path = write_worksheet(build_worksheet(conn), tmp_path / "worksheet.json")
    assert path.name != "ground_truth.json"
    assert "instructions" in json.loads(path.read_text())

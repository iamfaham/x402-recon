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


def test_worksheet_has_one_row_per_transaction_not_per_sender(conn):
    # PAYER_A has 2 transactions, ONE_OFF has 1: 3 total rows.
    rows = build_worksheet(conn)
    assert len(rows) == 3
    assert {row["tx_hash"] for row in rows} == {"0x1", "0x2", "0x3"}


def test_worksheet_rows_for_the_same_sender_are_grouped_together(conn):
    rows = build_worksheet(conn)
    senders_in_order = [row["sender_address"] for row in rows]
    payer_a_positions = [i for i, s in enumerate(senders_in_order) if s == PAYER_A]
    assert payer_a_positions == list(range(payer_a_positions[0], payer_a_positions[-1] + 1))


def test_every_row_starts_unlabeled(conn):
    # The tool never assigns truth. A row that arrived pre-filled would be the
    # tool labeling by address, which is exactly the circularity being avoided.
    for row in build_worksheet(conn):
        assert row["true_group"] is None
        assert row["evidence"] == ""


def test_worksheet_rows_sort_by_volume_descending(conn):
    # PAYER_A's net (2,000,000) outweighs ONE_OFF's (500,000), so PAYER_A's
    # rows lead the worksheet even though sorting is now per-row.
    rows = build_worksheet(conn)
    assert rows[0]["sender_address"] == PAYER_A


def test_a_labeler_can_split_one_sender_into_two_entities(conn):
    # THE POINT OF THE RE-KEY. A per-sender worksheet could not express this;
    # a per-transaction one can, because true_group is set per row.
    rows = build_worksheet(conn)
    payer_a_rows = [r for r in rows if r["sender_address"] == PAYER_A]
    assert len(payer_a_rows) == 2
    payer_a_rows[0]["true_group"] = "entity-one"
    payer_a_rows[1]["true_group"] = "entity-two"
    assert payer_a_rows[0]["true_group"] != payer_a_rows[1]["true_group"]


def test_instructions_forbid_labeling_from_the_address(conn):
    text = LABELING_INSTRUCTIONS.lower()
    assert "independent" in text
    assert "unlabelable" in text
    assert "address" in text
    assert "facilitator" in text


def test_written_worksheet_leads_with_the_instructions(tmp_path, conn):
    path = write_worksheet(build_worksheet(conn), tmp_path / "worksheet.json")
    document = json.loads(path.read_text())
    assert document["instructions"] == LABELING_INSTRUCTIONS
    assert len(document["senders"]) == 3


def test_write_worksheet_refuses_the_ground_truth_filename(tmp_path, conn):
    # ingest reads ground_truth.json. A half-filled worksheet written there
    # would crash ingest mid-transaction and take the transaction rows with it.
    with pytest.raises(ValueError, match="ground_truth.json"):
        write_worksheet(build_worksheet(conn), tmp_path / "ground_truth.json")


def test_written_worksheet_is_not_named_ground_truth(tmp_path, conn):
    # Ensure the happy path still works: normal filenames produce the
    # instructions + senders structure.
    path = write_worksheet(build_worksheet(conn), tmp_path / "worksheet.json")
    document = json.loads(path.read_text())
    assert path.name != "ground_truth.json"
    assert "instructions" in document
    assert "senders" in document

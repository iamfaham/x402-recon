from pathlib import Path

from ledger.db import connect, init_schema, load_transactions
from ledger.models import Transaction


def make_tx(tx_hash: str = "0xabc", **overrides) -> Transaction:
    defaults = dict(
        tx_hash=tx_hash,
        sender_address="0xsender",
        receiver_address="0xreceiver",
        amount_micro_usdc=1234,
        timestamp="2026-08-18T10:00:00Z",
        memo=None,
        chain="base-sepolia-sim",
        raw_payload="{}",
    )
    defaults.update(overrides)
    return Transaction(**defaults)


def test_init_schema_creates_all_three_tables(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    init_schema(conn)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {row["name"] for row in rows}
    assert {"transactions", "categorizations", "ground_truth"} <= names


def test_init_schema_is_idempotent(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    init_schema(conn)
    init_schema(conn)


def test_transaction_round_trips_through_sqlite(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    init_schema(conn)
    tx = make_tx(memo="weather-api", amount_micro_usdc=999_999)
    conn.execute(
        """INSERT INTO transactions
           (tx_hash, sender_address, receiver_address, amount_micro_usdc,
            timestamp, memo, chain, raw_payload)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tx.tx_hash,
            tx.sender_address,
            tx.receiver_address,
            tx.amount_micro_usdc,
            tx.timestamp,
            tx.memo,
            tx.chain,
            tx.raw_payload,
        ),
    )
    conn.commit()

    loaded = load_transactions(conn)
    assert len(loaded) == 1
    assert loaded[0].tx_hash == "0xabc"
    assert loaded[0].memo == "weather-api"
    assert loaded[0].amount_micro_usdc == 999_999
    assert isinstance(loaded[0].amount_micro_usdc, int)
    assert loaded[0].id is not None


def test_tx_hash_is_unique(tmp_path: Path):
    import sqlite3

    import pytest

    conn = connect(tmp_path / "test.db")
    init_schema(conn)
    sql = """INSERT INTO transactions
             (tx_hash, sender_address, receiver_address, amount_micro_usdc,
              timestamp, memo, chain, raw_payload)
             VALUES ('0xdup', 'a', 'b', 1, '2026-08-18T10:00:00Z', NULL, 'c', '{}')"""
    conn.execute(sql)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)


def test_load_transactions_returns_empty_list_when_no_data(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    init_schema(conn)
    assert load_transactions(conn) == []

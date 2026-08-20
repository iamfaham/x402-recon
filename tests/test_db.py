from pathlib import Path

import pytest

from ledger.db import SCHEMA_VERSION, SchemaVersionError, connect, init_schema, load_transactions
from ledger.models import AXIS_PAYER, AXIS_SERVICE, TX_TYPE_PAYMENT, TX_TYPE_REFUND, Transaction


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


def test_schema_creates_version_and_hazards_tables(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    names = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"schema_version", "hazards"} <= names


def test_schema_version_is_recorded_once(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    init_schema(conn)
    rows = conn.execute("SELECT version FROM schema_version").fetchall()
    assert len(rows) == 1
    assert rows[0]["version"] == SCHEMA_VERSION


def test_stale_database_without_version_table_is_refused(tmp_path: Path):
    conn = connect(tmp_path / "old.db")
    # Simulate a v0 database: transactions exist, schema_version does not.
    conn.execute("CREATE TABLE transactions (id INTEGER PRIMARY KEY)")
    conn.commit()

    with pytest.raises(SchemaVersionError) as exc:
        init_schema(conn)
    assert "out of date" in str(exc.value).lower()


def test_wrong_schema_version_is_refused(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION + 1,))
    conn.commit()

    with pytest.raises(SchemaVersionError):
        init_schema(conn)


def test_tx_type_defaults_to_payment_and_round_trips(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    conn.execute(
        """INSERT INTO transactions
           (tx_hash, sender_address, receiver_address, amount_micro_usdc,
            timestamp, memo, chain, raw_payload)
           VALUES ('0xa', 's', 'r', 10, '2026-08-18T10:00:00Z', NULL, 'sim', '{}')"""
    )
    conn.execute(
        """INSERT INTO transactions
           (tx_hash, sender_address, receiver_address, amount_micro_usdc,
            timestamp, memo, chain, raw_payload, tx_type)
           VALUES ('0xb', 's', 'r', 4, '2026-08-18T11:00:00Z', NULL, 'sim', '{}', ?)""",
        (TX_TYPE_REFUND,),
    )
    conn.commit()

    loaded = {t.tx_hash: t for t in load_transactions(conn)}
    assert loaded["0xa"].tx_type == TX_TYPE_PAYMENT
    assert loaded["0xb"].tx_type == TX_TYPE_REFUND


def test_schema_version_is_three(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    assert SCHEMA_VERSION == 3
    assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == 3


def test_service_truth_table_exists(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    names = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "service_truth" in names


def _one_transaction(conn) -> int:
    conn.execute(
        """INSERT INTO transactions
           (tx_hash, sender_address, receiver_address, amount_micro_usdc,
            timestamp, memo, chain, raw_payload)
           VALUES ('0xa', 's', 'r', 10, '2026-08-18T10:00:00Z', NULL, 'sim', '{}')"""
    )
    conn.commit()
    return conn.execute("SELECT id FROM transactions").fetchone()["id"]


def _insert_categorization(conn, tx_id: int, axis: str, label: str):
    conn.execute(
        """INSERT OR REPLACE INTO categorizations
           (transaction_id, axis, category_label, confidence_tier, rule_matched,
            categorized_at)
           VALUES (?, ?, ?, 'confident', 'sender_match', '2026-08-19T10:00:00Z')""",
        (tx_id, axis, label),
    )
    conn.commit()


def test_one_transaction_holds_a_row_per_axis(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    tx_id = _one_transaction(conn)

    _insert_categorization(conn, tx_id, AXIS_PAYER, "agent:0xa")
    _insert_categorization(conn, tx_id, AXIS_SERVICE, "service:weather-api")

    rows = conn.execute("SELECT axis, category_label FROM categorizations").fetchall()
    assert {r["axis"] for r in rows} == {AXIS_PAYER, AXIS_SERVICE}
    assert len(rows) == 2


def test_re_categorizing_one_axis_replaces_only_that_axis(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    tx_id = _one_transaction(conn)

    _insert_categorization(conn, tx_id, AXIS_PAYER, "agent:first")
    _insert_categorization(conn, tx_id, AXIS_SERVICE, "service:weather-api")
    _insert_categorization(conn, tx_id, AXIS_PAYER, "agent:second")

    rows = {
        r["axis"]: r["category_label"]
        for r in conn.execute("SELECT axis, category_label FROM categorizations")
    }
    assert rows[AXIS_PAYER] == "agent:second"
    assert rows[AXIS_SERVICE] == "service:weather-api"
    assert len(rows) == 2

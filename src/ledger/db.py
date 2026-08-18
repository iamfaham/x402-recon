"""SQLite storage for Ledger.

Raw transactions are never mutated after ingest. Categorizations live in a
separate table so the cascade can be tuned and re-run without touching source
data.
"""

import sqlite3
from pathlib import Path

from ledger.models import Transaction

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id                INTEGER PRIMARY KEY,
    tx_hash           TEXT    NOT NULL UNIQUE,
    sender_address    TEXT    NOT NULL,
    receiver_address  TEXT    NOT NULL,
    amount_micro_usdc INTEGER NOT NULL,
    timestamp         TEXT    NOT NULL,
    memo              TEXT,
    chain             TEXT    NOT NULL,
    raw_payload       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS categorizations (
    transaction_id  INTEGER PRIMARY KEY REFERENCES transactions(id),
    category_label  TEXT NOT NULL,
    confidence_tier TEXT NOT NULL,
    rule_matched    TEXT NOT NULL,
    categorized_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ground_truth (
    tx_hash    TEXT PRIMARY KEY,
    true_group TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transactions_timestamp
    ON transactions(timestamp);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with row access by column name and FKs enforced."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if absent. Safe to call repeatedly."""
    conn.executescript(_SCHEMA)
    conn.commit()


def load_transactions(conn: sqlite3.Connection) -> list[Transaction]:
    """Load all transactions, oldest first."""
    rows = conn.execute(
        """SELECT id, tx_hash, sender_address, receiver_address,
                  amount_micro_usdc, timestamp, memo, chain, raw_payload
           FROM transactions ORDER BY timestamp, id"""
    ).fetchall()
    return [
        Transaction(
            id=row["id"],
            tx_hash=row["tx_hash"],
            sender_address=row["sender_address"],
            receiver_address=row["receiver_address"],
            amount_micro_usdc=row["amount_micro_usdc"],
            timestamp=row["timestamp"],
            memo=row["memo"],
            chain=row["chain"],
            raw_payload=row["raw_payload"],
        )
        for row in rows
    ]

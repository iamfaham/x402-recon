"""SQLite storage for Ledger.

Raw transactions are never mutated after ingest. Categorizations live in a
separate table so the cascade can be tuned and re-run without touching source
data.
"""

import sqlite3
from pathlib import Path

from ledger.models import TX_TYPE_PAYMENT, TX_TYPE_REFUND, Transaction

SCHEMA_VERSION = 2


class SchemaVersionError(RuntimeError):
    """Raised when an existing database was written by a different schema."""


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
    raw_payload       TEXT    NOT NULL,
    tx_type           TEXT    NOT NULL DEFAULT 'payment'
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

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS hazards (
    tx_hash TEXT PRIMARY KEY,
    hazard  TEXT NOT NULL
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
    """Create tables if absent, refusing a database from a different schema.

    Migration is deliberately unsupported. Databases are regenerable scratch,
    so failing clearly beats migrating badly.
    """
    names = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    if "transactions" in names and "schema_version" not in names:
        raise SchemaVersionError(
            "This database is out of date (written before schema versioning). "
            "Delete it and re-ingest."
        )
    if "schema_version" in names:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        found = None if row is None else row["version"]
        if found != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"This database is out of date (schema version {found}, "
                f"expected {SCHEMA_VERSION}). Delete it and re-ingest."
            )

    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO schema_version (version) SELECT ? "
        "WHERE NOT EXISTS (SELECT 1 FROM schema_version)",
        (SCHEMA_VERSION,),
    )
    conn.commit()


def load_transactions(conn: sqlite3.Connection) -> list[Transaction]:
    """Load all transactions, oldest first."""
    rows = conn.execute(
        """SELECT id, tx_hash, sender_address, receiver_address,
                  amount_micro_usdc, timestamp, memo, chain, raw_payload, tx_type
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
            tx_type=row["tx_type"],
        )
        for row in rows
    ]

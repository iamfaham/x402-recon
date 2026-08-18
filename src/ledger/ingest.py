"""Ingest: the seam between a data source and the rest of the pipeline.

This is the only stage that knows where data came from. Swapping the simulator
for real Base Sepolia transactions or a public dataset changes this file alone.

Nothing is ever silently dropped. A rejected row is a row of money the business
received that would otherwise vanish from their revenue total without a trace,
so rejects are counted and surfaced in the run summary.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ledger.models import Transaction

_REQUIRED_FIELDS = (
    "tx_hash",
    "sender_address",
    "receiver_address",
    "amount_micro_usdc",
    "timestamp",
    "chain",
)
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class IngestResult:
    """What happened during one ingest run."""

    inserted: int
    skipped_duplicates: int
    rejects: list[tuple[str, str]]


def _validate(row: dict) -> tuple[Transaction | None, str | None]:
    """Return (transaction, None) or (None, reason)."""
    for field in _REQUIRED_FIELDS:
        if field not in row or row[field] is None:
            return None, f"missing required field: {field}"

    amount = row["amount_micro_usdc"]
    if isinstance(amount, bool) or not isinstance(amount, int):
        return None, f"amount must be an integer in micro-USDC, got {amount!r}"
    if amount < 0:
        return None, f"amount must not be negative, got {amount}"

    try:
        datetime.strptime(row["timestamp"], _TIMESTAMP_FORMAT)
    except (ValueError, TypeError):
        return None, f"timestamp must be ISO 8601 UTC, got {row['timestamp']!r}"

    return (
        Transaction(
            tx_hash=row["tx_hash"],
            sender_address=row["sender_address"],
            receiver_address=row["receiver_address"],
            amount_micro_usdc=amount,
            timestamp=row["timestamp"],
            memo=row.get("memo"),
            chain=row["chain"],
            raw_payload=row.get("raw_payload", "{}"),
        ),
        None,
    )


def ingest_from_dir(conn: sqlite3.Connection, source_dir: Path) -> IngestResult:
    """Load transactions.json (and ground_truth.json if present) into SQLite."""
    rows = json.loads((source_dir / "transactions.json").read_text())

    inserted = 0
    skipped = 0
    rejects: list[tuple[str, str]] = []

    for index, row in enumerate(rows):
        identifier = row.get("tx_hash", f"<row {index}>") if isinstance(row, dict) else f"<row {index}>"
        if not isinstance(row, dict):
            rejects.append((identifier, "row is not a JSON object"))
            continue

        transaction, reason = _validate(row)
        if transaction is None:
            rejects.append((identifier, reason or "unknown validation failure"))
            continue

        try:
            conn.execute(
                """INSERT INTO transactions
                   (tx_hash, sender_address, receiver_address, amount_micro_usdc,
                    timestamp, memo, chain, raw_payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    transaction.tx_hash,
                    transaction.sender_address,
                    transaction.receiver_address,
                    transaction.amount_micro_usdc,
                    transaction.timestamp,
                    transaction.memo,
                    transaction.chain,
                    transaction.raw_payload,
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            skipped += 1

    ground_truth_path = source_dir / "ground_truth.json"
    if ground_truth_path.exists():
        truth = json.loads(ground_truth_path.read_text())
        conn.executemany(
            "INSERT OR REPLACE INTO ground_truth (tx_hash, true_group) VALUES (?, ?)",
            list(truth.items()),
        )

    conn.commit()
    return IngestResult(inserted=inserted, skipped_duplicates=skipped, rejects=rejects)


def format_ingest_summary(result: IngestResult) -> str:
    """Human-readable run summary. Rejects are always shown, never hidden."""
    lines = [
        "Ingest complete.",
        f"  Inserted:            {result.inserted}",
        f"  Skipped (duplicate): {result.skipped_duplicates}",
        f"  Rejected:            {len(result.rejects)}",
    ]
    if result.rejects:
        lines.append("")
        lines.append("  Rejected rows (these were NOT counted as revenue):")
        for identifier, reason in result.rejects:
            lines.append(f"    - {identifier}: {reason}")
    return "\n".join(lines)

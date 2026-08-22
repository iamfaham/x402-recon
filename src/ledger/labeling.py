"""Emit a worksheet for a human to establish payer ground truth.

The tool never assigns truth. It cannot: the only signal it has is the sender
address, and that is precisely the signal being tested. Labeling from it would
make `sender_match` correct by construction and the measurement worthless.
"""

import json
import sqlite3
from pathlib import Path

from ledger.models import TX_TYPE_PAYMENT

LABELING_INSTRUCTIONS = (
    "Fill in `true_group` for each sender you can identify, and record what "
    "convinced you in `evidence`. Two senders share a true_group only when "
    "they are the same real-world entity.\n\n"
    "The evidence MUST be independent of the sender address itself - a "
    "Basename or ENS name, an explorer entity label, a shared funding source, "
    "a published agent identity. If the only thing linking or separating two "
    "senders is their addresses, you are re-deriving the rule under test and "
    "the measurement becomes worthless.\n\n"
    "Leave `true_group` as null when you cannot tell. Unlabelable is an "
    "honest answer and a common one; a guess is not. Only labeled rows are "
    "scored, so leaving a row blank costs coverage, never correctness."
)


def build_worksheet(conn: sqlite3.Connection) -> list[dict]:
    """One row per distinct sender, heaviest first, all rows unlabeled."""
    rows = conn.execute(
        "SELECT sender_address, amount_micro_usdc, tx_type FROM transactions"
    ).fetchall()

    by_sender: dict[str, list] = {}
    for row in rows:
        by_sender.setdefault(row["sender_address"], []).append(row)

    worksheet = [
        {
            "sender_address": sender,
            "transaction_count": len(members),
            "net_micro_usdc": sum(
                member["amount_micro_usdc"]
                if member["tx_type"] == TX_TYPE_PAYMENT
                else -member["amount_micro_usdc"]
                for member in members
            ),
            "true_group": None,
            "evidence": "",
        }
        for sender, members in by_sender.items()
    ]
    worksheet.sort(key=lambda row: (-row["net_micro_usdc"], row["sender_address"]))
    return worksheet


def write_worksheet(rows: list[dict], path: Path) -> Path:
    """Write the worksheet with its instructions attached.

    Deliberately not named ground_truth.json: `ingest` reads that name, and a
    half-filled worksheet must never be ingestable as truth.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"instructions": LABELING_INSTRUCTIONS, "senders": rows}, indent=2)
    )
    return path

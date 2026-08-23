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
    "Each row is one transaction, not one sender. Senders that share every "
    "transaction's evidence will naturally get the same true_group on every "
    "row. But if you find evidence that one address was used by more than "
    "one real entity - a custodial wallet, an exchange withdrawal address, "
    "a facilitator paying on behalf of several end users - give those "
    "transactions DIFFERENT true_group values even though the sender_address "
    "is identical. That split is the one thing this worksheet exists to let "
    "you record.\n\n"
    "Leave `true_group` as null when you cannot tell. Unlabelable is an "
    "honest answer and a common one; a guess is not. Only labeled rows are "
    "scored, so leaving a row blank costs coverage, never correctness."
)


def build_worksheet(conn: sqlite3.Connection) -> list[dict]:
    """One row per TRANSACTION, grouped and sorted by sender, all unlabeled.

    Keyed by tx_hash rather than sender_address so a labeler can express the
    one case that actually costs sender_match its precision: one address
    serving more than one real entity (a custodial wallet, an exchange
    withdrawal address, an x402 facilitator relayer). A worksheet keyed by
    address cannot express that split, which would make the confidence
    criterion unfalsifiable - every predicted cluster would share a
    true_group by construction, for any labeling.
    """
    rows = conn.execute(
        "SELECT tx_hash, sender_address, amount_micro_usdc, tx_type "
        "FROM transactions"
    ).fetchall()

    by_sender: dict[str, list] = {}
    for row in rows:
        by_sender.setdefault(row["sender_address"], []).append(row)

    def net_for(members):
        return sum(
            member["amount_micro_usdc"]
            if member["tx_type"] == TX_TYPE_PAYMENT
            else -member["amount_micro_usdc"]
            for member in members
        )

    worksheet = []
    for sender, members in sorted(
        by_sender.items(), key=lambda item: (-net_for(item[1]), item[0])
    ):
        for member in members:
            worksheet.append(
                {
                    "tx_hash": member["tx_hash"],
                    "sender_address": sender,
                    "amount_micro_usdc": member["amount_micro_usdc"],
                    "tx_type": member["tx_type"],
                    "true_group": None,
                    "evidence": "",
                }
            )
    return worksheet


def write_worksheet(rows: list[dict], path: Path) -> Path:
    """Write the worksheet with its instructions attached.

    Deliberately not named ground_truth.json: `ingest` reads that name, and a
    half-filled worksheet must never be ingestable as truth.
    """
    if path.name == "ground_truth.json":
        raise ValueError(
            "refusing to write the worksheet as ground_truth.json - ingest reads "
            "that filename, and a half-filled worksheet must never be loaded as "
            "truth. Choose another name."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"instructions": LABELING_INSTRUCTIONS, "senders": rows}, indent=2)
    )
    return path

"""Canonical data shapes for Ledger.

Transaction is the schema the ingest seam targets. Any future data source (Base
Sepolia, a public dataset) produces Transactions; nothing downstream changes.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Transaction:
    """One stablecoin payment received."""

    tx_hash: str
    sender_address: str
    receiver_address: str
    amount_micro_usdc: int
    timestamp: str
    memo: str | None
    chain: str
    raw_payload: str
    id: int | None = None


@dataclass(frozen=True)
class Categorization:
    """The cascade's verdict on one transaction, and why."""

    transaction_id: int
    category_label: str
    confidence_tier: str
    rule_matched: str
    categorized_at: str

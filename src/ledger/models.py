"""Canonical data shapes for Ledger.

Transaction is the schema the ingest seam targets. Any future data source (Base
Sepolia, a public dataset) produces Transactions; nothing downstream changes.
"""

from dataclasses import dataclass

# --- Canonical vocabulary -------------------------------------------------
# Every stage shares these strings. They live here, beside the data shapes,
# because a value duplicated across modules is a value that will eventually
# disagree with itself.

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Ground-truth vocabulary. UNGROUPABLE marks a transaction that genuinely
# belongs to no group. A human labeling real transactions writes this string,
# so it is ground-truth vocabulary rather than simulator vocabulary.
UNGROUPABLE = "__ungroupable__"

# Confidence tiers.
CONFIDENT = "confident"
UNCERTAIN = "uncertain"

# The label given when no rule fired.
UNCATEGORIZED = "uncategorized"

# Cascade rule names.
RULE_SENDER_MATCH = "sender_match"
RULE_MEMO_MATCH = "memo_match"
RULE_TIME_CLUSTER = "time_cluster"
RULE_NONE = "none"

# Transaction direction.
TX_TYPE_PAYMENT = "payment"
TX_TYPE_REFUND = "refund"


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

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

# A grouping that is stated, not claimed. The row records how the grouping was
# formed without asserting how far to trust it.
#
# Deliberately distinct from UNCERTAIN. Uncertain means the tool guessed and
# knows it might be wrong; descriptive means it is not guessing at all, only
# reporting what the payer's memo said. Collapsing the two would tell a reader
# the service axis is unreliable, which is a different false claim.
DESCRIPTIVE = "descriptive"

# Grouping axes. A transaction carries one categorization per axis: who paid
# (payer) and what they paid for (service). Collapsing these into one field is
# what let a service grouping be reported as a confident payer identification.
AXIS_PAYER = "payer"
AXIS_SERVICE = "service"

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
    tx_type: str = TX_TYPE_PAYMENT
    id: int | None = None


@dataclass(frozen=True)
class Categorization:
    """The cascade's verdict on one transaction along one axis, and why."""

    transaction_id: int
    axis: str
    category_label: str
    confidence_tier: str
    rule_matched: str
    categorized_at: str

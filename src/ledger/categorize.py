"""The categorization cascade.

Transactions pass through ordered rules; the first to fire assigns the label and
records why. Rules that group on repetition are confident because repetition is
evidence. Rules that group on proximity are uncertain because proximity is a
guess.

Nothing is ever forced into a bucket. A transaction with no confident match
stays explicitly uncategorized — the product's worst failure is false
confidence, not low coverage.
"""

from collections import Counter

from ledger.config import CascadeConfig
from ledger.models import Transaction

CONFIDENT = "confident"
UNCERTAIN = "uncertain"
UNCATEGORIZED = "uncategorized"

RULE_SENDER_MATCH = "sender_match"
RULE_MEMO_MATCH = "memo_match"
RULE_TIME_CLUSTER = "time_cluster"
RULE_NONE = "none"


def is_generic_memo(memo: str | None, config: CascadeConfig) -> bool:
    """A memo is generic when it carries no grouping signal."""
    if memo is None:
        return True
    return memo.strip().lower() in config.generic_memos


def build_sender_counts(txns: list[Transaction]) -> Counter[str]:
    """How many times each sender address appears in the dataset."""
    return Counter(t.sender_address for t in txns)


def build_memo_counts(txns: list[Transaction], config: CascadeConfig) -> Counter[str]:
    """How many times each non-generic memo appears in the dataset."""
    return Counter(
        t.memo.strip() for t in txns if not is_generic_memo(t.memo, config)
    )

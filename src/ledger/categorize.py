"""The categorization cascade.

Transactions pass through ordered rules; the first to fire assigns the label and
records why. Rules that group on repetition are confident because repetition is
evidence. Rules that group on proximity are uncertain because proximity is a
guess.

Nothing is ever forced into a bucket. A transaction with no confident match
stays explicitly uncategorized — the product's worst failure is false
confidence, not low coverage.
"""

import sqlite3
from collections import Counter
from datetime import UTC, datetime

from ledger.config import DEFAULT_CONFIG, CascadeConfig
from ledger.db import load_transactions
from ledger.models import (
    AXIS_PAYER,
    AXIS_SERVICE,
    CONFIDENT,
    RULE_MEMO_MATCH,
    RULE_NONE,
    RULE_SENDER_MATCH,
    TIMESTAMP_FORMAT,
    UNCATEGORIZED,
    UNCERTAIN,
    Categorization,
    Transaction,
)


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


def categorize_payers(
    txns: list[Transaction], config: CascadeConfig, categorized_at: str
) -> list[Categorization]:
    """Answer 'who paid this' for every transaction.

    Repetition of a sender address is evidence of identity, so sender_match
    claims confidence. A shared memo is deliberately NOT consulted here: it
    identifies a service, not a payer, and treating it as identity is what
    let unrelated strangers be reported as one payer.
    """
    sender_counts = build_sender_counts(txns)

    results = []
    for transaction in txns:
        label, tier, rule = UNCATEGORIZED, UNCERTAIN, RULE_NONE

        if sender_counts[transaction.sender_address] >= config.min_occurrences:
            label = f"agent:{transaction.sender_address}"
            tier, rule = CONFIDENT, RULE_SENDER_MATCH

        results.append(
            Categorization(
                transaction_id=transaction.id,
                axis=AXIS_PAYER,
                category_label=label,
                confidence_tier=tier,
                rule_matched=rule,
                categorized_at=categorized_at,
            )
        )
    return results


def categorize_services(
    txns: list[Transaction], config: CascadeConfig, categorized_at: str
) -> list[Categorization]:
    """Answer 'what was this paid for' for every transaction.

    Grouping is by exact memo string, which carries an inference - that the same
    memo means the same service - so the result is measured. memo_match cleared
    the calibration floor (B-cubed precision >= CALIBRATION_THRESHOLD on at
    least MIN_VERDICT_SAMPLE firings, measured at the canonical count), so this
    axis now mirrors the payer cascade: claimed rows are confident, declined
    rows are uncertain.
    """
    memo_counts = build_memo_counts(txns, config)

    results = []
    for transaction in txns:
        label, tier, rule = UNCATEGORIZED, UNCERTAIN, RULE_NONE
        memo = None if transaction.memo is None else transaction.memo.strip()

        if (
            not is_generic_memo(transaction.memo, config)
            and memo is not None
            and memo_counts[memo] >= config.min_occurrences
        ):
            label = f"service:{memo}"
            tier, rule = CONFIDENT, RULE_MEMO_MATCH

        results.append(
            Categorization(
                transaction_id=transaction.id,
                axis=AXIS_SERVICE,
                category_label=label,
                confidence_tier=tier,
                rule_matched=rule,
                categorized_at=categorized_at,
            )
        )
    return results


def categorize_transactions(
    txns: list[Transaction],
    config: CascadeConfig = DEFAULT_CONFIG,
    now: str | None = None,
) -> list[Categorization]:
    """Run both axes. Every transaction gets exactly one row per axis."""
    categorized_at = now or datetime.now(UTC).strftime(TIMESTAMP_FORMAT)
    return categorize_payers(txns, config, categorized_at) + categorize_services(
        txns, config, categorized_at
    )


def run_categorize(
    conn: sqlite3.Connection, config: CascadeConfig = DEFAULT_CONFIG
) -> int:
    """Categorize every stored transaction, replacing any previous verdict.

    Idempotent by design so the cascade can be tuned and re-run freely without
    corrupting state or double-counting.
    """
    txns = load_transactions(conn)
    categorizations = categorize_transactions(txns, config)

    conn.executemany(
        """INSERT OR REPLACE INTO categorizations
           (transaction_id, axis, category_label, confidence_tier, rule_matched,
            categorized_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (
                c.transaction_id,
                c.axis,
                c.category_label,
                c.confidence_tier,
                c.rule_matched,
                c.categorized_at,
            )
            for c in categorizations
        ],
    )
    conn.commit()
    return len(categorizations)

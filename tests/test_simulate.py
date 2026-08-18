import json
from collections import Counter
from pathlib import Path

from ledger.simulate import UNGROUPABLE, generate_batch, write_batch


def test_generates_at_least_the_requested_count():
    batch = generate_batch(count=120, seed=1)
    assert len(batch.transactions) >= 120


def test_is_deterministic_for_a_given_seed():
    a = generate_batch(count=120, seed=7)
    b = generate_batch(count=120, seed=7)
    assert [t.tx_hash for t in a.transactions] == [t.tx_hash for t in b.transactions]


def test_different_seeds_produce_different_data():
    a = generate_batch(count=120, seed=1)
    b = generate_batch(count=120, seed=2)
    assert [t.tx_hash for t in a.transactions] != [t.tx_hash for t in b.transactions]


def test_all_tx_hashes_are_unique():
    batch = generate_batch(count=120, seed=1)
    hashes = [t.tx_hash for t in batch.transactions]
    assert len(hashes) == len(set(hashes))


def test_every_transaction_has_ground_truth():
    batch = generate_batch(count=120, seed=1)
    for tx in batch.transactions:
        assert tx.tx_hash in batch.ground_truth


def test_amounts_are_positive_integers():
    batch = generate_batch(count=120, seed=1)
    for tx in batch.transactions:
        assert isinstance(tx.amount_micro_usdc, int)
        assert tx.amount_micro_usdc > 0


def test_timestamps_are_iso_utc():
    batch = generate_batch(count=120, seed=1)
    for tx in batch.transactions:
        assert tx.timestamp.endswith("Z")
        assert len(tx.timestamp) == 20


def test_contains_repeat_senders_across_multiple_transactions():
    batch = generate_batch(count=120, seed=1)
    counts = Counter(t.sender_address for t in batch.transactions)
    assert sum(1 for c in counts.values() if c > 1) >= 3


def test_contains_one_off_senders_that_are_ungroupable():
    batch = generate_batch(count=120, seed=1)
    counts = Counter(t.sender_address for t in batch.transactions)
    one_offs = [s for s, c in counts.items() if c == 1]
    assert len(one_offs) >= 3
    assert any(
        batch.ground_truth[t.tx_hash] == UNGROUPABLE
        for t in batch.transactions
        if t.sender_address in one_offs
    )


def test_contains_transactions_with_and_without_memos():
    batch = generate_batch(count=120, seed=1)
    memos = [t.memo for t in batch.transactions]
    assert any(m is None for m in memos)
    assert any(m for m in memos)


def test_contains_near_miss_addresses_that_differ():
    batch = generate_batch(count=120, seed=1)
    senders = {t.sender_address for t in batch.transactions}
    prefixes = Counter(s[:10] for s in senders)
    assert any(c > 1 for c in prefixes.values())


def test_contains_a_specific_memo_shared_by_distinct_senders():
    """Rule 2 (memo_match) needs a memo that repeats across different senders,
    not just repeat senders. Otherwise sender_match always wins first and
    memo_match is structurally unreachable."""
    batch = generate_batch(count=120, seed=1)
    generic = {"", "payment", "x402", "n/a", "-", "none", "tx", "transfer"}

    memo_to_senders: dict[str, set[str]] = {}
    for t in batch.transactions:
        if t.memo is None:
            continue
        memo = t.memo.strip()
        if memo.lower() in generic:
            continue
        memo_to_senders.setdefault(memo, set()).add(t.sender_address)

    assert any(
        len(senders) >= 5
        for senders in memo_to_senders.values()
    ), "expected a specific memo shared by at least 5 distinct senders"


def test_write_batch_writes_both_files(tmp_path: Path):
    batch = generate_batch(count=120, seed=1)
    tx_path, gt_path = write_batch(batch, tmp_path)

    assert tx_path.exists() and gt_path.exists()
    txs = json.loads(tx_path.read_text())
    gt = json.loads(gt_path.read_text())
    assert len(txs) == len(batch.transactions)
    assert txs[0]["tx_hash"] == batch.transactions[0].tx_hash
    assert gt[batch.transactions[0].tx_hash] == batch.ground_truth[
        batch.transactions[0].tx_hash
    ]

import json
from collections import Counter
from pathlib import Path

from ledger.models import TX_TYPE_PAYMENT, TX_TYPE_REFUND, UNGROUPABLE
from ledger.simulate import (
    HAZARD_INTERLEAVED_ONE_OFF,
    HAZARD_MEMO_DRIFT,
    HAZARD_REFUND,
    HAZARD_ROTATING_ADDRESS,
    HAZARD_SHARED_MEMO,
    generate_batch,
    write_batch,
)


def test_generates_at_least_the_requested_count():
    assert len(generate_batch(count=120, seed=1).transactions) >= 120


def test_is_deterministic_for_a_given_seed():
    a = generate_batch(count=120, seed=7)
    b = generate_batch(count=120, seed=7)
    assert [t.tx_hash for t in a.transactions] == [t.tx_hash for t in b.transactions]


def test_different_seeds_produce_different_data():
    a = generate_batch(count=120, seed=1)
    b = generate_batch(count=120, seed=2)
    assert [t.tx_hash for t in a.transactions] != [t.tx_hash for t in b.transactions]


def test_all_tx_hashes_are_unique():
    hashes = [t.tx_hash for t in generate_batch(count=120, seed=1).transactions]
    assert len(hashes) == len(set(hashes))


def test_every_transaction_has_ground_truth():
    batch = generate_batch(count=120, seed=1)
    for tx in batch.transactions:
        assert tx.tx_hash in batch.ground_truth


def test_amounts_are_positive_integers():
    for tx in generate_batch(count=120, seed=1).transactions:
        assert isinstance(tx.amount_micro_usdc, int)
        assert tx.amount_micro_usdc > 0


def test_timestamps_are_iso_utc():
    for tx in generate_batch(count=120, seed=1).transactions:
        assert tx.timestamp.endswith("Z")
        assert len(tx.timestamp) == 20


def test_output_is_sorted_by_timestamp():
    txs = generate_batch(count=120, seed=1).transactions
    assert [t.timestamp for t in txs] == sorted(t.timestamp for t in txs)


def test_contains_repeat_senders_across_multiple_transactions():
    counts = Counter(t.sender_address for t in generate_batch(count=120, seed=1).transactions)
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
    memos = [t.memo for t in generate_batch(count=120, seed=1).transactions]
    assert any(m is None for m in memos)
    assert any(m for m in memos)


def test_contains_near_miss_addresses_that_differ():
    senders = {t.sender_address for t in generate_batch(count=120, seed=1).transactions}
    prefixes = Counter(s[:10] for s in senders)
    assert any(c > 1 for c in prefixes.values())


def test_contains_a_specific_memo_shared_by_distinct_senders():
    batch = generate_batch(count=120, seed=1)
    by_memo: dict[str, set[str]] = {}
    for tx in batch.transactions:
        if tx.memo and tx.memo not in {"payment", "x402", ""}:
            by_memo.setdefault(tx.memo, set()).add(tx.sender_address)
    assert any(len(senders) >= 5 for senders in by_memo.values())


# --- Hazard coverage ------------------------------------------------------
# Each hazard exists to let one cascade rule be caught being wrong. These
# tests prove the hazard is actually generated, so a metric computed on this
# dataset is measuring something rather than confirming a construction.


def test_one_offs_are_interleaved_not_appended_in_a_tail():
    # REPLACES the v0 assumption that one-offs form a contiguous tail. Under
    # the old generator every cluster was pure-ungroupable by construction,
    # which forced time_cluster to 0% regardless of merit.
    batch = generate_batch(count=120, seed=1)
    tagged = {
        h for h, hz in batch.hazards.items() if hz == HAZARD_INTERLEAVED_ONE_OFF
    }
    assert tagged

    positions = [
        i for i, t in enumerate(batch.transactions) if t.tx_hash in tagged
    ]
    grouped_positions = [
        i
        for i, t in enumerate(batch.transactions)
        if batch.ground_truth[t.tx_hash] != UNGROUPABLE
    ]
    # At least one interleaved one-off sits between two real agent payments.
    assert any(
        min(grouped_positions) < p < max(grouped_positions) for p in positions
    )


def test_unrelated_payers_share_a_specific_memo():
    # Lets memo_match be caught collapsing strangers. Their true groups differ.
    batch = generate_batch(count=120, seed=1)
    tagged = [
        t for t in batch.transactions
        if batch.hazards.get(t.tx_hash) == HAZARD_SHARED_MEMO
    ]
    assert len(tagged) >= 2
    assert len({t.memo for t in tagged}) == 1
    assert len({batch.ground_truth[t.tx_hash] for t in tagged}) >= 2


def test_an_agent_rotates_its_address_mid_life():
    # Lets sender_match be caught splitting one payer. One group, many senders.
    batch = generate_batch(count=120, seed=1)
    tagged = [
        t for t in batch.transactions
        if batch.hazards.get(t.tx_hash) == HAZARD_ROTATING_ADDRESS
    ]
    assert len(tagged) >= 2
    assert len({batch.ground_truth[t.tx_hash] for t in tagged}) == 1
    assert len({t.sender_address for t in tagged}) >= 2


def test_an_agents_memo_drifts_over_its_life():
    batch = generate_batch(count=120, seed=1)
    tagged = [
        t for t in batch.transactions
        if batch.hazards.get(t.tx_hash) == HAZARD_MEMO_DRIFT
    ]
    assert len(tagged) >= 2
    assert len({batch.ground_truth[t.tx_hash] for t in tagged}) == 1
    assert len({t.memo for t in tagged}) >= 2


def test_refunds_are_generated_against_real_payments():
    batch = generate_batch(count=120, seed=1)
    refunds = [t for t in batch.transactions if t.tx_type == TX_TYPE_REFUND]
    assert refunds
    for refund in refunds:
        assert refund.amount_micro_usdc > 0  # positive amount, typed as a refund
        assert batch.hazards.get(refund.tx_hash) == HAZARD_REFUND
        assert batch.ground_truth[refund.tx_hash] != UNGROUPABLE


def test_amounts_span_sub_cent_to_large():
    amounts = [t.amount_micro_usdc for t in generate_batch(count=120, seed=1).transactions]
    assert min(amounts) < 10_000       # under a cent
    assert max(amounts) > 1_000_000    # over a dollar


def test_hazards_are_a_minority_of_the_dataset():
    # A dataset where everything is adversarial cannot tell you which weakness
    # matters. Ordinary traffic must stay the bulk of it.
    batch = generate_batch(count=120, seed=1)
    assert len(batch.hazards) < len(batch.transactions) / 2


def test_every_hazard_tagged_transaction_exists():
    batch = generate_batch(count=120, seed=1)
    hashes = {t.tx_hash for t in batch.transactions}
    assert set(batch.hazards) <= hashes


def test_write_batch_writes_all_three_files(tmp_path: Path):
    batch = generate_batch(count=120, seed=1)
    tx_path, gt_path, hz_path = write_batch(batch, tmp_path)

    assert tx_path.exists() and gt_path.exists() and hz_path.exists()
    txs = json.loads(tx_path.read_text())
    assert len(txs) == len(batch.transactions)
    assert txs[0]["tx_hash"] == batch.transactions[0].tx_hash
    assert "tx_type" in txs[0]
    assert json.loads(gt_path.read_text())[batch.transactions[0].tx_hash]
    assert json.loads(hz_path.read_text()) == batch.hazards

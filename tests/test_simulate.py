import json
from collections import Counter
from pathlib import Path

import pytest

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


def test_generates_at_least_the_requested_count_above_the_natural_floor():
    # The generator's fixed agent+hazard material already produces ~145
    # transactions before the top-up loop is ever reached, so a `count` at or
    # below that floor (e.g. 120 above) cannot exercise the top-up loop at
    # all - it would pass identically whether or not that loop worked. Only a
    # count above the natural floor forces the top-up loop to run, which is
    # why this is the case that actually catches a shadowed loop variable
    # (C1) breaking it.
    assert len(generate_batch(count=300, seed=1).transactions) >= 300


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


def test_rotating_address_hazard_actually_fragments_the_cascade():
    # THE PROPERTY THAT MATTERS (C1a): >=2 distinct senders is necessary but
    # not sufficient — each address must repeat at least twice for
    # sender_match to fire and actually split this one payer into more than
    # one predicted group. Run the real cascade and assert the split happens.
    from ledger.categorize import categorize_transactions

    batch = generate_batch(count=120, seed=1)
    tagged = [
        t for t in batch.transactions
        if batch.hazards.get(t.tx_hash) == HAZARD_ROTATING_ADDRESS
    ]
    assert len({batch.ground_truth[t.tx_hash] for t in tagged}) == 1

    import dataclasses

    numbered = [dataclasses.replace(t, id=i) for i, t in enumerate(batch.transactions)]
    cats = categorize_transactions(numbered)
    by_hash = {t.tx_hash: c for t, c in zip(numbered, cats)}

    labels = {by_hash[t.tx_hash].category_label for t in tagged}
    assert len(labels) > 1, (
        "rotating-address hazard did not fragment the payer across predicted "
        "groups - sender_match never actually split it"
    )


def test_an_agents_memo_drifts_over_its_life():
    batch = generate_batch(count=120, seed=1)
    tagged = [
        t for t in batch.transactions
        if batch.hazards.get(t.tx_hash) == HAZARD_MEMO_DRIFT
    ]
    assert len(tagged) >= 2
    assert len({batch.ground_truth[t.tx_hash] for t in tagged}) == 1
    assert len({t.memo for t in tagged}) >= 2


def test_memo_drift_is_seen_by_memo_match_not_intercepted_by_sender_match():
    # C1b: the drift agent's address must never repeat, so sender_match
    # cannot claim these transactions before memo_match gets a chance.
    #
    # memo_match now runs only on the service axis (a shared memo identifies a
    # service, not a payer), so the two axes are checked separately: the payer
    # axis must never claim sender_match for these transactions (it falls
    # through to none, since time_cluster was removed in v0.1c), and the
    # service axis is where memo_match is expected to fire.
    batch = generate_batch(count=120, seed=1)
    tagged = [
        t for t in batch.transactions
        if batch.hazards.get(t.tx_hash) == HAZARD_MEMO_DRIFT
    ]
    senders = Counter(t.sender_address for t in tagged)
    assert all(c == 1 for c in senders.values()), (
        "a memo-drift sender address repeats, so sender_match could "
        "intercept these transactions before memo_match ever sees them"
    )

    from ledger.categorize import categorize_transactions
    from ledger.models import (
        AXIS_PAYER,
        AXIS_SERVICE,
        RULE_MEMO_MATCH,
        RULE_NONE,
        RULE_SENDER_MATCH,
    )

    import dataclasses

    numbered = [dataclasses.replace(t, id=i) for i, t in enumerate(batch.transactions)]
    cats = categorize_transactions(numbered)
    hash_by_id = {t.id: t.tx_hash for t in numbered}
    by_hash_axis = {
        (hash_by_id[c.transaction_id], c.axis): c for c in cats
    }

    payer_rules_seen = {by_hash_axis[(t.tx_hash, AXIS_PAYER)].rule_matched for t in tagged}
    assert RULE_SENDER_MATCH not in payer_rules_seen
    assert payer_rules_seen <= {RULE_NONE}

    service_rules_seen = {by_hash_axis[(t.tx_hash, AXIS_SERVICE)].rule_matched for t in tagged}
    assert service_rules_seen <= {RULE_MEMO_MATCH, RULE_NONE}


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


@pytest.mark.parametrize("count", [120, 300])
def test_hazards_are_a_minority_of_the_dataset(count):
    # A dataset where everything is adversarial cannot tell you which weakness
    # matters. Ordinary traffic must stay the bulk of it. Pinned at both the
    # old canonical count (120) and the v0.1c canonical count (300, measured
    # at 20.3% - see docs/measurements-v0.1c.md).
    batch = generate_batch(count=count, seed=1)
    assert len(batch.hazards) < len(batch.transactions) / 2


def test_every_hazard_tagged_transaction_exists():
    batch = generate_batch(count=120, seed=1)
    hashes = {t.tx_hash for t in batch.transactions}
    assert set(batch.hazards) <= hashes


def test_write_batch_writes_all_three_files(tmp_path: Path):
    batch = generate_batch(count=120, seed=1)
    tx_path, gt_path, hz_path, _ = write_batch(batch, tmp_path)

    assert tx_path.exists() and gt_path.exists() and hz_path.exists()
    txs = json.loads(tx_path.read_text())
    assert len(txs) == len(batch.transactions)
    # NOTE: written row order is by tx_hash (C1c), not the in-memory
    # timestamp order of batch.transactions - look the row up by hash rather
    # than assuming position 0 lines up.
    written_by_hash = {row["tx_hash"] for row in txs}
    assert batch.transactions[0].tx_hash in written_by_hash
    assert "tx_type" in txs[0]
    assert json.loads(gt_path.read_text())[batch.transactions[0].tx_hash]
    assert json.loads(hz_path.read_text()) == batch.hazards


def test_written_transactions_are_not_in_timestamp_order(tmp_path: Path):
    # C1c: written JSON rows are ordered by tx_hash (a deterministic
    # shuffle), NOT by timestamp - so no downstream stage can wrongly rely
    # on arrival order. batch.transactions itself stays timestamp-sorted
    # (see test_output_is_sorted_by_timestamp); only the written file differs.
    batch = generate_batch(count=120, seed=1)
    tx_path, _, _, _ = write_batch(batch, tmp_path)
    written = json.loads(tx_path.read_text())
    timestamps = [row["timestamp"] for row in written]
    assert timestamps != sorted(timestamps)
    tx_hashes = [row["tx_hash"] for row in written]
    assert tx_hashes == sorted(tx_hashes)


def test_every_transaction_has_service_truth():
    batch = generate_batch(count=120, seed=1)
    for tx in batch.transactions:
        assert tx.tx_hash in batch.service_truth


def test_shared_memo_strangers_share_one_true_service():
    # They are different payers but genuinely the same service. This grouping
    # was never wrong - only its presentation as a payer identity was.
    batch = generate_batch(count=120, seed=1)
    tagged = [
        t for t in batch.transactions
        if batch.hazards.get(t.tx_hash) == HAZARD_SHARED_MEMO
    ]
    assert len(tagged) >= 2
    assert len({batch.service_truth[t.tx_hash] for t in tagged}) == 1
    assert len({batch.ground_truth[t.tx_hash] for t in tagged}) >= 2


def test_memo_drift_is_one_true_service_under_several_memos():
    batch = generate_batch(count=120, seed=1)
    tagged = [
        t for t in batch.transactions
        if batch.hazards.get(t.tx_hash) == HAZARD_MEMO_DRIFT
    ]
    assert len(tagged) >= 2
    assert len({batch.service_truth[t.tx_hash] for t in tagged}) == 1
    assert len({t.memo for t in tagged}) >= 2


def test_transactions_without_a_usable_memo_have_no_true_service():
    batch = generate_batch(count=120, seed=1)
    generic = {"", "payment", "x402", "n/a", "-", "none", "tx", "transfer"}
    for tx in batch.transactions:
        if tx.memo is None or tx.memo.strip().lower() in generic:
            assert batch.service_truth[tx.tx_hash] == UNGROUPABLE


def test_a_refund_carries_its_originals_service():
    batch = generate_batch(count=120, seed=1)
    refunds = [t for t in batch.transactions if t.tx_type == TX_TYPE_REFUND]
    assert refunds
    for refund in refunds:
        assert batch.service_truth[refund.tx_hash] != UNGROUPABLE


def test_write_batch_writes_all_four_files(tmp_path: Path):
    batch = generate_batch(count=120, seed=1)
    tx_path, gt_path, hz_path, st_path = write_batch(batch, tmp_path)

    assert st_path.exists()
    assert st_path.name == "service_truth.json"
    assert json.loads(st_path.read_text()) == batch.service_truth


from ledger.simulate import HAZARD_SHARED_MEMO_DIFFERENT_SERVICES


def _shared_memo_diff_services(batch):
    return [
        t for t in batch.transactions
        if batch.hazards.get(t.tx_hash) == HAZARD_SHARED_MEMO_DIFFERENT_SERVICES
    ]


def test_one_memo_covers_two_different_services():
    # The only hazard shape that can reduce service precision: a MERGE.
    # Every other generator derives service truth from the memo, so memo and
    # service agree and precision cannot fall.
    batch = generate_batch(count=120, seed=1)
    tagged = _shared_memo_diff_services(batch)

    assert len(tagged) >= 4
    assert len({t.memo for t in tagged}) == 1
    assert len({batch.service_truth[t.tx_hash] for t in tagged}) >= 2


def test_its_true_services_are_used_by_nothing_else():
    # Reusing an existing service would enlarge that service's true group and
    # depress the recall of unrelated transactions, spreading the hazard's
    # effect instead of isolating it to precision.
    batch = generate_batch(count=120, seed=1)
    tagged = _shared_memo_diff_services(batch)
    hazard_services = {batch.service_truth[t.tx_hash] for t in tagged}

    others = {
        batch.service_truth[t.tx_hash]
        for t in batch.transactions
        if batch.hazards.get(t.tx_hash) != HAZARD_SHARED_MEMO_DIFFERENT_SERVICES
    }
    assert hazard_services.isdisjoint(others)


def test_it_is_payer_axis_neutral():
    # Its senders repeat, so sender_match claims them on the payer axis
    # regardless of this hazard's presence. (time_cluster, which used to fire
    # on repeating senders too, was removed in v0.1c after failing its
    # pre-registered criterion; see docs/measurements-v0.1c.md.)
    from collections import Counter

    batch = generate_batch(count=120, seed=1)
    tagged = _shared_memo_diff_services(batch)
    counts = Counter(t.sender_address for t in batch.transactions)

    assert tagged
    for tx in tagged:
        assert counts[tx.sender_address] >= 2


def test_its_payers_are_genuinely_different():
    batch = generate_batch(count=120, seed=1)
    tagged = _shared_memo_diff_services(batch)
    assert len({batch.ground_truth[t.tx_hash] for t in tagged}) >= 2

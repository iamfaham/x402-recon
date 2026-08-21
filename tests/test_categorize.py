from ledger.categorize import build_memo_counts, build_sender_counts, is_generic_memo
from ledger.config import DEFAULT_CONFIG
from ledger.models import Transaction


def tx(tx_hash: str, sender: str, memo: str | None = None, ts: str = "2026-08-18T10:00:00Z") -> Transaction:
    return Transaction(
        id=int(tx_hash[2:]),
        tx_hash=tx_hash,
        sender_address=sender,
        receiver_address="0xmerchant",
        amount_micro_usdc=1000,
        timestamp=ts,
        memo=memo,
        chain="base-sepolia-sim",
        raw_payload="{}",
    )


def test_default_config_values():
    assert DEFAULT_CONFIG.min_occurrences == 2


def test_none_memo_is_generic():
    assert is_generic_memo(None, DEFAULT_CONFIG)


def test_empty_memo_is_generic():
    assert is_generic_memo("", DEFAULT_CONFIG)
    assert is_generic_memo("   ", DEFAULT_CONFIG)


def test_known_filler_memo_is_generic():
    assert is_generic_memo("payment", DEFAULT_CONFIG)
    assert is_generic_memo("X402", DEFAULT_CONFIG)


def test_specific_memo_is_not_generic():
    assert not is_generic_memo("weather-api", DEFAULT_CONFIG)


def test_sender_counts_tallies_repeats():
    txns = [tx("0x1", "0xa"), tx("0x2", "0xa"), tx("0x3", "0xb")]
    counts = build_sender_counts(txns)
    assert counts["0xa"] == 2
    assert counts["0xb"] == 1


def test_memo_counts_excludes_generic_memos():
    txns = [
        tx("0x1", "0xa", memo="weather-api"),
        tx("0x2", "0xb", memo="weather-api"),
        tx("0x3", "0xc", memo="payment"),
        tx("0x4", "0xd", memo=None),
    ]
    counts = build_memo_counts(txns, DEFAULT_CONFIG)
    assert counts["weather-api"] == 2
    assert "payment" not in counts
    assert None not in counts


from ledger.categorize import (
    categorize_transactions,
    run_categorize,
)
from ledger.models import (
    CONFIDENT,
    RULE_MEMO_MATCH,
    RULE_NONE,
    RULE_SENDER_MATCH,
    UNCATEGORIZED,
    UNCERTAIN,
)
from ledger.db import connect, init_schema


def by_hash(cats, txns):
    ids = {t.id: t.tx_hash for t in txns}
    return {ids[c.transaction_id]: c for c in cats}


def test_repeated_sender_is_confident_sender_match():
    txns = [tx("0x1", "0xa"), tx("0x2", "0xa")]
    payer = [c for c in categorize_transactions(txns) if c.axis == AXIS_PAYER]
    result = by_hash(payer, txns)

    assert result["0x1"].rule_matched == RULE_SENDER_MATCH
    assert result["0x1"].confidence_tier == CONFIDENT
    assert result["0x1"].category_label == "agent:0xa"
    assert result["0x2"].category_label == "agent:0xa"


def test_single_sender_does_not_get_sender_match():
    txns = [tx("0x1", "0xa"), tx("0x2", "0xb")]
    payer = [c for c in categorize_transactions(txns) if c.axis == AXIS_PAYER]
    result = by_hash(payer, txns)
    assert result["0x1"].rule_matched != RULE_SENDER_MATCH


def test_shared_memo_from_different_senders_is_descriptive_memo_match():
    # Grouping by memo is a service signal, not a payer identity, so it now
    # lands on the service axis and never claims CONFIDENT.
    txns = [
        tx("0x1", "0xa", memo="weather-api"),
        tx("0x2", "0xb", memo="weather-api"),
    ]
    service = [c for c in categorize_transactions(txns) if c.axis == AXIS_SERVICE]
    result = by_hash(service, txns)

    assert result["0x1"].rule_matched == RULE_MEMO_MATCH
    assert result["0x1"].confidence_tier == DESCRIPTIVE
    assert result["0x1"].category_label == "service:weather-api"


def test_sender_match_and_memo_match_are_independent_axes():
    # The two axes no longer compete in one elif chain: a repeated sender with
    # a specific memo earns sender_match on the payer axis AND memo_match on
    # the service axis, rather than one silently discarding the other.
    txns = [
        tx("0x1", "0xa", memo="weather-api"),
        tx("0x2", "0xa", memo="weather-api"),
    ]
    cats = categorize_transactions(txns)
    payer = by_hash([c for c in cats if c.axis == AXIS_PAYER], txns)
    service = by_hash([c for c in cats if c.axis == AXIS_SERVICE], txns)

    assert payer["0x1"].rule_matched == RULE_SENDER_MATCH
    assert service["0x1"].rule_matched == RULE_MEMO_MATCH


def test_no_payer_row_carries_time_cluster():
    # Pins the v0.1c removal: time_cluster failed its pre-registered
    # criterion (70.0% precision, but the seed sweep showed 11/19 seeds
    # failing at the identical count) and was deleted from the cascade.
    # Transactions that used to fall into a time-proximity cluster must now
    # fall through to "none" rather than resurrect the rule under any label.
    txns = [
        tx("0x1", "0xa", ts="2026-08-18T10:00:00Z"),
        tx("0x2", "0xb", ts="2026-08-18T10:01:00Z"),
        tx("0x3", "0xc", ts="2026-08-18T10:02:00Z"),
    ]
    payer = [c for c in categorize_transactions(txns) if c.axis == AXIS_PAYER]
    assert payer
    assert all(c.rule_matched != "time_cluster" for c in payer)


def test_isolated_transaction_is_uncategorized_not_forced_into_a_bucket():
    txns = [
        tx("0x1", "0xa", ts="2026-08-18T10:00:00Z"),
        tx("0x2", "0xb", ts="2026-08-18T18:00:00Z"),
    ]
    payer = [c for c in categorize_transactions(txns) if c.axis == AXIS_PAYER]
    result = by_hash(payer, txns)

    assert result["0x1"].rule_matched == RULE_NONE
    assert result["0x1"].category_label == UNCATEGORIZED
    assert result["0x1"].confidence_tier == UNCERTAIN


def test_run_categorize_is_idempotent(tmp_path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    for i in (1, 2):
        conn.execute(
            """INSERT INTO transactions
               (tx_hash, sender_address, receiver_address, amount_micro_usdc,
                timestamp, memo, chain, raw_payload)
               VALUES (?, '0xa', '0xm', 1000, '2026-08-18T10:00:00Z', NULL, 'sim', '{}')""",
            (f"0x{i}",),
        )
    conn.commit()

    first = run_categorize(conn)
    second = run_categorize(conn)

    assert first == 4
    assert second == 4
    count = conn.execute("SELECT COUNT(*) AS n FROM categorizations").fetchone()["n"]
    assert count == 4


from ledger.categorize import categorize_services
from ledger.models import AXIS_PAYER, AXIS_SERVICE, DESCRIPTIVE


def by_axis(cats):
    return {c.axis: c for c in cats}


def test_a_known_sender_with_a_specific_memo_gets_both_labels():
    # THE BUG THIS RELEASE UNDOES: the old elif chain gave this transaction
    # only the payer label and silently discarded the service.
    txns = [
        tx("0x1", "0xa", memo="weather-api"),
        tx("0x2", "0xa", memo="weather-api"),
    ]
    first = by_axis([c for c in categorize_transactions(txns) if c.transaction_id == 1])

    assert first[AXIS_PAYER].category_label == "agent:0xa"
    assert first[AXIS_PAYER].confidence_tier == CONFIDENT
    assert first[AXIS_SERVICE].category_label == "service:weather-api"
    assert first[AXIS_SERVICE].confidence_tier == DESCRIPTIVE


def test_every_transaction_gets_exactly_one_row_per_axis():
    txns = [tx("0x1", "0xa"), tx("0x2", "0xa"), tx("0x3", "0xb")]
    cats = categorize_transactions(txns)

    assert len(cats) == 2 * len(txns)
    seen = {(c.transaction_id, c.axis) for c in cats}
    assert len(seen) == 2 * len(txns)


def test_memo_match_never_appears_on_the_payer_axis():
    txns = [
        tx("0x1", "0xa", memo="weather-api"),
        tx("0x2", "0xb", memo="weather-api"),
    ]
    payer = [c for c in categorize_transactions(txns) if c.axis == AXIS_PAYER]
    assert all(c.rule_matched != RULE_MEMO_MATCH for c in payer)


def test_service_rows_never_claim_confidence():
    txns = [
        tx("0x1", "0xa", memo="weather-api"),
        tx("0x2", "0xb", memo="weather-api"),
        tx("0x3", "0xc"),
    ]
    service = [c for c in categorize_transactions(txns) if c.axis == AXIS_SERVICE]
    assert service
    assert all(c.confidence_tier == DESCRIPTIVE for c in service)


def test_a_transaction_with_no_usable_memo_is_uncategorized_on_the_service_axis():
    txns = [tx("0x1", "0xa"), tx("0x2", "0xa")]
    service = by_axis([c for c in categorize_services(txns, DEFAULT_CONFIG, "now") if c.transaction_id == 1])
    assert service[AXIS_SERVICE].category_label == UNCATEGORIZED
    assert service[AXIS_SERVICE].rule_matched == RULE_NONE
    assert service[AXIS_SERVICE].confidence_tier == DESCRIPTIVE


def test_run_categorize_writes_two_rows_per_transaction(tmp_path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    for i in (1, 2):
        conn.execute(
            """INSERT INTO transactions
               (tx_hash, sender_address, receiver_address, amount_micro_usdc,
                timestamp, memo, chain, raw_payload)
               VALUES (?, '0xa', '0xm', 1000, '2026-08-18T10:00:00Z', 'weather-api', 'sim', '{}')""",
            (f"0x{i}",),
        )
    conn.commit()

    first = run_categorize(conn)
    second = run_categorize(conn)

    assert first == 4
    assert second == 4
    assert conn.execute("SELECT COUNT(*) AS n FROM categorizations").fetchone()["n"] == 4

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
    assert DEFAULT_CONFIG.time_window_minutes == 5


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
    find_time_clusters,
    run_categorize,
)
from ledger.models import (
    CONFIDENT,
    RULE_MEMO_MATCH,
    RULE_NONE,
    RULE_SENDER_MATCH,
    RULE_TIME_CLUSTER,
    UNCATEGORIZED,
    UNCERTAIN,
)
from ledger.db import connect, init_schema


def by_hash(cats, txns):
    ids = {t.id: t.tx_hash for t in txns}
    return {ids[c.transaction_id]: c for c in cats}


def test_repeated_sender_is_confident_sender_match():
    txns = [tx("0x1", "0xa"), tx("0x2", "0xa")]
    result = by_hash(categorize_transactions(txns), txns)

    assert result["0x1"].rule_matched == RULE_SENDER_MATCH
    assert result["0x1"].confidence_tier == CONFIDENT
    assert result["0x1"].category_label == "agent:0xa"
    assert result["0x2"].category_label == "agent:0xa"


def test_single_sender_does_not_get_sender_match():
    txns = [tx("0x1", "0xa"), tx("0x2", "0xb")]
    result = by_hash(categorize_transactions(txns), txns)
    assert result["0x1"].rule_matched != RULE_SENDER_MATCH


def test_shared_memo_from_different_senders_is_confident_memo_match():
    txns = [
        tx("0x1", "0xa", memo="weather-api"),
        tx("0x2", "0xb", memo="weather-api"),
    ]
    result = by_hash(categorize_transactions(txns), txns)

    assert result["0x1"].rule_matched == RULE_MEMO_MATCH
    assert result["0x1"].confidence_tier == CONFIDENT
    assert result["0x1"].category_label == "service:weather-api"


def test_sender_match_takes_priority_over_memo_match():
    txns = [
        tx("0x1", "0xa", memo="weather-api"),
        tx("0x2", "0xa", memo="weather-api"),
    ]
    result = by_hash(categorize_transactions(txns), txns)
    assert result["0x1"].rule_matched == RULE_SENDER_MATCH


def test_time_clustered_one_off_senders_are_uncertain():
    txns = [
        tx("0x1", "0xa", ts="2026-08-18T10:00:00Z"),
        tx("0x2", "0xb", ts="2026-08-18T10:01:00Z"),
        tx("0x3", "0xc", ts="2026-08-18T10:02:00Z"),
    ]
    result = by_hash(categorize_transactions(txns), txns)

    assert result["0x1"].rule_matched == RULE_TIME_CLUSTER
    assert result["0x1"].confidence_tier == UNCERTAIN
    assert result["0x1"].category_label.startswith("cluster:")


def test_isolated_transaction_is_uncategorized_not_forced_into_a_bucket():
    txns = [
        tx("0x1", "0xa", ts="2026-08-18T10:00:00Z"),
        tx("0x2", "0xb", ts="2026-08-18T18:00:00Z"),
    ]
    result = by_hash(categorize_transactions(txns), txns)

    assert result["0x1"].rule_matched == RULE_NONE
    assert result["0x1"].category_label == UNCATEGORIZED
    assert result["0x1"].confidence_tier == UNCERTAIN


def test_every_transaction_receives_exactly_one_categorization():
    txns = [tx("0x1", "0xa"), tx("0x2", "0xa"), tx("0x3", "0xz", ts="2026-08-19T03:00:00Z")]
    cats = categorize_transactions(txns)
    assert len(cats) == len(txns)
    assert len({c.transaction_id for c in cats}) == len(txns)


def test_find_time_clusters_ignores_gaps_beyond_the_window():
    txns = [
        tx("0x1", "0xa", ts="2026-08-18T10:00:00Z"),
        tx("0x2", "0xb", ts="2026-08-18T10:02:00Z"),
        tx("0x3", "0xc", ts="2026-08-18T12:00:00Z"),
    ]
    clusters = find_time_clusters(txns, DEFAULT_CONFIG)
    assert clusters["0x1"] == clusters["0x2"]
    assert "0x3" not in clusters


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

    assert first == 2
    assert second == 2
    count = conn.execute("SELECT COUNT(*) AS n FROM categorizations").fetchone()["n"]
    assert count == 2

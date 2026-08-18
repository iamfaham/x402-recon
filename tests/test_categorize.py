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

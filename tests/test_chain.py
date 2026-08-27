import pytest

from x402_recon.chain import (
    TRANSFER_TOPIC0,
    USDBC_BASE_MAINNET_EXCLUDED,
    USDC_BASE_MAINNET,
    block_timestamp_to_iso,
    decode_address,
    decode_amount_micro_usdc,
    log_to_transaction,
)
from x402_recon.models import TX_TYPE_PAYMENT, TX_TYPE_REFUND


def test_native_usdc_address_is_the_circle_proxy():
    # Pinned so a typo can never silently point the fetcher at another token.
    assert USDC_BASE_MAINNET == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


def test_bridged_usdbc_is_a_different_token_and_is_excluded():
    # USDbC is the older bridged token. Including it would inflate totals.
    assert USDBC_BASE_MAINNET_EXCLUDED == "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca"
    assert USDBC_BASE_MAINNET_EXCLUDED != USDC_BASE_MAINNET


def test_transfer_topic0_is_the_erc20_transfer_signature():
    assert TRANSFER_TOPIC0 == (
        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    )


def test_decode_address_takes_the_low_twenty_bytes_of_a_padded_topic():
    topic = "0x000000000000000000000000abcdef0123456789abcdef0123456789abcdef01"
    assert decode_address(topic) == "0xabcdef0123456789abcdef0123456789abcdef01"


def test_decode_amount_is_an_integer_of_micro_usdc_with_no_conversion():
    # USDC has 6 decimals, so the raw uint256 IS a micro-USDC count.
    # 0x0f4240 == 1_000_000 == exactly one dollar.
    amount = decode_amount_micro_usdc("0x00000000000000000000000000000000000000000000000000000000000f4240")
    assert amount == 1_000_000
    assert isinstance(amount, int)
    assert not isinstance(amount, float)


def test_decode_amount_of_zero_is_zero_not_falsy_failure():
    assert decode_amount_micro_usdc("0x0") == 0


def test_block_timestamp_renders_zero_padded_utc():
    # 0x5f5e100 == 100_000_000 seconds after the epoch. The format must match
    # TIMESTAMP_FORMAT exactly, since everything downstream compares
    # timestamps as text.
    result = block_timestamp_to_iso("0x5f5e100")
    assert result == "1973-03-03T09:46:40Z"
    assert len(result) == 20
    assert result.endswith("Z")


def test_log_to_transaction_maps_every_field_from_the_log():
    log = {
        "transactionHash": "0xaaa111",
        "topics": [
            TRANSFER_TOPIC0,
            "0x000000000000000000000000" + "11" * 20,
            "0x000000000000000000000000" + "22" * 20,
        ],
        "data": "0x00000000000000000000000000000000000000000000000000000000000f4240",
    }
    tx = log_to_transaction(log, "2026-07-01T12:00:00Z", TX_TYPE_PAYMENT)

    assert tx.tx_hash == "0xaaa111"
    assert tx.sender_address == "0x" + "11" * 20
    assert tx.receiver_address == "0x" + "22" * 20
    assert tx.amount_micro_usdc == 1_000_000
    assert tx.timestamp == "2026-07-01T12:00:00Z"
    assert tx.chain == "base"
    assert tx.tx_type == TX_TYPE_PAYMENT


def test_log_to_transaction_leaves_memo_none_because_the_chain_has_none():
    # This is the fact that darkens the service axis in v0.2. Pinned so a
    # future change that invents a memo has to break a test to do it.
    log = {
        "transactionHash": "0xbbb222",
        "topics": [
            TRANSFER_TOPIC0,
            "0x000000000000000000000000" + "33" * 20,
            "0x000000000000000000000000" + "44" * 20,
        ],
        "data": "0x64",
    }
    assert log_to_transaction(log, "2026-07-01T12:00:00Z", TX_TYPE_PAYMENT).memo is None


def test_log_to_transaction_preserves_the_raw_log_verbatim():
    import json

    log = {
        "transactionHash": "0xccc333",
        "topics": [
            TRANSFER_TOPIC0,
            "0x000000000000000000000000" + "55" * 20,
            "0x000000000000000000000000" + "66" * 20,
        ],
        "data": "0x64",
        "blockNumber": "0x1234",
    }
    tx = log_to_transaction(log, "2026-07-01T12:00:00Z", TX_TYPE_REFUND)
    assert json.loads(tx.raw_payload) == log


def test_log_to_transaction_rejects_a_log_that_is_not_a_transfer():
    log = {
        "transactionHash": "0xddd444",
        "topics": ["0x" + "ee" * 32, "0x" + "00" * 32, "0x" + "00" * 32],
        "data": "0x64",
    }
    with pytest.raises(ValueError, match="not an ERC-20 Transfer"):
        log_to_transaction(log, "2026-07-01T12:00:00Z", TX_TYPE_PAYMENT)


def test_log_to_transaction_rejects_a_transfer_with_too_few_topics():
    # A non-indexed-parameter Transfer would carry fewer topics. Rather than
    # index out of range, say what is wrong.
    log = {"transactionHash": "0xeee555", "topics": [TRANSFER_TOPIC0], "data": "0x64"}
    with pytest.raises(ValueError, match="expected 3 topics"):
        log_to_transaction(log, "2026-07-01T12:00:00Z", TX_TYPE_PAYMENT)


def test_authorization_used_topic_is_derived_not_pasted():
    from x402_recon.chain import AUTHORIZATION_USED_TOPIC0
    from x402_recon.keccak import topic0

    assert AUTHORIZATION_USED_TOPIC0 == topic0("AuthorizationUsed(address,bytes32)")
    assert AUTHORIZATION_USED_TOPIC0 == (
        "0x98de503528ee59b575ef0c0a2576a82497bfc029a5685b209e9ec333479b10a5"
    )


def test_transfer_topic_is_derived_and_still_equals_the_pinned_literal():
    # The literal in test_transfer_topic0_is_the_erc20_transfer_signature was
    # pinned from an external source before keccak existed here. This asserts
    # the derivation reproduces it, so each validates the other.
    from x402_recon.keccak import topic0

    assert TRANSFER_TOPIC0 == topic0("Transfer(address,address,uint256)")

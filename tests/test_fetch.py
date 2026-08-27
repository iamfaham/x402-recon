import json

from x402_recon.chain import TRANSFER_TOPIC0, USDBC_BASE_MAINNET_EXCLUDED, USDC_BASE_MAINNET
from x402_recon.fetch import (
    fetch_transactions,
    format_fetch_summary,
    topic_for_address,
    write_fetched,
)
from x402_recon.models import TX_TYPE_PAYMENT, TX_TYPE_REFUND
from x402_recon.rpc import RpcClient

RECEIVER = "0x" + "99" * 20
PAYER = "0x" + "11" * 20
STRANGER = "0x" + "77" * 20


def _padded(address):
    return "0x000000000000000000000000" + address[2:]


def _log(tx_hash, sender, receiver, amount_hex, block="0x10"):
    return {
        "transactionHash": tx_hash,
        "topics": [TRANSFER_TOPIC0, _padded(sender), _padded(receiver)],
        "data": amount_hex,
        "blockNumber": block,
    }


class FakeTransport:
    def __init__(self, inbound, outbound, timestamp="0x5f5e100"):
        self.inbound = inbound
        self.outbound = outbound
        self.timestamp = timestamp
        self.calls = 0
        self.queried_addresses = []

    def __call__(self, payload):
        if payload["method"] == "eth_getBlockByNumber":
            return {"result": {"timestamp": self.timestamp}}
        self.calls += 1
        params = payload["params"][0]
        self.queried_addresses.append(params["address"])
        topics = params["topics"]
        # topics == [transfer, from, to]; a `to` filter means inbound.
        return {"result": self.inbound if topics[2] else self.outbound}


def _client(inbound, outbound):
    return RpcClient(transport=FakeTransport(inbound, outbound))


def test_topic_for_address_left_pads_to_thirty_two_bytes():
    topic = topic_for_address("0xabcdef0123456789abcdef0123456789abcdef01")
    assert topic == "0x000000000000000000000000abcdef0123456789abcdef0123456789abcdef01"
    assert len(topic) == 66


def test_inbound_transfers_become_payments():
    result = fetch_transactions(
        _client([_log("0xa", PAYER, RECEIVER, "0x0f4240")], []),
        receiver=RECEIVER,
        from_block=0,
        to_block=10,
    )
    assert len(result.transactions) == 1
    assert result.transactions[0].tx_type == TX_TYPE_PAYMENT
    assert result.transactions[0].amount_micro_usdc == 1_000_000


def test_outbound_transfer_to_a_prior_payer_becomes_a_positive_refund():
    result = fetch_transactions(
        _client(
            [_log("0xa", PAYER, RECEIVER, "0x0f4240")],
            [_log("0xb", RECEIVER, PAYER, "0x7a120")],
        ),
        receiver=RECEIVER,
        from_block=0,
        to_block=10,
    )
    refunds = [t for t in result.transactions if t.tx_type == TX_TYPE_REFUND]
    assert len(refunds) == 1
    # Refunds are stored as POSITIVE amounts; the tx_type carries the sign.
    assert refunds[0].amount_micro_usdc == 500_000
    assert refunds[0].amount_micro_usdc > 0
    # sender_address is ALWAYS the counterparty and receiver_address is
    # ALWAYS the merchant, for payments and refunds alike - only tx_type
    # carries direction. The raw on-chain Transfer runs merchant -> payer, so
    # this must NOT match the raw log direction.
    assert refunds[0].sender_address.lower() == PAYER.lower()
    assert refunds[0].receiver_address.lower() == RECEIVER.lower()


def test_refund_addresses_are_not_the_raw_on_chain_transfer_direction():
    # Pins the schema convention directly: a fetched refund's sender/receiver
    # must be the original payer / merchant, not swapped to match the raw
    # ERC-20 Transfer's from/to (which runs merchant -> payer for a refund).
    result = fetch_transactions(
        _client(
            [_log("0xa", PAYER, RECEIVER, "0x0f4240")],
            [_log("0xb", RECEIVER, PAYER, "0x7a120")],
        ),
        receiver=RECEIVER,
        from_block=0,
        to_block=10,
    )
    refunds = [t for t in result.transactions if t.tx_type == TX_TYPE_REFUND]
    assert len(refunds) == 1
    refund = refunds[0]
    assert refund.sender_address.lower() == PAYER.lower()
    assert refund.receiver_address.lower() == RECEIVER.lower()
    assert refund.amount_micro_usdc > 0


def test_outbound_transfer_to_a_stranger_is_rejected_not_silently_dropped():
    result = fetch_transactions(
        _client(
            [_log("0xa", PAYER, RECEIVER, "0x0f4240")],
            [_log("0xz", RECEIVER, STRANGER, "0x7a120")],
        ),
        receiver=RECEIVER,
        from_block=0,
        to_block=10,
    )
    assert all(t.tx_hash != "0xz" for t in result.transactions)
    assert any(tx_hash == "0xz" for tx_hash, _ in result.rejects)
    assert any("never paid" in reason for _, reason in result.rejects)


def test_a_malformed_log_is_rejected_with_a_reason_and_the_rest_survive():
    bad = {"transactionHash": "0xbad", "topics": ["0x" + "ee" * 32], "data": "0x1"}
    result = fetch_transactions(
        _client([_log("0xa", PAYER, RECEIVER, "0x0f4240"), bad], []),
        receiver=RECEIVER,
        from_block=0,
        to_block=10,
    )
    assert len(result.transactions) == 1
    assert [tx_hash for tx_hash, _ in result.rejects] == ["0xbad"]


def test_a_log_with_no_block_number_is_rejected_not_dated_to_genesis():
    bad = {
        "transactionHash": "0xnoblk",
        "topics": [TRANSFER_TOPIC0, _padded(PAYER), _padded(RECEIVER)],
        "data": "0x0f4240",
        # blockNumber deliberately omitted
    }
    result = fetch_transactions(
        _client([_log("0xa", PAYER, RECEIVER, "0x0f4240"), bad], []),
        receiver=RECEIVER, from_block=0, to_block=10,
    )
    assert all(t.tx_hash != "0xnoblk" for t in result.transactions)
    assert any(tx_hash == "0xnoblk" and "blockNumber" in reason
               for tx_hash, reason in result.rejects)


def test_only_the_native_usdc_contract_is_queried():
    transport = FakeTransport([], [])
    fetch_transactions(
        RpcClient(transport=transport), receiver=RECEIVER, from_block=0, to_block=10
    )
    assert transport.calls == 2
    assert transport.queried_addresses == [USDC_BASE_MAINNET, USDC_BASE_MAINNET]


def test_usdbc_is_never_queried():
    # USDbC is a different, bridged token. Including it would inflate totals.
    # This test would fail if fetch_transactions ever queried it.
    transport = FakeTransport([], [])
    fetch_transactions(
        RpcClient(transport=transport), receiver=RECEIVER, from_block=0, to_block=10
    )
    assert USDBC_BASE_MAINNET_EXCLUDED not in transport.queried_addresses


def test_write_fetched_writes_the_shape_ingest_already_reads(tmp_path):
    result = fetch_transactions(
        _client([_log("0xa", PAYER, RECEIVER, "0x0f4240")], []),
        receiver=RECEIVER,
        from_block=0,
        to_block=10,
    )
    path = write_fetched(result, tmp_path)

    assert path.name == "transactions.json"
    rows = json.loads(path.read_text())
    assert set(rows[0]) == {
        "tx_hash",
        "sender_address",
        "receiver_address",
        "amount_micro_usdc",
        "timestamp",
        "memo",
        "chain",
        "raw_payload",
        "tx_type",
    }
    assert rows[0]["memo"] is None
    assert isinstance(rows[0]["amount_micro_usdc"], int)


def test_write_fetched_writes_no_ground_truth_file(tmp_path):
    # Real data arrives unlabeled. Emitting an empty ground_truth.json would
    # make the report believe it had been calibrated.
    result = fetch_transactions(
        _client([_log("0xa", PAYER, RECEIVER, "0x0f4240")], []),
        receiver=RECEIVER,
        from_block=0,
        to_block=10,
    )
    write_fetched(result, tmp_path)
    assert not (tmp_path / "ground_truth.json").exists()
    assert not (tmp_path / "service_truth.json").exists()


def test_summary_reports_rejects_so_nothing_vanishes_quietly():
    result = fetch_transactions(
        _client(
            [_log("0xa", PAYER, RECEIVER, "0x0f4240")],
            [_log("0xz", RECEIVER, STRANGER, "0x7a120")],
        ),
        receiver=RECEIVER,
        from_block=0,
        to_block=10,
    )
    summary = format_fetch_summary(result)
    assert "1 transaction" in summary
    assert "0xz" in summary

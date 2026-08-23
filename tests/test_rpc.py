import pytest

from ledger.rpc import MAX_BLOCK_SPAN, RpcClient, RpcError


class FakeTransport:
    """Records requests and replays canned responses. No sockets."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, payload):
        self.requests.append(payload)
        if not self.responses:
            raise AssertionError("FakeTransport ran out of canned responses")
        return self.responses.pop(0)


def test_call_returns_the_result_field():
    transport = FakeTransport([{"jsonrpc": "2.0", "id": 1, "result": "0xabc"}])
    assert RpcClient(transport=transport).call("eth_blockNumber", []) == "0xabc"


def test_call_raises_on_a_json_rpc_error_rather_than_returning_none():
    transport = FakeTransport(
        [{"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "bad range"}}]
    )
    with pytest.raises(RpcError, match="bad range"):
        RpcClient(transport=transport).call("eth_getLogs", [{}])


def test_get_logs_splits_a_range_wider_than_the_span_cap():
    # Public endpoints cap the block span per request. The client must walk
    # the range rather than fail the whole batch.
    span = MAX_BLOCK_SPAN
    transport = FakeTransport(
        [
            {"result": [{"transactionHash": "0x1"}]},
            {"result": [{"transactionHash": "0x2"}]},
        ]
    )
    logs = RpcClient(transport=transport).get_logs(
        address="0xtoken", topics=["0xtopic"], from_block=0, to_block=span * 2 - 1
    )

    assert [entry["transactionHash"] for entry in logs] == ["0x1", "0x2"]
    assert len(transport.requests) == 2

    first, second = (req["params"][0] for req in transport.requests)
    assert int(first["fromBlock"], 16) == 0
    assert int(first["toBlock"], 16) == span - 1
    assert int(second["fromBlock"], 16) == span
    assert int(second["toBlock"], 16) == span * 2 - 1


def test_get_logs_makes_one_request_when_the_range_fits():
    transport = FakeTransport([{"result": []}])
    RpcClient(transport=transport).get_logs(
        address="0xtoken", topics=["0xtopic"], from_block=100, to_block=200
    )
    assert len(transport.requests) == 1


def test_get_logs_passes_address_and_topics_through():
    transport = FakeTransport([{"result": []}])
    RpcClient(transport=transport).get_logs(
        address="0xtoken", topics=["0xa", None, "0xb"], from_block=1, to_block=2
    )
    params = transport.requests[0]["params"][0]
    assert params["address"] == "0xtoken"
    assert params["topics"] == ["0xa", None, "0xb"]


def test_block_timestamp_is_cached_so_a_busy_block_is_fetched_once():
    # Many transfers share a block. Without caching this is one round trip per
    # transfer, which is both slow and rude to a public endpoint.
    transport = FakeTransport([{"result": {"timestamp": "0x5f5e100"}}])
    client = RpcClient(transport=transport)

    first = client.block_timestamp("0x10")
    second = client.block_timestamp("0x10")

    assert first == second == "1973-03-03T09:46:40Z"
    assert len(transport.requests) == 1


def test_call_raises_when_the_response_has_neither_result_nor_error():
    # A malformed response must not be treated as "no data" - that would
    # let real logs vanish silently under this exact condition.
    transport = FakeTransport([{"jsonrpc": "2.0", "id": 1}])
    with pytest.raises(RpcError, match="neither"):
        RpcClient(transport=transport).call("eth_getLogs", [{}])


def test_block_timestamp_raises_when_the_block_is_missing():
    transport = FakeTransport([{"result": None}])
    with pytest.raises(RpcError, match="no block"):
        RpcClient(transport=transport).block_timestamp("0x10")

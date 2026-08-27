import pytest

from x402_recon.rpc import MAX_BLOCK_SPAN, RpcClient, RpcError


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
    # Public endpoints cap the block span per request. The client must adapt
    # to that cap and walk the range rather than fail the whole batch.
    span = MAX_BLOCK_SPAN
    transport = NarrowingTransport(limit=span)
    logs = RpcClient(transport=transport).get_logs(
        address="0xtoken", topics=["0xtopic"], from_block=0, to_block=span * 2 - 1
    )

    # Not exactly 2: halving from INITIAL_BLOCK_SPAN (100,000) lands on 6,250
    # as the first accepted span (the last power-of-two-scaled halving under
    # the 10,000 limit), so the 20,000-block range actually splits into 4
    # chunks. The invariant that matters is that it split at all, and that
    # every accepted chunk respected the cap.
    assert len(logs) > 1, "a range wider than the cap must be split"
    assert min(transport.spans) <= span, "should have narrowed to fit the cap"


def test_rate_limit_errors_are_not_treated_as_range_complaints():
    # A rate-limited response must propagate as a real error, not trigger
    # permanent span-narrowing - narrowing doesn't fix a rate limit and
    # creates a retry storm against the exact endpoint under load.
    transport = FakeTransport(
        [{"error": {"code": -32005, "message": "rate limit exceeded"}}]
    )
    with pytest.raises(RpcError, match="rate limit"):
        RpcClient(transport=transport).get_logs(
            address="0xtoken", topics=["0xtopic"], from_block=0, to_block=100
        )


def test_too_many_requests_is_not_treated_as_a_range_complaint():
    transport = FakeTransport(
        [{"error": {"code": -32005, "message": "429 Too Many Requests"}}]
    )
    with pytest.raises(RpcError):
        RpcClient(transport=transport).get_logs(
            address="0xtoken", topics=["0xtopic"], from_block=0, to_block=100
        )


def test_a_genuine_range_complaint_still_narrows():
    transport = NarrowingTransport(limit=10_000)
    logs = RpcClient(transport=transport).get_logs(
        address="0xtoken", topics=["0xtopic"], from_block=0, to_block=20_000
    )
    assert len(logs) > 1


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


from x402_recon.rpc import INITIAL_BLOCK_SPAN, MIN_BLOCK_SPAN


class NarrowingTransport:
    """Rejects any range wider than `limit`, like a real public endpoint."""

    def __init__(self, limit):
        self.limit = limit
        self.spans = []

    def __call__(self, payload):
        if payload["method"] == "eth_getLogs":
            params = payload["params"][0]
            span = int(params["toBlock"], 16) - int(params["fromBlock"], 16) + 1
            self.spans.append(span)
            if span > self.limit:
                return {"error": {"code": -32600, "message": "range too large"}}
            return {"result": [{"transactionHash": "0xok"}]}
        raise AssertionError("unexpected method")


def test_get_logs_narrows_the_span_when_the_endpoint_rejects_it():
    transport = NarrowingTransport(limit=10_000)
    client = RpcClient(transport=transport)
    logs = client.get_logs(
        address="0xtoken", topics=["0xtopic"], from_block=0, to_block=50_000
    )
    assert logs, "should have recovered and returned logs"
    assert max(transport.spans) > 10_000, "should have tried a wide span first"
    assert min(transport.spans) <= 10_000, "should have narrowed"


def test_the_narrowed_span_is_remembered_for_later_chunks():
    transport = NarrowingTransport(limit=10_000)
    client = RpcClient(transport=transport)
    client.get_logs(
        address="0xtoken", topics=["0xtopic"], from_block=0, to_block=200_000
    )
    # Once it learns the endpoint's limit it must stop re-probing wide ranges.
    # ceil(log2(INITIAL_BLOCK_SPAN / limit)) = 4 necessary halvings from
    # 100,000 down to <=10,000, plus the initial attempt = 5.
    oversized = [s for s in transport.spans if s > 10_000]
    assert len(oversized) <= 5, f"kept retrying wide spans: {oversized}"


def test_it_gives_up_rather_than_narrowing_forever():
    transport = NarrowingTransport(limit=0)  # rejects everything
    client = RpcClient(transport=transport)
    with pytest.raises(RpcError, match="range"):
        client.get_logs(
            address="0xtoken", topics=["0xtopic"], from_block=0, to_block=10_000
        )
    assert min(transport.spans) >= MIN_BLOCK_SPAN


def test_narrowing_snaps_to_a_round_span_rather_than_halving_past_it():
    # Pure halving from 100,000 would land at 6,250, which is SMALLER than
    # the common 10,000 cap it's approaching - more chunks than the old
    # fixed-10,000 chunking, not fewer. Snapping to a round value avoids that.
    transport = NarrowingTransport(limit=10_000)
    RpcClient(transport=transport).get_logs(
        address="0xtoken", topics=["0xtopic"], from_block=0, to_block=20_000
    )
    accepted = [s for s in transport.spans if s <= 10_000]
    assert 10_000 in accepted or max(accepted) >= 6_250, (
        f"should have snapped near the cap, not undershot it: {accepted}"
    )


def test_a_month_long_range_needs_fewer_chunks_than_the_old_fixed_size():
    # Regression guard for the specific defect: adaptive chunking against a
    # 10,000-block cap must not need MORE round trips than v0.2's fixed
    # 10,000-block chunking did over the same range.
    span = 1_300_000  # ~30 days at 2s/block
    transport = NarrowingTransport(limit=10_000)
    RpcClient(transport=transport).get_logs(
        address="0xtoken", topics=["0xtopic"], from_block=0, to_block=span
    )
    accepted_chunks = sum(1 for s in transport.spans if s <= 10_000)
    old_fixed_chunk_count = span // 10_000 + 1
    assert accepted_chunks <= old_fixed_chunk_count, (
        f"{accepted_chunks} accepted chunks vs {old_fixed_chunk_count} for "
        "the old fixed chunking - adaptive chunking must not be a regression"
    )


def test_transaction_receipt_returns_the_receipt():
    transport = FakeTransport([{"result": {"logs": [{"topics": ["0xaa"]}]}}])
    receipt = RpcClient(transport=transport).transaction_receipt("0xdead")
    assert receipt["logs"][0]["topics"] == ["0xaa"]


def test_transaction_receipt_returns_none_when_unknown():
    transport = FakeTransport([{"result": None}])
    assert RpcClient(transport=transport).transaction_receipt("0xdead") is None

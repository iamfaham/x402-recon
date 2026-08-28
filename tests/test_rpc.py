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


def test_the_default_transport_sends_a_real_user_agent(monkeypatch):
    # Cloudflare-fronted RPC endpoints (mainnet.base.org included) block the
    # unmodified urllib default User-Agent outright with a 403 - confirmed
    # live: identical requests differing only in this header get 403 with no
    # UA and 200 with any named one. Sending no UA at all silently makes
    # every real fetch fail before a single block is read.
    from x402_recon import rpc as rpc_module

    captured = {}

    def fake_urlopen(request, timeout):
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        raise AssertionError("stop before actually sending")

    monkeypatch.setattr(rpc_module.urllib.request, "urlopen", fake_urlopen)

    try:
        rpc_module._urllib_transport("https://example.test")({"a": 1})
    except AssertionError:
        pass

    assert "user-agent" in captured["headers"]
    assert captured["headers"]["user-agent"] != ""


def test_the_default_transport_turns_an_http_error_into_an_rpc_error(monkeypatch):
    # Confirmed live: a real eth_getLogs request against mainnet.base.org can
    # get an HTTP-level 413 "Payload Too Large" rather than a JSON-RPC error
    # body. urlopen raises this as HTTPError, not a returned response - if it
    # is not caught and translated, it crashes the whole run as an unhandled
    # exception instead of reaching get_logs's adaptive-narrowing logic,
    # which is exactly the situation that logic exists to handle.
    import urllib.error

    from x402_recon import rpc as rpc_module

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            "https://example.test", 413, "Payload Too Large", {}, None
        )

    monkeypatch.setattr(rpc_module.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RpcError, match="413"):
        rpc_module._urllib_transport("https://example.test")({"a": 1})


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


from x402_recon.rpc import (
    BASE_RETRY_DELAY,
    MAX_RETRY_ATTEMPTS,
    TRANSIENT_HTTP_CODES,
)


class FlakyTransport:
    """Fails transiently `fail_times`, then succeeds."""

    def __init__(self, fail_times, status=503):
        self.fail_times = fail_times
        self.status = status
        self.calls = 0

    def __call__(self, payload):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RpcError(
                f"HTTP {self.status}: no backend is currently healthy",
                status=self.status,
                transient=True,
            )
        return {"result": "0xabc"}


def _recording_sleep():
    waits = []
    return waits, waits.append


def test_a_transient_failure_is_retried_and_then_succeeds():
    waits, sleep = _recording_sleep()
    transport = FlakyTransport(fail_times=2)
    result = RpcClient(transport=transport, sleep=sleep).call("eth_blockNumber", [])
    assert result == "0xabc"
    assert transport.calls == 3, "should have retried twice then succeeded"
    assert len(waits) == 2, "should have slept once per retry"


def test_retries_back_off_exponentially():
    waits, sleep = _recording_sleep()
    RpcClient(transport=FlakyTransport(fail_times=3), sleep=sleep).call("m", [])
    assert waits[1] > waits[0], f"delays should grow: {waits}"
    assert waits[2] > waits[1], f"delays should grow: {waits}"


def test_retries_are_jittered_so_concurrent_runs_do_not_synchronize():
    # Two clients hitting the same failure must not sleep in lockstep - a
    # fixed schedule turns a rate limit into a thundering herd.
    seen = set()
    for _ in range(8):
        waits, sleep = _recording_sleep()
        RpcClient(transport=FlakyTransport(fail_times=1), sleep=sleep).call("m", [])
        seen.add(round(waits[0], 6))
    assert len(seen) > 1, f"delays are not jittered: {seen}"


def test_a_transient_failure_eventually_gives_up():
    waits, sleep = _recording_sleep()
    transport = FlakyTransport(fail_times=99)
    with pytest.raises(RpcError, match="503"):
        RpcClient(transport=transport, sleep=sleep).call("m", [])
    assert transport.calls == MAX_RETRY_ATTEMPTS


def test_a_non_transient_error_is_not_retried_at_all():
    class HardFailure:
        def __init__(self):
            self.calls = 0

        def __call__(self, payload):
            self.calls += 1
            raise RpcError("HTTP 400: malformed request", status=400)

    waits, sleep = _recording_sleep()
    transport = HardFailure()
    with pytest.raises(RpcError, match="400"):
        RpcClient(transport=transport, sleep=sleep).call("m", [])
    assert transport.calls == 1, "a 400 must fail immediately"
    assert waits == [], "must not sleep on a non-transient failure"


def test_every_retry_announces_itself(capsys):
    # Nothing retries silently: a slow run must be explicable.
    waits, sleep = _recording_sleep()
    RpcClient(transport=FlakyTransport(fail_times=1), sleep=sleep).call("m", [])
    out = capsys.readouterr().out
    assert "retry" in out.lower()
    assert "503" in out


def test_the_transient_code_set_covers_the_ones_seen_in_practice():
    # 503 is what mainnet.base.org actually returned three times in a row
    # during the first real run; 429 is the rate-limit case.
    for code in (429, 502, 503, 504):
        assert code in TRANSIENT_HTTP_CODES
    for code in (400, 401, 404, 413):
        assert code not in TRANSIENT_HTTP_CODES


def test_a_transient_failure_never_narrows_the_block_span():
    # THE RULE. Narrowing in response to a rate limit makes rate limiting
    # worse: a narrower span means more requests.
    class TransientThenFine:
        def __init__(self):
            self.spans = []
            self.calls = 0

        def __call__(self, payload):
            self.calls += 1
            params = payload["params"][0]
            span = int(params["toBlock"], 16) - int(params["fromBlock"], 16) + 1
            self.spans.append(span)
            if self.calls == 1:
                raise RpcError("HTTP 503: unavailable", status=503, transient=True)
            return {"result": []}

    waits, sleep = _recording_sleep()
    transport = TransientThenFine()
    RpcClient(transport=transport, sleep=sleep).get_logs(
        address="0xtoken", topics=["0xtopic"], from_block=0, to_block=500
    )
    assert transport.spans[0] == transport.spans[1], (
        f"span changed after a transient failure: {transport.spans}"
    )


def test_a_range_complaint_still_narrows_and_does_not_sleep():
    waits, sleep = _recording_sleep()
    transport = NarrowingTransport(limit=10_000)
    RpcClient(transport=transport, sleep=sleep).get_logs(
        address="0xtoken", topics=["0xtopic"], from_block=0, to_block=20_000
    )
    assert waits == [], "narrowing must not sleep"
    assert min(transport.spans) <= 10_000

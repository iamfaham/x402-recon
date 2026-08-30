import io
import json
import urllib.error

import pytest

from x402_recon.chain import USDC_BASE_MAINNET
from x402_recon.discover import (
    BASE_MAINNET_CAIP2,
    DiscoveryError,
    discover,
    parse_402_body,
)

URL = "https://example.test/search"
PAY_TO = "0x" + "ab" * 20


def _v2_body(pay_to=PAY_TO, network=BASE_MAINNET_CAIP2, asset=USDC_BASE_MAINNET):
    return {
        "x402Version": 2,
        "accepted": {
            "scheme": "exact",
            "network": network,
            "amount": "10000",
            "asset": asset,
            "payTo": pay_to,
            "maxTimeoutSeconds": 60,
        },
    }


def _v1_body(pay_to=PAY_TO, network=BASE_MAINNET_CAIP2, asset=USDC_BASE_MAINNET):
    return {
        "x402Version": 1,
        "accepts": [
            {
                "scheme": "exact",
                "network": network,
                "maxAmountRequired": "10000",
                "asset": asset,
                "payTo": pay_to,
            }
        ],
    }


def test_parses_the_v2_accepted_object():
    got = parse_402_body(_v2_body(), URL)
    assert got.pay_to == PAY_TO
    assert got.network == BASE_MAINNET_CAIP2
    assert got.asset == USDC_BASE_MAINNET
    assert got.source_url == URL


def test_parses_the_v1_accepts_array():
    assert parse_402_body(_v1_body(), URL).pay_to == PAY_TO


def test_a_missing_pay_to_fails_loudly_rather_than_guessing():
    # A wrong address produces a beautiful and entirely fictional report,
    # which is worse than an error.
    body = _v2_body()
    del body["accepted"]["payTo"]
    with pytest.raises(DiscoveryError, match="payTo"):
        parse_402_body(body, URL)


def test_an_unrecognised_body_shape_names_what_it_found():
    with pytest.raises(DiscoveryError, match="could not find payment requirements"):
        parse_402_body({"x402Version": 9, "somethingElse": {}}, URL)


def test_a_non_base_network_is_refused_by_name():
    with pytest.raises(DiscoveryError, match="solana"):
        parse_402_body(_v2_body(network="solana:mainnet"), URL)


def test_a_non_usdc_asset_is_refused_by_name():
    other = "0x" + "cd" * 20
    with pytest.raises(DiscoveryError, match=other):
        parse_402_body(_v2_body(asset=other), URL)


def test_the_pay_to_address_shape_is_validated():
    with pytest.raises(DiscoveryError, match="not a valid address"):
        parse_402_body(_v2_body(pay_to="not-an-address"), URL)


def test_asset_comparison_is_case_insensitive():
    # Checksummed addresses are mixed case; the constant is lowercase.
    got = parse_402_body(_v2_body(asset=USDC_BASE_MAINNET.upper()), URL)
    assert got.asset.lower() == USDC_BASE_MAINNET


def test_discover_uses_the_injected_transport_and_never_the_network():
    calls = []

    def transport(url):
        calls.append(url)
        return 402, _v2_body()

    got = discover(URL, transport=transport)
    assert got.pay_to == PAY_TO
    assert calls == [URL]


def test_the_default_transport_sends_a_post_request(monkeypatch):
    # Real x402 endpoints are POST-only APIs (search/RPC style, not static
    # resources) - confirmed live against Tavily and Exa, both of which
    # answer GET with a plain 404 and only respond 402 to POST. A GET-only
    # transport can never discover a real seller's payTo.
    from x402_recon import discover as discover_module

    captured = {}

    class FakeHTTPError(Exception):
        def __init__(self, code, body):
            self.code = code
            self._body = body

        def read(self):
            return self._body

    def fake_urlopen(request, timeout):
        captured["method"] = request.get_method()
        captured["data"] = request.data
        raise FakeHTTPError(402, b'{"accepts": []}')

    monkeypatch.setattr(discover_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(discover_module.urllib.error, "HTTPError", FakeHTTPError)

    try:
        discover_module.discover(URL)
    except discover_module.DiscoveryError:
        pass  # the empty accepts list correctly fails discovery; irrelevant here

    assert captured["method"] == "POST"
    assert captured["data"] is not None


def test_a_200_response_says_the_endpoint_may_not_be_paywalled():
    def transport(url):
        return 200, {"results": []}

    with pytest.raises(DiscoveryError, match="did not ask for payment"):
        discover(URL, transport=transport)


def test_a_non_json_body_is_reported_rather_than_crashing():
    def transport(url):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    with pytest.raises(DiscoveryError, match="could not read"):
        discover(URL, transport=transport)


# --- transient-failure resilience -------------------------------------------
#
# discover is the first command a new user runs. A blip on the seller's
# endpoint should not read as "this is not an x402 endpoint".


def _recording_sleep():
    waits = []
    return waits, waits.append


def test_a_transient_failure_that_recovers_returns_the_requirements():
    waits, sleep = _recording_sleep()
    attempts = []

    def transport(url):
        attempts.append(1)
        if len(attempts) < 3:
            raise DiscoveryError("503", status=503, transient=True)
        return 402, _v2_body()

    got = discover(URL, transport=transport, sleep=sleep)
    assert got.pay_to == PAY_TO
    assert len(attempts) == 3
    assert len(waits) == 2


def test_a_permanent_failure_is_not_retried():
    waits, sleep = _recording_sleep()
    attempts = []

    def transport(url):
        attempts.append(1)
        return 404, {"detail": "not found"}

    with pytest.raises(DiscoveryError, match="did not ask for payment"):
        discover(URL, transport=transport, sleep=sleep)

    assert attempts == [1], "a 404 is an answer, not a blip"
    assert waits == []


def test_exhausted_retries_still_name_what_went_wrong():
    waits, sleep = _recording_sleep()

    def transport(url):
        raise DiscoveryError(
            "https://example.test/search answered HTTP 503",
            status=503,
            transient=True,
        )

    with pytest.raises(DiscoveryError, match="503"):
        discover(URL, transport=transport, sleep=sleep)

    assert len(waits) == 3, "should have retried before giving up"


def test_the_default_transport_retries_a_503_serving_an_html_body(monkeypatch):
    # The load-bearing case. Cloudflare and nginx answer 503 with an HTML
    # error page, not JSON. Classifying on the status code BEFORE parsing is
    # what keeps that from surfacing as an unretryable JSON parse failure.
    from x402_recon import discover as discover_module

    attempts = []

    def fake_urlopen(request, timeout):
        attempts.append(1)
        if len(attempts) < 3:
            raise urllib.error.HTTPError(
                URL, 503, "Service Unavailable", {}, io.BytesIO(b"<html>oh no</html>")
            )
        raise urllib.error.HTTPError(
            URL, 402, "Payment Required", {}, io.BytesIO(json.dumps(_v2_body()).encode())
        )

    monkeypatch.setattr(discover_module.urllib.request, "urlopen", fake_urlopen)

    waits, sleep = _recording_sleep()
    got = discover_module.discover(URL, sleep=sleep)

    assert got.pay_to == PAY_TO
    assert len(attempts) == 3
    assert len(waits) == 2


def test_the_default_transport_treats_a_dropped_connection_as_retryable(monkeypatch):
    from x402_recon import discover as discover_module

    attempts = []

    def fake_urlopen(request, timeout):
        attempts.append(1)
        if len(attempts) < 2:
            raise urllib.error.URLError("connection reset by peer")
        raise urllib.error.HTTPError(
            URL, 402, "Payment Required", {}, io.BytesIO(json.dumps(_v2_body()).encode())
        )

    monkeypatch.setattr(discover_module.urllib.request, "urlopen", fake_urlopen)

    waits, sleep = _recording_sleep()
    assert discover_module.discover(URL, sleep=sleep).pay_to == PAY_TO
    assert len(attempts) == 2


def test_the_default_transport_treats_a_body_read_timeout_as_retryable(monkeypatch):
    # A timeout during the body read raises a bare TimeoutError - an OSError
    # but NOT a urllib.error.URLError, and neither subclasses the other. The
    # same gap that was fixed in rpc.py.
    from x402_recon import discover as discover_module

    attempts = []

    def fake_urlopen(request, timeout):
        attempts.append(1)
        if len(attempts) < 2:
            raise TimeoutError("timed out")
        raise urllib.error.HTTPError(
            URL, 402, "Payment Required", {}, io.BytesIO(json.dumps(_v2_body()).encode())
        )

    monkeypatch.setattr(discover_module.urllib.request, "urlopen", fake_urlopen)

    waits, sleep = _recording_sleep()
    assert discover_module.discover(URL, sleep=sleep).pay_to == PAY_TO
    assert len(attempts) == 2


def test_a_404_from_the_default_transport_is_not_retried(monkeypatch):
    from x402_recon import discover as discover_module

    attempts = []

    def fake_urlopen(request, timeout):
        attempts.append(1)
        raise urllib.error.HTTPError(
            URL, 404, "Not Found", {}, io.BytesIO(b'{"detail": "nope"}')
        )

    monkeypatch.setattr(discover_module.urllib.request, "urlopen", fake_urlopen)

    waits, sleep = _recording_sleep()
    with pytest.raises(DiscoveryError, match="did not ask for payment"):
        discover_module.discover(URL, sleep=sleep)

    assert attempts == [1]
    assert waits == []

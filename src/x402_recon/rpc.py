"""JSON-RPC transport for reading chain logs.

This is the only module in the project that opens a network connection. Every
other stage runs offline, which is what keeps the pipeline testable and a
fetched batch replayable from disk.
"""

import json
import random
import time
import urllib.request

from x402_recon.chain import block_timestamp_to_iso

DEFAULT_BASE_RPC_URL = "https://mainnet.base.org"

# Public endpoints reject wide eth_getLogs ranges. 10_000 is the common cap;
# the client walks anything larger rather than failing the whole batch.
MAX_BLOCK_SPAN = 10_000

# A 30-day window is ~1.3M blocks. At a fixed 10,000-block span that is 130
# round trips to a public endpoint, which invites rate-limiting. Start wide,
# narrow only when the endpoint objects, and remember what it accepted.
INITIAL_BLOCK_SPAN = 100_000
MIN_BLOCK_SPAN = 1_000

_TIMEOUT_SECONDS = 30

# Cloudflare-fronted RPC endpoints (mainnet.base.org included) block
# requests carrying no User-Agent, or the unmodified urllib default,
# outright with a 403. Confirmed live: identical requests differing only in
# this header get 403 with none and 200 with any named one.
_USER_AGENT = "x402-recon (+https://github.com/iamfaham/x402-recon)"

# Codes that mean "try again shortly", not "your request was wrong".
# 503 is what mainnet.base.org actually returned three times consecutively
# during the first real run against it.
TRANSIENT_HTTP_CODES = frozenset({429, 502, 503, 504})

MAX_RETRY_ATTEMPTS = 4
MAX_RETRY_SECONDS = 30.0
BASE_RETRY_DELAY = 0.5


class RpcError(RuntimeError):
    """The endpoint returned an error, or a response we cannot use.

    `transient` distinguishes "try again shortly" from "your request was
    wrong". The two need opposite responses, and applying the wrong one makes
    things worse rather than merely failing to help: narrowing the block span
    in response to a rate limit produces MORE requests.
    """

    def __init__(self, message: str, *, status: int | None = None, transient: bool = False):
        super().__init__(message)
        self.status = status
        self.transient = transient


def _urllib_transport(url: str):
    def send(payload: dict) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # An HTTP-level error (confirmed live: a real 413 "Payload Too
            # Large" from eth_getLogs) arrives as an exception rather than a
            # JSON-RPC error body. Try the body first - some endpoints still
            # return a JSON-RPC-shaped error even on a non-200 status - and
            # fall back to the status line so the message is still
            # classifiable by _looks_like_range_complaint below.
            try:
                body = json.loads(exc.read().decode("utf-8"))
                if isinstance(body, dict) and "error" in body:
                    raise RpcError(
                        f"HTTP {exc.code}: {body['error'].get('message', body['error'])}",
                        status=exc.code,
                        transient=exc.code in TRANSIENT_HTTP_CODES,
                    ) from exc
            except (ValueError, AttributeError):
                pass
            raise RpcError(
                f"HTTP {exc.code}: {exc.reason}",
                status=exc.code,
                transient=exc.code in TRANSIENT_HTTP_CODES,
            ) from exc
        except urllib.error.URLError as exc:
            # A timeout or a dropped connection - retryable, and not the
            # endpoint telling us anything about our request.
            raise RpcError(f"connection failed: {exc.reason}", transient=True) from exc

    return send


class RpcClient:
    """Minimal JSON-RPC client with an injectable transport."""

    def __init__(self, url: str = DEFAULT_BASE_RPC_URL, *, transport=None, sleep=time.sleep):
        self._transport = transport or _urllib_transport(url)
        self._sleep = sleep
        self._request_id = 0
        self._block_timestamps: dict[str, str] = {}
        self._span = INITIAL_BLOCK_SPAN

    def _send_with_retry(self, payload):
        """Send, retrying transient failures with jittered exponential backoff.

        Nothing retries silently: a slow run must be explicable rather than
        mysterious, which is the same guarantee the reject list gives for data.
        """
        attempt = 0
        slept = 0.0
        while True:
            try:
                return self._transport(payload)
            except RpcError as exc:
                attempt += 1
                if (
                    not exc.transient
                    or attempt >= MAX_RETRY_ATTEMPTS
                    or slept >= MAX_RETRY_SECONDS
                ):
                    raise
                delay = BASE_RETRY_DELAY * (2 ** (attempt - 1))
                delay *= random.uniform(0.5, 1.5)  # jitter: avoid a thundering herd
                delay = min(delay, MAX_RETRY_SECONDS - slept)
                print(
                    f"  retry {attempt}/{MAX_RETRY_ATTEMPTS} in {delay:.1f}s: {exc}"
                )
                self._sleep(delay)
                slept += delay

    def call(self, method: str, params: list) -> object:
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        response = self._send_with_retry(payload)
        if "error" in response:
            raise RpcError(f"{method} failed: {response['error'].get('message')}")
        if "result" not in response:
            raise RpcError(
                f"{method} returned a response with neither 'result' nor "
                f"'error': {response!r}"
            )
        return response["result"]

    def get_logs(
        self, *, address: str, topics: list, from_block: int, to_block: int
    ) -> list[dict]:
        """Fetch logs, adapting the chunk span to what the endpoint accepts."""
        logs: list[dict] = []
        start = from_block
        while start <= to_block:
            end = min(start + self._span - 1, to_block)
            try:
                chunk = self.call(
                    "eth_getLogs",
                    [
                        {
                            "address": address,
                            "topics": topics,
                            "fromBlock": hex(start),
                            "toBlock": hex(end),
                        }
                    ],
                )
            except RpcError as exc:
                if self._span > MIN_BLOCK_SPAN and _looks_like_range_complaint(exc):
                    self._span = max(MIN_BLOCK_SPAN, _narrow(self._span))
                    continue
                raise
            logs.extend(chunk or [])
            start = end + 1
        return logs

    def transaction_receipt(self, tx_hash: str) -> dict | None:
        """The receipt for a transaction, or None when the node has no record."""
        return self.call("eth_getTransactionReceipt", [tx_hash])

    def block_timestamp(self, block_number_hex: str) -> str:
        """ISO 8601 UTC timestamp for a block, cached per block."""
        if block_number_hex in self._block_timestamps:
            return self._block_timestamps[block_number_hex]

        block = self.call("eth_getBlockByNumber", [block_number_hex, False])
        if not block or "timestamp" not in block:
            raise RpcError(f"no block returned for {block_number_hex}")

        formatted = block_timestamp_to_iso(block["timestamp"])
        self._block_timestamps[block_number_hex] = formatted
        return formatted


_ROUND_SPANS = (50_000, 20_000, 10_000, 5_000, 2_000, 1_000)


def _narrow(current_span: int) -> int:
    """The next span to try after a rejection.

    Prefers snapping to a round, commonly-accepted value over blind halving,
    since pure halving from a large optimistic start can overshoot past a
    round cap (e.g. 100,000 halves to 6,250, past the common 10,000 limit)
    and end up making MORE requests than a fixed chunk size would have.
    """
    for candidate in _ROUND_SPANS:
        if candidate < current_span:
            return candidate
    return max(MIN_BLOCK_SPAN, current_span // 2)


def _looks_like_range_complaint(error: Exception) -> bool:
    """Whether an RPC error is the endpoint objecting to the block span.

    Endpoints word this differently, so match on substance rather than an
    exact string. A miss here costs one failed request, not correctness.

    Deliberately excludes rate-limit wording ("rate limit", "too many
    requests") even though it can contain "limit" - narrowing the span in
    response to a rate limit doesn't fix the actual problem and creates a
    feedback loop (narrower span -> more requests -> more rate-limiting).
    """
    text = str(error).lower()
    if "rate limit" in text or "too many requests" in text or "429" in text:
        return False
    return any(
        phrase in text
        for phrase in ("range", "too large", "block range", "results")
    )

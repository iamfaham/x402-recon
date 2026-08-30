"""JSON-RPC transport for reading chain logs.

This is the only module in the project that opens a network connection. Every
other stage runs offline, which is what keeps the pipeline testable and a
fetched batch replayable from disk.
"""

import json
import time
import urllib.request

from x402_recon import retry as retry_module
from x402_recon.chain import block_timestamp_to_iso
from x402_recon.retry import retry_transient

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

# The retry policy is shared with discover.py so the two cannot drift apart;
# re-exported here because this module's callers and tests read them from it.
TRANSIENT_HTTP_CODES = retry_module.TRANSIENT_HTTP_CODES
MAX_RETRY_ATTEMPTS = retry_module.MAX_RETRY_ATTEMPTS
MAX_RETRY_SECONDS = retry_module.MAX_RETRY_SECONDS
BASE_RETRY_DELAY = retry_module.BASE_RETRY_DELAY

# One HTTP request carrying many eth_getBlockByNumber calls. A 30-day report
# touches thousands of distinct blocks; batching turns ~5,000 round trips
# into ~50 without approximating a single timestamp.
TIMESTAMP_BATCH_SIZE = 100


class RpcError(RuntimeError):
    """The endpoint returned an error, or a response we cannot use.

    `transient` distinguishes "try again shortly" from "your request was
    wrong". The two need opposite responses, and applying the wrong one makes
    things worse rather than merely failing to help: narrowing the block span
    in response to a rate limit produces MORE requests.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        transient: bool = False,
        batch_refused: bool = False,
    ):
        super().__init__(message)
        self.status = status
        self.transient = transient
        self.batch_refused = batch_refused


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
        except TimeoutError as exc:
            # A timeout during response.read() (the body read, after connect)
            # raises a bare TimeoutError - an OSError subclass, but NOT a
            # urllib.error.URLError, and neither subclasses the other. Left
            # uncaught, this escapes as an unclassified exception instead of
            # the documented retry-eligible RpcError. TimeoutError has no
            # `.reason` attribute, unlike URLError, so use str(exc) here.
            raise RpcError(f"connection failed: {exc}", transient=True) from exc

    return send


class RpcClient:
    """Minimal JSON-RPC client with an injectable transport."""

    def __init__(self, url: str = DEFAULT_BASE_RPC_URL, *, transport=None, sleep=time.sleep):
        self._transport = transport or _urllib_transport(url)
        self._sleep = sleep
        self._request_id = 0
        self._block_timestamps: dict[str, str] = {}
        self._span = INITIAL_BLOCK_SPAN
        self._batch_supported = True

    def _send_with_retry(self, payload):
        """Send, retrying transient failures with jittered exponential backoff.

        The policy itself lives in retry.py, shared with discover.py; RpcError
        carries the `transient` flag it reads.
        """
        return retry_transient(lambda: self._transport(payload), sleep=self._sleep)

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
                if (
                    not exc.transient
                    and self._span > MIN_BLOCK_SPAN
                    and _looks_like_range_complaint(exc)
                ):
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

    def call_batch(self, method: str, params_list: list[list]) -> list:
        """Send many JSON-RPC calls in one HTTP request, in order.

        Raises RpcError if any individual entry reports an error - that is
        real data about that request, distinct from the endpoint refusing
        arrays altogether, which surfaces as a non-list response.
        """
        payload = []
        for params in params_list:
            self._request_id += 1
            payload.append(
                {
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": method,
                    "params": params,
                }
            )

        try:
            response = self._send_with_retry(payload)
        except RpcError as exc:
            # A non-transient failure raised while *sending* the batch itself
            # (a definite HTTP-level rejection, e.g. 400) means this
            # endpoint's shape is unsupported - mark it structurally so
            # callers can distinguish it from an error about one entry
            # inside an accepted batch, without text-matching. A transient
            # failure (429/502/503/504/timeout) already went through the
            # normal retry path above; if it still reaches here, retries were
            # exhausted, and it must propagate as a real failure, not a
            # permanent "batching not supported" verdict.
            if not exc.transient:
                exc.batch_refused = True
            raise
        if not isinstance(response, list):
            raise RpcError(
                f"{method} batch got a non-array response; this endpoint may "
                f"not support batching: {response!r}",
                batch_refused=True,
            )

        by_id = {entry.get("id"): entry for entry in response}
        results = []
        for sent in payload:
            entry = by_id.get(sent["id"])
            if entry is None:
                raise RpcError(f"{method} batch response is missing id {sent['id']}")
            if "error" in entry:
                raise RpcError(
                    f"{method} failed: {entry['error'].get('message', entry['error'])}"
                )
            results.append(entry.get("result"))
        return results

    def prefetch_block_timestamps(self, block_numbers) -> None:
        """Fill the timestamp cache for many blocks in as few requests as possible.

        Callers keep using `block_timestamp` exactly as before; this only
        changes how many round trips that costs. An endpoint that refuses
        array payloads falls back to sequential calls for the rest of the run.
        """
        missing = [
            block
            for block in dict.fromkeys(block_numbers)
            if block not in self._block_timestamps
        ]
        if not missing:
            return

        if self._batch_supported:
            for start in range(0, len(missing), TIMESTAMP_BATCH_SIZE):
                chunk = missing[start : start + TIMESTAMP_BATCH_SIZE]
                try:
                    blocks = self.call_batch(
                        "eth_getBlockByNumber", [[block, False] for block in chunk]
                    )
                except RpcError as exc:
                    if not (exc.batch_refused or _looks_like_batch_refusal(exc)):
                        raise
                    # The endpoint will not take arrays. Remember it, and
                    # finish this prefetch sequentially below.
                    self._batch_supported = False
                    print(
                        f"  batching not supported by this endpoint, falling "
                        f"back to sequential calls: {exc}"
                    )
                    break
                for block, data in zip(chunk, blocks):
                    if not data or "timestamp" not in data:
                        raise RpcError(f"no block returned for {block}")
                    self._block_timestamps[block] = block_timestamp_to_iso(
                        data["timestamp"]
                    )
            else:
                return

        for block in missing:
            if block not in self._block_timestamps:
                self.block_timestamp(block)


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


def _looks_like_batch_refusal(error: Exception) -> bool:
    """Whether the endpoint rejected the batch SHAPE rather than its contents.

    This is now a defensive fallback, not the primary signal: the primary
    classification is structural, via `RpcError.batch_refused`, which is set
    at the two raise sites in `call_batch` that actually know the failure
    happened while sending/parsing the batch itself rather than about one
    entry inside it. This text heuristic only catches errors that predate
    that flag (or come from elsewhere) and would otherwise be missed.

    An error about one request inside a batch is real data about that request.
    An error saying arrays are unsupported means fall back to sequential.
    Conflating them either disables batching against a working endpoint or
    hides a genuine error against a broken one.
    """
    text = str(error).lower()
    return "batch" in text or "non-array response" in text


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

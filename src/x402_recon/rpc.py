"""JSON-RPC transport for reading chain logs.

This is the only module in the project that opens a network connection. Every
other stage runs offline, which is what keeps the pipeline testable and a
fetched batch replayable from disk.
"""

import json
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


class RpcError(RuntimeError):
    """The endpoint returned an error, or a response we cannot use."""


def _urllib_transport(url: str):
    def send(payload: dict) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))

    return send


class RpcClient:
    """Minimal JSON-RPC client with an injectable transport."""

    def __init__(self, url: str = DEFAULT_BASE_RPC_URL, *, transport=None):
        self._transport = transport or _urllib_transport(url)
        self._request_id = 0
        self._block_timestamps: dict[str, str] = {}
        self._span = INITIAL_BLOCK_SPAN

    def call(self, method: str, params: list) -> object:
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        response = self._transport(payload)
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
                    self._span = max(MIN_BLOCK_SPAN, self._span // 2)
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


def _looks_like_range_complaint(error: Exception) -> bool:
    """Whether an RPC error is the endpoint objecting to the block span.

    Endpoints word this differently, so match on substance rather than an
    exact string. A miss here costs one failed request, not correctness.
    """
    text = str(error).lower()
    return any(
        phrase in text
        for phrase in ("range", "too large", "too many", "limit", "exceed")
    )

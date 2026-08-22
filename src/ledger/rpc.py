"""JSON-RPC transport for reading chain logs.

This is the only module in the project that opens a network connection. Every
other stage runs offline, which is what keeps the pipeline testable and a
fetched batch replayable from disk.
"""

import json
import urllib.request

from ledger.chain import block_timestamp_to_iso

DEFAULT_BASE_RPC_URL = "https://mainnet.base.org"

# Public endpoints reject wide eth_getLogs ranges. 10_000 is the common cap;
# the client walks anything larger rather than failing the whole batch.
MAX_BLOCK_SPAN = 10_000

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
        return response.get("result")

    def get_logs(
        self, *, address: str, topics: list, from_block: int, to_block: int
    ) -> list[dict]:
        """Fetch logs, walking the range in chunks the endpoint will accept."""
        logs: list[dict] = []
        start = from_block
        while start <= to_block:
            end = min(start + MAX_BLOCK_SPAN - 1, to_block)
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
            logs.extend(chunk or [])
            start = end + 1
        return logs

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

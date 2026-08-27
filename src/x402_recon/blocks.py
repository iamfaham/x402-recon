# src/x402_recon/blocks.py
"""Turn dates into block numbers, exactly.

Base targets two-second blocks but drifts, so a block-time estimate silently
includes or drops real payments at a month boundary. Binary search costs about
twenty requests and is exact, which is the right trade for a financial edge.

Boundary semantics, fixed by the spec:
  --from D  -> the FIRST block whose timestamp is >= D T00:00:00Z
  --to   D  -> the LAST  block whose timestamp is <= D T23:59:59Z
"""

from datetime import datetime, timedelta, timezone

_DATE_FORMAT = "%Y-%m-%d"


def _head(client) -> int:
    return int(client.call("eth_blockNumber", []), 16)


def block_timestamp_seconds(client, block_number: int) -> int:
    """Unix seconds for a block, as an int."""
    block = client.call("eth_getBlockByNumber", [hex(block_number), False])
    if not block or "timestamp" not in block:
        raise ValueError(f"no block returned for {block_number}")
    return int(block["timestamp"], 16)


def first_block_at_or_after(client, target_seconds: int) -> int:
    """Lowest block number whose timestamp is >= target_seconds."""
    low, high = 0, _head(client)
    if block_timestamp_seconds(client, high) < target_seconds:
        raise ValueError(
            f"{_iso(target_seconds)} is after the latest block on this chain"
        )
    if block_timestamp_seconds(client, low) >= target_seconds:
        return low

    # Invariant: low is strictly before the target, high is at or after it.
    while high - low > 1:
        middle = (low + high) // 2
        if block_timestamp_seconds(client, middle) < target_seconds:
            low = middle
        else:
            high = middle
    return high


def last_block_at_or_before(client, target_seconds: int) -> int:
    """Highest block number whose timestamp is <= target_seconds."""
    low, high = 0, _head(client)
    if block_timestamp_seconds(client, high) <= target_seconds:
        return high
    if block_timestamp_seconds(client, low) > target_seconds:
        raise ValueError(
            f"{_iso(target_seconds)} is before the first block on this chain"
        )

    # Invariant: low is at or before the target, high is strictly after it.
    while high - low > 1:
        middle = (low + high) // 2
        if block_timestamp_seconds(client, middle) <= target_seconds:
            low = middle
        else:
            high = middle
    return low


def _iso(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def resolve_range(client, start_date: str, end_date: str) -> tuple[int, int]:
    """Resolve an inclusive YYYY-MM-DD range to an inclusive block range."""
    start = datetime.strptime(start_date, _DATE_FORMAT).replace(tzinfo=timezone.utc)
    end = datetime.strptime(end_date, _DATE_FORMAT).replace(tzinfo=timezone.utc)
    if end < start:
        raise ValueError(f"{end_date} is before {start_date}")

    start_seconds = int(start.timestamp())
    end_seconds = int((end + timedelta(days=1)).timestamp()) - 1
    return (
        first_block_at_or_after(client, start_seconds),
        last_block_at_or_before(client, end_seconds),
    )


def days_ago_range(client, days: int) -> tuple[int, int]:
    """The last `days` days, ending at the current head."""
    head = _head(client)
    head_seconds = block_timestamp_seconds(client, head)
    return first_block_at_or_after(client, head_seconds - days * 86_400), head

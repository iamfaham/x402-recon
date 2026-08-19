"""Synthetic x402-style transaction generator with ground truth.

The dataset must be able to break the cascade. It deliberately includes repeat
senders across separated bursts, one-off senders that belong to no group,
generic and absent memos, and near-miss addresses that share a prefix but must
not be collapsed together.
"""

import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ledger.models import TIMESTAMP_FORMAT, UNGROUPABLE, Transaction

_CHAIN = "base-sepolia-sim"
_RECEIVER = "0xmerchant000000000000000000000000000000001"
_START = datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC)

# Recurring agents: (group name, memo or None, number of bursts)
_AGENTS = [
    ("agent-weather", "weather-api", 3),
    ("agent-search", "search-api", 3),
    ("agent-scraper", None, 2),
    ("agent-generic", "payment", 2),
    ("agent-llm", "llm-inference", 2),
]

_GENERIC_MEMOS = [None, "payment", "x402", ""]


def _iso(moment: datetime) -> str:
    return moment.strftime(TIMESTAMP_FORMAT)


def _address(rng: random.Random, prefix: str = "0x") -> str:
    """Generate an address of realistic length, optionally sharing a prefix."""
    body_length = 42 - len(prefix)
    body = "".join(rng.choice("0123456789abcdef") for _ in range(body_length))
    return prefix + body


@dataclass(frozen=True)
class SimulatedBatch:
    """Generated transactions plus the correct grouping for each."""

    transactions: list[Transaction]
    ground_truth: dict[str, str]


def generate_batch(count: int = 120, seed: int = 42) -> SimulatedBatch:
    """Generate at least `count` transactions with known ground truth."""
    rng = random.Random(seed)
    transactions: list[Transaction] = []
    ground_truth: dict[str, str] = {}
    clock = _START

    def add(sender: str, memo: str | None, group: str, moment: datetime) -> None:
        tx_hash = "0x" + "".join(rng.choice("0123456789abcdef") for _ in range(64))
        transactions.append(
            Transaction(
                tx_hash=tx_hash,
                sender_address=sender,
                receiver_address=_RECEIVER,
                amount_micro_usdc=rng.randint(500, 250_000),
                timestamp=_iso(moment),
                memo=memo,
                chain=_CHAIN,
                raw_payload=json.dumps({"protocol": "x402", "simulated": True}),
            )
        )
        ground_truth[tx_hash] = group

    # Recurring agents, each appearing in separated bursts.
    for group, memo, bursts in _AGENTS:
        sender = _address(rng)
        for _ in range(bursts):
            clock += timedelta(hours=rng.randint(2, 20))
            for _ in range(rng.randint(4, 9)):
                clock += timedelta(seconds=rng.randint(5, 120))
                add(sender, memo, group, clock)

    # Near-miss pair: two distinct agents sharing an address prefix.
    shared_prefix = "0x" + "".join(rng.choice("0123456789abcdef") for _ in range(8))
    for suffix_group in ("agent-nearmiss-a", "agent-nearmiss-b"):
        sender = _address(rng, prefix=shared_prefix)
        clock += timedelta(hours=rng.randint(2, 8))
        for _ in range(rng.randint(3, 6)):
            clock += timedelta(seconds=rng.randint(5, 120))
            add(sender, "data-feed", suffix_group, clock)

    # An agent that rotates its sender address on every transaction but keeps
    # one consistent, specific memo (a fresh wallet per payment, tagged with
    # the same service identifier). Each sender appears exactly once, so
    # sender_match cannot fire; the shared specific memo is what makes these
    # groupable, which is exactly what memo_match exists to catch.
    for _ in range(6):
        clock += timedelta(seconds=rng.randint(10, 400))
        add(_address(rng), "invoice-settlement", "agent-rotating", clock)

    # One-off senders that belong to no group. The clock is strictly monotonic
    # and these are appended last, so they form one contiguous tail and only
    # ever cluster with each other, never with a real agent burst. Interleaving
    # them into the agent bursts above so time-clustering has a genuinely
    # plausible-but-wrong case to latch onto is a known v0.1 improvement.
    while len(transactions) < count:
        clock += timedelta(seconds=rng.randint(10, 400))
        add(_address(rng), rng.choice(_GENERIC_MEMOS), UNGROUPABLE, clock)

    return SimulatedBatch(transactions=transactions, ground_truth=ground_truth)


def write_batch(batch: SimulatedBatch, out_dir: Path) -> tuple[Path, Path]:
    """Write transactions.json and ground_truth.json into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tx_path = out_dir / "transactions.json"
    gt_path = out_dir / "ground_truth.json"

    tx_path.write_text(
        json.dumps(
            [
                {
                    "tx_hash": t.tx_hash,
                    "sender_address": t.sender_address,
                    "receiver_address": t.receiver_address,
                    "amount_micro_usdc": t.amount_micro_usdc,
                    "timestamp": t.timestamp,
                    "memo": t.memo,
                    "chain": t.chain,
                    "raw_payload": t.raw_payload,
                }
                for t in batch.transactions
            ],
            indent=2,
        )
    )
    gt_path.write_text(json.dumps(batch.ground_truth, indent=2))
    return tx_path, gt_path

"""Synthetic x402-style transaction generator with ground truth.

Every actor generates its activity independently across one shared time
window; all events then merge and sort by timestamp. Interleaving is therefore
a property of how generation works rather than a feature bolted on — which is
what lets a one-off payment land inside a real agent's burst, and lets
time-clustering be caught guessing wrong.

Each hazard exists to make one cascade rule falsifiable. A dataset that cannot
catch a rule being wrong cannot measure it either.
"""

import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ledger.models import (
    TIMESTAMP_FORMAT,
    TX_TYPE_PAYMENT,
    TX_TYPE_REFUND,
    UNGROUPABLE,
    Transaction,
)

_CHAIN = "base-sepolia-sim"
_RECEIVER = "0xmerchant000000000000000000000000000000001"
_WINDOW_START = datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC)
_WINDOW_SECONDS = 14 * 24 * 3600  # a two-week trading window

# Hazard names, recorded per transaction in hazards.json.
HAZARD_INTERLEAVED_ONE_OFF = "interleaved_one_off"
HAZARD_SHARED_MEMO = "shared_memo_strangers"
HAZARD_ROTATING_ADDRESS = "rotating_address"
HAZARD_MEMO_DRIFT = "memo_drift"
HAZARD_REFUND = "refund"

# Ordinary recurring agents: (group, memo or None, burst count).
_AGENTS = [
    ("agent-weather", "weather-api", 3),
    ("agent-search", "search-api", 3),
    ("agent-scraper", None, 2),
    ("agent-generic", "payment", 2),
    ("agent-llm", "llm-inference", 2),
]

_GENERIC_MEMOS = [None, "payment", "x402", ""]


@dataclass(frozen=True)
class HazardConfig:
    """How much adversarial material the dataset carries.

    Frozen before measurement so dataset difficulty is a deliberate setting.
    A later change in the metrics can then be attributed to a rule change
    rather than to silent drift in how hard the data got.
    """

    interleaved_one_offs: int = 22
    shared_memo_strangers: int = 6
    rotating_address_payments: int = 6
    memo_drift_agents: int = 1
    refund_count: int = 8


DEFAULT_HAZARDS = HazardConfig()


@dataclass(frozen=True)
class SimulatedBatch:
    """Generated transactions, their correct grouping, and hazard tags."""

    transactions: list[Transaction]
    ground_truth: dict[str, str]
    hazards: dict[str, str]


@dataclass
class _Event:
    moment: datetime
    transaction: Transaction
    true_group: str
    hazard: str | None


def _iso(moment: datetime) -> str:
    return moment.strftime(TIMESTAMP_FORMAT)


def _address(rng: random.Random, prefix: str = "0x") -> str:
    body = "".join(rng.choice("0123456789abcdef") for _ in range(42 - len(prefix)))
    return prefix + body


def _amount(rng: random.Random) -> int:
    """Spread amounts from sub-cent dust to multi-dollar calls."""
    if rng.random() < 0.35:
        return rng.randint(200, 9_999)
    return rng.randint(10_000, 4_000_000)


def _somewhere_in_window(rng: random.Random) -> datetime:
    return _WINDOW_START + timedelta(seconds=rng.randint(0, _WINDOW_SECONDS))


class _Builder:
    """Accumulates events; every emission records group and hazard together."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.events: list[_Event] = []

    def emit(
        self,
        sender: str,
        memo: str | None,
        group: str,
        moment: datetime,
        hazard: str | None = None,
        tx_type: str = TX_TYPE_PAYMENT,
        amount: int | None = None,
    ) -> Transaction:
        tx_hash = "0x" + "".join(
            self.rng.choice("0123456789abcdef") for _ in range(64)
        )
        transaction = Transaction(
            tx_hash=tx_hash,
            sender_address=sender,
            receiver_address=_RECEIVER,
            amount_micro_usdc=amount if amount is not None else _amount(self.rng),
            timestamp=_iso(moment),
            memo=memo,
            chain=_CHAIN,
            raw_payload=json.dumps({"protocol": "x402", "simulated": True}),
            tx_type=tx_type,
        )
        self.events.append(_Event(moment, transaction, group, hazard))
        return transaction

    def burst(
        self,
        sender: str,
        memo: str | None,
        group: str,
        size: int,
        hazard: str | None = None,
    ) -> list[Transaction]:
        """One session: several payments minutes apart, placed anywhere."""
        moment = _somewhere_in_window(self.rng)
        made = []
        for _ in range(size):
            moment += timedelta(seconds=self.rng.randint(5, 120))
            made.append(self.emit(sender, memo, group, moment, hazard))
        return made


def generate_batch(
    count: int = 120,
    seed: int = 42,
    hazards: HazardConfig = DEFAULT_HAZARDS,
) -> SimulatedBatch:
    """Generate at least `count` transactions with ground truth and hazard tags."""
    rng = random.Random(seed)
    b = _Builder(rng)

    # Ordinary recurring agents — the bulk of the data, which every rule is
    # expected to get right.
    for group, memo, bursts in _AGENTS:
        sender = _address(rng)
        for _ in range(bursts):
            b.burst(sender, memo, group, rng.randint(4, 9))

    # Near-miss pair: distinct agents whose addresses share a prefix.
    shared_prefix = "0x" + "".join(rng.choice("0123456789abcdef") for _ in range(8))
    for group in ("agent-nearmiss-a", "agent-nearmiss-b"):
        b.burst(_address(rng, prefix=shared_prefix), "data-feed", group, rng.randint(3, 6))

    # HAZARD: an agent rotating its address mid-life. It uses address A for
    # several payments, then switches to address B for several more. Each
    # address appears at least twice so sender_match fires on both halves and
    # splits this one true payer into two predicted groups — manufacturing
    # genuine fragmentation for B-cubed recall to catch. Ground truth stays
    # one group for all of them.
    _rotating_total = hazards.rotating_address_payments
    _rotating_first_half = max(2, _rotating_total // 2)
    _rotating_second_half = max(2, _rotating_total - _rotating_first_half)
    address_a = _address(rng)
    address_b = _address(rng)
    for address, count in ((address_a, _rotating_first_half), (address_b, _rotating_second_half)):
        for _ in range(count):
            b.emit(
                address,
                "invoice-settlement",
                "agent-rotating",
                _somewhere_in_window(rng),
                hazard=HAZARD_ROTATING_ADDRESS,
            )

    # HAZARD: memo drift. One payer, but its address rotates so no address
    # ever repeats — the opposite of the rotating-address hazard above — so
    # sender_match cannot intercept these before memo_match sees them. The
    # memo changes across versions while ground truth stays one group.
    for i in range(hazards.memo_drift_agents):
        group = f"agent-drift-{i}"
        for version, memo in enumerate(("report-api", "report-api-v2", "reports")):
            moment = _somewhere_in_window(rng)
            for _ in range(rng.randint(2, 4)):
                moment += timedelta(seconds=rng.randint(5, 120))
                b.emit(_address(rng), memo, group, moment, hazard=HAZARD_MEMO_DRIFT)

    # HAZARD: strangers sharing one specific memo. memo_match will collapse
    # them; ground truth says they are different payers.
    for i in range(hazards.shared_memo_strangers):
        b.emit(
            _address(rng),
            "monthly-usage",
            f"agent-stranger-{i}",
            _somewhere_in_window(rng),
            hazard=HAZARD_SHARED_MEMO,
        )

    # HAZARD: one-off payers scattered across the window. Because everything
    # shares one timeline, these land inside real agent bursts — giving
    # time_cluster both plausible-but-wrong and plausible-and-right cases.
    for _ in range(hazards.interleaved_one_offs):
        b.emit(
            _address(rng),
            rng.choice(_GENERIC_MEMOS),
            UNGROUPABLE,
            _somewhere_in_window(rng),
            hazard=HAZARD_INTERLEAVED_ONE_OFF,
        )

    # HAZARD: refunds against real earlier payments, same payer and group.
    # Memo-drift transactions are excluded: a refund reuses its original's
    # sender address, and doing that for a memo-drift payment would make that
    # one address repeat - letting sender_match intercept it and defeating
    # the whole point of the memo-drift hazard (C1b).
    refundable = [
        e for e in b.events
        if e.true_group != UNGROUPABLE and e.hazard != HAZARD_MEMO_DRIFT
    ]
    for original in rng.sample(refundable, min(hazards.refund_count, len(refundable))):
        b.emit(
            original.transaction.sender_address,
            original.transaction.memo,
            original.true_group,
            original.moment + timedelta(hours=rng.randint(1, 48)),
            hazard=HAZARD_REFUND,
            tx_type=TX_TYPE_REFUND,
            amount=original.transaction.amount_micro_usdc,
        )

    # Top up with further ungroupable one-offs until the requested size. This
    # filler exists only to reach `count`; it is not adversarial material, so
    # it carries no hazard tag. Only the configured
    # `hazards.interleaved_one_offs` count is tagged HAZARD_INTERLEAVED_ONE_OFF
    # — bounding hazard tags by HazardConfig alone (rather than by how long a
    # random top-up loop happens to run) is what keeps dataset difficulty a
    # deliberate, frozen setting.
    while len(b.events) < count:
        b.emit(
            _address(rng),
            rng.choice(_GENERIC_MEMOS),
            UNGROUPABLE,
            _somewhere_in_window(rng),
        )

    # One shared timeline. Ties break on tx_hash so runs cannot reorder.
    b.events.sort(key=lambda e: (e.transaction.timestamp, e.transaction.tx_hash))

    return SimulatedBatch(
        transactions=[e.transaction for e in b.events],
        ground_truth={e.transaction.tx_hash: e.true_group for e in b.events},
        hazards={
            e.transaction.tx_hash: e.hazard for e in b.events if e.hazard is not None
        },
    )


def write_batch(batch: SimulatedBatch, out_dir: Path) -> tuple[Path, Path, Path]:
    """Write transactions.json, ground_truth.json, and hazards.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tx_path = out_dir / "transactions.json"
    gt_path = out_dir / "ground_truth.json"
    hz_path = out_dir / "hazards.json"

    # Written ordered by tx_hash, not timestamp. tx_hash is random and
    # uncorrelated with time, so the JSON on disk is deliberately NOT in
    # arrival order — a deterministic shuffle that catches any downstream
    # stage that wrongly assumes input order. `batch.transactions` (the
    # canonical in-memory view) stays timestamp-sorted; only the written
    # file's row order differs.
    shuffled = sorted(batch.transactions, key=lambda t: t.tx_hash)
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
                    "tx_type": t.tx_type,
                }
                for t in shuffled
            ],
            indent=2,
        )
    )
    gt_path.write_text(json.dumps(batch.ground_truth, indent=2))
    hz_path.write_text(json.dumps(batch.hazards, indent=2))
    return tx_path, gt_path, hz_path

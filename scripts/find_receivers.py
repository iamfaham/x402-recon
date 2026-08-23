#!/usr/bin/env python
"""Rank Base mainnet USDC receivers by how painful they'd be to reconcile.

RESEARCH TOOL, NOT PART OF THE SHIPPED PACKAGE. It answers one question:

    Is there any single receiver whose transaction count and distinct-payer
    count are large enough that reconciling by hand actually hurts?

That is the question that decides whether Ledger has a customer. Market data
as of mid-2026 says x402 moves ~$28k/day ecosystem-wide with roughly half of
that estimated to be wash or self-dealing, so dollar volume is NOT the signal
to look for. Ledger's value scales with line-item count times distinct
counterparties: 10,000 payments of $0.30 from 3,000 different payers is a real
reconciliation problem; 10,000 payments from one payer is a spreadsheet.

HONEST LIMITS - read these before believing any output:

  * This does NOT identify x402 payments. It cannot: x402 settles through
    EIP-3009 `transferWithAuthorization`, and telling that apart from an
    ordinary transfer needs the `AuthorizationUsed` topic hash, which is a
    keccak256 the standard library cannot compute. What this does instead is
    filter by amount, on the assumption that agent payments are small. That is
    a HEURISTIC and it will include ordinary small human transfers.
  * A receiver ranking high here is a lead, not a finding. Confirm what it
    actually is before contacting anyone.
  * Public RPC endpoints rate-limit. Scanning a wide range takes a while and
    may fail partway; the script reports what it got rather than pretending
    the partial answer is complete.

Usage:

    python scripts/find_receivers.py --blocks 20000
    python scripts/find_receivers.py --from-block 34000000 --to-block 34020000
    python scripts/find_receivers.py --blocks 20000 --max-usdc 2.00 --top 40
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ledger.chain import (  # noqa: E402
    TRANSFER_TOPIC0,
    USDC_BASE_MAINNET,
    decode_address,
    decode_amount_micro_usdc,
)
from ledger.rpc import DEFAULT_BASE_RPC_URL, RpcClient, RpcError  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--blocks",
        type=int,
        default=10_000,
        help="how many blocks back from head to scan (ignored if --from-block given)",
    )
    parser.add_argument("--from-block", type=int)
    parser.add_argument("--to-block", type=int)
    parser.add_argument(
        "--max-usdc",
        type=float,
        default=2.00,
        help="only count transfers at or below this size, in dollars (heuristic "
        "for agent traffic; the average x402 payment is around $0.20-$0.52)",
    )
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--rpc-url", default=DEFAULT_BASE_RPC_URL)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = RpcClient(args.rpc_url)

    try:
        if args.from_block is None:
            head = int(client.call("eth_blockNumber", []), 16)
            from_block, to_block = head - args.blocks, head
        else:
            from_block = args.from_block
            to_block = args.to_block if args.to_block is not None else from_block + args.blocks

        span = to_block - from_block + 1
        print(f"Scanning blocks {from_block}..{to_block} ({span} blocks) on Base.")
        print(f"Counting native-USDC transfers of <= ${args.max_usdc:.2f}.\n")

        logs = client.get_logs(
            address=USDC_BASE_MAINNET,
            topics=[TRANSFER_TOPIC0],
            from_block=from_block,
            to_block=to_block,
        )
    except RpcError as exc:
        print(f"RPC failed: {exc}")
        print("Partial results are not shown - a truncated scan would rank wrongly.")
        return 2
    except (OSError, ValueError) as exc:
        print(f"Could not reach {args.rpc_url}: {exc}")
        return 2

    ceiling = int(args.max_usdc * 1_000_000)
    counts: dict[str, int] = defaultdict(int)
    senders: dict[str, set] = defaultdict(set)
    volume: dict[str, int] = defaultdict(int)
    skipped = 0

    for log in logs:
        topics = log.get("topics") or []
        if len(topics) < 3:
            skipped += 1
            continue
        try:
            amount = decode_amount_micro_usdc(log["data"])
        except (KeyError, ValueError):
            skipped += 1
            continue
        if amount > ceiling:
            continue
        receiver = decode_address(topics[2])
        counts[receiver] += 1
        senders[receiver].add(decode_address(topics[1]))
        volume[receiver] += amount

    print(f"{len(logs)} transfers in range; {sum(counts.values())} at or under the ceiling.")
    if skipped:
        print(f"{skipped} logs skipped as malformed.")
    if not counts:
        print("\nNo transfers matched. Try a wider range or a higher --max-usdc.")
        return 0

    # Rank by distinct payers, then count. A receiver with many payments from
    # one payer has no reconciliation problem; many payers is what creates it.
    ranked = sorted(
        counts, key=lambda r: (len(senders[r]), counts[r]), reverse=True
    )[: args.top]

    print(f"\n{'receiver':<44} {'txns':>7} {'payers':>7} {'volume':>12}")
    print("-" * 74)
    for receiver in ranked:
        dollars = volume[receiver] / 1_000_000
        print(
            f"{receiver:<44} {counts[receiver]:>7} "
            f"{len(senders[receiver]):>7} {dollars:>11.2f}"
        )

    blocks_per_month = 30 * 24 * 60 * 60 // 2  # Base targets ~2s blocks
    scale = blocks_per_month / span
    best = ranked[0]
    print(
        f"\nExtrapolated to a month, the top receiver sees roughly "
        f"{int(counts[best] * scale):,} payments from {len(senders[best]):,}+ payers."
    )
    print(
        "That is the number that decides whether Ledger has a customer. A few\n"
        "hundred a month is a spreadsheet. Tens of thousands from thousands of\n"
        "distinct payers is a real problem worth paying to solve.\n"
        "Extrapolation assumes this window is typical - check a second window\n"
        "before trusting it."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

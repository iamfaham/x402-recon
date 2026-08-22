"""Turn a receiver address and a block range into a batch of transactions.

Writes the same JSON shape `simulate` writes, so `ingest` needs no knowledge
that the data came from a chain rather than a generator.
"""

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

from ledger.chain import (
    TRANSFER_TOPIC0,
    USDC_BASE_MAINNET,
    decode_address,
    log_to_transaction,
)
from ledger.models import TX_TYPE_PAYMENT, TX_TYPE_REFUND, Transaction
from ledger.rpc import RpcClient


@dataclass(frozen=True)
class FetchResult:
    transactions: list[Transaction]
    rejects: list[tuple[str, str]]


def topic_for_address(address: str) -> str:
    """Left-pad an address to the 32 bytes an indexed topic filter needs."""
    return "0x" + address[2:].rjust(64, "0")


def _decode(log: dict, timestamp: str, tx_type: str, rejects: list) -> Transaction | None:
    try:
        return log_to_transaction(log, timestamp, tx_type)
    except (ValueError, KeyError) as exc:
        rejects.append((log.get("transactionHash", "<unknown>"), str(exc)))
        return None


def fetch_transactions(
    client: RpcClient, *, receiver: str, from_block: int, to_block: int
) -> FetchResult:
    """Fetch inbound payments and outbound refunds for one receiver."""
    receiver_topic = topic_for_address(receiver)
    rejects: list[tuple[str, str]] = []

    inbound_logs = client.get_logs(
        address=USDC_BASE_MAINNET,
        topics=[TRANSFER_TOPIC0, None, receiver_topic],
        from_block=from_block,
        to_block=to_block,
    )
    outbound_logs = client.get_logs(
        address=USDC_BASE_MAINNET,
        topics=[TRANSFER_TOPIC0, receiver_topic, None],
        from_block=from_block,
        to_block=to_block,
    )

    payments: list[Transaction] = []
    for log in inbound_logs:
        timestamp = client.block_timestamp(log.get("blockNumber", "0x0"))
        transaction = _decode(log, timestamp, TX_TYPE_PAYMENT, rejects)
        if transaction is not None:
            payments.append(transaction)

    payers = {t.sender_address.lower() for t in payments}

    refunds: list[Transaction] = []
    for log in outbound_logs:
        topics = log.get("topics") or []
        if len(topics) >= 3:
            destination = decode_address(topics[2]).lower()
            if destination not in payers:
                # Money leaving to someone who never paid in is an outgoing
                # payment, not a refund. Ledger reports money received, so it
                # does not belong in the batch - but it is named rather than
                # dropped, because nothing vanishes quietly here.
                rejects.append(
                    (
                        log.get("transactionHash", "<unknown>"),
                        f"outbound transfer to {destination}, which never paid this "
                        "receiver in range - not a refund",
                    )
                )
                continue
        timestamp = client.block_timestamp(log.get("blockNumber", "0x0"))
        transaction = _decode(log, timestamp, TX_TYPE_REFUND, rejects)
        if transaction is not None:
            # `log_to_transaction` decodes the raw ERC-20 Transfer direction:
            # sender = the merchant (topics[1], the "from"), receiver = the
            # payer being refunded (topics[2], the "to"). But the project's
            # schema convention - confirmed in simulate.py (refunds carry
            # sender_address = the original payer) and categorize.py (the
            # payer axis groups by sender_address for every tx_type) - is
            # that sender_address is ALWAYS the counterparty and
            # receiver_address is ALWAYS the merchant, regardless of
            # direction; only tx_type carries the sign. Swap the two fields
            # so a fetched refund matches that convention instead of the raw
            # on-chain direction.
            transaction = dataclasses.replace(
                transaction,
                sender_address=transaction.receiver_address,
                receiver_address=transaction.sender_address,
            )
            refunds.append(transaction)

    combined = sorted(payments + refunds, key=lambda t: (t.timestamp, t.tx_hash))
    return FetchResult(transactions=combined, rejects=rejects)


def write_fetched(result: FetchResult, out_dir: Path) -> Path:
    """Write transactions.json only.

    No ground_truth.json is written. Real data arrives unlabeled, and an empty
    truth file would make the report believe it had been calibrated.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "transactions.json"
    path.write_text(
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
                for t in result.transactions
            ],
            indent=2,
        )
    )
    return path


def format_fetch_summary(result: FetchResult) -> str:
    count = len(result.transactions)
    noun = "transaction" if count == 1 else "transactions"
    lines = [f"Fetched {count} {noun}."]
    if result.rejects:
        lines.append(f"Skipped {len(result.rejects)}:")
        lines += [f"  {tx_hash}: {reason}" for tx_hash, reason in result.rejects]
    return "\n".join(lines)

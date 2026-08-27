"""Decoding chain logs into transactions.

Pure functions only. Nothing here touches the network, so every mapping
decision is testable offline against a recorded log.
"""

import json
from datetime import datetime, timezone

from x402_recon.keccak import topic0
from x402_recon.models import TIMESTAMP_FORMAT, Transaction

# Circle's native USDC on Base (FiatTokenProxy), 6 decimals.
USDC_BASE_MAINNET = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"

# The older BRIDGED token. A different asset that would inflate totals if
# mixed in, so it is named here to make the exclusion explicit rather than
# implicit in the absence of a second address.
USDBC_BASE_MAINNET_EXCLUDED = "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca"

# Derived rather than pasted. tests/test_chain.py still asserts the literal
# value, which was pinned from an independent source before this project had
# a keccak implementation - so the derivation and the constant check each other.
TRANSFER_TOPIC0 = topic0("Transfer(address,address,uint256)")

# Emitted by EIP-3009 transferWithAuthorization, which is how x402 settles.
# Indexed on the AUTHORIZER (the payer), not the receiver - which is why it
# cannot be used to filter by recipient. See verify.py for how it is used.
AUTHORIZATION_USED_TOPIC0 = topic0("AuthorizationUsed(address,bytes32)")

CHAIN_NAME = "base"


def decode_address(topic: str) -> str:
    """An indexed address topic is 32 bytes, left-padded. Take the low 20."""
    return "0x" + topic[-40:]


def decode_amount_micro_usdc(data: str) -> int:
    """USDC carries 6 decimals, so the raw uint256 IS a micro-USDC count.

    There is deliberately no conversion here. The project's money invariant is
    that amounts are integers of micro-USDC, and the chain hands us exactly
    that, so the honest implementation is a base-16 parse and nothing else.
    """
    return int(data, 16)


def block_timestamp_to_iso(hex_seconds: str) -> str:
    """Format a block's hex Unix timestamp as zero-padded ISO 8601 UTC."""
    seconds = int(hex_seconds, 16)
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime(TIMESTAMP_FORMAT)


def log_to_transaction(log: dict, timestamp: str, tx_type: str) -> Transaction:
    """Map one ERC-20 Transfer log to a Transaction.

    `memo` is None and always will be: EIP-3009 settlement records no resource
    identifier, so the chain cannot say what was bought.
    """
    topics = log.get("topics") or []
    if not topics or topics[0].lower() != TRANSFER_TOPIC0:
        raise ValueError(f"log is not an ERC-20 Transfer: topic0={topics[:1]}")
    if len(topics) < 3:
        raise ValueError(f"expected 3 topics on a Transfer log, got {len(topics)}")

    return Transaction(
        tx_hash=log["transactionHash"],
        sender_address=decode_address(topics[1]),
        receiver_address=decode_address(topics[2]),
        amount_micro_usdc=decode_amount_micro_usdc(log["data"]),
        timestamp=timestamp,
        memo=None,
        chain=CHAIN_NAME,
        raw_payload=json.dumps(log, sort_keys=True),
        tx_type=tx_type,
    )

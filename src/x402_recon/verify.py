"""Check a bounded sample of payments for EIP-3009 settlement.

x402 settles through transferWithAuthorization, which emits AuthorizationUsed
alongside the Transfer. That event indexes the AUTHORIZER - the payer - not the
receiver, so it cannot be used to filter by the address under study. Covering
every payment would mean pulling millions of logs or one receipt call per
payment; neither belongs in a command that should feel instant.

So instead of filtering, measure: check a fixed number of transactions and
report what was found. An assertion becomes an observation, at fixed cost.
"""

from dataclasses import dataclass

from x402_recon.chain import AUTHORIZATION_USED_TOPIC0, USDC_BASE_MAINNET

X402_SAMPLE_SIZE = 50


@dataclass(frozen=True)
class SampleResult:
    checked: int
    settled_via_eip3009: int
    total_available: int


def _is_eip3009_receipt(receipt: dict | None) -> bool:
    if not receipt:
        return False
    for log in receipt.get("logs") or []:
        topics = log.get("topics") or []
        address = str(log.get("address", "")).lower()
        if address == USDC_BASE_MAINNET and topics[:1] == [AUTHORIZATION_USED_TOPIC0]:
            return True
    return False


def sample_x402_settlement(
    client, tx_hashes: list[str], *, sample_size: int = X402_SAMPLE_SIZE
) -> SampleResult:
    """Check up to `sample_size` transactions for EIP-3009 settlement.

    Takes an evenly spaced sample rather than the first N, so a burst at the
    start of the window cannot stand in for the whole of it.
    """
    total = len(tx_hashes)
    if not total:
        return SampleResult(checked=0, settled_via_eip3009=0, total_available=0)

    if total <= sample_size:
        chosen = list(tx_hashes)
    else:
        step = total / sample_size
        chosen = [tx_hashes[int(i * step)] for i in range(sample_size)]

    settled = sum(
        1 for tx_hash in chosen if _is_eip3009_receipt(client.transaction_receipt(tx_hash))
    )
    return SampleResult(
        checked=len(chosen), settled_via_eip3009=settled, total_available=total
    )


def render_sample(result: SampleResult) -> str:
    """One line describing what the sample found, or nothing if none was taken."""
    if not result.checked:
        return ""
    verdict = (
        "consistent with x402"
        if result.settled_via_eip3009 == result.checked
        else "so not all of this traffic settled the way x402 does"
    )
    return (
        f"Sampled {result.checked} of {result.total_available:,} payments: "
        f"{result.settled_via_eip3009} were EIP-3009 settlements, {verdict}."
    )

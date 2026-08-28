"""Read a seller's receiving address from their own 402 response.

This is the second and last module in the project permitted to open a network
connection. Its transport is injectable so no test ever exercises the real one.

An x402 server answers an unpaid request with HTTP 402 and a body describing
what it wants: the scheme, network, asset, amount, and the address to pay. That
last field is what makes a report possible without the seller's cooperation -
and it is public information the seller publishes themselves.
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from x402_recon.chain import USDC_BASE_MAINNET

BASE_MAINNET_CAIP2 = "eip155:8453"

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TIMEOUT_SECONDS = 20
_USER_AGENT = "x402-recon (+https://github.com/iamfaham/x402-recon)"


class DiscoveryError(RuntimeError):
    """The endpoint did not yield usable payment requirements."""


@dataclass(frozen=True)
class PaymentRequirements:
    pay_to: str
    network: str
    asset: str
    amount: str | None
    source_url: str


def _candidate_blocks(body: dict) -> list[dict]:
    """Payment-requirement objects, tolerating both protocol shapes.

    v1 carries an `accepts` array; v2 carries an `accepted` object. Rather than
    branch on x402Version - which a future version would break - look for
    either shape and let the caller fail if neither yields a payTo.
    """
    accepted = body.get("accepted")
    if isinstance(accepted, dict):
        return [accepted]
    accepts = body.get("accepts")
    if isinstance(accepts, list):
        return [entry for entry in accepts if isinstance(entry, dict)]
    return []


def parse_402_body(body: dict, source_url: str) -> PaymentRequirements:
    """Extract and validate payment requirements from a 402 body."""
    blocks = _candidate_blocks(body)
    if not blocks:
        raise DiscoveryError(
            f"could not find payment requirements in the 402 body from "
            f"{source_url}: expected an 'accepted' object or an 'accepts' "
            f"array, got keys {sorted(body)}"
        )

    block = blocks[0]

    pay_to = block.get("payTo")
    if not pay_to:
        raise DiscoveryError(
            f"the 402 body from {source_url} has no payTo field, so there is "
            f"no address to report on. Fields present: {sorted(block)}"
        )
    if not _ADDRESS_RE.match(str(pay_to)):
        raise DiscoveryError(f"payTo {pay_to!r} is not a valid address")

    network = str(block.get("network", ""))
    if network != BASE_MAINNET_CAIP2:
        raise DiscoveryError(
            f"{source_url} settles on {network!r}, and this tool only reads "
            f"Base mainnet ({BASE_MAINNET_CAIP2})"
        )

    asset = str(block.get("asset", ""))
    if asset.lower() != USDC_BASE_MAINNET:
        raise DiscoveryError(
            f"{source_url} is paid in token {asset!r}, and this tool only "
            f"reads native USDC ({USDC_BASE_MAINNET})"
        )

    amount = block.get("amount") or block.get("maxAmountRequired")
    return PaymentRequirements(
        pay_to=str(pay_to),
        network=network,
        asset=asset,
        amount=str(amount) if amount is not None else None,
        source_url=source_url,
    )


def _urllib_transport(url: str) -> tuple[int, dict]:
    # Real x402 endpoints are POST-only APIs (search/RPC style), not static
    # resources - confirmed live against Tavily and Exa, both of which answer
    # GET with a plain 404 and only respond 402 to POST. An empty JSON body
    # is enough: the 402 check happens before any request-body validation.
    request = urllib.request.Request(
        url,
        data=b"{}",
        headers={"User-Agent": _USER_AGENT, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # A 402 arrives as an HTTPError; its body is what we came for.
        return exc.code, json.loads(exc.read().decode("utf-8"))


def discover(url: str, *, transport=None) -> PaymentRequirements:
    """Make one unpaid request and read the payment requirements from it."""
    send = transport or _urllib_transport
    try:
        status, body = send(url)
    except DiscoveryError:
        raise
    except (ValueError, OSError) as exc:
        raise DiscoveryError(f"could not read a response from {url}: {exc}") from exc

    if status != 402:
        raise DiscoveryError(
            f"{url} answered {status}, not 402 - it did not ask for payment, "
            f"so it may not be an x402-paywalled endpoint"
        )
    if not isinstance(body, dict):
        raise DiscoveryError(f"could not read the 402 body from {url} as an object")
    return parse_402_body(body, url)

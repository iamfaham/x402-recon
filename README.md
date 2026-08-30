# x402-recon

[![CI](https://github.com/iamfaham/x402-recon/actions/workflows/ci.yml/badge.svg)](https://github.com/iamfaham/x402-recon/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/x402-recon)](https://pypi.org/project/x402-recon/)
[![Python versions](https://img.shields.io/pypi/pyversions/x402-recon)](https://pypi.org/project/x402-recon/)

Reconciliation and customer analytics for agent-initiated x402/USDC stablecoin
payments on Base.

Point it at a seller's endpoint or receiving address and it turns a wall of
tiny automated payments into a summary: how much came in, and who actually
came back versus who just tried it once. It never holds or moves funds, and
it is not tax or accounting advice.

Stdlib-only. Zero runtime dependencies. Python 3.11+.

## Install

```bash
uvx x402-recon --url https://api.example.com/search --last 30d
```

or install it properly:

```bash
pip install x402-recon
```

## Quick start

```console
$ x402-recon --url https://api.exa.ai/search --last 30d

x402-recon - 0x6d6E695b...0B9192
Base mainnet - 2026-07-28 to 2026-08-27 - payTo discovered from api.exa.ai

  Net received          $34.296    from 5349 payments
  Distinct payers            140    38.2 payments each

Who actually came back
----------------------
                    payers   payments         revenue    share
  Returning (3+)        69      5,255         $33.699    98.3%
  Tried twice           23         46          $0.301     0.9%
  One-shot              48         48          $0.296     0.9%
```

That's real output from a live run. `--url` discovers the seller's receiving
address from their own HTTP 402 response — only a discovered address gets
called "x402" in the output; a raw address is reported as "USDC payments,"
since there's no 402 response backing that stronger claim:

```bash
x402-recon 0xRECEIVER_ADDRESS --last 30d
```

Six commands cover normal use (`discover`, `report`, `customers`, `fetch`,
`ingest`, `categorize`); run `--advanced` to see the research/validation
tooling used to measure this tool's own accuracy.

**Independently validated.** The x402 Bazaar publishes per-service call and
unique-payer counts. Over a comparable 30-day window it reports 3,575 calls
from 89 payers for the endpoint above; this tool measured 5,349 on-chain
payments from 140 payers — within a pre-registered 2x acceptance criterion
(API calls and settled on-chain payments count different things over
non-identical windows, so close agreement rather than an exact match is the
expected result).

## What it can't tell you

- **What was bought.** x402 settlement carries no resource identifier
  on-chain, so every transaction's memo is `None` and the report says so
  instead of guessing.
- **Grouping accuracy on your data**, until you run `evaluate` against your
  own labeled sample — payer/service grouping is calibrated on simulated
  data by default.

## Privacy

Addresses on a public blockchain are not secret — anyone can read them. What
this tool creates that the chain does not publish is the **association**:
"these addresses are the customers of *this* seller." That association is
yours, and it should not leave your machine by accident.

So terminal output shortens addresses by default (`0x6d6E695b…0B9192`). Pass
`--full-addresses` when you want them whole.

CSV exports are the exception: they keep full addresses and transaction
hashes, because that is the artifact you reconcile against a bank export or
look up on a block explorer, and a truncated address is useless for both.
Writing one prints a reminder to review it before sharing.

The tool sends no telemetry. It talks to exactly two kinds of host: the Base
RPC endpoint you point it at, and — only when you pass `--url` — the x402
endpoint whose payment address you are discovering. It writes a cache of
fetched ranges and a copy of any skipped rows under `~/.x402-recon/`;
`--no-cache` writes nothing to disk at all.

## Development

```bash
uv sync
uv run pytest
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the rules (no runtime
dependencies, money is always integer micro-USDC, nothing silently dropped)
and [`SECURITY.md`](SECURITY.md) for the reporting policy and what this tool
does and doesn't send over the network.

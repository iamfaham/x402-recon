# Security

## Reporting a vulnerability

Open a private security advisory through GitHub:
<https://github.com/iamfaham/x402-recon/security/advisories/new>

Please do not open a public issue for a vulnerability. You should get a reply
within a week.

## What this tool does and does not do

**It never holds, moves, signs for, or spends funds.** It reads public
blockchain data and summarizes it. It has no wallet, no private keys, and no
signing capability of any kind.

**It sends no telemetry.** No usage data, no addresses, nothing. The only
network requests it makes are to the RPC endpoint you point it at (Base
mainnet by default, overridable with `--rpc-url`) and, when you use `--url`,
a single unpaid request to the endpoint you named.

**It stores a local cache.** Fetched transactions are cached under
`~/.x402-recon/`, keyed by receiving address, so re-runs do not re-scan the
chain. That cache contains counterparty addresses from public chain data.
Delete the directory to remove it, or pass `--no-cache` to use a temporary
database that is deleted when the run ends.

**Addresses it reports are public.** A seller's receiving address comes from
their own HTTP 402 response, which they publish to every unauthenticated
caller by protocol design. Nothing this tool reads is privileged.

## Runtime dependencies

There are none. The package installs no third-party code at runtime, which is
a deliberate choice for a tool that reads financial records.

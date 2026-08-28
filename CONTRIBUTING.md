# Contributing

Thanks for looking. This is a small tool with a few firm rules, all of which
exist for a reason.

## Getting set up

```bash
uv sync
uv run pytest
```

That is the whole loop. Python 3.11 or newer.

## The rules that are not negotiable

**No runtime dependencies.** The `dependencies` list in `pyproject.toml` is
empty and stays empty. This tool reads financial data; every dependency is
supply-chain risk taken on someone's behalf. Everything it needs is in the
standard library. `pytest` is the only development dependency.

**Money is always integers of micro-USDC.** Never a float. Sub-cent payments
summed thousands of times drift under floating point, and drift in a financial
total is the exact failure this tool exists to prevent.

**Nothing is silently dropped.** A row that cannot be processed is reported
with a reason. A retry announces itself. If you add a path where data or time
disappears without the user hearing about it, that is a bug regardless of how
convenient it is.

**Only two modules touch the network.** `rpc.py` and `discover.py`, both with
an injectable transport. A test that opens a socket will fail the structural
check in `tests/test_invariants.py`.

**Claims must be earned.** Output may describe payments as x402 only when the
address was resolved from an actual 402 response. Accuracy figures say which
data they were measured on. If you are unsure whether a claim is earned, it
is not.

## Changes come with tests

Behavioural changes need a test that fails without them. The suite is fast;
there is no reason to skip it.

If you are changing something the tool measures about itself, say what
changed in the measurement and why, in the PR description or commit message.

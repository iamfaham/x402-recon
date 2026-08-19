# Ledger

Reconciliation and reporting for agent-initiated stablecoin payments.

Turns a wall of tiny automated machine payments into a summary a business owner
or their accountant can actually read — with an honest split between what was
confidently identified and what still needs review.

Ledger only reads and summarizes payments a business has already received. It
never holds or moves funds, and it does not provide tax or accounting advice.

## Status: v0

v0 runs on simulated data. Real transaction data (Base Sepolia testnet, or a
public x402 dataset) is the next milestone — it plugs into the ingest stage
without changing anything downstream.

## Usage

```bash
uv sync

uv run ledger simulate --out sample/data --count 120 --seed 42
uv run ledger --db sample/ledger.db ingest --from sample/data
uv run ledger --db sample/ledger.db categorize
uv run ledger --db sample/ledger.db report --from 2026-08-01 --to 2026-09-30 --csv sample/report.csv
uv run ledger --db sample/ledger.db evaluate
```

## How categorization works

Transactions pass through ordered rules; the first to fire wins and records why.

| Rule | Fires when | Confidence |
|---|---|---|
| `sender_match` | The sender address repeats in the dataset | confident |
| `memo_match` | A specific (non-generic) memo repeats | confident |
| `time_cluster` | A one-off sender falls inside a burst of activity | uncertain |
| `none` | Nothing matched | uncertain, `uncategorized` |

Repetition is evidence, so rules 1 and 2 claim confidence. Proximity in time is
a guess, so rule 3 does not. Nothing is ever forced into a bucket.

## Measured accuracy (seed 42, 120 transactions)

| Metric | Value |
|---|---|
| Precision | 79.8% |
| Recall | 100.0% |
| Confident tier accuracy | 100.0% |
| Uncertain tier accuracy | 0.0% |

In plain terms: on every case in this test set, whenever the tool said it was
confident, it was right. The two rules behind a confident label
(`sender_match` and `memo_match`) only fire when there is real repeated
evidence — the same sender or the same specific memo showing up more than
once — and that evidence held up 100% of the time here. But this dataset does
not yet contain the cases that would be needed to catch a confident rule
being wrong — for example, two unrelated one-off payers who happen to share a
specific memo. So the 100% confident-tier figure is not yet a strong claim;
it is a clean result on the situations tested so far, not proof the confident
rules can't be fooled. The "needs review" label is a different story: the one
rule that can produce it, `time_cluster`, is a guess based on timing alone,
and in this run that guess was wrong every time it fired. That is exactly why
it is marked uncertain instead of confident — the tool is telling you not to
trust it. The overall precision figure, 79.8%, looks lower than either tier
on its own because it blends the confident results with the consistently
wrong uncertain ones. The number to trust is the confident total in the
report; the number to double-check by hand is the "needs review" total.

Calibration is the metric that matters most: if the confident tier is no more
accurate than the uncertain tier, the confidence signal is meaningless.

## Development

```bash
uv run pytest
```

## Docs

- Design spec: `docs/superpowers/specs/2026-08-18-ledger-v0-design.md`
- Implementation plan: `docs/superpowers/plans/2026-08-18-ledger-v0.md`
- Validation outreach: `validation/outreach.md`

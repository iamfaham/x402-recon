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
| Precision (B-cubed) | 96.5% |
| Recall (B-cubed) | 100.0% |
| Confident tier precision | 96.7% |
| Declined coverage | 100.0% |

**These numbers are not comparable to v0's.** v0 reported precision 79.8% and
recall 100.0% using majority-vote purity, which rewarded splitting one payer
across several groups while punishing merging two. v0.1a uses B-cubed, which
penalizes both errors, and measures against a dataset built to catch the rules
being wrong. A different number here reflects a different question being asked,
not a regression or an improvement.

Precision asks: of the payments grouped together, how many belonged together.
Recall asks: of the payments from one payer, how many were found. Declined
coverage asks what was given up by leaving payments uncategorized - without it,
a tool could score perfect calibration by categorizing almost nothing.

Calibration is the metric that matters most: if the confident tier is no more
accurate than the uncertain tier, the confidence signal is meaningless.

## Ground truth format

`evaluate` needs to know the correct answer. The simulator writes it; for real
transactions a human supplies it by hand.

`ground_truth.json` maps each transaction hash to the payer it truly came from:

```json
{
  "0xabc...": "acme-corp",
  "0xdef...": "acme-corp",
  "0x123...": "__ungroupable__"
}
```

Group names are arbitrary labels - any stable string identifying one payer.
Use `__ungroupable__` for a transaction that genuinely belongs to no group,
such as a one-off payer never seen again. This matters: those transactions are
excluded from coverage scoring, because failing to group them is correct
behavior rather than a miss.

`hazards.json` is written by the simulator only and is never required. It tags
which transactions carry deliberate adversarial structure, so accuracy can be
split between hazard cases and ordinary traffic. Real data has no such tags,
and its absence is normal.

## Development

```bash
uv run pytest
```

## Docs

- Design spec: `docs/superpowers/specs/2026-08-18-ledger-v0-design.md`
- Implementation plan: `docs/superpowers/plans/2026-08-18-ledger-v0.md`
- Validation outreach: `validation/outreach.md`

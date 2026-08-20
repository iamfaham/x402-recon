# Ledger

Reconciliation and reporting for agent-initiated stablecoin payments.

Turns a wall of tiny automated machine payments into a summary a business owner
or their accountant can actually read — with an honest split between what was
confidently identified and what still needs review.

Ledger only reads and summarizes payments a business has already received. It
never holds or moves funds, and it does not provide tax or accounting advice.

## Status: v0.1b

v0.1b runs on simulated data. Real transaction data (Base Sepolia testnet, or a
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

Every transaction is run through two independent rule cascades — one per axis
— and gets one label from each. Within each cascade, ordered rules fire in
turn; the first to match wins and records why.

**Who paid you** (payer axis):

| Rule | Fires when | Confidence |
|---|---|---|
| `sender_match` | The sender address repeats in the dataset | confident |
| `time_cluster` | A one-off sender falls inside a burst of activity | uncertain |
| `none` | Nothing matched | uncertain, `uncategorized` |

**What they paid for** (service axis):

| Rule | Fires when | Confidence |
|---|---|---|
| `memo_match` | A specific (non-generic) memo repeats | descriptive |
| `none` | Nothing matched | descriptive, `uncategorized` |

A repeating sender address is evidence of identity, so `sender_match` claims
confidence. Proximity in time is a guess, so `time_cluster` does not. A
repeating memo is evidence of a service, not of who is behind it, so every
service-axis row is descriptive: stated, not claimed. Nothing is ever forced
into a bucket. See [What the two axes mean](#what-the-two-axes-mean) below for
why the axes are kept apart.

## Measured accuracy (seed 42, 145 transactions)

| Axis | Precision (B-cubed) | Recall (B-cubed) |
|---|---|---|
| Who paid you (payer) | 98.9% | 92.9% |
| What they paid for (service) | 100.0% | 95.0% |

The payer axis has one confident rule, `sender_match`, and it measures 100%
confident-tier precision — no failing confident rule survives the split. The
service axis has no confident rules at all: both `memo_match` and `none` are
descriptive, so neither is subject to the confident-tier calibration floor.

**This is the finding v0.1b exists to record.** In v0.1a, `memo_match` was
scored as if it identified a payer and measured 70.6% precision there — a
"confident" rule that was wrong roughly three times in ten, diluted into the
headline number by `sender_match`'s easy cases. Scored against what it
actually groups — service, not payer — `memo_match` measures **100%
precision**. The rule was never wrong. Only presenting a service grouping as a
payer identity was. Service recall (95.0%) sits below 100% because
exact-string memo matching fragments a service that drifts across several
memo strings into separate groups; that is the measurement doing its job, not
a defect.

`time_cluster` fired 13 times post-split, measuring 87.7% B-cubed precision —
above the pre-registered 0.70 threshold — but the run still reports
`INSUFFICIENT DATA` because 13 is below `MIN_VERDICT_SAMPLE` (20). A rule can
clear its bar and still not have fired enough to trust that result.

Full per-rule detail for both axes, including the complete `evaluate` output,
is in [`docs/sample-report.md`](docs/sample-report.md).

Precision asks: of the payments grouped together, how many belonged together.
Recall asks: of the payments from one payer (or one service), how many were
found. Calibration is defined in absolute terms: a confident rule's B-cubed
precision must clear a pre-registered threshold (0.95) on its own. Descriptive
rules make no such claim and are never held to that floor.

## What the two axes mean

Ledger answers two separate questions about every payment, and keeps them
separate on purpose.

**Who paid you** groups by sender address. A sender that repeats is evidence of
one payer, so those groupings claim confidence.

**What they paid for** groups by the memo the payer sent. These groupings
describe what was bought - they are *not* a claim about who bought it, and they
claim no confidence at all.

Earlier versions collapsed both into one "category", which meant several
unrelated payers who happened to buy the same service were reported as one
payer under "Confidently identified". Separating the axes is what fixed that.

## Ground truth format

`evaluate` needs to know the correct answers. Two files, each optional and each
answering one question.

`ground_truth.json` maps a transaction hash to the payer it truly came from:

```json
{"0xabc...": "acme-corp", "0x123...": "__ungroupable__"}
```

`service_truth.json` maps a transaction hash to the service it truly paid for:

```json
{"0xabc...": "weather-api", "0x123...": "__ungroupable__"}
```

Group and service names are arbitrary labels - any stable string. Use
`__ungroupable__` when a transaction genuinely belongs to no group: a one-off
payer never seen again, or a payment whose memo names no real service. Those
are excluded from coverage scoring, because failing to group them is correct.

Supplying only `ground_truth.json` is normal. The payer axis is scored and the
service axis is reported unscored.

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

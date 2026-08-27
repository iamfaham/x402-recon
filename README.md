# x402-recon

Reconciliation and reporting for agent-initiated stablecoin payments.

Turns a wall of tiny automated machine payments into a summary a business owner
or their accountant can actually read — with an honest split between what was
confidently identified and what still needs review.

Ledger only reads and summarizes payments a business has already received. It
never holds or moves funds, and it does not provide tax or accounting advice.

## Status: v0.3

v0.2 can read real payments off Base mainnet. `x402-recon fetch` pulls native-USDC
transfers for one receiver address and writes the same JSON that `simulate`
writes, so `ingest` and everything downstream are unchanged. That was the
design bet made in v0.1c, and it held: `ingest.py` was not modified.

**The accuracy figures below are still measured on simulated data.** The staged
measurement against real transactions — fetch, inspect the batch's shape,
hand-label a sample, then apply the pre-registered criterion — is built and
tested but **has not been run**. Until it is, the payer axis's confidence claim
is calibrated on simulation only, and the report says so on any dataset that
carries no ground truth.

Two things are true of real chain data that are not true of the simulator:

- **The service axis goes dark.** x402 settles via EIP-3009
  `transferWithAuthorization`, whose payload identifies no resource. What was
  bought lives in the seller's HTTP request log, never on the chain — so every
  fetched transaction has `memo = None`, and the report suppresses the service
  breakdown with an explanation rather than printing a wall of "no service
  identified". Recovering that axis needs seller-side capture, not a better
  chain query.
- **There is no ground truth.** Real payments arrive unlabeled. The report
  distinguishes three states — uncalibrated, partially labeled, fully labeled
  — derived from how much of the reported range appears in `ground_truth`,
  never from a flag anyone can set wrongly.

## Usage

```bash
uv sync

uv run x402-recon simulate --out sample/data --count 300 --seed 42
uv run x402-recon --db sample/ledger.db ingest --from sample/data
uv run x402-recon --db sample/ledger.db categorize
uv run x402-recon --db sample/ledger.db report --from 2026-08-01 --to 2026-09-30 --csv sample/report.csv
uv run x402-recon --db sample/ledger.db evaluate

# Who actually came back: returning customers vs one-shot traffic.
uv run x402-recon --db sample/ledger.db customers --from 2026-08-01 --to 2026-08-31
```

On real data, `fetch` replaces `simulate` and two extra stages appear:

```bash
uv run x402-recon fetch --receiver 0xYOUR_ADDRESS --out sample/real     --from-block 34000000 --to-block 34100000
uv run x402-recon --db sample/real.db ingest --from sample/real
uv run x402-recon --db sample/real.db categorize

# Stage 1 - structure only. Reports no accuracy figure of any kind, so that
# seeing the answer cannot influence how the sample is later labeled.
uv run x402-recon --db sample/real.db shape

# Stage 2 - a worksheet for a human. The tool never assigns truth: the only
# signal it has is the sender address, which is the signal under test.
uv run x402-recon --db sample/real.db label --out sample/real/worksheet.json
```

Fill in `true_group` and `evidence` by hand using evidence **independent of the
sender address** — a Basename, an explorer entity label, a shared funding
source. Then convert the filled worksheet to `ground_truth.json` (each row
already carries its `tx_hash`), re-ingest, and read the verdict:

```bash
uv run x402-recon --db sample/real.db ingest --from sample/real
uv run x402-recon --db sample/real.db evaluate
uv run x402-recon --db sample/real.db report --from 2026-07-01 --to 2026-07-31
```

## Quick start: the combined overview

The fastest way to see a seller's real customer breakdown:

```bash
x402-recon --url https://x402.example.com/search --last 30d
```

This discovers the seller's receiving address from their own 402
response, fetches the range, and prints net revenue alongside a
returning-vs-one-shot customer split. A raw address also works
directly:

```bash
x402-recon 0xRECEIVER_ADDRESS --last 30d
```

Only an address resolved via `discover` (the `--url` form) may have
its payments associated with x402 in the output — a raw address is
reported as "USDC payments," since there is no 402 response backing
that stronger claim.

## How categorization works

Every transaction is run through two independent rule cascades — one per axis
— and gets one label from each. Within each cascade, ordered rules fire in
turn; the first to match wins and records why.

**Who paid you** (payer axis):

| Rule | Fires when | Confidence |
|---|---|---|
| `sender_match` | The sender address repeats in the dataset | confident |
| `none` | Nothing matched | uncertain, `uncategorized` |

**What they paid for** (service axis):

| Rule | Fires when | Confidence |
|---|---|---|
| `memo_match` | A specific (non-generic) memo repeats | confident |
| `none` | Nothing matched | uncertain, `uncategorized` |

A repeating sender address is evidence of identity, so `sender_match` claims
confidence. A repeating memo is evidence of a service, and as of v0.1c that
evidence has been measured against an adversarial case built to break it and
held up, so `memo_match` claims confidence too. Nothing is ever forced into a
bucket. See [What the two axes mean](#what-the-two-axes-mean) below for why
the axes are kept apart.

## Measured accuracy on simulated data (seed 42, 300 transactions)

The canonical count for v0.1c is 300. v0.1a and v0.1b both used `--count
120`, so the figures below are **not directly comparable** to earlier
releases' published numbers — a larger, less hazard-dense dataset changes
both axes' measured precision and recall.

| Axis | Precision (B-cubed) | Recall (B-cubed) |
|---|---|---|
| Who paid you (payer) | 100.0% | 95.7% |
| What they paid for (service) | 98.7% | 97.6% |

Both axes now have exactly one confident rule each — `sender_match` and
`memo_match` — and both clear their respective calibration floors: payer at
100.0% confident-tier precision (115 payments), service at 96.2%
confident-tier precision (105 payments), against the shared 0.95 threshold.

## Two settled decisions

**time_cluster** — REMOVED. Measured at 70.0% B-cubed precision on 32
payments against a threshold of 0.70 fixed before any measurement was taken.
It was withheld for two releases for want of evidence; this release had
enough — and the evidence said no. The literal canonical measurement clears
0.70 by exactly 0.0 points, and evidence commissioned before that number was
known shows the pass is not robust: across seeds 1–20 at the canonical count
the median is 69.4% (below threshold), 11 of the 19 seeds that clear the
20-firing bar FAIL, precision spans 59.1%–85.7%, and precision falls as
volume rises (70.0% at count 300, 59.3% at 500, 52.7% at 800) — worse, not
better, at the kind of volume a real business would generate. The payer
cascade is now `sender_match` → `none`.

**The service axis** — claims confidence. `memo_match` measured 96.2%
precision on 105 payments against the same 0.95 floor every confident rule
must clear. Service rows now tier the same way payer rows do — claimed rows
confident, declined rows uncertain — and the `DESCRIPTIVE` tier is gone.
Service money stays out of the payer axis's "Confidently identified" total:
confidence is a claim per axis, and summing them across axes is the defect
v0.1b existed to remove.

Both numbers now come from a dataset where they could have failed. Until
this release, service precision could not fall: every generator derived the
true service from the memo, so the two agreed by construction. A hazard
giving one memo string to two genuinely different services is what made the
figure falsifiable — and the verdict is sensitive to that hazard's size,
which is why real transaction data, not a larger synthetic hazard, is what
settles this properly. Concretely: the `shared_memo_different_services`
hazard is fixed at `N=8`, chosen for comparability with the other named
hazards before any measurement existed. At the 97 baseline `memo_match`
payments, `N=8` gives ≈0.962 and passes; a differently-sized, equally
defensible `N=12` gives ≈0.945 and fails. The margin (1.2 points) is thin
enough that this should be read as a real pass, not a settled one.

Full per-rule detail for both axes, including the complete `evaluate` output,
is in [`docs/sample-report.md`](docs/sample-report.md).

Precision asks: of the payments grouped together, how many belonged together.
Recall asks: of the payments from one payer (or one service), how many were
found. Calibration is defined in absolute terms: a confident rule's B-cubed
precision must clear a pre-registered threshold (0.95) on its own, and
uncertain rules are never held to that floor.

## What the two axes mean

Ledger answers two separate questions about every payment, and keeps them
separate on purpose.

**Who paid you** groups by sender address. A sender that repeats is evidence of
one payer, so those groupings claim confidence.

**What they paid for** groups by the memo the payer sent. These groupings
describe what was bought - they are *not* a claim about who bought it. As of
v0.1c, a repeating memo is measured evidence of a service and claims
confidence on its own axis, the same way `sender_match` claims confidence on
the payer axis - but the two claims are never summed together.

Earlier versions collapsed both into one "category", which meant several
unrelated payers who happened to buy the same service were reported as one
payer under "Confidently identified". Separating the axes is what fixed that,
and it is also why the service axis's new confidence claim never adds money
into the payer axis's "Confidently identified" total.

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

# Ledger v0 — Design

**Date:** 2026-08-18
**Status:** Approved for implementation planning

## Purpose

Turn a messy pile of agent-initiated stablecoin micro-transactions into a clean, honest
summary a business owner or their accountant can use. v0 proves the pipeline works end to
end on simulated data.

This tool only reads and summarizes transactions a business has already received. It never
holds or moves funds, and it does not provide tax or accounting advice — it organizes data
so a person can make their own decisions.

## Scope

**In scope for v0:**
- Simulated x402-style USDC transaction data with deliberate messiness
- Ingest into a canonical schema in SQLite
- Rule-cascade categorization with explicit confidence tiers
- CSV export plus a console/markdown summary
- An evaluation harness measuring precision, recall, and calibration

**Out of scope for v0:**
- Real transaction data (backlog: Base Sepolia testnet txns, or a public dataset)
- PDF report output (backlog)
- More than one payment rail
- QuickBooks/Xero integration, tax-form generation, or any tax advice

## Architecture

Four stages, each an independently runnable CLI command, communicating one-directionally
through SQLite:

```
simulate ──> ingest ──> categorize ──> report
                                  └──> evaluate
```

| Stage | Command | Responsibility |
|---|---|---|
| Simulator | `ledger simulate` | Generate synthetic x402-style transactions with known ground truth |
| Ingest | `ledger ingest` | Validate and normalize into the canonical transaction schema |
| Categorize | `ledger categorize` | Run the rule cascade, write labels + confidence + reason |
| Report | `ledger report --from X --to Y` | CSV export plus readable summary for a date range |
| Evaluate | `ledger evaluate` | Measure precision, recall, calibration against ground truth |

**The ingest seam.** Ingest is the only stage that knows where data came from. Swapping the
simulator for real Sepolia transactions or a public dataset changes ingest alone; everything
downstream consumes the canonical schema unchanged. This is the primary extensibility
requirement of v0.

## Data model

### `transactions`

Raw ingested data. Never mutated by later stages.

| Column | Type | Notes |
|---|---|---|
| `id` | integer pk | |
| `tx_hash` | text unique | Simulator generates unique synthetic hashes |
| `sender_address` | text | |
| `receiver_address` | text | |
| `amount_micro_usdc` | integer | Smallest unit (6 decimals). Never a float. |
| `timestamp` | text (ISO 8601 UTC) | |
| `memo` | text nullable | x402 payloads do not always carry one |
| `chain` | text | e.g. `base-sepolia-sim` |
| `raw_payload` | text (JSON) | Anything not yet modeled |

### `categorizations`

One row per transaction. Written by the categorize stage, kept separate so re-running
categorization never mutates ingested data.

| Column | Type | Notes |
|---|---|---|
| `transaction_id` | integer fk | |
| `category_label` | text | e.g. `agent:0xABC…`, or `uncategorized` |
| `confidence_tier` | text | `confident` or `uncertain` |
| `rule_matched` | text | `sender_match`, `memo_match`, `time_cluster`, or `none` |
| `categorized_at` | text (ISO 8601 UTC) | |

### `ground_truth`

Written by the simulator only. Records the correct grouping for each generated transaction
so the evaluation harness can score categorization automatically.

Note: real data arrives without ground truth. The evaluation harness must not assume this
table is always populated — see Evaluation below.

## Categorization: the rule cascade

Transactions pass through ordered rules. The first rule that fires assigns the label; each
rule records why it fired.

1. **`sender_match`** — the sender address appears more than once in the dataset, making it a
   recurring counterparty rather than a one-off. The group is keyed on the sender address.
   Confidence: `confident`.
2. **`memo_match`** — the memo field is present, non-generic, and shared by more than one
   transaction, making it a usable grouping key. Confidence: `confident`.
3. **`time_cluster`** — a sender seen only once, but falling inside a burst of activity within
   a configurable time window (default: 5 minutes) alongside other transactions. Suggests one
   agent session but cannot be confirmed. Confidence: `uncertain`.
4. **`none`** — no rule fired. Label `uncategorized`, confidence `uncertain`.

v0 has no manual labeling step, so "known" always means "derivable from the dataset itself."
Rules 1 and 2 are confident precisely because repetition is evidence; rule 3 is uncertain
because proximity in time is a guess. Thresholds (minimum occurrences, time window, what
counts as a generic memo) are configuration with stated defaults, not hardcoded constants —
tuning them is how the calibration metric gets improved.

**Nothing is ever forced into a bucket.** A transaction with no confident match stays
explicitly uncertain rather than being assigned to its nearest neighbour. The product's
worst failure is false confidence, not low coverage.

## Simulator design

The simulator must generate data that can actually break the cascade, not a toy dataset that
is trivially 100% categorizable. Required messiness:

- Repeat senders appearing across separate, time-separated bursts (same agent, multiple sessions)
- Some senders with consistent memos, some with none, some with generic/unhelpful memos
- One-off senders with no reuse anywhere in the dataset
- Near-miss cases: similar-but-distinct addresses that must not be collapsed together

Minimum output for v0: 100+ transactions.

## Reporting

- **CSV export** — line-item detail, suitable for a spreadsheet or handing to an accountant.
- **Console/markdown summary** — totals, breakdown by category, and an explicit split between
  confidently categorized and uncertain amounts.

Uncategorized transactions always appear as their own line with their own total. They are
never hidden or folded into an "other" bucket — "$X is unaccounted for" is a number the
business owner's accountant will ask about.

**Usability bar:** a non-technical person should be able to find a specific number in the
report without assistance. This is tested manually against simulated data in v0.

## Evaluation

The simulator records ground truth, so accuracy can be measured automatically on every run
across hundreds of transactions with no hand-labeling.

| Metric | Question it answers |
|---|---|
| Precision | Of transactions marked `confident`, what fraction got the right group? |
| Recall | Of transactions that had a correct grouping available, how many did we catch rather than dumping into `uncertain`? |
| Calibration | When we say `confident`, are we actually right that often? |

Calibration is the metric that matters most. A cascade that is 99% confident and 70% correct
is worse than useless for tax reporting, because it produces confident wrong numbers.

**When real data arrives** (backlog), ground truth disappears. The harness switches to a
hand-labeled sample of 100–200 transactions, and simulated evaluation becomes a regression
check rather than the source of truth. The harness must be built so ground truth is an input
it can be given, not an assumption baked into its structure.

## Error handling

Guiding principle: **the worst failure mode is false confidence, not a crash.** A crash is
visible; a silently miscategorized transaction becomes a wrong number in a tax report.

- **Ingest** — duplicate `tx_hash` is skipped, not overwritten (re-running is idempotent).
  Malformed rows are rejected into a rejects list and reported in the run summary with counts
  and reasons. Never silently dropped: a silent drop is money missing from a revenue total
  with no trace.
- **Categorize** — idempotent. Re-running replaces a transaction's categorization row rather
  than appending, so the cascade can be tuned and re-run freely. Every row records which rule
  fired, so any label traces back to its reason.
- **Report** — an empty date range prints "no transactions in this range" rather than a zeroed
  report that reads as real data saying revenue was $0.
- **Money** — amounts stored as integers in micro-USDC, never floats. Sub-cent payments summed
  thousands of times will drift with floating point, and drift in a financial total is exactly
  the quiet wrongness this tool exists to prevent.

## Testing

**Unit/integration (correctness), via TDD:**
- Each cascade rule fires when it should and only when it should
- Schema round-trips through SQLite
- Date-range reports include the right transactions and exclude boundary cases correctly
- Re-running categorize produces stable results
- Ingest deduplication and reject handling

**Evaluation harness (accuracy):** precision, recall, and calibration as described above.

**Manual (usability):** read the generated sample report end to end and confirm a
non-technical person could find a specific number in it. v0 uses simulated data for this.

## Definition of done

- [ ] 100+ simulated transactions ingested into the canonical schema
- [ ] Categorization distinguishes confident groupings from uncertain ones rather than forcing
      everything into a bucket
- [ ] Report is readable by a non-technical business owner without explanation
- [ ] Evaluation harness reports precision, recall, and calibration
- [ ] One clean sample report exists that could be shown to a real business owner

## Backlog

- Real transaction data: Base Sepolia testnet transactions, or a public x402 dataset
- PDF report output
- Hand-labeled evaluation set for real data
- Second payment rail, to prove the categorization approach generalizes
- Validation interviews with businesses accepting agent payments (see `validation/outreach.md`)

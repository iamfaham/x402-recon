# Ledger v0.1c measurements

Evidence supporting two pre-registered decisions:

- `time_cluster` survives only at B-cubed precision >= 0.70 with >= 20 firings
- the service axis earns a confidence claim only at `memo_match` precision >= 0.95
  with >= 20 firings

Three staged measurements isolate the two levers that can move these numbers: the
`shared_memo_different_services` hazard (Task 1) and a raised `--count`. Each stage
changes exactly one thing relative to the last.

All commands were run from `d:\Projects\agent-payment-reconciliation` on branch
`ledger-v0.1c`, `uv run ledger ...` / `uv run python ...`, stdlib-only.

## A code defect found and fixed before measuring

The original Stage 1 recipe was "set `shared_memo_different_services: int = 0` to
reproduce the pre-hazard dataset." The first attempt at Stage 1 did not reproduce
v0.1b's published figures. Root cause: `src/ledger/simulate.py` computed

```python
per_agent = max(2, hazards.shared_memo_different_services // 2)
```

unconditionally, so `shared_memo_different_services = 0` still floored to
`per_agent = 2` and emitted 4 hazard transactions instead of zero. A config field
that cannot express "none" is not a config field.

Fix (committed separately, `src/ledger/simulate.py` only, commit `596b51f`,
"fix: let shared_memo_different_services=0 disable the hazard"):

```python
if hazards.shared_memo_different_services:
    per_agent = max(2, hazards.shared_memo_different_services // 2)
    for index, service in enumerate(_SHARED_MEMO_SERVICES):
        ...
```

Verified before measuring:

```
config=0 -> 0 hazard txns, 145 total
config=8 -> 8 hazard txns, 153 total
```

`config=8`'s transaction total (153) and hazard count (8) are unchanged from before
the fix — the guard does not alter the RNG stream for the non-zero case. Full suite
(`uv run pytest -q`) was green at 201 passed both before and after this fix.

---

## Stage 1 — baseline (hazard disabled, count=120, seed=42)

`shared_memo_different_services` temporarily set to `0` for this run only, then
restored to `8` immediately after (verified via `git diff src/ledger/simulate.py` /
`git status` showing a clean tree before the final commit).

```
Generated 145 transactions.
  sample\data\transactions.json
  sample\data\ground_truth.json
  sample\data\hazards.json
  sample\data\service_truth.json
=== INGEST ===
Ingest complete.
  Inserted:            145
  Skipped (duplicate): 0
  Rejected:            0
=== CATEGORIZE ===
Categorized 145 transactions (290 rows across 2 axes).
=== EVALUATE ===
Who paid you
============

Categorization accuracy (B-cubed)
=================================

Precision:   98.9%   (of the payments grouped together, how many belonged together)
Recall:      92.9%   (of the payments from one payer, how many were found)
             scored over 145 payments

Calibration - does 'confident' actually mean confident?
  Confident tier precision: 100.0%  (107 payments, threshold 95%)
  Declined coverage:        100.0%  (25 payments left uncategorized)

Per rule
--------
  none           precision 100.0%   recall 100.0%   (25 payments)
    hazard cases     100.0%  (25)    ordinary      n/a  (0)
  sender_match   precision 100.0%   recall  97.2%   (107 payments)
    hazard cases     100.0%  (15)    ordinary   100.0%  (92)
  time_cluster   precision  87.7%   recall  44.1%   (13 payments)
    hazard cases      87.7%  (13)    ordinary      n/a  (0)

Pre-registered criterion: time_cluster B-cubed precision 87.7% on 13 payments - INSUFFICIENT DATA (need 20) - no verdict recorded

What they paid for
==================

These groupings describe what was bought, not who bought it, and
claim no confidence. The figures below say how well grouping by the
payer's memo matches the services actually purchased.

Precision:   100.0%   (of the payments grouped together, how many belonged together)
Recall:      95.0%   (of the payments from one service, how many were found)
             scored over 145 payments

Per rule
--------
  memo_match     precision 100.0%   recall  92.5%   (97 payments)
    hazard cases     100.0%  (31)    ordinary   100.0%  (66)
  none           precision 100.0%   recall 100.0%   (48 payments)
    hazard cases     100.0%  (22)    ordinary   100.0%  (26)

Pre-registered criterion: memo_match B-cubed precision 100.0% on 97 payments - EARNS a confidence claim (threshold 0.95)
```

**Reproduced v0.1b exactly:** payer precision 98.9% / recall 92.9%; service precision
100.0% / recall 95.0%; `time_cluster` 87.7% on 13 payments, INSUFFICIENT DATA. Matches
in every figure, once the config-floor defect above was fixed.

---

## Stage 2 — hazard enabled, same count (count=120, seed=42)

`shared_memo_different_services` at its committed default, `8`.

```
Generated 153 transactions.
  sample\data\transactions.json
  sample\data\ground_truth.json
  sample\data\hazards.json
  sample\data\service_truth.json
=== INGEST ===
Ingest complete.
  Inserted:            153
  Skipped (duplicate): 0
  Rejected:            0
=== CATEGORIZE ===
Categorized 153 transactions (306 rows across 2 axes).
=== EVALUATE ===
Who paid you
============

Categorization accuracy (B-cubed)
=================================

Precision:   99.0%   (of the payments grouped together, how many belonged together)
Recall:      93.3%   (of the payments from one payer, how many were found)
             scored over 153 payments

Calibration - does 'confident' actually mean confident?
  Confident tier precision: 100.0%  (115 payments, threshold 95%)
  Declined coverage:        100.0%  (25 payments left uncategorized)

Per rule
--------
  none           precision 100.0%   recall 100.0%   (25 payments)
    hazard cases     100.0%  (25)    ordinary      n/a  (0)
  sender_match   precision 100.0%   recall  97.4%   (115 payments)
    hazard cases     100.0%  (23)    ordinary   100.0%  (92)
  time_cluster   precision  87.7%   recall  44.1%   (13 payments)
    hazard cases      87.7%  (13)    ordinary      n/a  (0)

Pre-registered criterion: time_cluster B-cubed precision 87.7% on 13 payments - INSUFFICIENT DATA (need 20) - no verdict recorded

What they paid for
==================

These groupings describe what was bought, not who bought it, and
claim no confidence. The figures below say how well grouping by the
payer's memo matches the services actually purchased.

Precision:   97.4%   (of the payments grouped together, how many belonged together)
Recall:      95.2%   (of the payments from one service, how many were found)
             scored over 153 payments

Per rule
--------
  memo_match     precision  96.2%   recall  93.1%   (105 payments)
    hazard cases      89.7%  (39)    ordinary   100.0%  (66)
  none           precision 100.0%   recall 100.0%   (48 payments)
    hazard cases     100.0%  (22)    ordinary   100.0%  (26)

Pre-registered criterion: memo_match B-cubed precision 96.2% on 105 payments - EARNS a confidence claim (threshold 0.95)
```

**Service axis (causal):** precision fell 100.0% -> 96.2% — the first time it has
been able to fall at all, on 8 more `memo_match`-tagged hazard transactions. This is
the hazard directly creating merges the memo-match rule cannot separate. **Causal.**

**Payer axis (not causal — reframed):** `time_cluster` is **unchanged**: 87.7% on 13
payments in both Stage 1 and Stage 2, exact match on both precision and firing count.
Payer precision/recall moved marginally (98.9%/92.9% -> 99.0%/93.3%), but that
movement is **not** attributable to the hazard's own effect. Inserting the hazard's
generation phase consumes RNG draws before later actors are generated, so every actor
generated afterward shifts, and the whole dataset downstream of the insertion point
differs by a few transactions (145 -> 153 total, +8, exactly the hazard's size) —
not just the added rows. Payer-axis-neutrality means the hazard's *own* transactions
are claimed by `sender_match` (which they are, and `time_cluster` never sees them) —
it does not and cannot mean every payer-axis number is bit-identical, because
inserting a generation phase reshuffles the RNG stream for everything after it. The
one number that actually tests neutrality — `time_cluster`'s precision and firing
count, since `time_cluster` never touches the hazard's own transactions either way —
is exactly unchanged, which is the correct evidence for the neutrality claim.

---

## Stage 3 — raised count, canonical count search (seed=42)

| count | `time_cluster` firings | `time_cluster` precision | verdict |
|---|---|---|---|
| 300 | 32 | 70.0% | PASSES threshold 0.70 |
| 500 | 90 | 59.3% | FAILS threshold 0.70 |
| 800 | 215 | 52.7% | FAILS threshold 0.70 |

count=300 already cleared the >=20 firings bar (32 firings), so **no further counts
were needed to satisfy the firing-count requirement**. 500 and 800 were still run and
recorded per the brief's instruction to show the search, and because they surface a
notable trend: `time_cluster` precision *falls* as count rises (70.0% -> 59.3% ->
52.7%), even as firings and recall climb. More data makes `time_cluster` fire more
often but not more reliably at this seed — worth flagging even though it doesn't
change which count is canonical.

**Canonical count: 300** (the count at which the search first satisfied both the
>=20-firings gate and matched the brief's step-1 target).

### Verbatim evaluate output, count=300, seed=42

```
Generated 300 transactions.
  sample\data\transactions.json
  sample\data\ground_truth.json
  sample\data\hazards.json
  sample\data\service_truth.json
Ingest complete.
  Inserted:            300
  Skipped (duplicate): 0
  Rejected:            0
Categorized 300 transactions (600 rows across 2 axes).
Who paid you
============

Categorization accuracy (B-cubed)
=================================

Precision:   96.8%   (of the payments grouped together, how many belonged together)
Recall:      96.6%   (of the payments from one payer, how many were found)
             scored over 300 payments

Calibration - does 'confident' actually mean confident?
  Confident tier precision: 100.0%  (115 payments, threshold 95%)
  Declined coverage:        100.0%  (153 payments left uncategorized)

Per rule
--------
  none           precision 100.0%   recall 100.0%   (153 payments)
    hazard cases     100.0%  (20)    ordinary   100.0%  (133)
  sender_match   precision 100.0%   recall  97.4%   (115 payments)
    hazard cases     100.0%  (23)    ordinary   100.0%  (92)
  time_cluster   precision  70.0%   recall  77.3%   (32 payments)
    hazard cases      77.2%  (18)    ordinary    60.7%  (14)

Pre-registered criterion: time_cluster B-cubed precision 70.0% on 32 payments - PASSES threshold 0.70

What they paid for
==================

These groupings describe what was bought, not who bought it, and
claim no confidence. The figures below say how well grouping by the
payer's memo matches the services actually purchased.

Precision:   98.7%   (of the payments grouped together, how many belonged together)
Recall:      97.6%   (of the payments from one service, how many were found)
             scored over 300 payments

Per rule
--------
  memo_match     precision  96.2%   recall  93.1%   (105 payments)
    hazard cases      89.7%  (39)    ordinary   100.0%  (66)
  none           precision 100.0%   recall 100.0%   (195 payments)
    hazard cases     100.0%  (22)    ordinary   100.0%  (173)

Pre-registered criterion: memo_match B-cubed precision 96.2% on 105 payments - EARNS a confidence claim (threshold 0.95)
```

### Verbatim evaluate output, count=500, seed=42 (recorded per the search-transparency requirement)

```
Generated 500 transactions.
  sample\data\transactions.json
  sample\data\ground_truth.json
  sample\data\hazards.json
  sample\data\service_truth.json
Ingest complete.
  Inserted:            500
  Skipped (duplicate): 0
  Rejected:            0
Categorized 500 transactions (1000 rows across 2 axes).
Who paid you
============

Categorization accuracy (B-cubed)
=================================

Precision:   92.7%   (of the payments grouped together, how many belonged together)
Recall:      97.9%   (of the payments from one payer, how many were found)
             scored over 500 payments

Calibration - does 'confident' actually mean confident?
  Confident tier precision: 100.0%  (115 payments, threshold 95%)
  Declined coverage:        100.0%  (295 payments left uncategorized)

Per rule
--------
  none           precision 100.0%   recall 100.0%   (295 payments)
    hazard cases     100.0%  (18)    ordinary   100.0%  (277)
  sender_match   precision 100.0%   recall  97.4%   (115 payments)
    hazard cases     100.0%  (23)    ordinary   100.0%  (92)
  time_cluster   precision  59.3%   recall  91.9%   (90 payments)
    hazard cases      74.5%  (20)    ordinary    55.0%  (70)

Pre-registered criterion: time_cluster B-cubed precision 59.3% on 90 payments - FAILS threshold 0.70

What they paid for
==================

These groupings describe what was bought, not who bought it, and
claim no confidence. The figures below say how well grouping by the
payer's memo matches the services actually purchased.

Precision:   99.2%   (of the payments grouped together, how many belonged together)
Recall:      98.5%   (of the payments from one service, how many were found)
             scored over 500 payments

Per rule
--------
  memo_match     precision  96.2%   recall  93.1%   (105 payments)
    hazard cases      89.7%  (39)    ordinary   100.0%  (66)
  none           precision 100.0%   recall 100.0%   (395 payments)
    hazard cases     100.0%  (22)    ordinary   100.0%  (373)

Pre-registered criterion: memo_match B-cubed precision 96.2% on 105 payments - EARNS a confidence claim (threshold 0.95)
```

### Verbatim evaluate output, count=800, seed=42 (recorded per the search-transparency requirement)

```
Generated 800 transactions.
  sample\data\transactions.json
  sample\data\ground_truth.json
  sample\data\hazards.json
  sample\data\service_truth.json
Ingest complete.
  Inserted:            800
  Skipped (duplicate): 0
  Rejected:            0
Categorized 800 transactions (1600 rows across 2 axes).
Who paid you
============

Categorization accuracy (B-cubed)
=================================

Precision:   87.3%   (of the payments grouped together, how many belonged together)
Recall:      98.7%   (of the payments from one payer, how many were found)
             scored over 800 payments

Calibration - does 'confident' actually mean confident?
  Confident tier precision: 100.0%  (115 payments, threshold 95%)
  Declined coverage:        100.0%  (470 payments left uncategorized)

Per rule
--------
  none           precision 100.0%   recall 100.0%   (470 payments)
    hazard cases     100.0%  (16)    ordinary   100.0%  (454)
  sender_match   precision 100.0%   recall  97.4%   (115 payments)
    hazard cases     100.0%  (23)    ordinary   100.0%  (92)
  time_cluster   precision  52.7%   recall  96.6%   (215 payments)
    hazard cases      70.8%  (22)    ordinary    50.7%  (193)

Pre-registered criterion: time_cluster B-cubed precision 52.7% on 215 payments - FAILS threshold 0.70

What they paid for
==================

These groupings describe what was bought, not who bought it, and
claim no confidence. The figures below say how well grouping by the
payer's memo matches the services actually purchased.

Precision:   99.5%   (of the payments grouped together, how many belonged together)
Recall:      99.1%   (of the payments from one service, how many were found)
             scored over 800 payments

Per rule
--------
  memo_match     precision  96.2%   recall  93.1%   (105 payments)
    hazard cases      89.7%  (39)    ordinary   100.0%  (66)
  none           precision 100.0%   recall 100.0%   (695 payments)
    hazard cases     100.0%  (22)    ordinary   100.0%  (673)

Pre-registered criterion: memo_match B-cubed precision 96.2% on 105 payments - EARNS a confidence claim (threshold 0.95)
```

### Hazard fraction at the canonical count (Step 4)

```
uv run python -c "
from ledger.simulate import generate_batch
b = generate_batch(count=300, seed=42)
print(f'{len(b.hazards)} hazard-tagged of {len(b.transactions)} = {len(b.hazards)/len(b.transactions):.1%}')
"
```

```
61 hazard-tagged of 300 = 20.3%
```

At count=120 the hazard-tagged fraction was higher (hazards are fixed-size while
count=120 is close to the generator's natural floor); raising to count=300 adds
untagged filler transactions, so the fraction falls, as expected. 20.3% remains a
clear minority of the dataset.

---

## Comparison table: the three stages

| | Stage 1 (baseline, count=120) | Stage 2 (hazard, count=120) | Stage 3 (hazard, count=300) |
|---|---|---|---|
| Payer precision | 98.9% | 99.0% | 96.8% |
| Payer recall | 92.9% | 93.3% | 96.6% |
| Service precision | 100.0% | 96.2% | 98.7% (overall); `memo_match` rule 96.2% |
| Service recall | 95.0% | 95.2% | 97.6% |
| `time_cluster` precision | 87.7% | 87.7% | 70.0% |
| `time_cluster` firings | 13 | 13 | 32 |
| `time_cluster` verdict | INSUFFICIENT DATA | INSUFFICIENT DATA | PASSES (0.70 threshold) |
| `memo_match` verdict | EARNS (100.0% on 97) | EARNS (96.2% on 105) | EARNS (96.2% on 105) |

Note the Stage 3 `memo_match` figures (96.2% on 105 payments) are identical to
Stage 2's — raising count from 120 to 300 added no new `memo_match`-tagged hazard
transactions (the hazard's size is fixed at 8 regardless of `--count`), so that rule
is unaffected by the count increase. Only `time_cluster`, which scales with dataset
density, moves between Stage 2 and Stage 3.

---

## Seed sweep at the canonical count (count=300, seeds 1-20)

Requested because the very first (blocked) Stage 1 attempt measured `time_cluster`
at 100.0% on 13 payments where a corrected run measured 87.7% on 13 — a 12-point gap
from a dataset reshuffle alone, at exactly the sample size a binding decision rests
on. This sweep quantifies how much `time_cluster`'s verdict varies across seeds at
the canonical count.

Each row: `uv run ledger simulate --out <tmp>/data --count 300 --seed <N>` -> ingest
-> categorize -> evaluate, `time_cluster` line only.

| seed | firings | precision | verdict |
|---|---|---|---|
| 1 | 37 | 67.6% | FAILS |
| 2 | 19 | 78.9% | INSUFFICIENT DATA (below 20) |
| 3 | 26 | 73.1% | PASSES |
| 4 | 20 | 72.5% | PASSES |
| 5 | 31 | 67.7% | FAILS |
| 6 | 32 | 71.9% | PASSES |
| 7 | 24 | 69.4% | FAILS |
| 8 | 21 | 85.7% | PASSES |
| 9 | 32 | 68.8% | FAILS |
| 10 | 33 | 59.1% | FAILS |
| 11 | 26 | 64.1% | FAILS |
| 12 | 28 | 78.6% | PASSES |
| 13 | 21 | 69.8% | FAILS |
| 14 | 32 | 75.0% | PASSES |
| 15 | 29 | 70.3% | PASSES |
| 16 | 27 | 68.5% | FAILS |
| 17 | 25 | 76.0% | PASSES |
| 18 | 51 | 60.8% | FAILS |
| 19 | 37 | 63.5% | FAILS |
| 20 | 35 | 67.1% | FAILS |

(A throwaway Python script drove this sweep; it was not committed.)

**Distribution summary:**

- 19 of 20 seeds clear the >=20-firings bar (only seed 2, at 19 firings, falls just
  short and gets INSUFFICIENT DATA instead of a pass/fail verdict).
- Among those 19: precision ranges from **59.1%** (seed 10) to **85.7%** (seed 8) —
  a 26.6-point spread. Median precision is **69.4%**.
- Of the 19 that clear the firing bar: **8 seeds PASS** the 0.70 threshold (3, 4, 6,
  8, 12, 14, 15, 17) and **11 seeds FAIL** (1, 5, 7, 9, 10, 11, 13, 16, 18, 19, 20).
- The canonical seed=42 result (70.0% on 32, PASSES) sits almost exactly on the
  median of this distribution and barely clears the threshold — it is not an
  outlier, but it is also not comfortably clear of the line: a large minority of
  seeds (11/19, 58%) would have failed at the identical count.

**What this means for Task 4:** `time_cluster`'s pass/fail verdict at count=300 is
highly seed-sensitive — close to a coin flip around the 0.70 line, not a robust
margin. A single pre-registered seed (42) happens to land on the PASS side, but the
underlying rule's true precision at this dataset density is better characterized as
"clusters around 69-70%, plausibly anywhere from ~59% to ~86%" than as a clean pass.
Task 4 should treat the seed=42 PASS as a single draw from a wide distribution
straddling its own threshold, not as strong evidence `time_cluster` reliably clears
the bar.

---

## Sensitivity note: the hazard's size determines the service verdict

The service-axis verdict (`memo_match` earns/does not earn a confidence claim) is
sensitive to the size of `shared_memo_different_services`, which was fixed at `N=8`
for reasons unrelated to where the verdict lands:

- At the 97 baseline `memo_match`-tagged payments (Stage 1 dataset, before the
  hazard existed), `N=8` yields a measured precision of approximately **0.962**,
  which **passes** the 0.95 threshold (this matches the measured Stage 2/3 figure of
  96.2% on 105 payments — 97 baseline + 8 hazard-tagged = 105).
- The same baseline with `N=12` would yield approximately **0.945**, which **fails**
  the 0.95 threshold.

`N=8` was chosen for comparability with the other three named hazards in
`HazardConfig` (`shared_memo_strangers=6`, `rotating_address_payments=6`,
`interleaved_one_offs=22`, `refund_count=8`) **before any measurement was taken** —
not selected because it produces a passing result. Stated plainly: **the service
verdict is close enough to the 0.95 line that a differently-sized synthetic hazard
(chosen just as defensibly on comparability grounds) would flip it.** This does not
mean the verdict is invalid — `N=8` is a principled, pre-registered choice, and the
measured 96.2% is the correct figure for that choice. It means a reader should weigh
the verdict knowing it rests on a synthetic-dataset parameter with real sensitivity
near the threshold, and that only real transaction data — not a differently-sized
synthetic hazard — can settle the question with the confidence the "EARNS a
confidence claim" language implies.

---

## Full test suite

```
uv run pytest -q
```

```
201 passed in 3.37s
```

Run both immediately after the `simulate.py` floor fix and confirmed unaffected by
any of the measurement runs above (measurement runs only touch the gitignored
`sample/` directory and never modify source).

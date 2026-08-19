# Sample report

This is a real, unedited run of the Ledger pipeline against simulated data
(seed 42, 120 transactions requested; the simulator writes 143 transactions
once refunds and hazard cases are included), generated with:

```bash
uv run ledger simulate --out sample/data --count 120 --seed 42
uv run ledger --db sample/ledger.db ingest --from sample/data
uv run ledger --db sample/ledger.db categorize
uv run ledger --db sample/ledger.db report --from 2026-08-01 --to 2026-09-30 --csv sample/report.csv
uv run ledger --db sample/ledger.db evaluate
```

## Console summary (`ledger report`)

```
Payments received, 2026-08-01 to 2026-09-30
===========================================

Payments received:  $195.939028  (143 payments)
Refunds issued:     $17.928226
Net received:       $178.010802

  Confidently identified: $144.538667
  Needs review:           $33.472135

Breakdown by source (net of refunds)
------------------------------------
  agent:0xa3a4419f4fe020864d3979317de23f0749d0b7d5       $25.130738  (20 payments)
  agent:0x5163f631cf81b7206f2e1bdb1812926337c6675d       $23.206618  (15 payments)
  agent:0x30877432d1026706d7e805da846a32c3bb81e3c2       $21.301404  (22 payments)
  agent:0x2feb1f5b5833701071fbc451d7a7da82b31571c2       $17.695868  (15 payments)
  agent:0xeacf44eee4a2dc7ca1e8250932616f0350867e2a       $16.642457  (10 payments)
  agent:0xaca34a61b19926535aa98b3b4049bfda5364763d       $12.390873  (6 payments)
  agent:0x8278dcecda0c30212b39929ecc0f574c949b0431        $9.651106  (13 payments)
  service:invoice-settlement                              $7.161092  (6 payments)
  service:monthly-usage                                    $5.86274  (5 payments)
  agent:0xaca34a615a2384d5b5e7143c50f200529df4648e        $5.495771  (7 payments)
  agent:0xf34f2a72accd77839232a63b4ac0916cdab473c0            $0.00  (2 payments)
  cluster:2026-08-04T19:37:26Z                            $3.506467  (2 payments)   [needs review]
  Uncategorized                                          $29.965668  (20 payments)   [needs review]

Anything marked [needs review] could not be confidently matched to a
single payer. Please confirm these before relying on the totals.

This report organizes payment data you have already received.
It is not tax or accounting advice.
```

## Accuracy summary (`ledger evaluate`)

```
Categorization accuracy (B-cubed)
=================================

Precision:   96.5%   (of the payments grouped together, how many belonged together)
Recall:      100.0%   (of the payments from one payer, how many were found)
             scored over 143 payments

Calibration - does 'confident' actually mean confident?
  Confident tier precision: 96.7%  (121 payments, threshold 95%)
  Declined coverage:        100.0%  (20 payments left uncategorized)

Per rule
--------
  memo_match     precision  63.6%   recall 100.0%   (11 payments)
    hazard cases      63.6%  (11)    ordinary     0.0%  (0)
  none           precision 100.0%   recall 100.0%   (20 payments)
    hazard cases     100.0%  (20)    ordinary     0.0%  (0)
  sender_match   precision 100.0%   recall 100.0%   (110 payments)
    hazard cases     100.0%  (18)    ordinary   100.0%  (92)
  time_cluster   precision  50.0%   recall 100.0%   (2 payments)
    hazard cases      50.0%  (2)    ordinary     0.0%  (0)

Pre-registered criterion: time_cluster B-cubed precision 50.0% - FAILS threshold 0.70
```

## Line-item CSV (`--csv`)

The full CSV has a header row plus 143 data rows (one per transaction).
[`docs/sample-report.csv`](./sample-report.csv) is an excerpt: the header
plus the first 25 data rows, sorted by timestamp. It is not the complete
file — see the command above to regenerate the full 143-row CSV locally.

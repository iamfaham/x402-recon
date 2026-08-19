# Sample report

This is a real, unedited run of the Ledger pipeline against simulated data
(seed 42, 120 transactions), generated with:

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

Total received:     $16.495202  (120 payments)
  Confidently identified: $13.708366
  Needs review:           $2.786836

Breakdown by source
-------------------
  agent:0x30877432d1026706d7e805da846a32c3bb81e3c2        $3.048011  (18 payments)
  agent:0x5236bb4734865425feeaa4e2fe981b29ee11b922        $2.549794  (21 payments)
  agent:0x208611c9ddc24829264ac29d7172d3e19530405f        $2.505478  (16 payments)
  agent:0x36d240ea122158278dcecda0c30212b39929ecc0        $2.001587  (13 payments)
  agent:0x1abdd370c191a4a741ce27d9c44a2f1c82cd44f6        $1.567651  (11 payments)
  service:invoice-settlement                              $0.802639  (6 payments)
  agent:0xbd8a88385a795572df6fe80d77ad740d11f1dcf3        $0.687395  (6 payments)
  agent:0xbd8a8838ce76a5a0020d33eb7986102163324c53        $0.545811  (4 payments)
  cluster:2026-08-09T16:04:04Z                            $0.832859  (7 payments)   [needs review]
  cluster:2026-08-09T15:39:00Z                            $0.795089  (7 payments)   [needs review]
  cluster:2026-08-09T15:16:34Z                             $0.62816  (6 payments)   [needs review]
  cluster:2026-08-09T16:26:23Z                            $0.239327  (2 payments)   [needs review]
  cluster:2026-08-09T15:02:54Z                            $0.164764  (2 payments)   [needs review]
  Uncategorized                                           $0.126637  (1 payment)   [needs review]

Anything marked [needs review] could not be confidently matched to a
single payer. Please confirm these before relying on the totals.

This report organizes payment data you have already received.
It is not tax or accounting advice.
```

## Accuracy summary (`ledger evaluate`)

```
Categorization accuracy
=======================

Precision:   79.8%   (of 119 grouped payments, how many landed in the right group)
Recall:      100.0%   (of 95 groupable payments, how many we caught correctly)

Calibration - does 'confident' actually mean confident?
  Confident tier accuracy: 100.0%  (95 payments)
  Uncertain tier accuracy: 0.0%  (24 payments)
```

## Line-item CSV (`--csv`)

The full CSV has a header row plus 120 data rows (one per transaction).
[`docs/sample-report.csv`](./sample-report.csv) is an excerpt: the header
plus the first 25 data rows, sorted by timestamp. It is not the complete
file — see the command above to regenerate the full 120-row CSV locally.

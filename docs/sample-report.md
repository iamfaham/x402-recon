# Sample report

This is a real, unedited run of the Ledger pipeline against simulated data
(seed 42, 120 transactions requested; the simulator writes 145 transactions
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

Payments received:  $185.9197  (137 payments)
Refunds issued:     $9.851201  (8 refunds)
Net received:       $176.068499

  Confidently identified: $150.62246
  Needs review:           $25.446039

Breakdown by source (net of refunds)
------------------------------------
  agent:0xa3a4419f4fe020864d3979317de23f0749d0b7d5       $25.917158  (19 payments, 2 refunds)
  agent:0x30877432d1026706d7e805da846a32c3bb81e3c2       $24.327816  (20 payments, 1 refund)
  agent:0x5163f631cf81b7206f2e1bdb1812926337c6675d       $23.206618  (15 payments)
  agent:0x2feb1f5b5833701071fbc451d7a7da82b31571c2       $17.678155  (15 payments, 2 refunds)
  agent:0x8278dcecda0c30212b39929ecc0f574c949b0431       $12.558327  (11 payments, 1 refund)
  service:reports                                        $11.074617  (4 payments)
  agent:0xaca34a61b19926535aa98b3b4049bfda5364763d        $8.810276  (6 payments, 1 refund)
  service:monthly-usage                                   $7.724616  (6 payments)
  agent:0x4daef485a962db5cc70072e6851cd842b530def3        $7.169687  (3 payments)
  agent:0xaca34a615a2384d5b5e7143c50f200529df4648e        $4.811442  (6 payments, 1 refund)
  service:report-api                                      $3.323097  (3 payments)
  agent:0x8927965ead182ffdad3582bdae015e40c69a2357        $2.411903  (3 payments)
  service:report-api-v2                                   $1.608748  (4 payments)
  cluster:2026-08-03T06:08:05Z                             $2.54847  (1 payment)   [needs review]
  cluster:2026-08-08T11:49:10Z                            $0.176702  (1 payment)   [needs review]
  Uncategorized                                          $22.720867  (20 payments)   [needs review]

Anything marked [needs review] could not be confidently matched to a
single payer. Please confirm these before relying on the totals.

This report organizes payment data you have already received.
It is not tax or accounting advice.
```

Note the `agent:0xa3a...` line: 19 payments and 2 refunds, reported as such
rather than "(21 payments)" — the payment count is now reported against the
gross figure and the refund count separately, so a payer who made one payment
and received one refund back never reads as having made two payments (I5).

## Accuracy summary (`ledger evaluate`)

```
Categorization accuracy (B-cubed)
=================================

Precision:   96.6%   (of the payments grouped together, how many belonged together)
Recall:      92.9%   (of the payments from one payer, how many were found)
             scored over 145 payments

Calibration - does 'confident' actually mean confident?
  Confident tier precision: 95.9%  (123 payments, threshold 95%)
  Declined coverage:        100.0%  (20 payments left uncategorized)

Per rule
--------
  memo_match     precision  70.6%   recall  57.2%   (17 payments)
    hazard cases      70.6%  (17)    ordinary      n/a  (0)
  none           precision 100.0%   recall 100.0%   (20 payments)
    hazard cases     100.0%  (20)    ordinary      n/a  (0)
  sender_match   precision 100.0%   recall  97.2%   (106 payments)
    hazard cases     100.0%  (14)    ordinary   100.0%  (92)
  time_cluster   precision 100.0%   recall 100.0%   (2 payments)
    hazard cases     100.0%  (2)    ordinary      n/a  (0)

Pre-registered criterion: time_cluster B-cubed precision 100.0% on 2 payments - INSUFFICIENT DATA (need 20) - no verdict recorded
```

Recall is now below 100% (92.9%) for the first time. This is the C1a fix
working, not a regression: the rotating-address hazard now genuinely
fragments one true payer into two predicted `sender_match` groups (each
address appears twice, so `sender_match` fires on both halves), which
B-cubed recall correctly penalizes. Under the old generator each rotating
address appeared once, `sender_match` never fired on any of them, and the
dataset contained zero fragmentation — 100% recall was a statement about the
dataset, not the tool.

`memo_match` now scores over 17 payments instead of 11: the memo-drift
hazard's sender address no longer repeats, so `sender_match` no longer
intercepts it, and `memo_match` sees (and is scored on) those transactions
too (C1b).

### The branch's strongest finding (I6)

`memo_match` measured **70.6% B-cubed precision on 17 payments** — a rule
the cascade marks *confident*. That means roughly three in ten payments this
rule groups together are grouped wrong, yet they are folded into the
headline "Confidently identified" total ($150.62) at face value. The
aggregate confident-tier figure, 95.9%, clears the pre-registered 0.95 gate
only because `sender_match`'s 106 easy, unambiguous cases dilute
`memo_match`'s much weaker 70.6%. A cascade that reported confident-tier
accuracy per rule, rather than blended, would show this immediately; the
blended figure currently hides it. This is the result v0 (majority-vote
purity, no per-rule split) was structurally incapable of producing, and it
matters more than where the `time_cluster` verdict lands.

### time_cluster verdict: a distribution, not one draw

The pre-registered criterion (B-cubed precision >= 0.70) applies only when
`time_cluster` has fired on enough transactions to mean something. A
one-off sweep of seeds 1-40 (`count=120`, same hazard configuration as
above) shows why a single seed's verdict cannot be trusted on its own:

- `time_cluster` fired at all in **16 of 40 seeds** (24 seeds: the rule
  never matched anything, so no verdict is even attempted).
- Of the 16 seeds where it fired: **13 PASS**, **3 FAIL** against the 0.70
  threshold.
- Sample size (`n`) ranged **1-5** across every seed it fired in.

Every one of those `n` values is below `MIN_VERDICT_SAMPLE` (20), so under
the C2a gate, every seed in this sweep — including seed 42 above — would
print `INSUFFICIENT DATA`, never a bare `PASSES`/`FAILS`. That is the fix
working as intended: with the current hazard density, `time_cluster` simply
does not fire often enough for its precision to be measured reliably, and
the tool now says so instead of asserting a verdict that seed selection
alone could flip. This sweep was run with a throwaway script, not committed;
it exists to document the distribution v0.1b inherits.

## Line-item CSV (`--csv`)

The full CSV has a header row plus 145 data rows (one per transaction).
[`docs/sample-report.csv`](./sample-report.csv) is an excerpt: the header
plus the first 25 data rows, sorted by timestamp. It is not the complete
file — see the command above to regenerate the full 145-row CSV locally.

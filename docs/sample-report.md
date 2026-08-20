# Sample report

This is a real, unedited run of the Ledger pipeline against simulated data
(seed 42, `--count 120` requested; the simulator's fixed set of ordinary
agents plus its hazard cases already produces 145 transactions on their own,
before `--count` ever comes into play - `--count` only tops the dataset up
with further untagged filler if the natural output falls short of it, which
120 does not), generated with:

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
Refunds issued:     $10.677028  (8 refunds)
Net received:       $175.242672

  Confidently identified: $126.081426
  Needs review:           $49.161246

Who paid you (net of refunds)
-----------------------------
  agent:0xa3a4419f4fe020864d3979317de23f0749d0b7d5       $25.917158  (19 payments, 2 refunds)
  agent:0x30877432d1026706d7e805da846a32c3bb81e3c2       $24.327816  (20 payments, 1 refund)
  agent:0x5163f631cf81b7206f2e1bdb1812926337c6675d       $18.845364  (15 payments, 2 refunds)
  agent:0x2feb1f5b5833701071fbc451d7a7da82b31571c2       $17.695868  (15 payments)
  agent:0x8278dcecda0c30212b39929ecc0f574c949b0431       $15.196557  (11 payments)
  agent:0xaca34a61b19926535aa98b3b4049bfda5364763d        $9.021302  (6 payments, 1 refund)
  agent:0x4daef485a962db5cc70072e6851cd842b530def3        $7.169687  (3 payments)
  agent:0xaca34a615a2384d5b5e7143c50f200529df4648e        $5.495771  (6 payments, 1 refund)
  agent:0x8927965ead182ffdad3582bdae015e40c69a2357        $2.411903  (3 payments)
  agent:0xbd7a15101a69f83d58fba93304abbb786c234316            $0.00  (1 payment, 1 refund)
  cluster:2026-08-04T12:14:39Z                           $11.074617  (4 payments)   [needs review]
  cluster:2026-08-03T06:08:05Z                            $4.157218  (5 payments)   [needs review]
  cluster:2026-08-09T15:51:09Z                            $3.323097  (3 payments)   [needs review]
  cluster:2026-08-08T11:49:10Z                            $0.176702  (1 payment)   [needs review]
  Not identified                                         $30.429612  (25 payments)   [needs review]

What they paid for (net of refunds)
-----------------------------------
  Grouped by the memo the payer sent. These groupings describe what was
  bought; they are not a claim about who bought it.
  service:search-api                                     $25.917158  (19 payments, 2 refunds)
  service:weather-api                                    $24.327816  (20 payments, 1 refund)
  service:llm-inference                                  $18.845364  (15 payments, 2 refunds)
  service:data-feed                                      $14.517073  (12 payments, 2 refunds)
  service:reports                                        $11.074617  (4 payments)
  service:invoice-settlement                               $9.58159  (6 payments)
  service:monthly-usage                                   $7.708745  (6 payments, 1 refund)
  service:report-api                                      $3.323097  (3 payments)
  service:report-api-v2                                   $1.608748  (4 payments)
  No service identified                                  $58.338464  (48 payments)

Anything marked [needs review] could not be confidently matched to a
single payer. Please confirm these before relying on the totals.

This report organizes payment data you have already received.
It is not tax or accounting advice.
```

Both breakdowns independently reconcile to the same net received
($175.242672); each just partitions it along a different axis. The payer
breakdown's "Not identified" and the service breakdown's "No service
identified" are not the same set of transactions — a payment can have a
confident payer and no service, or the reverse.

## Accuracy summary (`ledger evaluate`)

```
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
Recall:      95.0%   (of the payments from one payer, how many were found)
             scored over 145 payments

Per rule
--------
  memo_match     precision 100.0%   recall  92.5%   (97 payments)
    hazard cases     100.0%  (31)    ordinary   100.0%  (66)
  none           precision 100.0%   recall 100.0%   (48 payments)
    hazard cases     100.0%  (22)    ordinary   100.0%  (26)
```

### The finding this release exists to record

`memo_match` measured **70.6% B-cubed precision against payer ground truth**
in v0.1a — a rule the old, single-axis cascade marked *confident*, folded
straight into "Confidently identified" at face value. Scored against what it
actually groups — service, not payer — `memo_match` now measures **100%
precision**. The rule was never wrong. Only its presentation as a payer
identity was: six unrelated payers who all bought `monthly-usage` were the
same memo, not the same sender, and reporting them as one confidently
identified payer was the defect.

Service recall (95.0%) sits below 100% because exact-string memo matching
fragments the memo-drift hazard's service into three separate memo strings.
That is the measurement working as designed, not a regression: a service that
genuinely changes its memo over time should not be silently merged back
together by a tool that only compares exact strings.

The payer axis, cleanly separated from service grouping, now has exactly one
confident rule — `sender_match` — measuring 100% confident-tier precision
over 107 payments. No confident rule fails calibration on either axis; the
service axis has no confident rules to fail, because both of its rules
(`memo_match`, `none`) are descriptive by construction and are never held to
the 0.95 floor.

### Service precision is currently unfalsifiable

The service axis's 100.0% precision above should not be read as a stronger
result than the payer axis's 98.9%. In this dataset, `service_truth` is
derived from the payment's memo for essentially every generator, and the only
place service truth and memo diverge is the memo-drift hazard — one true
service spread across three memo strings — which costs `memo_match` **recall**
only, never precision. No hazard in this dataset gives one memo string to two
genuinely different services, which is the only kind of case that could push
service precision below 100%. That makes the current 100.0% figure
near-tautological: it is close to guaranteed by how the data is built, not
something the tool had to earn against an adversarial case. Only service
**recall** is presently falsifiable. A `shared_memo_different_services`
hazard — deliberately built, not implied by an existing one — is a
precondition for treating any future service-axis precision figure as
evidence of anything, and for any future confidence claim on that axis.
Building it is out of scope for this release, since it would change the
dataset and every published number again; this section records the caveat so
the number is not read as more than it is.

### time_cluster after the split

Splitting the two axes changed which transactions fall through to
`time_cluster`: the memo-drift hazard that `memo_match` used to intercept (on
the old, single payer/service cascade) no longer competes with it on the
payer axis, since `memo_match` is now service-only. `time_cluster` fired on
**13** payments this run, measuring **87.7%** B-cubed precision — above the
pre-registered 0.70 threshold — but the run still prints `INSUFFICIENT DATA`
because 13 is below `MIN_VERDICT_SAMPLE` (20). The rule would pass; it simply
has not fired often enough for that pass to be trustworthy. This is the C2a
gate working as designed, not a regression from the v0.1a distribution
documented below.

The prior sweep across seeds 1-40 (documented in the v0.1a measurement, not
re-run here) still describes the shape of the problem: `time_cluster` fires
rarely and at low sample sizes, so any single seed's verdict — including this
one — should be read as one draw from a distribution, not a settled result.

## Line-item CSV (`--csv`)

The full CSV has a header row plus 145 data rows (one per transaction).
[`docs/sample-report.csv`](./sample-report.csv) is an excerpt: the header
plus the first 25 data rows, sorted by timestamp. It carries both axes'
labels per row (`payer_label`/`payer_tier`/`payer_rule` and
`service_label`/`service_rule`). It is not the complete file — see the
command above to regenerate the full 145-row CSV locally.

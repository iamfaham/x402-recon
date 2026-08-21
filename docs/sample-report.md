# Sample report

This is a real, unedited run of the Ledger pipeline against simulated data
(seed 42, `--count 300`), generated with:

```bash
uv run ledger simulate --out sample/data --count 300 --seed 42
uv run ledger --db sample/ledger.db ingest --from sample/data
uv run ledger --db sample/ledger.db categorize
uv run ledger --db sample/ledger.db report --from 2026-08-01 --to 2026-09-30 --csv sample/report.csv
uv run ledger --db sample/ledger.db evaluate
```

300 is the canonical count for v0.1c. v0.1a and v0.1b both used `--count 120`,
so figures in this document are **not directly comparable** to earlier
releases' sample reports — a larger, less hazard-dense dataset changes both
axes' measured precision and recall.

## Console summary (`ledger report`)

```
Payments received, 2026-08-01 to 2026-09-30
===========================================

Payments received:  $393.629715  (292 payments)
Refunds issued:     $2.712232  (8 refunds)
Net received:       $390.917483

  Confidently identified (who paid you): $147.372312
  Needs review (who paid you):           $243.545171

Who paid you (net of refunds)
-----------------------------
  agent:0xa3a4419f4fe020864d3979317de23f0749d0b7d5        $27.53843  (19 payments, 1 refund)
  agent:0x30877432d1026706d7e805da846a32c3bb81e3c2       $24.323933  (20 payments, 2 refunds)
  agent:0x5163f631cf81b7206f2e1bdb1812926337c6675d       $23.203252  (15 payments, 1 refund)
  agent:0x2feb1f5b5833701071fbc451d7a7da82b31571c2       $17.695868  (15 payments)
  agent:0x8278dcecda0c30212b39929ecc0f574c949b0431       $15.196557  (11 payments)
  agent:0xaca34a61b19926535aa98b3b4049bfda5364763d       $12.390873  (6 payments)
  agent:0x340cf1954e227645ae4a9bd1c7624f30492f3ea5        $8.668991  (4 payments)
  agent:0x4daef485a962db5cc70072e6851cd842b530def3        $7.169687  (3 payments)
  agent:0xbba284d9a10b785803c86e7a86c4e7db4f2f5e55        $4.657099  (4 payments)
  agent:0xaca34a615a2384d5b5e7143c50f200529df4648e        $4.115719  (6 payments, 3 refunds)
  agent:0x8927965ead182ffdad3582bdae015e40c69a2357        $2.411903  (3 payments)
  agent:0xbd7a15101a69f83d58fba93304abbb786c234316            $0.00  (1 payment, 1 refund)
  Not identified                                        $243.545171  (185 payments)   [needs review]

What they paid for (net of refunds)
-----------------------------------
  Grouped by the memo the payer sent. These groupings describe what was
  bought; they are not a claim about who bought it.
  service:search-api                                      $27.53843  (19 payments, 1 refund)
  service:weather-api                                    $24.323933  (20 payments, 2 refunds)
  service:llm-inference                                  $23.203252  (15 payments, 1 refund)
  service:data-feed                                      $16.506592  (12 payments, 3 refunds)
  service:monthly-plan                                    $13.32609  (8 payments)
  service:reports                                        $11.074617  (4 payments)
  service:invoice-settlement                               $9.58159  (6 payments)
  service:monthly-usage                                   $7.708745  (6 payments, 1 refund)
  service:report-api                                      $3.323097  (3 payments)
  service:report-api-v2                                   $1.608748  (4 payments)
  No service identified                                 $252.722389  (195 payments)   [needs review]

Each section marks its own [needs review] rows. A payment can appear
in both - once because its payer is unconfirmed, once because its
service is. The two sets overlap, so do not add them together.

This report organizes payment data you have already received.
It is not tax or accounting advice.

Wrote 300 rows to sample/report.csv
```

Both breakdowns independently reconcile to the same net received
($390.917483); each just partitions it along a different axis. The payer
breakdown's "Not identified" and the service breakdown's "No service
identified" are not the same set of transactions — a payment can have a
confident payer and no service, or the reverse. `Confidently identified`
sums only the payer axis's confident rows; the service axis's own confident
tier (`memo_match`) is reported separately and is never added into that
total — confidence is a claim per axis, not a claim that sums across them.

## Accuracy summary (`ledger evaluate`)

```
Who paid you
============

Categorization accuracy (B-cubed)
=================================

Precision:   100.0%   (of the payments grouped together, how many belonged together)
Recall:      95.7%   (of the payments from one payer, how many were found)
             scored over 300 payments

Calibration - does 'confident' actually mean confident?
  Confident tier precision: 100.0%  (115 payments, threshold 95%)
  Declined coverage:        94.6%  (185 payments left uncategorized)

Per rule
--------
  none           precision 100.0%   recall  94.6%   (185 payments)
    hazard cases     100.0%  (38)    ordinary   100.0%  (147)
  sender_match   precision 100.0%   recall  97.4%   (115 payments)
    hazard cases     100.0%  (23)    ordinary   100.0%  (92)

What they paid for
==================

These groupings describe what was bought, not who bought it. The
figures below say how well grouping by the payer's memo matches
the services actually purchased.

Precision:   98.7%   (of the payments grouped together, how many belonged together)
Recall:      97.6%   (of the payments from one service, how many were found)
             scored over 300 payments

Calibration - does 'confident' actually mean confident?
  Confident tier precision: 96.2%  (105 payments, threshold 95%)
  Declined coverage:        100.0%  (195 payments left uncategorized)

Per rule
--------
  memo_match     precision  96.2%   recall  93.1%   (105 payments)
    hazard cases      89.7%  (39)    ordinary   100.0%  (66)
  none           precision 100.0%   recall 100.0%   (195 payments)
    hazard cases     100.0%  (22)    ordinary   100.0%  (173)

Pre-registered criterion: memo_match B-cubed precision 96.2% on 105 payments - EARNS a confidence claim (threshold 0.95)
```

### Two decisions settled this release

**`time_cluster` is removed from the payer cascade.** At the canonical count
(seed 42, 300 payments) it measured 70.0% B-cubed precision on 32 payments —
clearing the pre-registered 0.70 threshold by exactly 0.0 points, the
smallest possible margin. Evidence gathered before that number existed shows
the pass is not robust: across seeds 1–20 at the same count the median is
69.4% (below threshold), 11 of the 19 seeds that clear the 20-firing bar
FAIL, precision spans 59.1%–85.7%, and precision falls as dataset volume
rises (70.0% at count 300, 59.3% at 500, 52.7% at 800) — the rule gets worse,
not better, at the kind of volume a real business would have. Keeping the
rule on the strength of the one favourable seed would be exactly the
cherry-picking pre-registration exists to prevent. The payer cascade is now
`sender_match` → `none`; payments `time_cluster` used to group now fall
through to "not identified" instead.

**The service axis now earns a confidence claim.** `memo_match` measured
96.2% B-cubed precision on 105 payments, clearing the 0.95 floor every
confident rule must clear by 1.2 points. Service rows now tier the same way
payer rows do — claimed rows confident, declined rows uncertain — and the
`DESCRIPTIVE` tier is gone, having no remaining user. Service money stays out
of the payer axis's "Confidently identified" total: confidence is a claim
per axis, and summing them across axes is the defect v0.1b existed to
remove.

**The service verdict's margin is thin, and rests on a synthetic hazard
whose size determines it.** The `shared_memo_different_services` hazard was
fixed at `N=8` — chosen for comparability with the other named hazards
(sized 6, 6, 8, 22), before any measurement was taken. At the 97 baseline
`memo_match` payments, that choice of `N=8` gives ≈0.962 and passes; a
differently-sized, equally defensible `N=12` gives ≈0.945 and fails. `N=8`
was not selected to produce a passing result, but the margin (1.2 points) is
thin enough that this should be read as a real pass, not a settled one.
Nothing short of measuring against real transaction data, rather than a
differently-sized synthetic hazard, resolves that with the confidence the
word "earns" implies.

**Service precision was unfalsifiable until this release, and now is not.**
Every generator prior to this release derived the true service from the
memo, so `memo_match`'s labels and ground truth agreed by construction and
100% precision could not fall no matter how the tool behaved. The
`shared_memo_different_services` hazard — one memo string genuinely shared by
two different services — is what made the figure capable of failing, and
this run's 96.2% is the first service precision measurement that could have
come out lower. The earlier caveat calling service precision unfalsifiable
no longer applies and has been removed from the README.

### time_cluster removal, before/after (count=300, seed=42)

| metric | before (with time_cluster) | after (removed) |
|---|---|---|
| Payer precision | 96.8% | 100.0% |
| Payer recall | 96.6% | 95.7% |
| Declined coverage | 100.0% (153 payments declined) | 94.6% (185 payments declined) |
| Confident-tier (`sender_match`) precision | 100.0% (115 payments) | 100.0% (115 payments) |

`sender_match` is untouched by the removal — its precision, recall, and
firing count are identical before and after, since it never depended on
`time_cluster`. Overall payer precision rises because the removed rule's
70.0% precision was dragging the aggregate down; recall and declined
coverage both move against the tool, which is the honest cost of a rule that
guessed wrong roughly three times in ten now declining instead of guessing.

## Line-item CSV (`--csv`)

The full CSV has a header row plus 300 data rows (one per transaction).
[`docs/sample-report.csv`](./sample-report.csv) is an excerpt: the header
plus the first 25 data rows, sorted by timestamp. It carries both axes'
labels per row (`payer_label`/`payer_tier`/`payer_rule` and
`service_label`/`service_rule`). It is not the complete file — see the
command above to regenerate the full 300-row CSV locally.

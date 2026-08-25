# What `ledger customers` says about x402 traffic

**The payment counts and distinct-payer counts below are the real published
figures** from the x402 Bazaar discovery API, retrieved 2026-08-24.

Two things are modelled, because the Bazaar does not publish them: payment
*amounts* (set near the ~$0.05 average the public dashboards report), and
the repeat *distribution* within each service - assumed long-tailed with
35% one-time triallists for the real service, and flat for the probe-shaped
one. **The contrast between the two is the finding. The exact split inside
the first is an assumption, not a measurement** - and it is precisely the
number a seller could tell us in one query against their own data.

### A real service - Tavily's published profile (8,701 calls / 249 payers)

```
Who actually came back  (2026-07-01 to 2026-07-31)
==================================================

  Payments received:     8,701
  Distinct payers:         249
  Payments per payer:     34.9

                    payers   payments         revenue    share
  ------------------------------------------------------------
  Returning (3+)       162      8,614     $433.330284    98.9%
  Tried twice            0          0           $0.00     0.0%
  One-shot              87         87       $4.890795     1.1%

  Total                249      8,701     $438.221079

  A returning payer is one that paid three or more times in this range.
  Bands describe this window only: a payer who buys monthly counts as
  a one-shot inside any single month.

  This organizes payment data you have already received.
  It is not tax or accounting advice.
```

### A probe-shaped service - one OneSource endpoint (1,078 calls / 1,075 payers)

```
Who actually came back  (2026-07-01 to 2026-07-31)
==================================================

  Payments received:     1,078
  Distinct payers:       1,075
  Payments per payer:      1.0

                    payers   payments         revenue    share
  ------------------------------------------------------------
  Returning (3+)         0          0           $0.00     0.0%
  Tried twice            3          6       $0.254074     0.5%
  One-shot           1,072      1,072      $53.461982    99.5%

  Total              1,075      1,078      $53.716056

  ! Almost every payer here appeared exactly once. That pattern is
    consistent with directory probes or automated sampling rather
    than customer usage - the payment count is real, but it is not
    evidence of demand. Worth confirming before treating this as
    a customer base.

  A returning payer is one that paid three or more times in this range.
  Bands describe this window only: a payer who buys monthly counts as
  a one-shot inside any single month.

  This organizes payment data you have already received.
  It is not tax or accounting advice.
```

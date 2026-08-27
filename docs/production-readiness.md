# What "production ready and open-sourceable" requires

**Date:** 2026-08-26
**Purpose:** the gap between where Ledger is today and something that can be published
on GitHub and put in front of Tavily, Exa and OneSource.

---

## Where we actually are

281 tests, stdlib-only Python 3.13, nine CLI commands, five merged releases with a
measurement apparatus that has caught itself being wrong four times. That is a strong
engineering base.

It is also, today: **never once run against a real transaction.** Everything published
is measured on data we generated. That single fact governs the ordering below.

## Competitive position (checked 2026-08-26)

| Exists | Does not exist |
|---|---|
| **Onyx Bazaar** — leaderboard of every x402 service, sortable by unique payers, 15-min refresh, JSON export | Seller-side revenue reconciliation or tax reporting |
| **x402Scan**, **x402station** — ecosystem analytics and service monitoring | Repeat-vs-one-time segmentation from a seller's *own* data |
| **AgentZone** — agent identity + payment history explorer | Categorizing incoming payments by payer identity |
| Concentration-risk scoring (HHI, top-payer share, risk tier); **Crest** buyer profiling | Anything that answers "point this at my address" |

Everything shipped is an **outside-in, ecosystem-level** view. The inside-out seller view
is genuinely open. That is the wedge, and it is narrower than the earlier claim that
nobody could see this at all.

---

# P0 — Nothing else counts until these are done

### 1. Run the whole thing against real data, end to end
Task 9 has never been executed. Before any polish, `fetch → ingest → categorize →
customers → report` must be run against a real Base mainnet address and the output
inspected by a human. **Expect this to surface bugs no test caught** — every prior release
found defects only when the data changed shape.

### 2. `fetch --from DATE --to DATE`
Today `fetch` takes `--from-block 34000000`. A seller does not know their block numbers.
Resolve dates to blocks by binary search over `eth_getBlockByNumber` — roughly 20 lines
against the client that already exists. **This is the single biggest usability blocker**
and it is currently the step where a real user gives up.

### 3. RPC resilience
Public endpoints rate-limit and fail mid-scan. Needs: retry with backoff, resumable/
checkpointed fetch, progress output on long ranges, and support for a user's own provider
URL. A month of real data is a large scan and it *will* fail partway.

### 4. Decide what the product is
Right now the CLI ships two products and a research toolkit in one binary. `customers`
answers a live problem; `report` answers a problem that mostly hasn't arrived;
`evaluate`/`label`/`shape` are measurement machinery that will confuse a stranger.
**Recommendation: lead with `customers`, keep `report` as the second act, and move the
research commands behind a documented "how we validate this" section.**

### 5. The name
**"Ledger" is a major hardware-wallet company.** Publishing a crypto-adjacent tool under
that name is a trademark risk and makes the project unfindable. This needs deciding before
the repo is public — renaming after launch costs the stars and links.

---

# P1 — Required to publish credibly

### 6. Licence
None currently. MIT or Apache-2.0. Apache-2.0 if patent protection matters.

### 7. README for a stranger
The current one is a development log. A visitor needs: what it does in one sentence,
install, a 60-second demo that works with no wallet, one screenshot of real output, and an
honest limitations section.

### 8. Install story
Currently "clone the repo and run uv". Needs `uvx ledger ...` or `pipx install`, which
means publishing to PyPI or supporting a git install.

### 9. CI
GitHub Actions running the suite on push, on all three OSes. There is no automated check
that the branch is green today.

### 10. Python floor
Requires **3.13**, released Oct 2024. That excludes most users. Dropping to 3.11 costs
little and roughly triples the addressable install base — check what actually needs 3.13.

### 11. Cross-platform
Developed on Windows only. Terminal encoding already bit us once (an em-dash rendered as
`?`). Needs testing on macOS and Linux, and non-UTF-8 terminals handled.

### 12. Ship demo data
A stranger with no x402 address must be able to see output in 30 seconds.
`ledger simulate` already does this — it just needs to be the documented first step.

---

# P2 — Correctness and honesty issues that will get noticed

### 13. It cannot actually identify x402 payments
`fetch` pulls **all native USDC transfers**, not x402 ones. Distinguishing them needs the
`AuthorizationUsed` topic, a keccak256 the stdlib cannot compute. So "your x402 revenue"
is really "your USDC revenue". Options: pin the topic hash as a documented constant, add
~60 lines of pure-Python keccak, or state the limitation plainly. **Not fixing this while
claiming x402 support would be dishonest.**

### 14. The service axis is dark on chain data
"What they paid for" cannot work from chain data — EIP-3009 records no resource. Half the
two-axis story is unavailable on the primary data source. Either cut it from the pitch or
build seller-log ingestion (the old v0.3).

### 15. Money formatting
Renders `$437.914959`. Correct for sub-cent micropayments, noisy in a summary. Needs a
display rule that keeps precision where it matters and rounds where it doesn't.

### 16. Reject list is stdout-only
"Nothing silently dropped" currently depends on the user reading their terminal. Write it
next to `transactions.json`.

### 17. Privacy
Outputs contain real counterparty addresses. Needs a stated policy, a `--redact` option,
and a warning before anyone commits sample output to a public repo.

---

# P3 — Real-world usage gaps

18. **Incremental fetch** — re-running must not duplicate or re-scan from zero.
19. **Multiple receiver addresses** — a business may take payments to several.
20. **Multiple chains** — x402 also settles on Solana and Polygon; Base is hardcoded.
21. **Timezones** — reports are UTC; fiscal years are not.
22. **JSON output** — for anyone scripting against it.
23. **Accounting export** — CSV exists; QuickBooks/Xero shapes are what "reconciliation"
    actually means to the buyer.
24. **Performance at scale** — fine at 8,701 rows; unverified at 100k.
25. **Config file** — so the receiver address and RPC URL aren't retyped every run.
26. **Exit codes and `--help` polish** — for scripting and first impressions.

---

# P4 — Community scaffolding

27. `CONTRIBUTING.md`, issue and PR templates, `CODE_OF_CONDUCT.md`
28. `CHANGELOG.md` and tagged releases
29. `SECURITY.md` — it reads addresses and talks to RPCs
30. Publish the measurement docs as evidence — **this is the differentiator.** Pre-registered
    thresholds, B-cubed scoring, and a tool that has repeatedly proven itself wrong is a
    genuinely unusual thing to show in this ecosystem. Most tools assert; this one measures.

---

## Review pass — what I nearly missed

- **The name.** Caught late; it is arguably P0 and blocks the repo going public.
- **The x402-identification gap (#13).** Easy to gloss over, but it undermines the core
  claim if a knowledgeable reader spots it first.
- **The Python 3.13 floor (#10).** Silently excludes most of the install base.
- **Deciding what to cut (#4).** Shipping nine commands including research tooling makes a
  stranger's first impression "what is this?" rather than "oh, useful."
- **Cross-platform.** We have literally only ever run this on one machine.

## What I would not do

- Build v0.3 seller-side capture before validation. It is the architecturally correct next
  release and it is premature.
- Add a web UI. The CLI is the right surface for the first version.
- Add telemetry. Its absence is a selling point.

---

## Suggested sequence

**Phase 1 (P0):** real-data run → date-based fetch → RPC resilience → scope decision →
name. *Until Phase 1 is done, everything else is polish on an unvalidated foundation.*

**Phase 2 (P1):** licence, README, install, CI, Python floor, cross-platform, demo data.

**Phase 3 (P2):** the honesty issues — x402 identification, service-axis scope, formatting,
rejects, privacy.

**Phase 4 (P3/P4):** usage gaps and community scaffolding, driven by what real users hit.

**Ship after Phase 3.** Phase 4 is better done with issues filed by real users than guessed
at in advance.

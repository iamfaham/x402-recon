# What "production ready and open-sourceable" requires

**Date:** 2026-08-26
**Purpose:** the gap between where `x402-recon` is today and something that can be published
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

### 5. The name — RESOLVED
Was: "Ledger" collides with a major hardware-wallet company — trademark risk on a
crypto-adjacent tool, and unfindable. **Settled 2026-08-26 as `x402-recon`.** Repo renamed;
git remote updated.

Remaining mechanical work: rename the Python package and the typed CLI command (still
`ledger` internally), and claim the PyPI name. Note "recon" reads as *reconciliation* to
finance and *reconnaissance* to developers — both land, given a developer runs it and
finance reads the output.

### 6. One command, not six
**The pipeline is currently leaking into the UX.** Today a user runs:

```bash
uv run ledger fetch --receiver 0x… --out sample/real --from-block 34000000 --to-block 34100000
uv run ledger --db sample/real.db ingest --from sample/real
uv run ledger --db sample/real.db categorize
uv run ledger --db sample/real.db customers --from 2026-07-01 --to 2026-07-31
```

Four steps, a database path, and block numbers nobody knows. `fetch → ingest → categorize`
is *how it works*, not how it should be *used*. Target:

```bash
uvx x402-recon customers 0xYOURADDRESS --last 30d
```

The granular commands stay as escape hatches; they stop being the front door. This
subsumes P0 #2 (date-based fetch) — `--last 30d` needs the same date-to-block resolution.

### 7. `discover` — resolve a seller's address from their endpoint
An x402 server's 402 response carries a `PaymentRequired` object containing the accepted
schemes, price, network, and **destination address**. So a seller's receiving address is
discoverable by making one unpaid request to their endpoint.

```bash
uvx x402-recon customers --url https://x402.tavily.com/search --last 30d
```

Two consequences, one product and one strategic:

- **Product:** removes the chicken-and-egg of needing an address the user may not know.
  They know their own URL; they may not know their `payTo`.
- **Strategic:** it means **their report can be generated before they are contacted.**
  That is the "show them something working" opener, without needing their cooperation.

**Ethical line, and it is not optional.** This is public data — the address is advertised
in the seller's own 402 response — but the outreach must say so plainly. *"Here's what
public chain data shows about your service, generated with this open-source tool"* is a
strong opener. Anything implying privileged access is the fastest way to lose all three
conversations at once.

---

# How people actually use it — distribution

Ranked. The first is required; the second is the differentiator.

### CLI via `uvx` / `pipx` — primary
The users are developers at these companies. `uvx x402-recon …` runs with no install and
no clone. Requires the PyPI publish in P1 #10.

### MCP server — the differentiator
The targets are AI-agent infrastructure companies. OneSource ships an MCP server; these
are people who consume tools *through agents*. Exposing x402-recon over MCP means a
seller's own agent can answer "who were my repeat customers last month?" Nothing in the
competitive set does this, and it is unusually on-brand for this ecosystem. Worth
prototyping early — it may be a better wedge than the CLI.

### GitHub Action — recurring use
A scheduled monthly run producing a report artifact fits reconciliation's natural cadence
and costs little once the CLI exists.

### Hosted web — not now
Biggest reach, but it changes the privacy story (you would hold their addresses), and it
is a large lift. Revisit only after the CLI has real users.

---

# P1 — Required to publish credibly

### 8. Licence
None currently. MIT or Apache-2.0. Apache-2.0 if patent protection matters.

### 9. README for a stranger
The current one is a development log. A visitor needs: what it does in one sentence,
install, a 60-second demo that works with no wallet, one screenshot of real output, and an
honest limitations section.

### 10. Install story
Currently "clone the repo and run uv". Needs `uvx x402-recon ...` or `pipx install`, which
means publishing to PyPI or supporting a git install.

### 11. CI
GitHub Actions running the suite on push, on all three OSes. There is no automated check
that the branch is green today.

### 12. Python floor
Requires **3.13**, released Oct 2024. That excludes most users. Dropping to 3.11 costs
little and roughly triples the addressable install base — check what actually needs 3.13.

### 13. Cross-platform
Developed on Windows only. Terminal encoding already bit us once (an em-dash rendered as
`?`). Needs testing on macOS and Linux, and non-UTF-8 terminals handled.

### 14. Ship demo data
A stranger with no x402 address must be able to see output in 30 seconds.
`ledger simulate` already does this — it just needs to be the documented first step.

---

# P2 — Correctness and honesty issues that will get noticed

### 15. It cannot actually identify x402 payments
`fetch` pulls **all native USDC transfers**, not x402 ones. Distinguishing them needs the
`AuthorizationUsed` topic, a keccak256 the stdlib cannot compute. So "your x402 revenue"
is really "your USDC revenue". Options: pin the topic hash as a documented constant, add
~60 lines of pure-Python keccak, or state the limitation plainly. **Not fixing this while
claiming x402 support would be dishonest.**

### 16. The service axis is dark on chain data
"What they paid for" cannot work from chain data — EIP-3009 records no resource. Half the
two-axis story is unavailable on the primary data source. Either cut it from the pitch or
build seller-log ingestion (the old v0.3).

### 17. Money formatting
Renders `$437.914959`. Correct for sub-cent micropayments, noisy in a summary. Needs a
display rule that keeps precision where it matters and rounds where it doesn't.

### 18. Reject list is stdout-only
"Nothing silently dropped" currently depends on the user reading their terminal. Write it
next to `transactions.json`.

### 19. Privacy
Outputs contain real counterparty addresses. Needs a stated policy, a `--redact` option,
and a warning before anyone commits sample output to a public repo.

---

# P3 — Real-world usage gaps

20. **Incremental fetch** — re-running must not duplicate or re-scan from zero.
21. **Multiple receiver addresses** — a business may take payments to several.
22. **Multiple chains** — x402 also settles on Solana and Polygon; Base is hardcoded.
23. **Timezones** — reports are UTC; fiscal years are not.
24. **JSON output** — for anyone scripting against it.
25. **Accounting export** — CSV exists; QuickBooks/Xero shapes are what "reconciliation"
    actually means to the buyer.
26. **Performance at scale** — fine at 8,701 rows; unverified at 100k.
27. **Config file** — so the receiver address and RPC URL aren't retyped every run.
28. **Exit codes and `--help` polish** — for scripting and first impressions.

---

# P4 — Community scaffolding

29. `CONTRIBUTING.md`, issue and PR templates, `CODE_OF_CONDUCT.md`
30. `CHANGELOG.md` and tagged releases
31. `SECURITY.md` — it reads addresses and talks to RPCs
32. Publish the measurement docs as evidence — **this is the differentiator.** Pre-registered
    thresholds, B-cubed scoring, and a tool that has repeatedly proven itself wrong is a
    genuinely unusual thing to show in this ecosystem. Most tools assert; this one measures.

---

## Review pass — what I nearly missed

- **The name (#5).** Caught late; it blocked the repo going public. Now resolved.
- **The one-command UX (#6) and `discover` (#7).** Missing from the first draft entirely —
  added after being asked "how would people actually use it", which was the right question.
  `discover` in particular turned out to be the shortest path to the outreach goal.
- **The x402-identification gap (#15).** Easy to gloss over, but it undermines the core
  claim if a knowledgeable reader spots it first.
- **The Python 3.13 floor (#12).** Silently excludes most of the install base.
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

**Phase 1 (P0):** real-data run → `discover` → one-command UX (which subsumes date-based
fetch) → RPC resilience → scope decision. Name is settled. *Until Phase 1 is done,
everything else is polish on an unvalidated foundation.*

Note that `discover` + the one-command UX together are the shortest path to the outreach
goal: they are what let you generate Tavily's, Exa's and OneSource's reports before
emailing them. That is a materially shorter path than the full list.

**Phase 2 (P1):** licence, README, install, CI, Python floor, cross-platform, demo data.

**Phase 3 (P2):** the honesty issues — x402 identification, service-axis scope, formatting,
rejects, privacy.

**Phase 4 (P3/P4):** usage gaps and community scaffolding, driven by what real users hit.

**Ship after Phase 3.** Phase 4 is better done with issues filed by real users than guessed
at in advance.

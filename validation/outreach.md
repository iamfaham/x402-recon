# Validation outreach — Ledger

**Status:** ready to send. Rewritten 2026-08-25 after the market probe; supersedes the
2026-08-18 version, which was written before any data existed.

---

## What changed, in two paragraphs

The original list was seven companies inferred from the market landscape. We now have
**real published numbers**: the x402 Bazaar discovery API reports, per service, its call
count and unique-payer count over the last 30 days. That turns a guessed list into a
measured one, and it means every message below can open with the recipient's own figures.

It also changed what we're asking. The market is thinner than the brief assumed — roughly
$28k/day ecosystem-wide, down ~77% from its November 2025 peak, with an analyst estimate
that about **half of all activity is wash or self-dealing**. Reconciliation pain at scale
mostly hasn't arrived yet. But a second problem *has*: nobody can tell real customers from
directory probes, and the ratio that separates them (payments per payer) is something
Ledger already computes. So we're testing two hypotheses in one conversation, and the
second one is the live one. Full evidence in
[`market-reality-2026-08.md`](market-reality-2026-08.md).

## The two questions we're testing

1. **Reconciliation (the original bet).** Is the volume of small agent payments already
   painful to account for? *Prediction from the data: mostly no, not yet.*
2. **Signal quality (the new bet).** Do sellers know how much of their agent traffic is
   real repeat customers versus one-shot probes — and do they care? *Prediction: they
   can't see it, and the ones with real usage will care.*

A "no" on both is a genuinely useful answer and means shelving this. Say so in the log.

---

## Who to contact

Numbers are live from the Bazaar discovery API, retrieved 2026-08-24. **Contact channels
below need verifying before you send** — they're the obvious public routes, not confirmed
inboxes.

### Tier 1 — confirmed real repeat usage. Start here.

| Company | Calls/30d | Payers | Per payer | Why them |
|---|---:|---:|---:|---|
| **Tavily** | 8,701 | 249 | **34.9** | Highest absolute volume with a genuine repeat pattern. The single best-qualified target on the directory. Channel: tavily.com contact / X. |
| **Exa** | 3,575 | 89 | **40.2** | Highest repeat ratio of any service listed. Funded, real support channels, was already the top guess on the old list — now confirmed. Channel: exa.ai contact / X (@ExaAILabs). |

These two are the only services on the directory whose usage pattern looks like customers
rather than sampling. If neither has the pain, that is close to a decisive answer.

### Tier 2 — real but small. Good for a second data point.

| Company | Calls/30d | Payers | Per payer | Notes |
|---|---:|---:|---:|---|
| stableenrich | 816 | 78 | 10.5 | People-search API. Small operator, likely no finance tooling — closest to the "indie developer" case. |
| ottoai | 780 | 126 | 6.2 | Crypto news feed. Lower ratio; may be partly sampled. |

### Tier 3 — the probe-shaped one. Different conversation, possibly the most interesting.

| Company | Calls/30d | Payers | Per payer | Notes |
|---|---:|---:|---:|---|
| **OneSource** | ~15,244 across 25 endpoints | ~1,075 per endpoint | **1.0–1.2** | Largest raw volume on the directory, and almost certainly not commerce — every payer calls once and never returns. **They may not know this.** Telling them is genuinely valuable and is a strong, honest opener. |

### Tier 4 — from the original list, not on the Bazaar

Not visible in the discovery API, which means either they run their own facilitator or
they're not registered. Worth contacting only after Tier 1 responds, and the opener has to
be the old generic one since we have no numbers for them.

Apify · Nansen · JarvisClaw · Strale · Zinin M2M Hub · DwellData

### Not customers — but worth knowing about

**Daydreams** (8.1M+ transactions) and **Coinbase CDP** (7.6M+) are the two dominant
facilitators. They see every payment *including the resource identifier the chain never
records* — the exact data that would revive Ledger's service axis. They are infrastructure
partners or acquirers, not customers. Don't pitch them; if the seller conversations go
well, they're the next call.

---

## Message A — Tier 1 and 2 (leads with their numbers)

> **Subject:** 249 payers, 8,701 payments — how many came back?

Hi [name],

The x402 Bazaar publishes per-service call and payer counts, and [Tavily]'s stood out:
roughly **8,701 payments from 249 distinct payers** over the last 30 days. That's ~35
payments per payer — one of the highest repeat ratios on the entire directory. Most
services sit near 1.0, meaning every payer calls once and never comes back.

I've been digging into agent payment data and that ratio turns out to separate real usage
from directory probing almost perfectly. Which raises a question I can't answer from
outside:

**Of those 249 payers, do you know how many came back versus tried once and vanished?**
And is that something you can see today, or would you have to go digging for it?

Also curious, separately: as the payment count grows, is reconciling those line items for
your own books something you've solved, something you eyeball, or something you haven't
got to yet?

No pitch — I'm trying to work out whether this is a real problem or one I've invented.
Happy to send back what I've found across the rest of the directory either way; some of it
is unflattering to the ecosystem.

— [Your name]

*Swap in the right figures per company: Exa is 3,575 payments from 89 payers, ~40 per
payer, the highest ratio on the directory.*

## Message B — OneSource (the probe-shaped one)

> **Subject:** ~99% of your x402 payers appear exactly once

Hi [name],

I've been analysing public x402 Bazaar data and OneSource has the highest raw call volume
on the directory — around 15,000 across your endpoints in 30 days. But the pattern is
unusual and I wanted to flag it in case it's useful.

On your individual endpoints the call count and the *unique payer* count are almost
identical — e.g. 1,078 calls from 1,075 distinct payers. Effectively **every payer calls
once and never returns.** For comparison, the services with genuine repeat usage sit at
35–40 calls per payer.

That pattern usually means directory probing or automated sampling rather than customer
usage. It doesn't make the volume fake, but it does mean the headline number probably
isn't demand — and if you're reporting that figure anywhere, it's worth knowing.

Two questions if you have a minute: **is that what you'd expect?** And can you currently
see the repeat-versus-one-shot split in your own data, or is it not broken out anywhere?

No pitch. Happy to share the full directory comparison.

— [Your name]

## Message C — Tier 4 (no numbers available)

> **Subject:** Quick question about your agent payment records

Hi — I saw [Company] accepts x402/stablecoin payments for [product]. I'm researching the
accounting side of agent-to-agent payments and wanted to ask two no-pitch questions:

**How do you track these payments for your own records** — who paid, how much, how it
rolls up for revenue? Solved, eyeballed, or not got to yet?

And: **do you know how many of your agent payers are repeat customers versus one-time?**
Across the public directory that ratio varies from 1.0 to 40, and it's the clearest signal
I've found for separating real usage from automated probing — but most services don't seem
to have it broken out.

Genuinely just trying to understand the real pain before building anything. Happy to share
what I learn back.

— [Your name]

---

## If they ask what you've built

[`demo/customers-demo.md`](../demo/customers-demo.md) renders both profiles side by side —
a real service and a probe-shaped one. **Be upfront that the payment amounts and the
within-service repeat split are modelled**; only the call and payer counts are real. That
honesty is the point: the exact split is precisely the number they could tell you in one
query against their own data, which is a good reason for them to reply.

## What to listen for, and what each answer means

| Response | Reading | Action |
|---|---|---|
| "We can't see the repeat split" + "that's interesting" | **Strongest possible outcome.** Live problem, no incumbent. | Ask what they'd do with it. Push for a data sample. |
| "We already track that in [tool]" | Solved for them; ask what's still annoying and whether smaller sellers have it. | Note the tool. It's the competitor. |
| "Reconciliation is a mess" | Validates hypothesis 1 after all — against the market data's prediction. | Get specifics: how many line items, how long it takes, who does it. |
| "Not enough volume to matter" | Confirms the market read. | Ask what volume *would* make it matter, and when they expect it. |
| Silence from all of Tier 1 | Two best-qualified targets don't care enough to reply. | That's data. Log it and shelve per the boundary. |

## Log responses here

Append below as replies come in — date, company, channel, verbatim quote where possible.
The point is that a later reader can see what was actually said rather than a summary of
how it felt.

*(no responses yet)*

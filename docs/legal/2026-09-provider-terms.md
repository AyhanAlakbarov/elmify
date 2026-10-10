# Provider terms on file — search, fetch and classification vendors

Read on the cited hosts on the dates given. Re-read before relying on any clause; a
vendor's terms page is not under our version control. Owner correspondence (Exa and Brave
written permissions, 2026-09-17) is held outside this repository; this file records what it
grants and its condition.

## Exa (Exa Labs, Inc.) — read 2026-09-22

- Terms of Service (PDF at `exa.ai/assets/Exa_Labs_Terms_of_Service.pdf`), **§1.2(c)**: "You grant
  us a nonexclusive, royalty-free, transferable, sub-licensable, worldwide, perpetual and
  irrevocable license to access, use, host, cache, store, reproduce, transmit, display, publish,
  distribute, and modify any User Input and Output as needed to provide, develop, and improve upon
  our products and services." **Consequence:** every query is profile-free
  (`research_fit.anchors.guard_phrase`, tested).
- **§4.2(a)/(f)** (no reproduction of information obtained through the Services; no use of Output
  to develop a competitive product) — superseded by the owner's written permission of 2026-09-17,
  condition: **no training of a competing search model on Exa output.** Not done anywhere.
- Privacy policy (`exa.ai/privacy-policy`): query data used "to improve Exa's products and
  technology, including by training and fine-tuning models"; "query fields are not intended for
  the submission of personal information." Zero-data-retention exists (`exa.ai/blog/zdr-search-engine`)
  and is not relied on.
- DPA (`exa.ai/dpa`): incorporated into the ToS for business customers; Exa is processor; EU SCCs
  Module 2 + UK Addendum (§14); sub-processors at `docs.exa.ai/reference/security` (§9); Annex 1:
  personal data in User Input "as determined by Customer", no special-category data intended.
  With profile-free queries no personal data is sent.

## Tavily — recorded 2026-08-30 / 2026-09-17 (roster §8)

- **§9.2** takes a perpetual licence over query text → profile-free queries (same guard).
- Retention of Output permitted by structure ("Services" excludes "Output").
- **§3.2(xvi)** (automated decisions in high-risk areas) — open legal question, recorded in
  `CLAUDE.md`; research fit does not decide anything about a person, it proposes a sentence a
  counselor and the student can strike.

## TypeSafe (Jev) — read 2026-09-22

- Master Customer Agreement (`typesafe.ai/legal/mca`): **§4.1** processing licence for the term only,
  "does not grant TypeSafe the right to … include Customer Data in a dataset used to train any
  artificial intelligence or machine learning models without Customer's prior consent"; **§4.2**
  TypeSafe disclaims ownership of Output and assigns it to Customer; **§2.3** no distillation, no
  training a model to imitate the Services; **§16.2** California law, San Francisco venue.
- Privacy policy (`typesafe.ai/legal/privacy-policy`): "We will not train or fine tune any
  artificial intelligence or machine learning models on your prompts or other Input"; "We will not
  disclose any Input to a third party other than our service providers"; hosted in the United
  States; no concrete retention period.
- DPA (`typesafe.ai/legal/data-processing`): Customer controller, TypeSafe processor (§1.1); EU
  SCCs Modules 2/3 (§6.2), UK IDTA (§6.3); sub-processors at `trust.typesafe.ai/subprocessors`
  with a 15-day objection window (§3.1); retention "as long as necessary" (Schedule I §8).
- ~~**Status:** candidate only. No real student text reaches Jev until this DPA is countersigned or
  accepted through the account and the sub-processor list has been read once. The live gate uses
  synthetic anchors.~~ *Superseded 2026-10-04 by the owner decision below; kept as the record of
  the earlier position.*
- **Owner decision, 2026-10-04:** "we operate in Azerbaijan; you can send to TypeSafe (using
  OpenRouter)". Student mail **may** reach Jev through OpenRouter from now on, for the mail
  decision reader (`apps/mailbox/decision_reader.py`, student-dashboard spec §4). **Mitigation,
  enforced in code before every request:** the student's own name words (account name and CV
  identity facts, `apps/documents/transcript.py::personal_names`), every email address and every
  phone number are replaced with placeholders, and a test proves a seeded name and address never
  reach the request payload. Requests use `record=False`, so no student text lands in the shared
  `DecisionRecord` table. The DPA countersignature and the sub-processor read named in the struck
  line above remain open items, now as follow-ups rather than as a gate.

## Open-data enumerators (build item 7) — recorded 2026-09-26, NOT re-read on the host

These are data sources under open terms, not vendors, and persisting what they return is
permitted (`CLAUDE.md`, "do not carry either rule onto the other"). **The three pages below
were not opened on 2026-09-26**: egress to every one of these hosts was blocked from the
environment that wrote the adapters. What follows is carried from
`docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md` §6.2 and the
2026-09-14 EMJM partner design; re-read each page before the first live run.

- **Wikidata** — data CC0 (`https://www.wikidata.org/wiki/Wikidata:Licensing`). The Wikimedia
  User-Agent policy (`https://meta.wikimedia.org/wiki/User-Agent_policy`) requires a contact in
  the User-Agent, which is why `WIKIDATA_USER_AGENT` carries the repository URL.
- **ROR** — data CC0 (`https://ror.org/about/faqs/#what-is-the-license-for-ror-data`). A
  client id sent as `Client-Id` is optional and identifies heavy clients (`ROR_CLIENT_ID`,
  blank sends none).
- **EACEA project API** (`POST https://ec.europa.eu/programmes/service/search/project/search`)
  — the Europa reuse notice (`https://commission.europa.eu/legal-notice_en`); the platform's
  Terms of Use govern uploading, not retrieval (09-14 design §2.2).

## Diffbot Knowledge Graph Enhance (build item 8) — NOT re-read, 2026-09-26

The resolver's residue rung (`apps/research/providers/diffbot.py`). **The terms page
(`https://www.diffbot.com/company/terms/`) was not opened on 2026-09-26**: the environment that
built the adapter had no egress and no token. The position on file is still the 2026-09-17 read
(`docs/superpowers/research/2026-09-17-diffbot-perplexity-recon.md` §1): an explicit grant to
"display and use the facts generated by the Service as part of a commercial application", no
storage, derivative or training clause, and **no effective date** — so a read from memory is no
read. Therefore:

- `DIFFBOT_TERMS_READ_ON` is unset, and `resolve_register --diffbot` and `resolver_gate
  --diffbot` both refuse until it names a read within 31 days (and not in the future).
- Whoever runs either first reads the page, quotes any change here with the date, and sets the
  variable. Nothing in this repository records a 2026-09-26 read, because none happened.
- Only the entity's `homepageUri` is read; the request is pinned to `type=Organization` (the
  Knowledge Graph holds people, and "the rights of any person" is the clause that would bite).
  No confidence, category or name is kept on any row.

## What none of these change

Provenance comes from the origin, never the provider: a provider yields a URL and a billed cost;
the institution's page is fetched, split by code, and verified. Nothing from a provider response
is persisted.

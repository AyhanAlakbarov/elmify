# Exa `category: company` with client-side exclusion — re-measured 2026-09-27

Plan Task 1 (`docs/superpowers/plans/2026-09-25-sweep-harness.md`), run once with owner approval
of the spend. **Result: not adopted.** `ExaProvider` keeps sending no `category`.

## Setup

- The plan's Task 1 Step 2 script, unchanged: six Turkish page-voiced foundation angles, each
  asked twice at `numResults: 15` — once `type: auto` with `excludeDomains` = the aggregator
  denylist (arm `auto`), once with `category: company` and no `excludeDomains` (arm `company`),
  because Exa rejects the two together. The denylist was applied client side to both arms.
- Recapture set: the local database `tehsil_ladder_tr` (item 6a's run), which holds 4,028 `vgm_tr`
  register rows. "Held" means any registrable domain already in `OrganisationDomain`.
- Billed cost, read from each response's `costDollars.total`: **$0.072 per arm, $0.144 total**.

## Counts

| arm | domains | VGM recaptured | held | novel | denied client side |
|---|---|---|---|---|---|
| `auto` | 57 | 25 | 25 | 32 | 0 |
| `company` | 36 | 19 | 19 | 17 | 0 |

## Labels of the novel domains

Labelled by the executing session from the domain name and general knowledge, **not by visiting
each page** — a person should re-check the "unclear" rows before anyone cites a per-row figure.

**`auto` (32 novel)**
- foundation (12): altug.org.tr, bastuzelvakfi.org, bereketvakfi.org.tr, cenanvakfi.org, gaev.org,
  ibtav.org, imdatvakfi.org, iuvakiflari.org, kumevakfi.org, mesvak.org.tr, turgev.org,
  yasarvakfi.org.tr (altug and gaev by name only)
- government (6): meb.gov.tr, mevzuat.gov.tr, ttk.gov.tr, tubitak.gov.tr, yok.gov.tr, ytb.gov.tr
- university (2): itu.edu.tr, yildiz.edu.tr
- noise (12): aa.com.tr, bilimsenligi.com, egeetkinlik.com, eleman.net, gazipasamanset.com.tr,
  guncel-egitim.org, lexpera.com.tr, memurlar.net, ogrenciburs.org, ogrenciislerim.com,
  ogrencikariyeri.com, revotas.com — **noise share 12/32 = 38%**

**`company` (17 novel)**
- foundation (5): anadoluvakfi.org.tr, hagev.org, husnuozyeginvakfi.org.tr, rev.org.tr, tauv.org.tr
- alumni association (1): odtumd.org.tr
- unclear (2): bura.org.tr, gencburda.org
- government (1): turkiyeburslari.gov.tr
- university (4): hacibayram.edu.tr, ieu.edu.tr, itu.edu.tr, sabanciuniv.edu
- noise (4): bursverenler.org, euburs.eu, linktr.ee, tdavyayinlari.com — **noise share 4/17 = 24%**

## Decision

The rule, stated in the plan before the run: *`category: company` is adopted only if it returns at
least as many VGM-recaptured domains **and** at least as many novel foundations as `auto`, with no
higher noise share.*

- VGM recaptured: 19 < 25 — fails.
- Novel foundations: 5 (at most 8 counting the alumni body and both unclear rows) < 12 — fails.
- Noise share: 24% < 38% — passes, but the rule needs all three.

**Not adopted.** This agrees with the 2026-09-17 measurement (−2.7 points on the German key).

## Worth knowing, not a decision

The two arms barely overlap: 16 of `company`'s 17 novel domains are absent from `auto`'s 32,
including four foundations. On one cell and six angles this is one run, not a finding; if a later
per-angle tally keeps showing `company` contributing hosts `auto` misses, running it as a second
arm (not a replacement) is the question to measure then.

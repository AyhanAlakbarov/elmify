# Reconnaissance — the United States, the gap nobody noticed

**Date:** 2026-08-31. **Status: NOT a research run.** Fourth and last in the register series.

**Why this exists.** Neither research run examined the United States, neither did the four register
recons, and it was not on the follow-up list of five countries either. It surfaced only when the
question "is anything left?" was asked directly. The screen currently sees **4 US institutions out of
286 listed in DEQAR**, against a real sector of roughly six thousand.

**The result is the largest single finding of the whole programme, and it is not the accreditation
register.** The US Department of Education publishes **selectivity, price, accreditor and graduate
earnings for every institution, in one free file with no key** — the exact combination
`2026-08-31-screen-coverage-measurement.md` §7 said no register anywhere provides.

> **Qualified 2026-08-31 by `2026-08-31-register-open-questions-closed.md` §6.** The price half does
> **not** hold for master's applicants: Scorecard's tuition fields are undergraduate, and the
> field-of-study file carries debt and earnings by credential level but no price at all. For our
> population the US supplies selectivity, accreditor and outcomes — not cost. Read §5's last bullet
> as answered, negatively.

---

## 1. College Scorecard — the register that answers the other half of the brief

`collegescorecard.ed.gov/data/` → `ed-public-download.scorecard.network`. **No authentication, no
API key, no terms gate.** (The companion REST API at `api.data.gov/ed/collegescorecard/v1` returns
**403** without a key; the bulk files do not need one, so the key is avoidable.)

- **`Most-Recent-Cohorts-Institution.zip`** — HTTP 200, **23,559,465 bytes**, downloaded in **3.1 s**.
  `Last-Modified: Tue, 09 Jun 2026`.
- Unpacked: **`Most-Recent-Cohorts-Institution.csv`, 100,102,932 bytes, 6,273 institutions,
  3,308 columns.**
- Sibling files exist for field-of-study level data and the full raw historical set.

**The columns that matter to this brief**, all present and measured:

| column | what it is | coverage |
|---|---|---|
| `ADM_RATE` | **admission rate** | **1,910 of 6,273** usable |
| `TUITIONFEE_OUT` | out-of-state tuition (the rate an international student pays) | present |
| `TUITIONFEE_IN`, `COSTT4_A` | in-state tuition, average annual total cost | present |
| `ACCREDAGENCY` | **the institution's accreditor, by name** | **6,273 of 6,273** |
| `CONTROL` | public / private nonprofit / for-profit | 2,047 / 1,901 / **2,325** |
| `HIGHDEG` | highest degree awarded — **1,982 award graduate degrees** | present |
| `CURROPER` | currently operating — 6,243 of 6,273 | present |
| `MD_EARN_WNE_P10` | median earnings ten years after entry | present |
| `SAT_AVG`, `UGDS`, `DISTANCEONLY`, `OPEID`, `UNITID` | | present |

**Measured on the admission-rate column — this is the brief's population, published:**

- median admission rate **0.779**
- **882 institutions admit 80% or more**
- **127 institutions admit essentially everyone (≥99.9%)**

The brief asked for institutions that are genuinely low-selectivity, affordable and safe, and said the
hard part was that nobody publishes selectivity. **The United States publishes it, with the price
next to it, for free.** No other country examined in this series does.

**Two cautions.**

- **`ADM_RATE` is blank or suppressed for 4,363 of 6,273 rows** — an initial count of "all rows
  populated" was wrong and was corrected by filtering the sentinel values properly. Open-enrolment
  institutions frequently report no rate *because* they admit everyone, so **a missing admission rate
  is not evidence of selectivity**, and in this file it is weakly correlated with the opposite.
  Never infer selectivity from absence here.
- **2,325 of 6,273 institutions are for-profit** — larger than either the public or the private
  nonprofit sector. `CONTROL` is therefore the single most important field in the file for our
  purposes, and the same lesson CRICOS taught in Australia: presence in a national dataset is not a
  quality signal, and the provider category is.

## 2. SEVP — reachable, and the 403 was the client again

`ice.gov/sevis/schools` returns **403 to plain `curl` and 200 to a browser transport** — the third
government host in this series to do so, after Japan's ISA and (for a different reason) KHDA.

The certified-school list itself lives at **`studyinthestates.dhs.gov/school-search`**, which also
403s to plain `curl`. SEVP certification is the US equivalent of the UK sponsor licence and Canada's
DLI designation: a school must hold it to enrol F and M visa students, and `8 CFR 214.4` governs
denial and withdrawal of that certification.

**Not yet extracted.** The search interface was located but its underlying data route was not
probed, and no bulk export was found. Treat as "reachable, format unknown".

## 3. DAPIP — located, endpoints not enumerated

`ope.ed.gov/dapip/` is an Angular application over an API at
**`surveys.ope.ed.gov/dapip/api/`**. Guessed routes return well-formed JSON 404s — *"No HTTP resource
was found that matches the request URI"* — which, unlike anabin, means **guessing is safe here: a 404
is a real 404.**

Its data model is visible in the client bundle and is richer than a flat list: institutions carry
`ActiveStatus`, `ClosedDate`, `MergedInto`, `Alias` and `PublicNotes`; accrediting agencies carry
`IsTitleIVGateKeeper`, `RecognitionYear` and `ClosedDate`; accreditation actions carry
`AccreditationDate`, `AccreditationEndDate` and `EndingActionId`. **That is closure and merger
history at institution level** — the same thing Australia's monthly snapshots give by brute force,
here as first-class fields.

The site offers CSV and Excel downloads from a data-files page. **Exact download URLs were not
captured**; that is the one remaining fetch.

## 4. What the US changes about the design

1. **The "no register holds price or selectivity" rule is not universal — it is a rule about
   *everywhere except the United States*.** The screen's data model must allow a country to supply
   admission rate and cost directly, rather than assuming those always come from scraping programme
   pages. Designing for the scraping path only would throw away the best dataset available.
2. **`ACCREDAGENCY` is a name string, not an identifier**, and it is populated for all 6,273 rows.
   Joining it to the recognised-accreditor list is a name-matching problem — the same one Korea's
   uppercase institution names pose, and the one DEQAR's ROR column solves in Europe. **Identity
   resolution is now a confirmed cross-cutting requirement, not a European detail.**
3. **Three of the four US-relevant sources needed a browser transport or a key.** A plain `curl` from
   a worker reaches College Scorecard and nothing else. That belongs in the fetch layer's design, not
   discovered per-source later.

## 5. Not established here

- **SEVP's data route or bulk export**, if one exists.
- **DAPIP's download URLs and API route names.**
- **College Scorecard's licence.** US federal works are ordinarily public domain, but the page was
  not read for an explicit statement — do not assume.
- **Whether Scorecard covers graduate tuition.** `TUITIONFEE_OUT` is an undergraduate field; our
  students are master's applicants, and `HIGHDEG=4` identifies the 1,982 institutions awarding
  graduate degrees but not what they charge for it. **This is the important open question** — the
  file may answer the selectivity half brilliantly and the price half not at all for our population.

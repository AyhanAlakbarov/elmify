# Fulbright per-country terms — nine national competitions, verified individually

**Date:** 2026-08-29. **Closes** open item 5 of `2026-08-29-nationality-keyed-synthesis.md` §9.

**Method:** each country's own competition page, fetched directly. Eight of nine are run by the US
embassy in-country; Türkiye is run by a binational commission.

**A trap worth recording.** `us.fulbrightonline.org/countries/...` ranks highly for these queries and
is the **wrong programme** — it is the US Student Program, for Americans going abroad. The
inbound-to-USA competition our students enter is the **Foreign** Student Program, run by the embassy
or commission. A run that reads the `us.` pages will describe a programme our population cannot enter.
`az.usembassy.gov` and friends also block a plain `curl`; they answer to ordinary browser headers.

---

## 1. Per-country table

All are **master's degree** grants — none of the nine is research-only or FLTA-only, which answers the
question the open item posed. Cycle is 2027-28 unless noted.

| Country | Degree & duration | Deadline | Work experience required | Source |
|---|---|---|---|---|
| **Azerbaijan** | Master's, "one year or longer" | **28 Jul 2026**, 23:59 | **Minimum 2 years professional** | az.usembassy.gov |
| **Armenia** | Master's — **"funded for one year"** | not on page | not stated on page | am.usembassy.gov |
| **Georgia** | Master's, "full financial support" | **1 Jul 2026** | not stated in page text | ge.usembassy.gov |
| **Kazakhstan** | Master's | **15 Jul 2026**, 00:00 Astana | **At least 2 years substantive, after graduation** | kz.usembassy.gov |
| **Kyrgyzstan** | Master's, stipend up to 24 months | **10 Jun 2026**, 17:00 Bishkek | **None stated** | kg.usembassy.gov |
| **Tajikistan** | Master's, "up to two years" (AY 2026-27) | not in page text | not stated | tj.usembassy.gov |
| **Turkmenistan** | Master's, one or two years | **31 May 2026** | **At least 2 years full-time post-graduate** | tm.usembassy.gov |
| **Uzbekistan** | Master's | **30 Jun 2026** | **Minimum 2 years professional** | uz.usembassy.gov |
| **Türkiye** | Master's, **max 2 academic years** | **10 Apr 2026**, 23:59 | **Only for MBA/business: 1 yr full-time** | fulbright.org.tr/burs/3 |

## 2. The finding that generalises: every Fulbright award is bonded, by visa law

Georgia states the mechanism plainly:

> "Applicants must be eligible for the **J-1 visa, which requires the grantee to return to Georgia for
> a minimum of two years** at the end of the grant period"

Kyrgyzstan states the obligation twice:

> "All grantees are **expected to return to their home countries for at least two years** at the
> conclusion of their grant **in compliance with the J-visa requirements**."

**This is §212(e) of the US Immigration and Nationality Act, not a Fulbright policy.** It attaches to
the visa class, so it binds **every** Fulbright grantee in all nine countries — including the pages
that never mention it. A student reading Azerbaijan's page would not learn they are accepting a
two-year home-residency obligation.

**This is a modelling gap, and a different shape from the one we built.** `RETURN_SERVICE` was
designed as a *funder* obligation — ADB-JSP, Bolashak, YLSY bind you because the funder says so. Here
the obligation comes from the **destination's visa regime** and would attach to any J-1-sponsored
award, not only Fulbright. Modelling it per-scheme means restating it on every J-1 scheme and missing
it wherever a page stays silent.

It belongs on `DestinationPolicy` — the same object §8.3 already needs for visa lead time — keyed to
the visa class the award routes through, with the scheme-level `RETURN_SERVICE` reserved for
obligations the funder itself imposes. A student can then be told once, correctly, for any J-1 award.

## 3. The work-experience bar varies by country, and that is the point

Four of nine state a **two-year post-graduation professional experience requirement**: Azerbaijan,
Kazakhstan ("substantive… after university graduation"), Turkmenistan ("full-time, post-graduate"),
Uzbekistan. **Kyrgyzstan's page states none** and lists no equivalent. Georgia, Armenia and Tajikistan
do not state one in their page text.

**A single "Fulbright requires two years' experience" encoding would be wrong for at least one of the
nine, and unsourced for three more.** This is precisely why the open item asked for the nine
competitions individually, and it vindicates the `APPLICANT_CONDITION` design decision to attach
conditions per route rather than per family.

Absence of a stated requirement is **not** evidence of absence — three pages are thin. Recorded as
"not stated on the page read", never as "no requirement".

## 4. Other per-country conditions found

- **Azerbaijan** — priority fields named explicitly (STEM, agriculture, education, economic
  development, public administration and policy, public health, social work, urban planning, tourism,
  law); clinical fields excluded; TOEFL iBT 90 / IELTS 7.0 minimum; dual AZ/US citizens and US
  permanent residents ineligible; must reside in Azerbaijan.
- **Kyrgyzstan** — holders of a US master's are ineligible; alumni of US-government long-term
  exchanges (FLEX, Global UGRAD, Muskie, Fulbright, Humphrey) considered only after candidates without
  such experience; **"An applicant's financial need or status is not a factor in the selection
  process"** — a direct contrast with ADB-JSP's means test.
- **Turkmenistan** — "AI-generated or plagiarized essays (whether fully or partially) will be
  disqualified"; relatives of embassy staff ineligible.
- **Tajikistan** — names especially competitive fields: business and entrepreneurship, critical
  mineral management and mining, public policy and administration, law enforcement.
- **Georgia** — a writing sample is mandatory for a named list of master's fields (anthropology,
  archaeology, area studies, art history, biology…).
- **Common** — nearly all use the same portal, `apply.iie.org/ffsp2027`, and IIE performs university
  placement. Nominees do not choose their university: Kyrgyzstan states nominees "are only informed of
  the final choice." That makes the destination **unknown at application time**, which the portfolio
  model assumes is known.

## 5. Türkiye and Armenia, resolved

### Türkiye — the fullest terms of the nine, and it settles §2

Retrieved through the browser path; the tabs are JS-loaded and invisible to a plain GET. The
commission states the funder/visa distinction **explicitly**, in the exact terms §2 argues for:

> "Alınan bursun karşılığında herhangi bir **zorunlu hizmet bulunmamakla beraber**, bursiyerin ABD'deki
> öğrenimini tamamladıktan sonra ABD **J-1 Vizesi kuralı gereği** Türkiye'ye dönme ve iki yıl kalma
> **zorunluluğu vardır**."
>
> *"While there is **no mandatory service** in return for the scholarship, the scholar is **obliged**,
> **by rule of the US J-1 visa**, to return to Türkiye and remain two years."*

A funder saying "we impose no service obligation, but the visa does" is the cleanest possible evidence
that these are two different things and must be modelled separately.

Other terms, all published:

- **Deadline 10 April 2026**, 23:59, for AY 2027-28 Fall entry. Deferral is explicitly impossible.
- **Coverage capped at USD 60,000 per academic year** — tuition and fees, a city-indexed monthly living
  allowance, USD 1,000 books, USD 350 settling-in, ~USD 2,000 return airfare; ASPE health insurance is
  separate and additional. **"If your tuition and living costs exceed USD 60,000, you must cover the
  remainder yourself."** A *capped* award, not a full-cost one — the residual is the student's, and an
  affordability model that treats it as full coverage is wrong at exactly the expensive institutions.
- **Duration**: year one 9–12 months; a renewable second year of at most 9 months, **conditional on
  first-year academic performance**. Three-year programmes are funded for two; the third is the
  student's. So the award is *conditionally* renewable, not granted for the full degree.
- **Published minimum grade: 3.00/4.00 or 76.66/100**, applied at application *and* at graduation —
  a hard, quotable bar of the kind the corridor sweep found is usually unpublished.
- English: TOEFL iBT 75, IELTS Academic 6, PTE 60, METU IYS 75, Boğaziçi BÜYES C.
- **Work experience is field-scoped**, not scheme-wide: at least 1 year full-time, *only* for MBA and
  business sub-fields (accounting, finance, marketing, logistics, international trade, engineering
  management). No general requirement — which is why a family-level encoding fails here too.
- **No upper age limit**, stated explicitly. Final-year undergraduates may apply.
- Ineligible: US citizens, green-card holders or anyone who has begun that process; anyone resident,
  working or studying in the US during selection; anyone resident in the US for 5+ years of the last 6;
  clinical sub-fields of medicine, dentistry, veterinary science and psychology; Turkish law graduates
  seeking a JD (LLM only).
- **No per-field quotas.** Placement runs through IIE *or* by the candidate's own applications — two
  routes, unlike Kyrgyzstan's IIE-only rule.

### Armenia — the linked flyer is three cycles stale

The PDF the page links is the **2024-25** flyer with a **9 June 2023** deadline, still served from the
live page today. Treat the page as unmaintained and the terms below as indicative, not current.

It does confirm the "**funded for one year**" wording, lists priority fields (economic development,
education administration, international relations, journalism and communication, law, public policy
and administration, environmental studies, public health policy and management), and states **no work
experience requirement**.

**It also names a condition our taxonomy has no slot for:**

> "• **Completed or deferred your military service**"

That is neither work experience, age, means, nor affiliation — it is a **legal/civic status**
condition, and it will recur across conscription states, Türkiye and Armenia most obviously. Recorded
as a candidate fifth `ApplicantConditionType`; not added to code on the strength of one stale flyer.

## 6. Still open on Fulbright

- **Armenia's current cycle** — the live flyer is stale; the real 2027-28 terms are not published on a
  page we have found. Ask the embassy or wait for the flyer to be replaced.
- **Georgia, Tajikistan** — no work-experience statement found in page text; confirm from their
  application instructions before encoding either way.
- **Tajikistan's deadline** — not stated in the page text retrieved.
- How a pack should represent a funded award whose **destination is not yet known** — Kyrgyzstan places
  through IIE only and nominees "are only informed of the final choice", while Türkiye permits
  self-placement. The portfolio model assumes a known destination.

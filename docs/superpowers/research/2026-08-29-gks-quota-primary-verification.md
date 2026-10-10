# GKS per-country quota — verified against the NIIED guideline

**Date:** 2026-08-29. **Closes** open item 2 of `2026-08-29-nationality-keyed-synthesis.md` §9.

**Source:** *2026 GKS-G Application Guidelines (English)*, NIIED, §3 PROGRAM QUOTA (pp. 5–7).
Retrieved as PDF and parsed with `pdftotext -layout`.

**Source caveat, stated plainly.** The copy read was the one hosted by the **Korean Education Centre
in the UK** (`koreaneducentreinuk.org/wp-content/uploads/2026/02/2026-GKS-G-Application-Guidelines-English.pdf`),
an official Korean government education centre abroad, not `studyinkorea.go.kr` itself — that host was
found browser-required and partly 404 by the 2026-08-27 probe. This is the same document, on an
official host, but it is a **mirror**. Identical PDFs were also found on `uakoreaedu.org` and on Ewha
Womans University; aggregator copies (`kgspscholarship.com`, `scholarshipscorner.website`) were
deliberately not used. If the numbers ever become load-bearing for a published claim, read NIIED's own
copy through the browser path.

---

## 1. The compiled figures were right

The synthesis flagged its GKS numbers as coming from "a compilation of the official 2026 NIIED
guideline" rather than the guideline itself, and told the reader to verify before encoding. **Verified.
Every figure it cited checks out** against the primary document:

| synthesis claim | primary document | verdict |
|---|---|---|
| Kazakhstan and Uzbekistan, 13 Embassy each | Kazakhstan 13, Uzbekistan 13 | ✅ |
| Armenia 2 | Armenia 2 | ✅ |
| Kazakhstan R-GKS 18 | Kazakhstan R-GKS 18 | ✅ |

No correction needed. The caution was still correct to record — the numbers being right this time does
not make a compilation a source.

## 2. Embassy Track — General

**"776 scholars from 143 countries or regions."** Our nine, verbatim from the table:

| Country | Quota | | Country | Quota |
|---|---|---|---|---|
| Armenia | 2 | | Tajikistan | 5 |
| Azerbaijan | 5 | | Turkmenistan | 7 |
| Georgia | 4 | | Türkiye (Turkiye) | 11 |
| Kazakhstan | 13 | | Uzbekistan | 13 |
| Kyrgyzstan | 9 | | **Nine-country total** | **69** |

A footnote on the same page qualifies every one of these:

> "Depending on local circumstances, the Korean embassy in the inviting country may choose not to
> recommend a candidate."

**So the quota is a ceiling, not a commitment**, and the embassy may decline to fill it. A denominator
built from these numbers is an upper bound on places, not a guaranteed count — which matters for the
band ladder in spec §4.2, where a per-nationality quota is preferred over a global rate precisely
because it is meant to be a better denominator.

## 3. University Track — General and R-GKS

**"General: 160 scholars from 54 countries / R-GKS: 480 scholars from 56 countries or regions."**

| Country | General | R-GKS | Total |
|---|---|---|---|
| Armenia | 1 | 1 | 2 |
| Azerbaijan | 2 | 1 | 3 |
| Georgia | 1 | 1 | 2 |
| Kazakhstan | 5 | 18 | 23 |
| Kyrgyzstan | 7 | 3 | 10 |
| Tajikistan | 2 | 2 | 4 |
| Turkmenistan | — | 3 | 3 |
| Türkiye | 2 | 5 | 7 |
| Uzbekistan | 6 | 6 | 12 |

Turkmenistan's General cell is an em-dash, not a zero: **R-GKS only**. Encoding it as 0 and encoding
it as "not offered on this track" are different claims, and the document says the latter.

## 4. NEW — an Overseas Korean/Adoptee track neither prior run found

The same section carries a third, small table that no run in this programme has mentioned:

> **"◈ Overseas Korean/Adoptee: 24 scholars from 8 countries"**

| Country | Quota |
|---|---|
| Canada | 1 |
| Cuba | 1 |
| **Kazakhstan** | **7** |
| **Kyrgyzstan** | **3** |
| Norway | 1 |
| Russia | 4 |
| Ukraine | 1 |
| **Uzbekistan** | **6** |
| **Total** | **24** |

**Sixteen of the twenty-four places sit in three of our launch-adjacent countries.** That is not a
coincidence: the Koryo-saram, ethnic Koreans deported to Central Asia in 1937, are concentrated
exactly there.

**This is an `AFFINITY_OR_DIASPORA` track inside a `GOVERNMENT_SCHOLARSHIP` scheme** — eligibility
keyed to descent rather than citizenship, which is the precise distinction the 2026-08-29 family
addition was made to express. It is also a live demonstration of spec §4.1: a scheme is a set of
tracks, and this track has its own quota table, its own eligible-country list and its own keying. A
model with one row per scheme cannot represent it.

**It matters commercially** — but not in the way first written here. See §5.

~~For a Kazakh applicant of Korean descent the effective quota is 13 + 7 = 20 rather than 13.~~
**Corrected 2026-08-29 (§5.2): the tracks are mutually exclusive in a single cycle, so the two
quotas do not add.** The applicant chooses one. Nothing in our catalog would surface either.

## 5. The three open questions, closed from the same guideline

All three were answered by reading further into the document already held
(`2026-GKS-G-Application-Guidelines-English.pdf`). No new source was needed.

### 5.1 The 24 are **additional** to the 776 — confirmed

The Application Tracks table on p.3 settles it arithmetically:

| Embassy Track | | | University Track | | | | | | |
|---|---|---|---|---|---|---|---|---|---|
| General | Overseas Korean/Adoptee | **Subtotal** | General | R-GKS | Research | Intl. Organization | R&D | Global Network | **Subtotal** |
| 776 | 24 | **800** | 160 | 480 | 5 | 72 | 403 | 80 | **1,200** |

Total 2,000. The Overseas Korean/Adoptee column sits beside Embassy General and sums with it to the
Embassy subtotal — the 24 are a separate allocation, not a reservation carved out of the 776. The
earlier inference from the heading's phrasing was correct, and is now sourced.

### 5.2 An applicant may **not** enter both tracks — the quotas do not add

> "Embassy track applicants must apply to only **ONE** program among General, and Overseas Korean/
> Adoptee program"

Enforced, not advisory:

> "Duplicate submissions are not permitted and will be excluded from the evaluation. If identified at
> any stage of the selection process, the scholarship will be revoked."

Two adjacent rules bound the same cycle:

- An Embassy-track candidate (including a reserve candidate) **who passed round 1 cannot then apply
  through a University Track**.
- An Embassy-track applicant **whose application failed round 1 may re-apply through a University
  Track** in the same cycle — "However, applicants cannot apply for both tracks at once."

**So the real decision is a choice between two pools, and it is not the lopsided choice it looks
like.** For a Kazakh applicant of Korean descent:

| | Places | Countries contesting them | Notes |
|---|---|---|---|
| Embassy General | 13 | 143 | Descent still earns an **evaluation preference** here — the guideline lists "Overseas Koreans" first among its Evaluation Preference criteria |
| Overseas Korean/Adoptee | 7 | 8 | Descent is the eligibility key, so it confers no further advantage inside the pool |

That the descent attribute is *also* a scoring preference in the General track is the finding that
makes this a genuine portfolio judgement rather than an obvious switch — and it is a second, softer
use of the same attribute that a boolean eligibility filter cannot express.

### 5.3 Proof of descent — the requirement is stated, the hard part is not

Document **16**, "Proof of Overseas Korean Document / Proof of Korean Adoptee Document", listed as
optional in general and marked **"Required for relevant applicants"**. Its stated requirement:

> "Submit supporting documents such as **family register or birth certificate that proves family
> relationship between an applicant and his/her lineal ascendant**"

The definition the track runs on:

> "Overseas Koreans refer to **ethnic Korean without Korean citizenship**. Overseas Koreans include
> offspring of Korean diaspora or Korean immigrants who live in countries out of the Korean peninsula"

Two hard constraints attach, and they disqualify rather than merely document:

- Applicant **and** parents must hold citizenship other than Korean. **Dual citizenship — applicant
  or parent — is disqualifying outright.**
- Applicant and parents who previously held Korean citizenship must submit government-issued proof of
  its renunciation (document 17). "An application or a receipt for renunciation of Korean citizenship
  is not accepted."

**Still unresolved, and it is the operative gap for our population.** The guideline says how to prove
the *relationship* to a lineal ascendant. It never says how the ascendant's **Korean-ness** is
established. For Koryo-saram this is the whole question: Soviet-era and successor-state documents
commonly record ethnicity (*национальность: кореец*) but no Korean citizenship, and the guideline
states elsewhere that "ethnic group, birth place, or current residency in the submitted documents are
not accepted as **citizenship** information". That rule is scoped to citizenship proof, not descent
proof, so it does not settle the descent case either way. On the evidence in this document the
determination sits with the reviewing embassy. Resolving it means asking a post, not reading a PDF —
and it belongs to whoever builds the Kazakhstan/Uzbekistan channel, not to the catalog.

Whether document 16 must itself be apostilled or consular-confirmed is likewise not stated
unambiguously: the apostille rule is scoped to "Required Certificates", and 16 is filed under the
optional block while being required for relevant applicants.

## 6. What to encode

- Embassy General quota per country, as a **ceiling** with the embassy-discretion footnote attached.
- University General and R-GKS as **separate** quotas, not summed — they are different selection pools.
- The Overseas Korean/Adoptee track as its own track with `AFFINITY_OR_DIASPORA` keying, quota 24,
  eligible in 8 countries.
- **Mutual exclusion between the two Embassy tracks.** This is not an eligibility rule — the student
  is eligible for both — it is a *selection* constraint, and it is the first instance we hold of one.
  A portfolio builder that treats two tracks of one scheme as independent options will construct an
  application plan the funder will revoke. Whatever represents tracks needs to carry
  "at most one of this set per cycle".
- **Descent as an evaluation preference, separately from descent as an eligibility key.** The same
  applicant attribute does two different jobs in two tracks of one scheme.
- Disqualification on Korean or dual Korean citizenship of applicant *or* parent — this is an
  exclusion condition, not a document requirement.
- Cycle label **2026**, source dated by the guideline, mirror host recorded.

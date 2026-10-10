# Master's CV evidence — two independent research passes

**Date:** 2026-08-27. **Question:** does a programme-tailored CV outperform a strong generic one in
master's admissions, how is a CV actually read, and how is an unfamiliar institution made legible?

Two passes were run against the same brief by two different research systems. Both are kept
because they **disagree in three places**, and in this project a disagreement between two passes is
itself a finding — the resolution decides whether a rule is binding, advisory or folklore.

| File | Character |
|---|---|
| `pass-1-rules-and-findings.md` | Source-tier disciplined. Labels every claim (a) published policy / (b) institutional / (c) professional / (d) folklore, and reports nulls as nulls. Ships a rules CSV (C-01…C-14) and an evidence-quality verdict per track |
| `pass-2-evaluation-and-architecture.md` | Broader institutional sweep. Found the point-scored rubrics pass 1 lacked (TUM's 120-point aptitude assessment, TU Delft's 60/40 split, Swedish merit rating). Mixes primary sources with re-uploads and coaching sites — see the source hygiene warning below |

## Where they agree (high confidence — both passes, primary sources)

- **Tailoring is unevidenced.** No study, audit experiment or admissions outcome data shows a
  tailored CV outperforms a strong generic one. Both passes report this as an empirical void, not
  as a weak effect.
- **The CV is required to submit but carries little or no scoring weight.** Pass 2 makes this
  concrete: TUM's M.Sc. Quantum Science awards 40 points for the bachelor's grade and 40 for the
  motivation letter, and **zero** for the CV, while still requiring it without chronological gaps.
- **ATS keyword screening in admissions is folklore.** Neither pass found any primary evidence of
  it. It is a recruitment practice projected onto admissions.
- **Gaplessness is the one widely binding content rule** — ETH Zürich, uni-assist, TUM, DAAD. Note
  that it points the opposite way from tailoring: omission for the sake of curation is penalised.
- **Fabrication is binding and enforced** (UK universities, UCAS, Charles University), and no
  institution draws a written line between legitimate emphasis and misrepresentation.
- **Institutional legibility is institutional work** — ENIC-NARIC, Diploma Supplement, ECTS,
  uni-assist VPD, WES — not something the applicant asserts on the CV.
- **No published time-per-file figure exists for European master's admissions.** The 8-minute and
  4-minute figures are US *undergraduate* consultancy claims. Do not import them.

## Where they conflict — unresolved, do not treat either as settled

1. **Do reviewers follow hyperlinks?** Pass 1: null, no admissions-office statement found. Pass 2:
   "clear, published evidence", citing Charles University MFDA asking for hypertext links.
2. **Should the institution's URL go in the education entry?** Pass 1: coaching advice, not
   primary-sourced. Pass 2: "fully supported by primary sources", citing the same MFDA document
   plus the Europass XML schema's `WebsiteType` field.
3. **Coursework/module lists on the CV.** Pass 1: advisory, defensible where prerequisites gate
   admissibility. Pass 2: folklore — the institutional mechanism (TUM's curriculum document,
   Charles University's syllabi bundle) lives outside the CV entirely.

**Source hygiene warning, and it decides conflicts 1 and 2.** Pass 2's Charles University quotes
are cited to a **Scribd re-upload** (`scribd.com/document/702530644/MFDA-admission-requirements-23`),
not to Charles University's own site, and its Europass schema claims are cited to **SlideShare and
Scribd** rather than to europass.europa.eu. Under P1-4 those are not official sources, whatever the
quotes say. Both conflicts are resolvable by one fetch each of the primary page — until then, pass
1's null stands.

Pass 2 also cites coaching and aggregator sites in places (`delftprep.nl`, `careerlauncher.com`,
`mastersportal.com`, `whatisagoodgpa.com`, `calcarena.com`). Its institutional findings cited to
`tum.de`, `cbs.dk`, `ox.ac.uk`, `universityadmissions.se`, `uni-assist.de` and `ulb.be` are sound;
treat the rest as leads.

## Findings that matter outside the CV engine

- **DIGICREA (Erasmus Mundus, Université Libre de Bruxelles)** requires the applicant's degree to
  come from "an accredited university (listed in the IAU's List of Universities of the World or in
  some of three top university rankings Shanghai, QS and Times)", and if unlisted, the applicant
  must separately email proof of quality. Cited to `deai.ulb.be` — primary. This is a **funder-side
  legitimacy gate**, and it is exactly the mechanism the portfolio design's legitimacy gate needs
  (see `../2026-08-27-portfolio-data-availability.md`, Q6). It also shows the gate can be a
  *funding* eligibility rule, not only an accreditation fact.
- **uni-assist publishes an Azerbaijan country page** with per-country document requirements
  (`uni-assist.de/en/tools/info-country-by-country/details-country/country/az/`) — directly relevant
  to the home corridor.

## Status

Neither pass has been verified claim-by-claim against primary sources. Anything from here that ends
up in a rule, a prompt or the catalog must be re-fetched from the official page and cited, per P1-4.
Pass 1's rules CSV (C-01…C-14) is the closest thing to a ready-to-use artefact and is the right
starting point for that verification.

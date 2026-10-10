# CV Ruleset v4 — master's admission and scholarship CVs (2026/27 cycle)

Status: input to the Phase 2 CV engine (`phased requirements.md` §4.1, §4.2.2). Supersedes v1 (Claude deep research), v2 (reconciliation), and v3 (deep links). Rules live in [`cv-rules.csv`](cv-rules.csv) — the machine-readable source of truth, now 77 rows; this file carries the context, decisions, and caveats that the CSV cannot.

Provenance vocabulary used in the CSV's `Source URL` and `Verified for cycle` columns:

- **[fetched]** — official page read directly by this project.
- **[downloaded, read]** — PDF downloaded and text-extracted by this project.
- **[this session]** — re-verified in the session named in the `Verified for cycle` cell.
- **[reported]** — official URL surfaced by a research tool; not re-fetched by anyone.
- **[v1-only]** — stands on the v1 deep-research task alone.
- **[3rd pass, …]** — from the Gemini pass, with its verification outcome stated (`agrees`, `verified`, `unverified`, `refuted`).

## How this was produced

1. v1: Claude deep research against a primary-source-ranked prompt (funder/university pages → Europass spec → university career services → discipline conventions → design blogs).
2. Second-opinion pass on the two architecture-deciding questions only (Europass handling; portal parsing): Perplexity `ask` sweeps plus direct fetches of Erasmus Mundus programme pages and DAAD checklist PDFs.
3. Reconciliation: one factual error in v1 corrected (Europass schema status), one unsupported claim withdrawn (portal CV parsing), one missing category added (funder templates).
4. v3: deep links merged with provenance; three evidence corrections (R-010, R-012, R-068) and three flags (R-059, R-062, R-067).
5. v4 (2026-08-21): a third pass from Gemini deep research covering the five funders no earlier pass reached, plus its own resolutions of three flagged discrepancies. **Every claim was re-checked against primary sources before ingestion, and most of it did not survive** — see below.

## The third pass: what survived verification

The Gemini pass was right about the discrepancies it was asked to resolve and wrong about most of the funders it was asked to add. Its conclusions on DAAD EPOS's signature scope, the Fulbright Scholar/Student split, and the phased Campus France file limits all checked out and are now folded into R-010/R-017/R-031/R-067. Two of its "verbatim policy quotes" do not exist in the documents it cited, and one funder classification was exactly inverted.

| Gemini claim | Outcome | What the primary source actually says |
|---|---|---|
| Stipendium Hungaricum: `europass_required`, "only CVs in Europass format are accepted; the CV must include a photo" | **Refuted → inverted** | The 2026/27 Application Guide never mentions CV, curriculum vitae, or Europass. "Required Documents for All Applicants" = school certificates, language proof, ID copy, transcript, medical certificate. The application is DreamApply structured fields. Now **R-073, `structured_fields_only`** |
| WE-TEAM: long verbatim requirement, cycle 2026/27, HIGH | **Quote fabricated** | Page reads only "The CV should be Europass format." and still says "there are no Erasmus Mundus scholarships available for the Edition 2025-2027" (re-fetched 2026-08-21) |
| EMSHIP: long "strongly recommended" verbatim, cycle 2026/27, HIGH | **Quote fabricated** | Page reads "(Europass) CV" in a checklist and refers to the 2024-2025 intake — the staleness flag stands |
| Eiffel: CV "sur une ou deux pages" | **Partly wrong** | That is the *doctorate* clause. The **master's** clause is stricter: "sur deux pages maximum". Now **R-072** |
| Türkiye Bursları: HIGH, 2026/27, `any / structured_fields_only` | **Overstated** | Only located wording is advice prose on a guidance page; no format, length, upload rule or cycle. Also not a valid enum value — the field is single-valued. Now **R-075**, low confidence |
| NAWA: `structured_fields_only`, HIGH | **Unverified** | nawa.gov.pl refused connection 2026-08-21; cited announcements are 2023/2025 documents. Now **R-076**, advisory pending verification |
| VLIR-UOS: `any`, host-specific | **Directionally right** | Its own quote doesn't mention CVs, but the delegation to host Flemish universities is real. Now **R-077** as a delegation rule, not a format rule |

**Process rule this establishes:** a research pass's *reasoning* can be worth ingesting while its *quotations* are not. Do not paste a "verbatim policy quote" into the ruleset without opening the cited document. Three of the eight funder rows above would have introduced false binding requirements.

## Verified facts that decide the architecture

- **EU/EACEA does not mandate a CV format for Erasmus Mundus**; each consortium sets its own (Erasmus+ Programme Guide 2026). In a 15-programme sample: **7 require Europass** (AMIR, MemBioMed, STEPS, GLOBED, i-MESC, MathMods, WE-TEAM), **3 prefer** (Europubhealth+, EMSHIP, DAAD PRIME), **5 accept any** (EMHRPP, EMJM Imaging, Mundus Journalism, CoMEM, Glasgow CLMCE). Roughly half require it — the per-programme flag is load-bearing.
- **No funder requires the CV to be produced by the official Europass editor.** Wording is always "Europass format / model / template". GLOBED's "Resumes in other formats won't be accepted" is the strictest found and still speaks to format, not provenance.
- **The Europass XML/JSON CV schema is legacy.** Interoperable Europe lists it as *Archived*; the last substantive documentation is v3.4.0 with 2015-era content; 2024/25 timestamps are catalogue-migration metadata. "Europass" in 2026 means the editor's visual layout and section vocabulary.
- **No admissions vendor documents applicant-side CV parsing** (Slate, Liaison CAS, CollegeNET, Ellucian, Mobility-Online). Only DreamApply documents an optional admin-side extractor. Transcript OCR exists and is a different thing.
- **Structured fields beside or instead of the CV are the dominant portal pattern**: Chevening (≤15 work entries, hours auto-calculated), Commonwealth, Fulbright/Embark, Liaison CAS, Campus France EEF, uni-assist, UCAS, Europubhealth+.
- **Some funders mandate their own CV template**, and those templates are *schemas, not stylesheets*. SISGP and Rhodes have now been opened: their category sets do not map onto each other (SISGP requires Education and a "Network/Civil Society Engagement" category; Rhodes has no Education section at all), SISGP caps Work Experience at **3 entries** and warns that altering the template "will render your application ineligible", and SISGP mandates Sex and Date of birth where our default suppresses both. Each such funder needs its own mapping, not a shared renderer (R-078 → R-081). Australia Awards' template could not be downloaded — its structure is unknown.
- **DAAD**: EPOS requires Europass format + date of issue (checklist read); Study Scholarships require tabular form, ≤3 pages, nothing about Europass or signature (checklist read). **The signature question is resolved**: the original signature belongs on the ST42 checklist form and on work certificates and recommendation letters — *not* on the CV. No funder in the whole ruleset has been verified as requiring a signature on the CV itself; the signature line survives only as German custom (R-031).
- **A portal profile photo is not a CV photo.** Stipendium Hungaricum mandates a formal photo in the DreamApply profile and says nothing about a CV; EMSHIP lists a passport photo as its own checklist item beside the CV; Campus France carries one in the portal header. Conflating the two is how a photo ends up on a CV bound for a US committee that must not see one (R-074, R-032).

## Settled product decisions

1. Europass output is a **self-rendered variant** mirroring the editor's sections and CEFR grid. **No XML/JSON embedding or parsing** (R-053).
2. Per-programme field `cv_format_requirement ∈ {europass_required, europass_preferred, any, funder_template, structured_fields_only}` (R-002).
3. "Machine readability" in requirements §4.2.2 means **text-layer, unencrypted, copy-pasteable PDF** — not ATS keyword optimisation (R-043/R-044/R-047/R-055).
4. Five template archetypes (below); archetype E is **field-mapped output**, justified by structured portals and funder templates, not by parse-safety.
5. **Structured per-entry export from `CVContent` is a first-class output** — it feeds structured portals and funder templates alike.

## Inputs for the Phase 2 CV-engine design spec

The spec does not exist yet (expected at `docs/superpowers/specs/2026-08-20-phase2-cv-engine-design.md`). When it is written it must take these from here:

- The `cv_format_requirement` enum above, stored per programme/opportunity, with `verified_for_cycle` and `source_url` beside it.
- Europass variant toggles: date-of-issue line (binding at DAAD EPOS), optional signature line (evidence-weak, default on for German-context output), 2-page cap mode (i-MESC) — R-070.
- PDF output contract: text layer, unencrypted, no commenting restrictions, embedded fonts, default ≤2 MB, lean image-free mode for low-limit portals, distinct filename on regeneration — R-043/R-044/R-047/R-049/R-067/R-068.
- A per-cycle re-verification job keyed off the CSV's `Verified for cycle` column. Europubhealth+ already publishes its 2027–29 call and Swiss ESKAS opened 2027/28 on 2026-08-20; rules drift every cycle.

## Template archetypes (minimum set: five)

- **A. Europass** — REQUIRE consortia (R-003/004/005/056/057/058/059), DAAD EPOS (R-010), PREFER consortia on opt-in (R-011/060/062). Editor section set + CEFR grid, no XML, toggles per R-070.
- **B. German tabular Lebenslauf** — uni-assist, German universities, DAAD default. Two-column, personal-data block, optional photo, gap-free mode, optional signature line, optional "University — Programme" header (R-012/029/030/031/042/069).
- **C. Free-format taught/professional** — UK/US/CA/AU/Asia taught tracks and ANY-state consortia. 1–2 pages, education-first, no photo/DOB (R-006/007/008/023/026/032/054/061).
- **D. Research-track academic-lite** — 2–3 pages, thesis + supervisor, research and publications ordered up (R-024/027/028/039/051).
- **E. Field-mapped output** — one structured per-entry export from `CVContent` serving structured portals (Chevening R-015, Fulbright/Embark R-016, Liaison R-019, Campus France R-071) and funder heading templates (SISGP R-064, Australia Awards R-065, Rhodes R-066).

Why not four: A's fixed schema, B's signature/photo/gap-free conventions, C's data-suppression defaults, D's ordering/length envelope, and E's non-page-shaped output are mutually exclusive structural constraints.

## Conflicts left for product decisions

1. **Aggregators vs official pages on Europass** — aggregators say "most Erasmus Mundus require Europass"; the census says half. Aggregators also got MathMods wrong ("any format" vs the official "use the Europass template"). Ingest from primary sources only.
2. **Europubhealth+ dual wording** — "Europass format preferred" (admissions page) vs "any format accepted… strongly recommended" (instructions PDF). Both map to `europass_preferred`.
3. **Master's CV length** — 1–2 pp vs 2–3 pp; turns on track and on importing the PhD-CV convention. Funder caps override.
4. **German photo/signature** — job-market guides insist; DAAD PRIME says no photo required; the AGG makes photo/DOB optional. Follow the funder.
5. **Grade conversion** — self-convert-to-4.0 coaches vs native-scale-plus-key credential bodies. Default: native scale + key, optional labelled conversion.
6. **Fulbright no-hyperlinks (R-017)** — sourced from the Scholar (faculty) programme; transfer to the Foreign Student award is undocumented.
7. ~~**DAAD signature**~~ — **resolved in v4.** The signature belongs to the ST42 checklist form, not the CV. Keep the signature line as a German-custom toggle (R-031), never as a funder requirement.

## Weak evidence — do not build on these without another look

- NAWA's `structured_fields_only` classification — nawa.gov.pl unreachable on 2026-08-21, cited announcements are 2023/2025 (R-076).
- Türkiye Bursları — the only wording found is advice prose on a guidance page, not the binding call regulation (R-075).
- WE-TEAM as a *scholarship* target — page still says no Erasmus Mundus scholarships for the 2025–27 edition (R-059).
- EMSHIP page is stale — refers to the 2024–25 intake (R-062).
- Campus France ≤300 KB tier — real but geographically phased; legacy consular spaces enforce it, modernised ones allow ~1.5 MB (R-067).
- Mobility-Online CV field structure — unverified to field level by any pass.
- Tagged PDF / embedded fonts — best practice; no mandate found (R-049).
- AI-use policy at master's level — every cited policy is US undergraduate essay policy (R-050). **This is the top research backlog item** — see below.

## AI-use policy (R-087 → R-093), researched 2026-08-21

**The headline: two of the most prestigious destinations in this market prohibit exactly what the CV engine does.**

- **Cambridge postgraduate — CVs are named explicitly.** "AI must not be used when writing personal statements and CVs. This prohibition covers the use of AI to help your use of English." Hallucinated achievements "will be treated like any other application fraud". Verified by direct fetch.
- **Oxford graduate — research yes, generation no.** "AI tools may be used to research materials in preparing your application, but may not be used to generate documents or form the basis of documents that are then adapted", and "any submitted documents must be written by the candidate". Assessors "may reject your application". Verified by direct fetch.
- **Chevening — prohibited, and actively enforced.** "Using artificial intelligence software to generate answers to Chevening's essay questions is strictly prohibited"; "Chevening uses tools to detect fraud, plagiarism, and AI-generated content". Binds the letter engine, not the CV engine, since Chevening collects no CV (R-015). Verified by direct fetch.

**Three findings that change the design:**

1. **The CV is not outside these policies.** The open question was whether admissions AI policy covers only essays, since a CV is a factual document. Cambridge answers it directly by naming CVs — and extends the ban to language polishing, so even an editing-only pass is disallowed there.
2. **Policy resolves per document *kind*, not per programme.** Cambridge prohibits AI for CVs and personal statements while *permitting* it for research proposals with acknowledgement. A single `ai_use_policy` value on the programme cannot express that; it must resolve per `DocumentDraft.kind` (R-088).
3. **Disclosure takes the form of a negative attestation on the form**, not a note in the document — Chevening asks applicants "to confirm that you have not used artificial intelligence to generate your answers" (R-092). So a disclosure requirement cannot be satisfied by anything the engine writes *into* the document; it is a declaration the applicant makes on the form.

## Product decision: `ai_use_policy` is reference data, not a gate

**Decided 2026-08-21. Do not re-derive the alternative — it was considered and overruled.**

`ai_use_policy` is stored per programme (and per document kind, per R-088), surfaced to the counselor as a note where a destination has a published position, and **does not block generation**. R-087 through R-093 remain in the ruleset because they are verified facts, independently useful to a counselor advising a student.

An earlier draft of this section argued the field should *gate* generation — refusing to produce a CV for Cambridge or Oxford, on the grounds that a platform-generated document plus a "I did not use AI" attestation puts the applicant in a false declaration. That reasoning is recorded here so it is not rediscovered and re-argued, but it was **overruled as a product decision**: third-party-written application materials long predate AI in this market, and the platform does not enforce a destination's policy on the applicant's behalf. The applicant decides what to declare.

**One boundary this does not move.** Not gating on policy is a different thing from *defeating detection*. Stripping AI-provenance marks, statistical rewriting to evade classifiers, or any equivalent remains out of scope — `phased requirements.md` §4.2 and §4.2.2 prohibit manipulating admissions systems, and §4.2.3 explicitly does not narrow them. Metadata and text hygiene stay permitted; evasion does not.

**Gates Cambridge inherits Cambridge's prohibition** (R-089) — R-018 established that Gates applicants apply through the University's own portal, so the ban reaches them even though Gates publishes nothing itself.

**Honest gap (R-093) — partially closed 2026-08-22.** DAAD and Rhodes do publish AI policies; both are *disclosure* regimes (L-024, L-025 in `letter-rules.csv`, see `2026-08-22-letter-ruleset.md` §A10), so `ai_use_policy` needs a REQUIRES DISCLOSURE value beside prohibit/silent. A direct-fetch pass on the same day found nothing for Erasmus Mundus/EACEA, Fulbright, SISGP, Australia Awards or the Commonwealth Scholarship Commission (L-067). Those stay **unknown, not permitted** — absence of a published policy is not permission, and several of these route through universities that do publish one.

## Research backlog

**Per-funder AI-use policy — CLOSED 2026-08-22 (R-093 direct-fetch sweep done; residual funders are silent, not unresearched).** Original framing follows. R-050 is the largest hole in the ruleset and the one with the most direct consequence for applicants. Everything either research pass found was US *undergraduate essay* policy (Common App's fraud clause, Brown's outright prohibition, Yale's revocation warning, the UC readability-only allowance). Nothing at master's level, nothing CV-specific.

It matters because the positions are not merely advisory. Common App treats presenting AI output as one's own as **fraud**; Yale states it "may result in admission revocation or expulsion" — a penalty that lands *after* an offer is accepted. A platform that generates application documents at scale without knowing which destinations prohibit AI assistance, which require its disclosure, and which are silent, is exposing its own clients to the worst available outcome.

Scope the pass the way the CV-format research was scoped — narrow, primary sources, per funder:

- For the 2026/27 cycle, which universities and funders **prohibit** AI assistance in application materials, which **require disclosure**, and which are **silent**? Quote the policy and link it.
- Does any policy distinguish the **CV** from the personal statement or essay? Most published policy concerns essays; a CV is a factual document and may fall outside it.
- Where disclosure is required, what form does it take — an attestation checkbox, a statement in the document, a separate declaration?
- Do the funders already in this ruleset (DAAD, Erasmus Mundus consortia, Chevening, Fulbright, SISGP, Rhodes, Australia Awards) publish anything at all?

Product shape once answered: an `ai_use_policy` field on the programme alongside `cv_format_requirement` (`prohibited` / `disclosure_required` / `permitted` / `unknown`), resolved through the same three-layer ladder and failing closed to a counselor flag. Where a destination prohibits AI assistance, the engine must not silently generate for it; where disclosure is required, the platform complies rather than conceals — per `phased requirements.md` §4.2.3.
- **v1-only rows without a deep link: R-008, R-016/R-040, R-017, R-018, R-019, R-021, R-022.** First targets for the next verification sweep.
- ~~Türkiye Bursları, Stipendium Hungaricum, NAWA, VLIR-UOS, Eiffel~~ — **closed in v4** as R-072 through R-077, at the confidence each source actually supports (Eiffel and Stipendium high, VLIR-UOS medium, Türkiye and NAWA low).

## Rules that deliberately contradict job-market CV advice

- No one-page cap (R-054). No ATS keyword optimisation (R-055). Photo/DOB rules are per country, not "never" (R-030/R-032/R-033). Reverse-chronological-only is relaxed on research tracks (R-027). PhD "unlimited length" does not apply either (R-025).

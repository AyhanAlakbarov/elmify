# Open-source landscape — Track B

Date 2026-08-22. Companion to `2026-08-22-letter-ruleset.md`. Licence, last push, stars and latest
release were read from the GitHub API on 2026-08-22; everything else is from the projects' own
docs via `perplexity_ask`. Verdicts are against *this* codebase: the CV engine design already
settled "no Europass XML/JSON" (R-053) and the ingestion design already settled the OCR
benchmark shortlist and scrapling — Track B does not reopen those.

## CV data schemas

| Project | Licence / activity (GitHub, 2026-08-22) | What it is | Reusable here | Verdict |
|---|---|---|---|---|
| **JSON Resume** `jsonresume/resume-schema` | MIT; v1.2.1 (2024-08); pushed 2026-06; 2.4k★ | Community JSON schema for a CV; large theme ecosystem; `resume-cli` says it is unmaintained | The *section vocabulary* (basics/work/education/publications/skills/languages) as a sanity check for `CVContent`; nothing else — our content model is claim-bearing and theirs is not | **Reference only** |
| **European Learning Model (ELM)** `european-commission-empl/European-Learning-Model` | EUPL-1.2; 3.0 (2023-04); pushed 2024-02; 53★ | EU credential model (JSON-LD / Verifiable Credentials + XSD profiles) for *qualifications and credentials*, not a person-facing CV | Nothing. It models issued credentials, not applicant narratives; R-053 already rules out Europass XML/JSON | **Ignore** (R-053 stands) |
| **Europass legacy XML** | EU-controlled; Interoperable Europe lists it *Archived* (R-053) | 2015-era CV schema | None | **Ignore** |
| **HR Open Standards** (HR-XML) | Industry body; specs behind membership terms | Enterprise HRIS/ATS interchange | None for admissions | **Ignore** |

Conclusion: there is **no credible external schema for an applicant CV with evidence-bearing
claims**. `CVContent` stays ours.

## CV renderers

| Project | Licence / activity | Output | Assessment | Verdict |
|---|---|---|---|---|
| **RenderCV** `rendercv/rendercv` | MIT; v2.8 (2026-03); pushed 2026-05; 17k★ | YAML → PDF via Typst; JSON-schema-validated input; locale and font control | Best deterministic PDF typography of the set; **no DOCX**; no Europass layout; a funder's fixed template (DAAD EPOS Europass layout, R-010) cannot be met without writing our own Typst theme anyway | **Adapt** — only if `render.py`'s PDF path proves inadequate; otherwise skip |
| **Typst** | Apache-2.0 | Typesetter | Same as above; embedding fonts deterministically is its strength | **Reference only** |
| **Reactive Resume** `AmruthPillai/Reactive-Resume` | MIT; v5.2.7 (2026-08-17); 41k★ | Full web app, browser-PDF | Interactive builder, not a library; wrong shape for a counselor-gated pipeline | **Ignore** |
| **OpenResume** `xitanggg/open-resume` | AGPL-3.0; no release; last push 2024-10 | Web app + resume parser | AGPL and stale | **Ignore** |
| **JSON Resume themes / resume-cli** | Mixed; CLI unmaintained | HTML/PDF themes | Theme quality and text layers vary; not funder-template capable | **Ignore** |

Conclusion: keep the existing `render.py` / `hygiene.py` path. No renderer here produces
DOCX, and DOCX plus funder templates is the actual requirement.

## Europass tooling

No open-source library produces a *valid* current Europass CV, and the EU publishes no public
CV-export API; the live direction is ELM/EDC credentials, not CVs. Confirms R-053: Europass is
a **self-rendered layout variant**, not a format to emit.

## Document extraction / OCR

| Project | Licence / activity | Note | Verdict |
|---|---|---|---|
| **Docling** `docling-project/docling` | MIT; v2.121.0 (2026-08-20); 65k★ | Layout/table/reading-order; OCR pluggable; model weights have their own licences | **Adopt as a benchmark candidate** under the ingestion design's retake gate — not pre-decided |
| **PaddleOCR** `PaddlePaddle/PaddleOCR` | Apache-2.0; v3.7.0 (2026-06); 88k★ | Already on the ingestion shortlist (PaddleOCR-VL) | **Already shortlisted** |
| **MinerU** `opendatalab/MinerU` | GitHub shows NOASSERTION; README says AGPL-3.0; mineru-3.4.5 (2026-08-14); 78k★ | Already on the shortlist; **AGPL** — network-service obligations for a hosted product | **Already shortlisted; licence gate before adoption** |
| **marker** `datalab-to/marker` | Apache-2.0 per GitHub as of v2.0.0 (2026-07-20); formerly GPL-3.0 + commercial — read the LICENSE file in the pinned tag | PDF → Markdown/JSON | **Adapt** only if it beats the shortlist on the transcript benchmark |
| **Unstructured** | Apache-2.0 core; hosted/enterprise proprietary | Partitioning pipeline | Heavier than needed; core only | **Reference only** |
| **pyresparser / "resume-parser" repos** | MIT-ish, stale, regex/spaCy | Toy parsers | **Ignore** — `extraction.py`'s schema-constrained LLM pass is already better |

Nothing here changes the ingestion design; Docling is the one name worth adding to the
benchmark set if it is not already in the run.

## Motivation-letter / SOP generators and prompt libraries

Thin, as expected. The GitHub field is prompt collections, Cursor rules and "resume agents"
wrapping a commercial LLM; none encodes funder rules, length floors, paired-document
non-duplication, claim provenance, or AI-disclosure regimes — the things `letter-rules.csv`
now holds. The most useful artefacts are not repositories at all: **DAAD's own one-page "How to
Write a Letter of Motivation"** (L-028), **Purdue OWL** and **Berkeley Career Center** (L-062),
which are already folded into the ruleset as prompt constraints.

Verdict: **Ignore** as software; the rules CSV *is* the asset.

## Taxonomies to consume

| Taxonomy | Form | Verdict |
|---|---|---|
| **UNESCO ISCED-F 2013** | 11 broad / 29 narrow / 80 detailed fields; official PDF and tabular files from UIS (`uis.unesco.org` — the 2013 PDF URL now 301-redirects; pin the current one) | **Adopt** for `Program.discipline` at **narrow-field** granularity (29 values), as the letter design already proposes; ESCO itself uses ISCED-F for its knowledge pillar, so the two compose |
| **ESCO** (skills/occupations) | EU API + downloadable dataset; API software EUPL-1.2; dataset under its own EU reuse terms; versioned releases | **Defer** — nothing in §4.1/§4.2 needs skill normalisation yet; record the release id if/when adopted |

## Two or three projects worth the time

1. **ISCED-F 2013 narrow fields** — the one external thing the letter design needs now (cluster key, `Program.discipline`). Load it as reference data with a one-off command, like the CSV loaders.
2. **Docling** — add to the ingestion benchmark set; MIT, very active, and the only general extractor without a copyleft catch.
3. **RenderCV / Typst** — keep in the back pocket for PDF typography; do not adopt ahead of evidence that the current render path fails a funder check.

Everything else: reference or ignore.

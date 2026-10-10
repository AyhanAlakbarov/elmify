# Extraction non-determinism — observations before any investigation

Written 2026-08-30, from six live runs of **one** CV
(`CV-2026-07-UMR7140-01-ABDULLAYEV-ORKHAN.pdf`, 2 pages, 5,055 characters after
`extract_text`) against `OPENAI_EXTRACTION_MODEL` at its default. Recorded here
because the runs are paid and the evidence would otherwise live only in a
transcript.

Nothing here is a diagnosis. No hypothesis has been tested.

## What varied, same input, same model

| Dimension | Observed values |
| --- | --- |
| experience / research split | `exp=4 res=4` (double-counted), `exp=3 res=0`, `exp=4 res=0` |
| Skill name fidelity | `Scikit -learn` in one run, `Scikit-learn` in others — the PDF text carries the space, so one run cleaned it and another did not |
| Grade fields | `grade_native="16.45"` + `≈ Highest Honors`; then `grade_native="GPA: 16.45/20.0 (Highest Honors)"` + `grade_scale="20.0"`, rendering `Grade: GPA: 16.45/20.0 (Highest Honors) (20.0)` |
| Country | one run emitted `BA` (Bosnia) for Strasbourg and `AA` for Baku; other runs emitted `FR` / `AZ` |
| `degree_english` | absent in early runs, populated later |

The CV's own text is stable across runs — `extract_text` is deterministic
(pypdf). The variation is downstream of it.

## Why it matters

A student regenerating the same CV gets a materially different document. Two
of the observed variations are not cosmetic:

- **Losing a role.** `exp=3 res=0` means one of the four positions on the CV
  reached neither section. Nothing reported it.
- **The country.** That run produced a factually wrong CV that passed with
  40 verdicts and 0 UNSUPPORTED.

The country case is now caught (`CountryCode` + `city`/`country` as
`spec.detail` — see PR #30). The rest still varies silently.

## Where to start

Two candidate layers, and they have not been separated:

1. `apps/documents/ingestion.py::_extract_claims` — the upload → `CVContent`
   call.
2. `apps/documents/generation.py::_call_model` — the facts → `CVContent` call.

The fact ledger sits between them, so a cheap first cut is to ingest once,
dump the `VerifiedFact` payloads, and then run `generate_cv` several times off
that fixed ledger. If the output still varies, layer 2 is implicated; if it
does not, layer 1 is.

`tests/documents/test_live_tailoring.py` (marked `live`) already does both
halves and prints the section counts, so it is the cheapest harness. Each run
is 2–3 model calls.

Untested and worth knowing before designing anything: whether the API exposes
a seed or temperature control for this model, and whether the SDK call in
these two modules passes one.

---

# Measured, 2026-08-30 — the layers are now separated

Everything above this line was observation without a hypothesis. This section
is measurement. Method: freeze each layer's input and run only that layer.

- **Frozen input, layer 1.** `extract_text` once (5,055 characters,
  sha256 `4f02889574ca…`), then `_extract_claims` three times off that same
  string.
- **Frozen ledger, layer 2.** Take layer-1 run 0's `CVContent`, build the
  `facts_json` string `generate_cv` would build (`fact_payload` over
  `_SECTIONS`, then `_facts_payload`; 44 facts, 12,214 characters, ids minted
  deterministically so no database is involved), then `_call_model` three
  times off that one string.

Both dumped canonical JSON per run and diffed.

## Result: the non-determinism is entirely in layer 1

| | run 0 | run 1 | run 2 |
| --- | --- | --- | --- |
| **L1** `_extract_claims` | edu=2 exp=4 res=4 pub=2 skills=22 | edu=2 exp=4 res=4 pub=2 skills=22 | edu=2 exp=4 **res=0** pub=2 skills=22 |
| **L2** `_call_model` | edu=2 exp=4 res=4 pub=2 skills=22 | identical | identical |

Layer 2's three outputs: runs 0 and 2 byte-identical; run 1 differed **only**
in the order of the `education` array (bachelor first rather than master
first) with no field changed. `render.reverse_chronological` sorts that
section newest-first at the single render funnel, so even that difference
cannot reach the document.

**Given a fixed ledger, generation produces the same CV.** Whatever is worth
fixing is in `ingestion._extract_claims`, and the fact ledger is a clean
firebreak. Small N (three runs a layer) — but the split is not marginal: one
layer varied in every category and the other in none.

## No sampling control exists to reach for

Asked directly, against `gpt-5.6-luna` on the Responses API:

- `temperature=0.0` → **400** `Unsupported parameter: 'temperature' is not supported with this model.`
- `top_p=1.0` → **400**, same message.
- `seed` → not a parameter of `responses.parse` at all (openai 2.53.0).

So the open question from the section above is answered, and answered
closed: this variance cannot be tuned away. It has to be constrained by the
schema, constrained by the prompt, or detected.

## What varies in layer 1, and the shape of it

Every field that drifted is a field the prompt states no rule for. The fields
the prompt *does* rule on held, with one exception.

| Field | Values across three runs | Prompt rule? |
| --- | --- | --- |
| `experience.title` | `Research Intern` / `Research Intern, Project Title: …` / `Research Intern — …` | none |
| `research.supervisor` | `Prof. Alexandre Varnek` / `…'s group` | none |
| `research.methods` / `outcomes` | fully populated / both null | none |
| `end_date` from "June 2024" | `2024-06-01` / `2024-06-30` | none |
| `education.degree_english` | populated / null | none |
| `grade_native` / `grade_conversion` | `16.45/20.0 (Highest Honors)` + null / `16.45/20.0` + `Highest Honors` | none |
| whether a role appears in `research` **as well as** `experience` | yes, yes, no | none |
| `language.mother_tongue` | flipped | **yes**, and it still flipped |

The prompt has grown one clause per observed defect, and it works: sub-skills,
handles, DOIs, `self_author_index`, bullets-per-line and location-invention
all held across all three runs. The drift is concentrated where nothing was
ever said.

## Two defects, distinct from drift

**1. Impossible dates, and they propagate silently. Fixed in this commit.**
From the CV line `September 2020 – June 2024` the extractor emitted
`start_date` `0944-09-01` in one run and `0901-09-20` in another — two of
three. `date` accepts both, so the ledger stored one and layer 2 carried it
through unchanged into all three of its runs: a generated CV reading
"Sep 0944" with 0 UNSUPPORTED verdicts. `schemas.CVDate` now bounds every
date field to 1900–2100; `test_a_date_must_fall_in_a_human_lifetime` pins it.
Deliberately a hard failure rather than a coercion: neither `ingest_uploaded_cv`
nor `generate_cv` has a production caller yet, so loud is free today. **When
ingestion is wired to a view, revisit this** — a 2-in-3 rejection rate on a
real upload needs the bounded retry `generate_cv` already has and
`_extract_claims` does not.

**2. Roles are printed twice, not lost.** The note above read `exp=4 res=4` as
double-counting and `exp=3 res=0` as a lost role. Half right. The four roles
carry a non-null `employer` in *every* run — nothing is lost. What varies is
whether the same four also appear under `research`:

```
research:   AZIMUTH: Hierarchical GTM…      | University of Strasbourg | 2026-01..2026-06
experience: Master's Thesis                 | University of Strasbourg | 2026-01..2026-06
```

…the same work, twice, in runs 0 and 1; once in run 2. Nothing in the prompt
says which section a supervised research post belongs to, and
`ExperienceEntry.supervisor` (added in this PR) now makes `experience` able to
hold one — so the two buckets genuinely overlap and the model picks. **This is
a product decision, not a bug to patch**: either `research` is for the project
and `experience` for the post (and a role legitimately appears in both, which
the renderer should then not duplicate), or a supervised post lives in exactly
one of them and the prompt must say which. Unresolved deliberately.

## What is still open

- The prompt-underspecified fields in the table above. Each is one clause,
  and the evidence says clauses hold — but "add a clause per field" is an
  unbounded programme, and nobody has decided whether the target is a
  *stable* extraction or merely a *correct* one.
- Nothing detects that two ingests of one file disagree. Layer 1's output is
  never compared to anything. That is a cheap thing to add (hash the
  canonical dump) and the only thing that would have caught any of this in
  production.

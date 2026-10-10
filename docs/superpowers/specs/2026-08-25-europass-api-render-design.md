# Design: the Europass CV over europa.eu's API

Status: **implemented and current.** Briefly superseded by
`2026-08-25-europass-browser-render-design.md`, which was retired 2026-08-25 on its own
false premise; see that document's "Why this was retired". The two omissions that made
this path look dead — no `PUT` to store the profile, and an empty
`preference.profileStructure` — are fixed in `ac499e1`. Scope: a new `EUROPASS_API` render variant that produces a
CV rendered by europa.eu itself, carrying genuine Europass provenance, for the programmes that
make Europass binding. Extends `docs/superpowers/specs/2026-08-21-phase2-cv-engine-design.md`.

This is the second of two specs. The first —
`docs/superpowers/specs/2026-08-25-language-self-assessment-grid-design.md`, implemented in
`eb40837`..`38ae425` — created the five CEFR sub-skills this one sends over the wire. It is a
hard dependency: without those fields there is nothing to put in `languageSkills.otherLanguages`.

## The problem

`select_render_variant` maps `europass_required` to the `EUROPASS` variant
(`apps/documents/render.py:29`). That variant is a WeasyPrint template of our own — correct
sections, correct CEFR grid, Europass-shaped. It is a **lookalike**, and it cannot satisfy the
requirement it is mapped to.

The funders that make Europass binding say so in the strongest terms available to them: R-056
GLOBED ("resumes in other formats won't be accepted"), R-003 AMIR, R-058 MathMods, R-005 STEPS,
R-057 i-MESC. What a reviewer at those programmes can actually check is not the layout — it is
whether the file is a Europass document. Empirically, that check has exactly one reliable answer:

```
europass_api.pdf   (europa.eu)  ->  attachments: {'attachment.xml': 2448}
europass.pdf       (our render) ->  attachments: {}
```

Every PDF europa.eu emits embeds an `attachment.xml` — a `Candidate` document at
`http://www.europass.eu/1.0`, `schemeVersionID="4.0"`, `schemeAgencyName="EUROPASS"`. Ours embeds
nothing, and no template change adds one honestly.

So today a `europass_required` draft can be approved and released with an artefact that
misrepresents its own format. That is the gap this spec closes.

**Note that PDF metadata is not the discriminator.** The genuine artefact's `/Producer` is
`cairo 1.15.12` — the same rendering library family anyone could use — and our release-time
`scrub_pdf_metadata` clears `/Title: Europass` anyway. The embedded XML is the signal.

## Out of scope here

- **Editing a Europass CV on europa.eu.** We create one, render it, download it, and never come
  back. No account, no stored profile, no sync.
- **The Europass ELM/JSON-LD import format.** A separate interchange concern.
- **Every other variant.** STANDARD, GERMAN_TABULAR, SISGP, Rhodes and the existing local
  EUROPASS lookalike are untouched, except that EUROPASS gains a second job as the fallback
  target described below.
- **The editing surface** where a student refines sub-skill levels or their own name parts. Still
  the same deferred piece of work spec 1 named.

## What the spike established, and what it did not

Recorded here because the spike is not to be repeated. Artefacts live in
`/home/orkhan/Desktop/cv-samples/` (`europass_api.pdf`, `europass_embedded.xml`) and the driver
scripts in the job scratch directory.

**Established:**

- Guest access needs no account. No login, no API key, no bot wall — plain `urllib` with a
  browser `User-Agent` completed the whole flow headlessly.
- The flow is four calls against `https://europa.eu/europass/eportfolio/api`:

  | # | Call | Purpose |
  |---|---|---|
  | 1 | `GET /frontend-config` | issues the guest session cookies, including `XSRF-TOKEN` |
  | 2 | `POST /eprofile/cv` | creates the CV, returns `{"id": "<uuid>"}` |
  | 3 | `POST /eprofile/cv/{uuid}` | renders it, returns the download hash |
  | 4 | `GET /office/download/pdf/{hash}` | returns the PDF |

- The `XSRF-TOKEN` **cookie** value must be echoed as the `X-XSRF-TOKEN` **header** on every
  mutating call. Without it the POSTs are rejected.
- Call 2 will not accept `{}`. It wants the full profile skeleton the browser sends — the shape
  captured in the spike script, rooted at `profile` / `template` / `profilePicture`, with
  `personalInformation`, `workExperiences.solidWorkExperiences`, `preference`, `skillsAssessment`,
  `customSections` all present, empty collections included.
- Every returned PDF embeds `attachment.xml` at schema v4.0.
- Our own `scrub_pdf_metadata` **preserves** the embedded attachment while clearing metadata —
  verified against the genuine artefact. The existing release-time hygiene pass is safe to apply
  to an API-rendered PDF, and must still be applied.

**Not established, and the implementation must not pretend otherwise:** the spike exercised
`personalInformation` only. The resulting PDF's XML shows `<EducationHistory/>` and
`<EmploymentHistory/>` empty, because nothing was sent for them. **The field names for education,
experience, publications, awards, skills and languages are unconfirmed.** The language-grid keys
in the spike's probe script (`languageSkills.otherLanguages[].{language, listening, reading,
spokenInteraction, spokenProduction, writing}`) were a *guess being tested*; the read-back was
never recorded.

Task 1 of the implementation is therefore: create one CV through the API, `GET` it back, and
commit the returned document as a fixture. The mapper is written against that captured file, not
against this paragraph.

## The core decision: API-first, and never a lookalike in its place

```
europass_required   -> EUROPASS_API.  On any failure: raise. No fallback, ever.
europass_preferred  -> EUROPASS_API.  On any failure: fall back to the local EUROPASS
                                      variant, and say so in a violation.
```

This follows the rule `UnsupportedRenderVariant` already states in `render.py:60`: an artefact
must never misreport what was actually rendered. A silent downgrade would put a plausible-looking
PDF in the wrong format past an approval gate with no violation and no warning — which is
precisely the failure the `europass_required` funders reject applications over.

`RenderedArtifact.variant` therefore carries `"EUROPASS_API"` only when europa.eu actually
produced the bytes. If we fell back, it says `"EUROPASS"`, truthfully.

`DocumentDraft.RenderVariant` gains `EUROPASS_API` and `_REQUIREMENT_TO_VARIANT` is remapped.
Unlike spec 1, **this one does need a migration** — an `AlterField` on `render_variant`'s
choices, exactly like `documents/0007_render_variant_choices.py`.

## Where the API call happens: release only, never preview

The API path runs in `render_draft` (release), not in `render_cv` (preview).

Three reasons, and the first is not negotiable:

1. **It transmits a student's personal data to a third party.** Name, contact email, institutions,
   employers, dates. Preview happens repeatedly, before anyone has agreed to anything; release
   happens once, after approval, when an open `ConsentEvent` exists for the draft. Sending PII to
   europa.eu on every preview keystroke is egress without consent.
2. It is a network call to an undocumented service. Putting it on the interactive path makes
   every preview as slow and as fragile as europa.eu is that minute.
3. Nothing about the *content* differs. Preview renders the local EUROPASS lookalike, which is
   built from the same `CVContent`. The student reviews the same facts in the same sections.

The trade-off, stated plainly: **the student approves content in one rendering house and receives
it from another.** That is acceptable because the approval gate is about facts and verdicts, not
typography — but the student-facing approval copy must say the released CV is generated by
europa.eu, since that is also where their data goes. Wording is a product task; the requirement
belongs to this spec.

## The mapper

`apps/documents/europass.py`, a new module, with a deliberately small surface:

```python
def europass_payload(content: CVContent) -> dict[str, object]:
    """CVContent -> the eportfolio profile document. Pure, no network."""

def render_europass_pdf(content: CVContent) -> bytes:
    """The four calls. Raises EuropassUnavailable / EuropassProvenanceMissing."""

def assert_europass_provenance(pdf_bytes: bytes) -> None:
    """Refuse a PDF that does not carry a genuine attachment.xml."""
```

Keeping `europass_payload` pure is the whole testing strategy: the part that will churn when the
undocumented API shifts is a dictionary, and a dictionary can be asserted against a committed
fixture with no network in CI.

### Three mapping questions this spec settles

**1. `research` has no Europass section. Map it to `Projects`.**

The Europass `Candidate` schema offers `Projects`, `PublicationHistory`, `CreativeWorks`,
`PersonQualifications`, `CourseCertifications`, `ConferencesAndSeminars` — and `customSections`.
`ResearchEntry` is a thesis: title, supervisor, methods, outcomes.

`Projects` wins over a custom section titled "Research". The entire point of this path is a
machine-readable artefact a funder can parse, and `Projects` is a first-class element in
`Candidate.xsd` — it appears in the embedded XML with a stable name. A custom section is free-form
and has no guaranteed mapping into the schema, so it would degrade exactly the provenance we are
paying a network call to obtain. A master's thesis is, without strain, a research project.

The runner-up is recorded because it is close: a custom section preserves the *word* "Research",
which a reviewer scanning an academic CV looks for. If a funder ever complains that a thesis is
filed under Projects, the fix is a one-line change of target section, not a redesign.

**2. Mother tongue: `LanguageEntry` gains one boolean.**

Deferred to this spec by spec 1, because this is where the distinction goes over the wire —
Europass separates `nativeLanguages` from `otherLanguages` and they are different fields.

```python
mother_tongue: bool = False
```

It follows the pattern spec 1 established for the five sub-skills exactly: carried in
`_PAYLOAD_KEYS` for provenance, **never** added to the LANGUAGE spec's `detail` tuple. No document
states a mother tongue in a way another document can contradict, and a student correcting it must
not produce a CONFLICTING verdict that blocks their own draft.

Unlike the sub-skills, this one *is* frequently stated outright — CVs say "Mother tongue:
Azerbaijani" as a heading. So ingestion can extract it truthfully, and the prompt rule stays what
it already is: only what DATA states. Default `False` means "not stated", which sends the language
under `otherLanguages` — accurate, never a false claim.

Without the flag, an Azerbaijani student's Europass CV lists Azerbaijani as a foreign language.
That is the kind of small wrongness a European reviewer notices immediately.

**3. `full_name` must be split, and this is the one inference the design permits.**

`PersonalInformation` carries `full_name`. The API requires `firstName` and `lastName` as separate
fields. There is no honest way to have both without either splitting the name or sourcing two new
values nobody has yet recorded.

The rule: **last whitespace-separated token is the family name, everything before it is the given
name.** A single-token name goes entirely to `firstName` with an empty `lastName`.

This is an inference, and this codebase's standing claim is that it does not invent. Three things
make it acceptable here, in order of weight:

- **A human sees the result before it is released.** This is the same reasoning that already
  keeps `generate_cv` from stamping `full_name` (`generation.py:173-176`): a name can be wrong in
  a way only a human catches, so the correction belongs at the approval gate, not in code that
  manufactures a clean value. The split is visible in the artefact the student approves.
- Europass's own boxes are free text. A student who types their whole name into the first box gets
  the same document. We are not asserting a parse the tool itself enforces.
- The alternative — refusing to render until someone records given/family names — makes the
  feature unavailable to every existing student, for the exact funders that need it most.

It is marked with a `ponytail:` comment naming the ceiling. The upgrade path is explicit optional
`given_name` / `family_name` on `PersonalInformation`, sourced from the IDENTITY fact, used when
present and falling back to the split when absent — which lands naturally with the editing surface
and needs no migration, since `CVContent` is a pydantic schema.

Names where the split is simply wrong (Spanish double surnames, patronymic-final orders) are a
known and accepted defect of the fallback, not of the design.

## Provenance verification

Never trust that call 4 returned what we asked for. Before the bytes become a `RenderedArtifact`:

```python
reader.attachments  # must contain "attachment.xml"
```

`pypdf` is already a dependency and already imported in `render.py`; `reader.attachments` is one
line. The check is:

1. `attachment.xml` is present.
2. It parses as XML.
3. Its root carries `schemeAgencyName="EUROPASS"`.

Anything else raises `EuropassProvenanceMissing`, which is treated as an API failure and routed
through the fallback table above. A `europass_required` draft then fails loudly rather than
shipping a PDF whose provenance we could not confirm.

Deliberately **not** checked: that the XML's name matches the content's. europa.eu is the authority
on what it rendered; re-litigating its output field by field is a second mapper with no owner.

### We never forge the XML

We could embed a schema-valid `attachment.xml` into our own WeasyPrint PDF and produce something
that passes every check above. We will not, and no future task should.

That XML asserts EU-tool origin for a document Europass never rendered. It would be a forged
provenance claim made to a funder, on a student's behalf, in the student's name — and it would be
the single fastest way to get a cooperating institution's applicants blacklisted. The lookalike
variant is honest precisely because it makes no such claim; that is why it stays the fallback and
why it may never satisfy `europass_required`.

## Security and egress

The worker this runs in is the environment `_no_fetch` was written to defend
(`render.py:156-170`): `169.254.170.2` hands out the Fargate task role's credentials and NAT
provides the way out. A new outbound HTTP client in that process is a new SSRF surface, so:

- **Host is pinned in code**, not configuration: a module constant for `europa.eu`. There is no
  setting to point this at another host, because there is no legitimate reason to.
- **`egress.validate_public_url` runs on every URL before every call.** It rejects non-HTTP(S)
  schemes, embedded credentials, and — the reason it matters here — any hostname resolving to a
  non-global address, which is what closes DNS rebinding against the metadata endpoint.
- **HTTPS required.** Downgrade is refused, not followed.
- **Redirects are not followed.** These are four known endpoints; a redirect is a signal the API
  changed, and it should surface as a failure rather than be chased.
- **Response cap and content-type check** on call 4: `MAX_RESPONSE_BYTES` (10 MB, reused from
  `egress`) and `application/pdf`.
- Connect and read timeouts on every call.

`fetch_official_source` is **not** extended to POST. It is a security-critical shared function
used elsewhere; widening it to arbitrary methods and bodies for one caller enlarges its blast
radius for everything that already depends on it. Only `validate_public_url` is reused — it is the
part that does the checking — and the four-call transport lives in `europass.py` where it belongs.

**Rate limiting is not optional.** Per this repo's own baseline, an outbound call wired to a code
path gets a limiter in the same change. Reuse `apps.ratelimit.rate_limited()` keyed on the
student, as the pack-command and MFA endpoints already do. A release path that can be triggered
repeatedly is a way to hammer a public EU service from our IP, which is how access gets withdrawn.

## Failure modes

| Failure | `europass_required` | `europass_preferred` |
|---|---|---|
| `validate_public_url` refuses the host | raise | fall back, violation |
| Any of the four calls errors or times out | raise | fall back, violation |
| Call 4 returns non-PDF, or over the cap | raise | fall back, violation |
| PDF carries no `attachment.xml` | raise | fall back, violation |
| Rate limit hit | raise | fall back, violation |

Every fallback records a `ConstraintViolation` so the counsellor sees *why* a preferred-Europass
student got the local render. A silent fallback is the same defect as a silent downgrade.

## Testing

**CI is hermetic. The live API is a canary. These are different jobs and must not be merged.**

| Test | Where | What it holds |
|---|---|---|
| `europass_payload` matches the committed fixture | CI | The mapper's shape, with no network |
| A language with `mother_tongue=True` lands in `nativeLanguages`, not `otherLanguages` | CI | Question 2 |
| A `ResearchEntry` lands in `Projects` | CI | Question 1, and it is the decision most likely to be silently "tidied" later |
| `full_name` splits on the last token; a single-token name yields an empty `lastName` | CI | Question 3's stated ceiling |
| A PDF without `attachment.xml` raises `EuropassProvenanceMissing` | CI | Uses our own EUROPASS render as the negative fixture — it genuinely has no attachment |
| The genuine `europass_api.pdf` passes provenance | CI | Real artefact, committed as a fixture |
| `scrub_pdf_metadata` leaves `attachment.xml` intact | CI | Pins the empirical finding above; a hygiene change that strips it would destroy provenance silently |
| `europass_required` + API failure raises, and does **not** return an EUROPASS artefact | CI | The core decision. Fails if anyone adds a "helpful" fallback |
| `europass_preferred` + API failure returns `variant == "EUROPASS"` with a violation | CI | The fallback is truthful about itself |
| The four calls against the live API still work | **canary** | The undocumented endpoint has not moved |

The canary is a management command run on a schedule, not a CI step. An undocumented third-party
API that changes shape must page someone, but it must never be able to fail a pull request that
did not touch this code.

The last two CI rows are the ones that rot silently — both pass today for reasons unrelated to
what they claim. They should each be verified against a deliberately wrong implementation before
being trusted, the way spec 1's `detail`-tuple guard was.

## Risks

- **The API is undocumented and unversioned.** No contract, no deprecation notice, no version
  header. The canary is the entire early-warning system. `EMPL-ELM-SUPPORT@ec.europa.eu` is the
  published contact; **the email asking whether this usage is sanctioned has not been sent**, and
  it should be, before this ships to real students.
- **Guest CVs create resources on europa.eu that we never delete.** Call 2 creates a CV under a
  guest session. Whether those are retained, and for how long, is unknown. Worth asking in the
  same email, because it is a data-protection question and not merely a housekeeping one.
- **Terms of service.** Plain Playwright and plain `urllib` both worked, and no bot wall was
  encountered — but "it was not blocked" is not "it was permitted". This is the other half of the
  email.
- Every mapping beyond `personalInformation` is unconfirmed until Task 1 captures the real
  document. Treat this spec's field names outside that section as intent, not as contract.

## What this unblocks

`europass_required` becomes satisfiable for the first time. R-056, R-003, R-058, R-005 and R-057
stop being programmes we route to a variant that cannot meet their stated bar.

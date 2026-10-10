# Phase 2 design: Verified Fact Ledger + CV Engine (P2-A)

Status: design, not yet implemented. Scope: `phased requirements.md` §4.1 (CV engine) plus the fact-ledger and document-versioning infrastructure §4.2 (motivation-letter engine) and §4.2.1 (counselor review) will extend later. Format rules come from `docs/research/cv-rules.csv` (86 rules) and `docs/research/2026-08-20-cv-ruleset.md`.

## Out of scope here

- Motivation-letter generation content (§4.2) — the models below are shaped to extend to it (`DocumentDraft.kind`) but no letter-specific logic is built.
- Counselor review UI (§4.2.1) — `DocumentDraft.status` supports an approval step later; the split-screen fact-overlay UI is not designed here.
- Standalone direct-to-consumer CV Polish product (§4.2.2) — its **fact-ingestion path is designed here** (see "Populating the ledger"), because it determines the shape of `VerifiedFact` and would otherwise force a migration later. Its commercial surface — storefront, pricing, bundles, the agency-tenant exclusion — is not designed here. Whether ingestion lands in the first implementation phase is a sequencing call for the plan.
- PDF rendering library choice — flagged as an implementation-plan decision, not fixed here.
- Malware-scanner selection — the scan is a required step in the ingestion path; which scanner backs it is an implementation-plan decision.

## New app: `apps/documents/`

Follows the existing one-app-per-domain layout (`apps/accounts`, `apps/research`, `apps/funding`, …).

### Models (`apps/documents/models.py`)

All extend `apps.tenancy.models.TenantScopedModel` (fail-closed tenant scoping, `save()` rejects tenant mismatch — see `apps/tenancy/models.py:47`).

**`VerifiedFact`** — append-only fact ledger per student.
- `student` (FK `Membership`), `category` (enum: `EDUCATION`, `EXPERIENCE`, `RESEARCH`, `PUBLICATION`, `AWARD`, `LANGUAGE`, `SKILL`, `PERSONAL`)
- `payload` (JSONField, validated against a per-category Pydantic schema before save — mirrors `apps/accounts/profile_versions.py`'s `schema.model_validate(...)` pattern)
- `source_tier` (enum: `AUTHORITATIVE_DOCUMENT`, `STUDENT_STATEMENT`) — what kind of thing backs this fact
- `source_ref` — the transcript/certificate it was read from, or the consultation exchange the student said it in
- `confirmed_by` (FK `Membership`, nullable), `confirmed_at` (nullable)
- `supersedes` (self-FK, nullable) — correction chain; never mutate a row, only add a new one pointing back
- `created_at`, `created_by`

Never updated in place. Corrections are new rows with `supersedes` set — this is what unlimited `FACTUAL_CORRECTION` revisions (requirements §4.1) write to.

**Every fact carries what backs it.** `idea_v2.md:85` permits exactly two origins — "facts stated by the student **or** extracted from authoritative documents supplied by the student" — and `source_tier` is that distinction, nothing more:

| `source_tier` | What it means | Examples |
|---|---|---|
| `AUTHORITATIVE_DOCUMENT` | Issued by an institution. Independent of the applicant. | Transcript, degree certificate, employment letter, language certificate |
| `STUDENT_STATEMENT` | The student's own word, on record. | An answer given to the consultant; a claim carried over from a CV the student wrote |

**A CV the student supplies is `STUDENT_STATEMENT`, not evidence.** This is the distinction most easily lost. A transcript is issued by a university and constrains what can be claimed; a CV the applicant wrote is their own assembled claims and verifies nothing. Extracting from it is legitimate — we carry forward their claim rather than inventing one — but the ledger must not launder it into evidence. It is `idea_v2.md:85`'s *first* branch, not its second.

That distinction is load-bearing for review: §4.2.1 requires the counselor to see each claim marked `supported` or `uncertain`. If an unverifiable line imported from an old CV rendered as `supported`, the counselor would lose the ability to spot the one thing worth checking — a claimed publication, a claimed award, a grade that disagrees with the transcript.

**The consultant collects statements; there is no separate attestation step.** When the LLM consultant asks "did you lead a team?" and the student answers "yes, five people", that *is* the attestation — the student stated it, it is not from a document, and it is recorded. `idea_v2.md:85`'s requirement to record such facts as student-attested is satisfied by `source_tier = STUDENT_STATEMENT` plus the `source_ref` pointing at the exchange. No confirmation screen, no batch step, no extra touchpoint: the collection *is* the record.

**Assume the student has no CV.** For master's applicants worldwide — particularly fresh graduates from non-Anglophone systems — arriving without a CV, or with a poor one, is the common case rather than the exception. The consultant question path is therefore the *primary* route into the ledger, not a fallback branch, and should be built as such.

**Machine-generated facts still need a human.** A fact whose `confirmed_by` is NULL is a *candidate*, invisible to generation. This binds the two paths where no human has yet spoken: the profile bridge, and extraction from an uploaded file. A fact the student stated to the consultant is confirmed by that act; a fact a model read out of a PDF is not.

**`DocumentDraft`** — one row per generated version, append-only like `StudentProfileVersion`.
- `student`, `kind` (enum: `CV`, `MOTIVATION_LETTER` — only `CV` behavior built now)
- `version` (int, `latest + 1` under `select_for_update()`, same pattern as `create_profile_version`)
- `content` (JSONField — the `CVContent` Pydantic model, `model_dump(mode="json")`)
- `render_variant` (enum, see below)
- `programme` (FK to the funding app's opportunity model, nullable — which programme's `cv_format_requirement` drove this render)
- `source_facts` (M2M to `VerifiedFact`) — every fact actually used, for the anti-fabrication gate and for diffing
- `status` (`DRAFT` / `APPROVED` / `SUPERSEDED`), `approved_by`, `approved_at`
- `created_at`

**`RevisionRequest`**
- `document` (FK `DocumentDraft`), `kind` (`STYLE_STRUCTURE` / `FACTUAL_CORRECTION`)
- `requested_by`, `note`
- `resulting_draft` (FK `DocumentDraft`, nullable until fulfilled)
- `superseding_fact` (FK `VerifiedFact`, nullable — **required** when `kind=FACTUAL_CORRECTION`)
- `created_at`

Revision-round accounting (requirements §4.1: "Allow two student-requested style or structure revision rounds. Allow unlimited corrections of objectively wrong facts."):
- `count = RevisionRequest.objects.filter(document__student=student, document__kind=kind, kind=STYLE_STRUCTURE).count()` — reject a new `STYLE_STRUCTURE` request at `count >= 2`.
- `FACTUAL_CORRECTION` has no cap but is rejected unless `superseding_fact` is set and is itself unsuperseded (`supersedes` chain tip) — this is what keeps "unlimited" from becoming a way to bypass the style-round cap under a different label.

### Who approves what

**Facts and craft are different approvals, held by different people.** `phased requirements.md:482` already separates them — "the student approves **verified facts** and the application pack once" — and collapsing them is a design error with a real consequence.

| Question | Authority | Why |
|---|---|---|
| *"Is this true about me?"* | **Student, exclusively.** Non-delegable per `:43` and `idea_v2.md:135`, which list attestation beside identity and signature. | Only they know they led a team of five. |
| *"Is this a good CV?"* | **Counselor.** | The student is buying this judgment precisely because they do not have it. |

A student who applies through a service like this generally does not know what a strong CV looks like. Asking them to approve *craft* is therefore not consent — it is risk transfer wearing consent's clothes: they click yes because they trust the service, and if the application fails the approval means nothing, because they were never positioned to evaluate it. So the counselor owns craft, and the student is never asked to certify quality they cannot assess.

What remains genuinely the student's at the end is narrower and real: **consent for the document to go out in their name.**

**`DocumentApprovalMode`** — that consent may be granted per document or once, following the pattern `phased requirements.md:486` already establishes for `student-submit`: authorization "granted once, with the mode, recorded as an approval event," the student "notified when it triggers," and anyone declining it "told plainly" what the consequence is.

- `PER_DOCUMENT` (default) — the student consents to each document before use.
- `COUNSELOR_APPROVES` — captured by the LLM consultant during consultation, recorded as an approval event, revocable at any time. Counselor approval then releases the document.

The mode covers consent-to-send only. It can never extend to attestation, new facts, signature, identity or spending — `:290` states plainly that "counselor approval cannot substitute" for a non-delegable declaration, and `:43` puts attestation in that set. A student who is out of the loop still supplies the facts; they simply stop being asked to bless the wording.

### When the student dislikes the result

The 2-round cap in §4.1 governs **agent regeneration**, not the student's satisfaction. §4.2.1 separately gives the counselor a **quick-edit**, and a counselor's hand edit is not a revision round. So a student who is still unhappy after both rounds keeps being helped: the counselor edits directly, without limit, absorbed as service labour. That is what a concierge engagement implies, and it needs no new commercial mechanism — the cost is bounded by counselor time, and a chronically unsatisfiable student is a margin problem rather than a product one.

**Expectation-setting belongs at consultation, not at delivery.** Most dissatisfaction here is a mismatched expectation rather than a bad document, so the consultant states up front: we build only from your documents and what you tell us and **will not invent qualifications** (§4.2.2 forbids it); some funders mandate formats we must follow even where you would prefer otherwise; two style rounds with factual corrections always unlimited; and no admission guarantee (§4.2.2 forbids claiming one).

**Student override of an advisory convention — settled.** Resolved by the three-tier `enforcement` model under "Constraints the enum cannot express": binding funder rules cannot be overridden by anyone, high-risk conventions are overridable by the student alone after being shown the specific consequence, and pure style preferences are honoured silently. Overrides are scoped per programme and never travel.

### `cv_format_requirement` (docs/research R-002)

Lives on the funding app's opportunity/programme model, not on `documents` — it's a fact about the programme, not the document. Add:

```python
class CVFormatRequirement(models.TextChoices):
    EUROPASS_REQUIRED = "europass_required"
    EUROPASS_PREFERRED = "europass_preferred"
    ANY = "any"
    FUNDER_TEMPLATE = "funder_template"
    STRUCTURED_FIELDS_ONLY = "structured_fields_only"
```

plus `cv_format_requirement`, `cv_format_verified_for_cycle`, `cv_format_source_url` fields on the programme model, seeded from `docs/research/cv-rules.csv` (R-003 through R-083 map one-to-one to rows there — do not hand-retype them; write a one-off management command that loads the CSV). Rows marked "unconfirmed" or "[v1-only]" in the CSV load with `cv_format_verified_for_cycle = null` and must not be treated as binding until reverified — the loader should refuse to set `EUROPASS_REQUIRED`/`FUNDER_TEMPLATE` from a `[v1-only]` row without an explicit override flag.

#### Resolving the requirement for a programme we have never catalogued

**This is the normal case, not an edge case.** The product covers master's programmes in every country and the funding engine's whole purpose is surfacing hard-to-find opportunities; the ruleset covers roughly 25 funders out of tens of thousands of programmes. A design where `cv_format_requirement` is only ever populated from a CSV silently renders a `STANDARD` CV for GLOBED ("Resumes in other formats won't be accepted") or for SISGP (where a wrong format is *ineligibility*), and the student never learns why they were rejected. Resolution therefore has three layers, in priority order:

1. **Verified** — a row from the ruleset CSV with a non-null `cv_format_verified_for_cycle`. Highest authority; hand-checked against a primary source.
2. **Extracted** — for an uncatalogued programme, read the requirement off the programme's own page. `apps/research/extraction.py` already does exactly this shape of work: `ExtractedClaims` carries `required_documents`, a `confidence` float and an `uncertainty` list. Extend that pattern rather than building a second extractor, and store the result with its confidence, its source URL and the cycle it was read for.
3. **Fail closed** — below the confidence threshold, on conflicting signals, or with no reachable page: render `STANDARD`, stamp the draft `cv_format_confidence = UNVERIFIED`, and raise a counselor red flag under §4.2.1 rather than guessing silently.

Bias the failure deliberately. Rendering `STANDARD` where `ANY` was acceptable costs nothing; rendering `STANDARD` where Europass was required costs the application. So an unresolved requirement is never a silent default — it is a visible unresolved item on the counselor's queue.

#### Constraints the enum cannot express

The five enum values capture the *format family* and nothing else. Real constraints already collected do not fit it: Europubhealth's "city + country per experience, no abbreviations" (R-061), SISGP's cap of three work-experience entries (R-078), Rhodes' ban on publication abstracts (R-080), Cambridge's 2 MB ceiling (R-082), Mundus Journalism's fixed document order (R-008). Uncatalogued programmes will keep producing more of these, and a renderer cannot read a prose rule.

Carry them as a `constraints` JSONField beside the enum, with a small closed vocabulary of machine-checkable keys — `max_pages`, `max_bytes`, `max_entries_per_section`, `language`, `required_fields`, `prohibited_content`, `date_of_issue_required`, `signature_required`. Anything that does not fit a key stays as free text attached to the counselor flag, never silently dropped.

Validate the rendered artefact against `constraints` **before** the draft can be marked ready — page count, byte size, entry counts, required fields present, prohibited content absent. A violation is a blocking red flag under §4.2.1, which already requires blocking application use until resolved. This is the pre-flight check that makes the whole ruleset operative rather than decorative: rules that are never enforced against real output are documentation, not behaviour.

#### Enforcement levels and student override

Whether a student may insist on something the ruleset advises against depends on what the rule costs to break, and "advisory" alone does not carry that. R-032 (no photo on a US/UK/CA/AU CV) is advisory only because no funder writes it down — yet a photo can get a CV discarded by an admissions office with anti-discrimination policies. "Reorder my skills section" is equally advisory and costs nothing. One policy cannot serve both, so every constraint carries an `enforcement` level derived from the ruleset's **Binding or advisory** column plus a risk read:

| `enforcement` | Source | Override |
|---|---|---|
| `BINDING` | The funder states it in writing; breaking it risks ineligibility or rejection. SISGP's "alterations will render your application ineligible" (R-078), GLOBED's Europass-only rule (R-056), page caps, file-size ceilings. | **None.** No override path exists for anyone — not the student, not a counselor. Breaking these causes the outcome the student is paying to avoid. |
| `ADVISORY_HIGH_RISK` | Nobody publishes it, but violating it carries documented real harm. R-032's photo/DOB suppression for US/CA/UK/AU. | **Student only**, after being shown the specific risk, recorded as their decision. |
| `ADVISORY_STYLE` | Convention with no material downside — section ordering, phrasing, emphasis, within limits the funder allows. | **Honour the preference silently.** No warning, no record; ceremony here trains people to click through the warnings that matter. |

Two mechanics carry more weight than the tiering itself:

**The risk is shown specifically, never generically.** The override surface renders that rule's own text and consequence out of its ruleset row — *"US admissions offices commonly discard CVs containing photographs for anti-discrimination reasons"* — not "are you sure?". A warning the reader cannot act on is not informed consent, and a generic one is indistinguishable from a dialog to dismiss.

**An override never travels.** It is scoped to `(student, programme, rule_id)` — never global, never per-student. A photograph is conventional in Germany (R-030) and harmful in the US (R-032), so a student-level "I want a photo" preference would be actively dangerous the moment it reached a US application. A student who wants it on ten applications overrides ten times, seeing each destination's risk. The friction *is* the safety mechanism.

`ConstraintOverride` records `student`, `programme`, `rule_id`, `decided_by`, `risk_text_shown`, `created_at` — `risk_text_shown` persisted verbatim, so the record shows what the student was actually told rather than what the rule says today.

```
render → pre-flight
   ├─ BINDING violated ──────────→ blocked; no override path exists
   ├─ ADVISORY_HIGH_RISK violated → show rule text + consequence
   │                                 └─ student accepts → recorded, proceeds
   └─ ADVISORY_STYLE ─────────────→ honour preference silently
```

Counselors cannot override an `ADVISORY_HIGH_RISK` rule on the student's behalf: the risk lands on the student's application, so the decision is theirs. This is the same boundary as attestation — a counselor may advise, but cannot consent to a personal risk for someone else.

### Populating the ledger

**Bridge from `StudentProfileVersion`.** `apps/accounts/profile_versions.py` already maintains a validated, versioned, tenant-scoped profile snapshot; that is the seed. `bridge_profile_to_facts(student)` reads the latest `StudentProfileVersion`, maps `StudentProfileSnapshot` fields onto per-category fact payloads, and writes them with the `source_tier` the underlying profile field carries and `confirmed_by = NULL`. It is idempotent: re-running after a profile update creates superseding rows for changed values and touches nothing else. Bridged facts are candidates until confirmed — the bridge never produces something the generator may use.

**Ingestion from an uploaded CV** (needed by CV Polish, §4.2.2, and by any student who arrives with a CV already written):

1. Student uploads a PDF or DOCX.
2. **Malware scan before anything else reads it** (requirements §3.4: "Malware-scan student documents"). Scan failure quarantines the file and aborts; no extraction, no storage in the normal prefix.
3. Extract text, then extract candidate facts with an LLM using the `apps/research/extraction.py` pattern — the uploaded document is untrusted content and is labelled as data in the prompt, output is schema-constrained, `max_output_tokens` capped, and the call is rate-limited per the same rule as generation.
4. Each extracted item is written as `source_tier = STUDENT_STATEMENT` (an applicant-written CV is the applicant's own claim, never evidence) with `confirmed_by = NULL`.
5. The student (or counselor) confirms each candidate before it becomes usable. **Nothing extracted from an upload is ever used unconfirmed** — an uploaded CV is a claim by the applicant, not evidence, and the whole anti-fabrication design collapses if a model's reading of an unverified file can flow into a generated document.

This is what makes §4.2.2's "reuses this engine" true rather than aspirational: CV Polish is upload → scan → extract → confirm → the ordinary generation path, with no second engine.

### `CVContent` schema (`apps/documents/schemas.py`)

Pydantic, `extra="forbid"`, `frozen=True` — same discipline as `apps/research/extraction.py`'s `ExtractedClaims`. Fields carry the field-level rules from the ruleset directly:

- `personal_information` — name, contact; `photo` and `date_of_birth` are **optional** fields, never auto-included (R-030/R-032/R-033 — inclusion is a per-render decision, not a content decision)
- `education: tuple[EducationEntry, ...]` — `degree_as_awarded`, `degree_english`, `institution_original`, `institution_english`, `city`, `country`, `start_date`, `end_date`, `grade_native`, `grade_scale`, `grade_conversion` (optional, must be labelled if present — R-036/R-037), `ects_credits` (optional — R-038)
- `experience: tuple[ExperienceEntry, ...]` — employer, title, city, country, start/end dates, description
- `research: tuple[ResearchEntry, ...]` — `thesis_title`, `supervisor` (R-039), methods/outcomes
- `publications`, `awards`, `skills`
- `languages: tuple[LanguageEntry, ...]` — the student's language skills: CEFR level and/or test score (R-041)
- `summary` (optional, may be `None`) — a short "About Me" block. **Emitted by the `EUROPASS` variant only**; every other variant omits it by default. See the note below, because the default matters more than the field.
- `document_language` — the language the CV itself is written in, distinct from the above. Eiffel accepts "rédigé en français ou en anglais" (R-072) and Stipendium expects "the language of the selected study programme or in English"; a CV may therefore have to be *generated* in French, not merely styled differently. This is a generation input, not a render setting, and pairs with the `language` key in `constraints`.

**Why `summary` exists but is off by default.** Nearly every commercial CV template opens with a summary or "about me", so its absence here looks like an oversight. It is not:

- **Europass has one**, and 7 of the 15 sampled programmes mandate Europass. The current editor carries an "About Me" section — "Do not include a full detailed history. Focus on facts and main points" (R-084). The field must therefore exist, or we cannot render a compliant Europass CV.
- **Every funder template we opened omits it.** SISGP, Rhodes and Australia Awards each designed a CV form for exactly this population and allocated no space to a summary; SISGP goes further and makes adding a category grounds for ineligibility (R-078). `FUNDER_TEMPLATE` must never emit it.
- **Admissions guidance routes that content elsewhere.** Cornell places academic objectives in the statement of purpose and motivation in the personal statement; Berkeley's admissions resume specification lists education, work history, activities and productivity, with no summary (R-085). The applicant is already submitting a motivation letter that does this job at length and with evidence.
- **The "include a job objective" advice is employment guidance** from a career-services page, aimed at someone targeting a vacancy (R-086). Same non-transfer class as the one-page cap (R-054) and ATS optimisation (R-055).

There is a second reason to keep it off by default: a summary is the one part of a CV made of assertions rather than records. *"Motivated graduate with a passion for sustainable engineering"* traces to no `VerifiedFact` and would be marked `UNSUPPORTED` by the gate — correctly. Where a Europass CV does carry one, it must be built from confirmed facts like every other field, not written as a pitch.

`city` + `country` and full (non-abbreviated) institution names are mandatory on every entry, not just where a specific funder states it (R-061 generalized as a baseline quality bar, not a Europubhealth-only rule) — cheap to always do, expensive to special-case.

Dates render unambiguously (spelled month or ISO — R-046) at the render layer, not stored ambiguously in content.

### Generation service (`apps/documents/generation.py`)

Clones the `extraction.py` pattern exactly:
- OpenAI Responses API, `CVContent` as the schema-constrained output
- Prompt explicitly labels `VerifiedFact` rows as **data**, the instruction is generate-from-data-only — same untrusted-content labeling discipline as `extraction.py` and `funding/explanations.py`
- `safety_identifier=privacy_safe_identifier(...)`, `max_output_tokens` capped (start at 3000 — CVs are longer than the 2000-token funding extractions)
- **Rate limiting added in the same change** — this is the CLAUDE.md rule under LLM/AI security, not optional. Follow the `_pack_command_rate_limited` pattern at `apps/funding/views.py:53`:
  ```python
  def _cv_generation_rate_limited(actor_id):
      return rate_limited("cv_generation", actor_id, limit=..., window_seconds=...)
  ```

### Anti-fabrication gate (`apps/documents/verification.py`)

`verify_against_facts(content: CVContent, facts: Iterable[VerifiedFact]) -> tuple[ClaimVerdict, ...]`, deterministic — no LLM call, no model judging its own output. Every material claim in `content` is traced against the supplied `VerifiedFact` rows and assigned one of the four states §4.2.1 requires the review UI to display:

| Verdict | Meaning | Effect |
|---|---|---|
| `SUPPORTED` | traces to a confirmed `AUTHORITATIVE_DOCUMENT` fact | clean |
| `UNCERTAIN` | traces to a `STUDENT_STATEMENT` fact, or to any unconfirmed fact | non-blocking warning; counselor may override **with a record** |
| `CONFLICTING` | contradicts another fact — overlapping dates, mismatched quantities, differing institution names | **blocking** |
| `UNSUPPORTED` | traces to nothing — fabrication | **blocking, never overridable** |

**It classifies; it does not raise.** An earlier draft of this design aborted generation on the first unsupported claim, which contradicts §4.2.1 — that section requires the UI to *mark* claims "supported, conflicting, unsupported or uncertain", so generation must be able to produce an unsupported claim and label it. Aborting is also worse in practice: it destroys the evidence, telling you generation failed but not what was invented.

**Blocking applies to application use, not to draft creation** (§4.2.1: "Block application use while a blocking red flag remains unresolved"). A draft is always produced, so the counselor always has something concrete to inspect beside the facts. A fabricated claim can never reach an application, because `UNSUPPORTED` is blocking and no override exists for it — the escape hatch opens only for claims a human will put their name to.

Verdicts persist on the draft; they are the data dependency for the §4.2.1 fact-overlay UI and for `document.format_unverified`-style flags.

**Amendment, 2026-08-23** (from the §4.2 design review — `2026-08-22-phase2-motivation-letter-engine-design.md`, decisions 8–9, and the same-day amendment to requirements §4.2.1): `UNCERTAIN` is informational, not a warning needing a counselor override — a `STUDENT_STATEMENT` fact is accepted on the student's attestation and counts as supported for application use; the overlay still colours the two tiers differently. A draft with no `CONFLICTING` or `UNSUPPORTED` verdict and no `BINDING` violation auto-approves on the student's acceptance; the counselor queue holds flagged drafts only. `UNSUPPORTED` and `CONFLICTING` are unchanged.

### Bounded retry (inside `generation.py`)

When the first verification pass returns any `UNSUPPORTED` verdict, generation retries **exactly once**: the same fact set is restated and the specific failed claims are named as having no supporting fact. The deterministic check then runs again and whatever still fails is marked and handed to the counselor.

- **Hard cap of one.** No loop, no escalating retries; the second result is final whatever it says.
- The retry is a second LLM call and so is counted by the same rate limiter.
- The deterministic gate runs on both passes. The model is never asked to assess its own output — the retry only gives it another chance to comply, it does not grant it authority.
- §4.2.1's counselor-initiated "request an inline AI revision" is a separate, human-triggered path on top of this, not a replacement for it.

### Deterministic diff (`apps/documents/diffing.py`)

`diff_cv_content(old: CVContent, new: CVContent) -> tuple[FieldChange, ...]` — structured field-path diff, no LLM call. Satisfies "Explain major changes" (§4.1) deterministically, consistent with `engineering.md`'s "grade LLM evals deterministically when possible" — there's no reason to spend a model call explaining a diff that's mechanically computable.

### Render layer (`apps/documents/render.py`)

`render_variant` enum on `DocumentDraft`, chosen from `programme.cv_format_requirement` at generation time — mirrors the five archetypes:

| `render_variant` | Driven by | Output |
|---|---|---|
| `EUROPASS` | `europass_required` / `europass_preferred` (opt-in) | Self-rendered Europass section order + CEFR grid. **No XML/JSON embedding** (R-053). Toggles: date-of-issue line (mandatory where the programme's checklist requires it, e.g. DAAD EPOS), optional signature line, 2-page cap mode (R-070) |
| `GERMAN_TABULAR` | German-context default (DAAD non-Europass, uni-assist) | Two-column, personal-data block, optional photo, gap-free-history mode, optional signature+date, optional bold "University — Programme" header (R-012/029/030/031/042/069) |
| `STANDARD` | `any` | Free-format, 1–2pp taught / 2–3pp research-track ordering (archetypes C/D), no photo/DOB by default |
| `FUNDER_TEMPLATE` | `funder_template` | **A per-funder schema, not a parameterised renderer** — see R-081 and the note below. One implementation per funder (SISGP R-064/078/079, Rhodes R-066/080, Australia Awards R-065 — template not yet obtained) |
| `FIELD_MAPPED` | `structured_fields_only` | Not a PDF — structured JSON/dict export of `CVContent` per-entry, for portals that replace the CV with form fields (Chevening, Fulbright/Embark, Liaison, Campus France EEF — R-015/016/019/071) |

PDF output contract (all PDF variants — R-043/044/047/049/067/068):
- Real text layer (no scanned-image-only content); never encode substantive data only in an image
- Unencrypted, not password-protected, no commenting restrictions
- Fonts embedded
- Default size target ≤2 MB; a lean image-free mode for portals with tighter limits (Campus France-class, ≤300 KB — low confidence per R-067, verify before enforcing as a hard ceiling)
- Regeneration emits a new filename per version (`{student-slug}-cv-v{version}.pdf`), never overwrites
- **Metadata scrubbed and text normalised** before release, per `phased requirements.md` §4.2.3: clear `Producer`, `Creator`, `Author`, XMP packets and editing history, leaving only fields the tenant or target application needs; strip zero-width, control and non-printing characters and normalise quotes and dashes. Toolchain metadata would leak through an agency tenant's white-label identity, and stray non-printing characters corrupt the receiving side's text extraction — the same extraction R-043 depends on being clean. Both are properties of the renderer, not an external post-processing step in the render path.

§4.2.3 covers hygiene only. It does not extend to removing or defeating signals that a document was AI-assisted; where a destination requires disclosure of AI assistance or prohibits it, the platform complies rather than conceals (see the AI-policy backlog item in `docs/research/2026-08-20-cv-ruleset.md`).

#### `FUNDER_TEMPLATE` is one implementation per funder

Two of the three funder templates have now been opened (SISGP, Rhodes; Australia Awards' file is not downloadable from `dfat.gov.au`), and they do not share a shape:

- **SISGP** mandates five categories in fixed order — Personal Information, Work Experience, Education and Training, Network/Civil Society Engagement, Previous Scholarships/Awards — and states that altering the formatting or adding a category "**will render your application ineligible**". Unused headings may be deleted; nothing may be added. Work Experience is capped at **3 entries** regardless of page count. Personal Information mandates **Sex, Date of birth, Citizenship**.
- **Rhodes** has six differently-named sections, **no Education section at all** (education lives in the Embark form), a 2-page cap where "no additional pages will be read", per-section space limits, and an explicit ban on publication abstracts.

Three consequences for implementation:

1. **Do not build one renderer parameterised by a heading list.** The category sets are not translations of each other — SISGP's "Network/Civil Society Engagement" and Rhodes' "Volunteering, Community Involvement and Leadership" overlap only partly, and one funder omits Education entirely. Each funder gets its own mapping module.
2. **`CVContent` needs optional per-funder extension fields.** These templates demand data the base schema has no home for: industry/sector, a description of the employing organisation, headcount supervised, ORCiD, and duration plus level of mastery for a skill. Model these as optional fields rather than forcing every student to supply them.
3. **Per-section entry caps are a new constraint class.** SISGP's "maximum 3 entries" is not a page limit and not a character limit; the generator must be able to select the best N entries for a section. This is the same selection problem Rhodes states in prose ("choose the experiences you feel are most important"), so build it once.

R-079 also settles a question the base schema got wrong by default: SISGP *requires* sex and date of birth, so personal-data inclusion is a per-destination render decision, never a global content decision. `CVContent` stores these as optional fields; each variant decides whether to emit them.

#### Craft reference for `STANDARD`: Jake's Resume — layout only, not its rationale

[Jake's Resume](https://www.overleaf.com/latex/templates/jakes-resume/syzfjbzwjncs) (MIT, [jakegut/resume](https://github.com/jakegut/resume)) is a reasonable typographic reference for the `STANDARD` variant and nothing else. Take from it: single-column with no tables, columns, images, or icons; tight vertical rhythm; dates right-aligned against left-aligned entries. Its `\resumeSubheading{Title}{Date}{Organization}{Location}` macro maps 1:1 onto our entry schema (title, dates, institution, city+country) — independent confirmation the four-axis entry shape is right.

**Its stated purpose does not transfer, and must not be imported with the layout.** It is a tech-job résumé optimized for employer ATS parsers (Greenhouse, Lever, Workday, Taleo) — see its own source comment, "Ensure that generate pdf is machine readable/ATS parsable". No admissions portal documents CV parsing (R-043), so that goal is inert here. Concretely, do not import from it:

- its one-page cap (violates R-054; R-024 allows 2–3pp research-track; R-012 allows 3pp at DAAD)
- any keyword optimisation for parsers (violates R-055)
- its section set — Education / Experience / Projects / Technical Skills carries no publications, thesis+supervisor, teaching (fails archetype D, R-027/R-039), and no languages/CEFR grid or personal-data block (fails archetypes A and B, R-041/R-029/R-030/R-031)

The one technical detail worth carrying regardless of renderer: it sets `\pdfgentounicode=1` to guarantee a Unicode-extractable text layer. That is our R-043 requirement expressed in LaTeX; whichever renderer we pick must give the same guarantee, and the test at step 5 below is what proves it.

### Storage (`apps/documents/storage.py`)

Rendered artefacts go to S3 with tenant-prefixed keys, satisfying requirements §3.4's "isolate tenant object-storage prefixes". `boto3[crt]` is already a dependency and `EVIDENCE_BUCKET_NAME` is the existing precedent, so add `DOCUMENT_BUCKET_NAME` beside it in `config/settings/base.py`.

Key layout — tenant first, so a prefix-scoped IAM policy or a prefix delete covers a whole tenant:

```
{tenant_id}/students/{student_id}/documents/{draft_id}/{filename}
```

Rules:
- Objects are private; never public-read. Downloads go through a Django view that re-checks tenant context and membership, not a public URL.
- The key is derived from `current_tenant_id()` at write time, never from user input, and a write whose derived tenant differs from the draft's tenant raises rather than writing.
- Uploaded originals (CV Polish) live under a separate `.../uploads/` prefix and are only moved out of quarantine after a clean malware scan.

**Objects do not cascade.** `TenantScopedModel`'s tenant FK cascades the database rows, so `VerifiedFact` and `DocumentDraft` are purged with the tenant for free — but S3 objects are not, and would silently outlive a deletion request. `apps/audit/deletion.py`'s `advance_deletion` must therefore also delete the tenant's object prefix, and a test must assert the prefix is empty after deletion. This is the one place where "it cascades" is wrong and quietly leaves personal data behind.

### Audit (`apps/audit` / `AuditEvent`)

P1-14 requires every automated, counselor and student action as an append-only event including affected object versions and the approval decision. `AuditEvent` already exists (`apps/funding/models.py:189`) with an established pattern — `AuditEvent.objects.create(actor=..., event="...", object_id=...)` — and it is sufficient here without extension, because `DocumentDraft` is append-only and versioned: **`object_id = draft.id` is itself the version reference.**

Events: `document.generated`, `document.approved`, `document.rejected`, `document.revision_requested`, `fact.confirmed`, `fact.superseded`, `document.format_unverified` (the fail-closed flag from the resolution ladder).

P1-14 also says to exclude "unnecessary document content" from audit records, so events carry identifiers and decisions only — never CV text, never the generation prompt, never model output.

**Approval invalidation** (§4.2.1: "Invalidate approval whenever the approved document changes") falls out of append-only storage rather than needing its own mechanism: a change *is* a new `DocumentDraft` row, so approval never transfers. On a new version the prior draft moves to `SUPERSEDED` and the new one starts at `DRAFT`. There is no code path that mutates an `APPROVED` draft — that is the invariant the test asserts.

### Master's-level AI-disclosure policy (R-050)

No CV-specific or master's-level AI-use policy was found in either research pass — everything cited is US undergraduate essay policy. Do not build an attestation/watermark feature speculatively. Revisit if a specific funder's checklist is found to require one.

## Testing strategy (TDD order)

1. `VerifiedFact` append-only + supersession chain; tenant isolation (missing/wrong tenant context rejected)
2. `verify_against_facts` **classifies rather than raises**: a claim with no matching fact returns `UNSUPPORTED` and the draft is still created; an evidence-backed confirmed fact returns `SUPPORTED`; an attested-only fact returns `UNCERTAIN`; contradictory dates return `CONFLICTING`. Assert all four states.
3. **Blocking is at use, not creation**: a draft carrying `UNSUPPORTED` or `CONFLICTING` cannot be marked ready for an application, but exists and is inspectable. `UNSUPPORTED` cannot be overridden by anyone; `UNCERTAIN` can, and the override writes an audit record naming the counselor.
4. **Retry is bounded to one**: a generation whose first pass returns `UNSUPPORTED` triggers exactly one retry and no more, even if the second pass also fails; both passes run the deterministic gate; both count against the rate limiter.
5. **Student statements never render as supported**: a `STUDENT_STATEMENT` fact produces `UNCERTAIN`, never `SUPPORTED`, however it was collected. Assert this for both a consultant answer and a claim extracted from an applicant-written CV — an applicant's own CV must not be laundered into evidence.
6. Revision-round cap: 3rd `STYLE_STRUCTURE` request rejected; `FACTUAL_CORRECTION` without `superseding_fact` rejected; unlimited `FACTUAL_CORRECTION` with valid superseding facts accepted
7. `render_variant` selection: each of the five `cv_format_requirement` values produces the matching variant; a `[v1-only]`/unverified CSV row cannot set `EUROPASS_REQUIRED` without override
8. PDF output contract: text extractable, unencrypted, under the size ceiling
9. Generation rate limiting: Nth call within the window rejected
10. **Uncatalogued programme fails closed**: a programme with no ruleset row and no reachable page renders `STANDARD`, stamps `cv_format_confidence = UNVERIFIED`, and raises a counselor red flag — it never silently picks a variant. Same for an extraction whose confidence is below threshold, and for conflicting signals.
11. **Verified beats extracted**: where both a ruleset row and an extracted value exist for one programme, the ruleset row wins and the extracted value is retained for audit, not applied.
12. **Constraint pre-flight blocks a bad artefact**: a render exceeding `max_pages`, `max_bytes` or `max_entries_per_section`, missing a `required_fields` entry, or containing `prohibited_content` cannot be marked ready and produces a blocking flag. Assert on a real rendered file, not on the content object — a rule enforced only against the model is not enforced.
13. **Unconfirmed facts are invisible to generation**: a bridged or upload-extracted fact with `confirmed_by = NULL` cannot satisfy `verify_against_facts` and cannot appear in a draft. A fact the student stated to the consultant is confirmed by that act and is usable as `UNCERTAIN`.
14. **Profile bridge is idempotent**: running it twice over an unchanged `StudentProfileVersion` creates no new rows; running it after a changed value creates exactly one superseding row.
15. **Upload ingestion order**: a file failing the malware scan is quarantined and never reaches extraction or the normal storage prefix.
16. **Storage isolation**: keys are tenant-prefixed and derived from `current_tenant_id()`; a write whose derived tenant differs from the draft's tenant raises. Downloads re-check membership.
17. **Deletion purges objects**: after `advance_deletion`, the tenant's S3 prefix is empty — not just its database rows.
18. **Audit records carry no document content**: generated events reference IDs only; assert CV text, prompts and model output never appear in an `AuditEvent`.
19. **Approval never transfers**: no code path mutates an `APPROVED` draft; a new version leaves the old `SUPERSEDED` and starts at `DRAFT`.
20. **Consent-to-send modes**: under `PER_DOCUMENT` a draft cannot be released without student consent; under `COUNSELOR_APPROVES` counselor approval releases it, and the mode grant exists as a recorded approval event. Assert neither mode can release a document whose facts are unconfirmed, and that the mode never extends to attestation.
21. **Enforcement tiers**: a `BINDING` violation is blocked with no override path reachable by student or counselor; an `ADVISORY_HIGH_RISK` violation is overridable by the student only, and the stored `risk_text_shown` matches what was displayed; an `ADVISORY_STYLE` preference is honoured with no warning and no record.
22. **Overrides never travel**: an override on programme A does not suppress the same rule on programme B for the same student. Assert with R-032 (photo) across a US and a German destination.
23. **Summary is Europass-only**: `summary` is emitted by the `EUROPASS` variant and by no other. Assert `STANDARD`, `GERMAN_TABULAR` and `FUNDER_TEMPLATE` omit it even when `CVContent.summary` is populated, and that a summary claim is verified against facts like any other content.
24. **Counselor quick-edit is not a revision round**: a counselor hand edit does not increment the `STYLE_STRUCTURE` count and stays available after the 2-round cap is reached.
25. End-to-end: facts → generate → gate → approve → revise → regenerate → distinct filename, version incremented
26. Tenant isolation across every model and service above (background-job and export paths too, per §3.4)

## Open decisions for the implementation plan

- PDF rendering library (WeasyPrint vs headless-Chromium vs ReportLab) — pick based on font-embedding and text-layer guarantees, not covered here. **LaTeX was considered and is not recommended**, despite being the obvious inheritance from Jake's Resume above: it is Turing-complete, so compiling LLM-generated and student-supplied content is a live injection surface (`\input`, `\write18`) needing `-no-shell-escape`, sandboxing, and hand-escaping of ten special characters, where an HTML renderer gets escaping for free from template autoescaping. It also solves one of five variants well and four badly — Europass, German tabular, and `FUNDER_TEMPLATE` (filling someone else's DOCX headings) are layout problems LaTeX makes harder, and `FIELD_MAPPED` is not a PDF at all. If this is revisited, the security argument is the one to answer first.
- Rate-limit `limit`/`window_seconds` values for CV generation — no existing precedent in `apps/funding/views.py` to copy verbatim; needs a product call.
- CSV-loader management command for `cv_format_requirement` seeding — one-off script, not a recurring sync job, per the "no scaffolding for later" rule; a real per-cycle reverification job is a separate later decision, not built now.

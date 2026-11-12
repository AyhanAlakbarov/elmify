# Document fact reading, plan 3 of 3: the co-pilot's one-tap offer, upload prompts and marks

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- A portal box we hold no confirmed value for, where a document read left a doubtful one, shows
  "We read X from your passport — use it?" in the panel. One tap confirms that value and types
  it.
- A box no upload could supply says "Upload your passport once…" with a link to the dashboard.
- An expired passport says so.
- Every box filled from a document read is marked "From your passport" (or diploma, or
  certificate).

**Architecture:**
- **Server.** The packet's hints gain `offer`, `upload_kind` and `expired_on`, and its entries
  gain `source_kind`. All of it is computed in `mint_packet` from plan 1's ledger rows
  (`source_ref="document:<id>"`; unconfirmed = doubtful). The PACKET step records each offered
  `fact_id` and stays the authority.
- **Confirm route.** `POST /ext/applications/<app>/facts/<fact>/confirm` accepts only a fact
  that the latest PACKET step offered. It writes the tapped value as a new confirmed row through
  `fact_writer.use_document_value`, superseding the waiting row, with the student as actor. It
  then returns the value formatted for this portal.
- **Extension.** The service worker attaches each offer to the dock row from its own cached
  packet, never from the page. The panel's Use button goes panel → worker → confirm route → the
  bound tab's content script. The content script types the one box through the same verify →
  fill → read-back path as every entry. The co-pilot types; it never clicks.

**Tech Stack:** Django, Pydantic, TypeScript (MV3 extension, esbuild via `extension/build.mjs`),
Playwright e2e (`-m extension`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-document-fact-reading-design.md`: §3 step 2, §7.2–7.5
and §10 (extension e2e). It builds on plan 1
(`docs/superpowers/plans/2026-10-12-document-fact-reading-1-passport.md`). From plan 1 it uses:
- the `VerifiedFact` document-read rows;
- `verified_values` / `_id_document_values`, `verification.id_document_groups` / `id_documents`
  and `disowned_refs`;
- `apps/portals/fact_reading.KIND_FOR_PREFIX`.

Plan 2 (diplomas and certificates) is built. Its kinds appear here as data (`DIPLOMA`,
`LANGUAGE_CERTIFICATE`), and this plan uses two of its pieces: `fact_writer.needs_typing` (no tap
writes an unread date) and `fact_labels.FIELD_LABELS` (the keys a document read writes).

## Reconciled with plan 1 as built (2026-10-13)

Plan 3 was first written against plan 1's original text. Plan 1 was then built at HEAD `bea2089e`
with many review rulings (`.superpowers/sdd/2026-10-12-document-fact-reading-1-passport/progress.md`).
Every task below was checked against that code. Where plan 3's first design conflicted with a
plan-1 ruling, the ruling won. What changed:

- **Task 1: offers.** `document_offers` drops every document `disowned_refs` names, so a passport
  whose latest read is `owner_mismatch` serves and offers nothing. This is the plan-1 carry item.
  It also drops every value whose reading carries `owner_unknown`. Plan 1 settles an
  `owner_unknown` read only by a clean re-read of the same file, so no such value is one tap from
  a portal.
- **Task 1: offers come from one document.** `id_document.*` and `identity.citizenship` are
  offered only from the one document portals are served. Plan 1's `_id_document_values` choice is
  extracted, unchanged, as `_picked`. When no document is served, the offer comes from the
  student's latest own passport read. This follows the owner's ruling of 2026-10-13: number,
  expiry and citizenship travel together. The first design offered any document's waiting value,
  which could put passport B's issue date beside passport A's number. No `id_document.*` value is
  offered while every passport is expired.
- **Task 1: marks.** `document_sources(student, values)` now marks a served value when a
  confirmed document read holds exactly that value. The first design took the last row, which
  for `id_document.*` and citizenship could disagree with the document `verified_values` picks
  (the chosen passport, dedup by number, the student's own entry).
- **Task 1: expiry.** `expired_id_document` counts documents through `verification.id_documents`
  (per document, re-uploads merged, disowned excluded), as portals do. It no longer counts per row.
- **Task 1: uploads.** A disowned passport does not count as "uploaded", so the box still asks
  for the student's own.
- **Task 1, Step 6b, carry item.** Before `FACT_READING_ENABLED` is on, the SQS enqueue in
  `mint_packet`'s hook uses a client with 2 s / 3 s timeouts and one attempt.
- **Task 2, carry item.** A Use tap makes the tapped value the one served next. The route no
  longer confirms in place with `confirm_facts`, because `verified_values` and
  `id_document_groups` let the newest row win, and an in-place confirmation keeps its old
  `created_at`. It calls `fact_writer.use_document_value`, which writes a new confirmed row
  superseding the waiting one. That is plan 1's own rule for a proof ("a new row, never confirm
  in place"). A second tap finds the row superseded and gets 404, as do a racing tap
  (`IntegrityError`) and a fact whose document was disowned after the packet was minted. This
  departs from spec §7.3's "calls `confirm_facts`". The audit event is still `fact.confirmed`
  with the student as actor.
- **Task 5.** The CLAUDE.md bullet goes after the "Built, 2026-10-12" record's
  `FACT_READING_ENABLED` bullet and names `use_document_value`.
- **Unchanged:** Tasks 3 and 4. Plan 1 did not touch `extension/`. Plan 1 added no extension
  label tokens, so Task 3 Step 5 is still needed. Plan 2 Task 1 adds the language and diploma
  tokens to the same table.

## Reconciled with plan 2 and master as built (2026-10-14)

Since the reconcile above, plan 2 was built with its own rulings
(`.superpowers/sdd/2026-10-12-document-fact-reading-2-diploma-certificate/progress.md`), and
origin/master (164 commits) was merged in at `0412e2d8` (fixes to `4e8e67fa`, report at
`.superpowers/sdd/2026-10-12-document-fact-reading-3-copilot/merge-report.md`). Every step below
was re-read against HEAD. Two rulings still being built are treated as true: a retired
`DocumentVersion` (master's replace flow, `retired_at`) counts as disowned through
`verification.disowned_refs`, and the passport upload form gains "add another passport". What
changed:

- **Task 1: one place decides "offered".** `document_offers` now also drops every `id_document.*`
  value while every ID document has expired. That rule moved out of `mint_packet`, so the confirm
  route (Task 2) can ask the same function at tap time.
- **Task 1: no tap writes an unread date** (plan 2 ruling, final review I3).
  `document_offers` skips any value `fact_writer.needs_typing` refuses. Test
  `test_a_date_the_code_could_not_read_is_never_offered` is new.
- **Task 1: one value per row.** Offers come only from one-key waiting rows (`len(payload) == 1`).
  A passport's waiting rows are always one key (`_write_person_value`, `_write_id_document`), so
  nothing is lost. The rule says in code what the global constraint says in words.
- **Task 1: `owner_unknown` is read as the dashboard reads it** (plan 2 ruling: offered on no
  surface). The first text blocked a (document, key) when *any* reading ever marked it. Now the
  latest reading's `why` per (document, key) decides, later readings winning, exactly as
  `documents/views.py` builds `snippets`. A clean re-read of the same file lifts it, as plan 1
  ruled.
- **Task 1: an upload prompt only where an upload can fill the box.** `KIND_FOR_PREFIX` maps every
  `identity.*` key to PASSPORT, so the first text told a student to upload a passport for their
  phone number. `upload_kind` is now set only when `field_class(field)` is in
  `fact_labels.FIELD_LABELS`, which lists exactly the keys a document read writes. That reuses
  plan 2's table rather than adding a second list. `test_nothing_uploaded_asks_for_the_upload_once`
  gains an `identity.phone` hint that gets no prompt.
- **Task 1: an unsure hint carries no `upload_kind` and no `expired_on`.** The first text gave an
  unsure box an upload prompt the content script then hid behind `our_guess`. The packet now says
  only what the panel shows.
- **Task 1: replaced and second passports.** `held_kinds` excludes disowned documents, and with
  the in-flight ruling that includes retired ones. New test
  `test_a_replaced_passport_offers_nothing_and_does_not_count_as_held` pins it. Master's
  `register` defaults a passport to REPLACE and refuses a third with `replace_which`, so the
  two-passport test registers the second one with `mode="ADD"` through a local `_add_upload`
  helper, as the merge did for the reading tests.
- **Task 1: imports at HEAD.** `packets.py` already imports `DocumentVersion` from
  `apps.concierge.models` (it gains `UPLOAD_REJECTIONS`) and `request_fact_reading` from
  `.fact_reading`. `profile.py` gains `from apps.documents.fact_writer import needs_typing`.
  `packets.py` gains `FIELD_LABELS` and `field_class`. `_id_document_values` at HEAD is exactly
  the code the `_picked` refactor assumes. `mint_packet`'s hint branch now first types back the
  student's own earlier answer (`from_answer`, master), so an offer appears only on a box with no
  earlier answer. The plan's code goes after that `continue`.
- **Task 1, Step 7: the exact hints assertion.** It is
  `tests/portals/test_packet.py::test_a_fact_the_student_lacks_is_a_hint_and_blocks_nothing`, the
  only one. It gains `"offer_fact_id": ""`.
- **Task 2: the route re-asks `document_offers`** instead of re-querying
  `unsuperseded_facts`/`disowned_refs` itself. A fact must have been offered by the latest PACKET
  step *and* still be offered now. That covers, in one call, a passport disowned, replaced, read
  `owner_unknown` or expired since the packet was minted, and the unread-date rule.
  `test_a_passport_disowned_after_the_packet_is_refused` is parametrised over `owner_mismatch` and
  `owner_unknown`. The route catches `FactNotFound` as well as `IntegrityError`. The first text
  let `FactNotFound` from `use_document_value` escape as a 500.
- **Task 2: `use_document_value` is not in plan 2.** Plan 2 built `adopt_document_value`, which
  supersedes a *confirmed target row* with the reading's value for one key. That is a different
  operation, and the waiting passport rows have no target. So the function is still added here,
  under the name the plan-2 ruling and spec amendment use. It now refuses anything but a one-key,
  unconfirmed, current IDENTITY or ID_DOCUMENT row of a document the student owns. It also refuses
  a value `needs_typing` refuses. A whole-document row (`placed_whole_rows`, `held_whole_rows`)
  therefore can never be confirmed through it, by construction.
- **Task 2, Step 5:** also runs `tests/documents/test_fact_writer_documents.py`.
- **Task 2: the spec is amended.** §7.3 now says the tap writes a new confirmed row through
  `fact_writer.use_document_value`. That is the plan-2 ruling's owed amendment, made in this
  commit.
- **Task 3: the one-box fill is verified against the whole packet.** `useOffer` called
  `verifyEntries([entry])`, which judges the label against that one field only. The run judges
  against every entry's class, so a box whose label also fits another packet field is refused as
  `ambiguous_name`. It now calls `verifyEntries([...packet.entries, entry])` and keeps the last
  verdict, so "exactly as an entry" is true.
- **Task 3, Step 5: no vitest exists in `extension/`.** The birth-label case is now a concrete e2e
  test, `test_a_passport_s_two_birth_boxes_each_verify_as_their_own`, beside the certificate
  verify tests (`_verify_in_page`, `page.set_content`). No existing test pins the bare `birth`
  token. Master added IDENTITY `given_name` (file names). The new `given_names` tokens equal
  `given_name`'s, so a map naming both on one page refuses both boxes (`ambiguous_name`). That
  fails closed, and is accepted.
- **Task 3: the e2e tap test also checks the mark text** ("From your passport" on focus), which
  is spec §10's "a fill and a mark".
- **Task 4: `k_PASSPORT`, `k_DIPLOMA` and `k_LANGUAGE_CERTIFICATE` already exist** in
  `panel/i18n.ts`. They are master's `kindLabel` nouns ("Passport"), and the first text's keys
  would be duplicate object keys, which is a tsc error. The upload-sentence nouns are renamed
  `u_PASSPORT`, `u_DIPLOMA` and `u_LANGUAGE_CERTIFICATE`, and `reasonText` reads `u_${upload_kind}`.
- **Task 4: the panel's field labels for plan 1's keys.** `fieldLabel` falls back to the bare key
  ("number", "expiry date"), in English in every language. Without labels, every row this plan
  adds would read like that. Step 5 adds the ten passport keys to `LABELS` in all four languages.
- **Task 4: the link opens `#upload`, not `#details`.** Both prompts ask for an upload, and
  `templates/student/_documents.html` has an `id="upload"` section with the form. "Your details"
  (`#details`) lists values read.
- **Task 4:** the worker's handlers live in `handle()` at HEAD, next to `choice:answer`. The
  `messageRefusal` additions go after its `review:open` block. The dock filter is still the
  one-line `filter`, and `hintsByKey` is built beside `keys`. Neither `offer:use` nor
  `open:documents` collides with master's messages. Master's `OPEN_UPLOAD_PAGE` device action opens
  the *portal's* upload page and is unrelated.
- **Task 5:** the record now lives in `.claude/rules/portals.md`, under "Built, 2026-10-12: reading
  a student's documents into facts". The bullet goes last in that list, after "Every Azure answer
  counts toward the shared daily page ceiling", and names `document_offers` as the one gate.
- **Unchanged, checked at HEAD:**
  - Step 6b (master added no short-timeout SQS client; `apps/queue.enqueue` still builds
    `boto3.client("sqs")`);
  - `_record_packet`'s hints comprehension;
  - `_device_endpoint`, `_limit`, `_application_for` and `_ApiError` (master added the
    `processing_stopped` / `acceptance_required` refusals, which this route inherits);
  - `contentLabels`, `FieldRecord.hint`, the hint loop's `reason:` expression, the `lastRun` shape;
  - `fillVerified` / `readBack` signatures and `shownActiveBinding` / `cachedPacket` / `dashboardOrigin`;
  - every e2e helper the tests use (`_run_with_stubbed_messaging`, `_last_dock_with`,
    `_load_worker`, `_send`, `_calls`, `_open_panel`, `_push_state`, `_portal_packet`, `_binding`,
    `PANEL_SENDER`, `CONTENT`, `APP_A`, `DASHBOARD`);
  - `MIN_EXTENSION_VERSION` stays `0.2.0`.

### Open for the controller

1. **The dashboard's Use on a passport value still confirms in place.** The "details to check"
   row posts to `/api/documents/facts/confirm` (`confirm_facts`), the defect plan 1 ruled out for
   the panel. Recommended: in Task 2, route a one-key IDENTITY/ID_DOCUMENT document row's Use
   through `use_document_value` too (a small view change), so both surfaces serve the tapped value
   next.
2. **The hook still queues a retired upload for reading.** `fact_reading._request` filters only
   `state="AVAILABLE"`, so it pays Azure to read a replaced passport whose facts are then
   disowned. Recommended: add `retired_at__isnull=True` in Step 6b, unless the in-flight
   retired-is-disowned change already does.
3. **The panel has no labels for plan 2's diploma and certificate keys.** "test name" and
   "cefr level" show in English in every language. Recommended: add them to `LABELS` in Task 4
   Step 5, beside the passport rows.
4. **A diploma value attached into a CV degree carries no "From your diploma" mark.** `_attach`
   keeps the CV row's STUDENT_STATEMENT tier, and `document_sources` marks only AUTHORITATIVE
   rows, which is also what keeps a student's correction unmarked. Recommended: accept. The mark
   is reassurance only, and under-marking fails closed.
5. **Spec §7.3 still writes the route as `/ext/facts/<fact_id>/confirm`.** Plan 3 rules the
   application into the path. Recommended: amend the spec's path too, in the same one-line style
   (not done here: only the confirm amendment was asked for).

## Global Constraints

- Run everything from the worktree `/home/orkhan/Desktop/fact-reading`, with `git -C` for git.
  Tests: `POSTGRES_DB=elmify_fact_reading uv run pytest -q`. Extension:
  `npm --prefix extension run typecheck && npm --prefix extension run build && npm --prefix extension run build:test`,
  then `POSTGRES_DB=elmify_fact_reading uv run pytest -q -m extension tests/portals/test_extension_e2e.py`.
- Lint `uv run ruff check .` (never `ruff format`); types `uv run mypy apps config`.
- **The co-pilot never clicks** a portal control. The one tap is the student's press in our own
  panel; the extension then types one value into one box.
- **No `chrome.storage` in content scripts.** Messages carry codes, never sentences.
- **A value reaches the page from the server only.** The worker takes the offer from its cached
  packet and the typed value from the confirm route's answer. Nothing the page sends can name a
  value, a fact id or a box.
- **Offers come only from unconfirmed, unsuperseded document-read facts** (`source_ref` starts
  with `document:`) in category **IDENTITY or ID_DOCUMENT**, for **unindexed** keys, on hints
  whose reason is `no_fact`, and only of documents the student owns:
  - never a disowned document (`verification.disowned_refs`);
  - never a value its reading marked `owner_mismatch` or `owner_unknown`;
  - `id_document.*` and `identity.citizenship` only from the one document portals are served;
  - one value per row, and never a value `fact_writer.needs_typing` refuses (an unread date);
  - no `id_document.*` offer while every passport is expired.

  `profile.document_offers` is the one function that decides this. `mint_packet` and the confirm
  route both ask it. Plan 2 holds doubtful diploma and certificate values on the
  `DocumentReading`, adopted through `adopt_document_value`, or as one whole-document row. A tap
  on one box must never confirm values the student did not see, so those values are settled on
  the dashboard. Their boxes keep the red hint, plus the upload prompt when nothing is
  uploaded. A panel offer for them is a follow-up that would call `adopt_document_value`. An `unsure` hint
  never gets an offer, an upload prompt or an expiry line: the map is not sure of the box, so
  putting a value in it would be a guess.
- An upload prompt (`upload_kind`) is set only for a key a document read writes
  (`fact_labels.FIELD_LABELS`): a passport never fills a phone box.
- `source_kind` is one of `passport`, `diploma`, `certificate`, mapped from the upload kind
  `PASSPORT`, `DIPLOMA`, `LANGUAGE_CERTIFICATE`.
- Rate limit for the confirm route: 30 an hour per membership, bucket `ext-fact-confirm`.
- Panel and mark strings exist in all four languages (az, tr, ru, en).
- `MIN_EXTENSION_VERSION` is **not** bumped. Every new packet field is optional with a default.
  An older extension ignores an offer, and the student types the box as they do today. Nothing
  is unsafe for a client that does not understand it.

## Review Focus

1. **A forged `offer:use` from a portal page, or a forged dock row carrying its own value or
   fact id.** It must be refused at the worker boundary (`untrusted_sender`), and the dock row's
   offer must be overwritten from the cached packet. Owner: Task 4.
2. **A double tap, or a tap after the packet was re-minted.** The second confirm must answer 404
   and type nothing new. A tap whose fact the latest PACKET no longer offers, or that
   `document_offers` no longer offers now (disowned, replaced, `owner_unknown`, expired), must
   answer 404. Owner: Task 2.
3. **A box the student already typed into before the tap.** The content script must never type
   over a held value (the `fillVerified` rule): the tap reports failure and the box stays the
   student's. Owner: Task 3.
4. **A student-corrected value** (`STUDENT_STATEMENT` with a `document:` source_ref). It must not
   be marked "From your passport": it is theirs. Owner: Task 1.
5. **An expired-only passport.** No `id_document.*` value may be typed, and the box must say it
   expired, with the date. Owner: Task 1.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/portals/profile.py` (modify) | `_picked` (extracted from `_id_document_values`), `document_sources`, `document_offers`, `expired_id_document`, `SOURCE_KINDS` |
| `apps/portals/fact_reading.py` (modify) | the hook's SQS client with short timeouts (plan 1 carry item) |
| `apps/documents/fact_writer.py` (modify) | `use_document_value`: a tap is a new confirmed row, never confirmed in place |
| `apps/portals/packets.py` (modify) | `PacketOffer`; new fields on `PacketHint` and `PacketField`; `mint_packet` fills them; `_record_packet` records `offer_fact_id` |
| `apps/portals/ext_api.py`, `apps/portals/urls.py` (modify) | `confirm_offer` route |
| `extension/src/types.ts` (modify) | `PacketOffer`, the new hint/entry/FieldView fields |
| `extension/src/content/index.ts` (modify) | hint reasons, `fromDocument` marks, `useOffer`, the `offer:fill` listener, test hook |
| `extension/src/content/labels.ts` (modify) | "From your passport/diploma/certificate" mark text |
| `extension/src/content/vocabulary.ts` (modify) | label tokens for plan 1's new identity and ID-document keys |
| `extension/src/api.ts` (modify) | `confirmOffer` |
| `extension/src/service_worker.ts` (modify) | `offer:use`, `open:documents`, offers attached in the dock filter |
| `extension/src/panel/panel.ts`, `panel/i18n.ts` (modify) | Use and Open-my-documents buttons; the new strings and the passport field labels in four languages |
| `tests/portals/fixtures/passport_form.html` (create) | an e2e form with passport boxes |
| `tests/portals/test_packet_offers.py`, `tests/portals/test_fact_offer_api.py` (create) | server tests |
| `tests/portals/test_packet.py`, `tests/portals/test_fact_reading_hook.py` (modify) | the step's new `offer_fact_id` key; the hook's short-timeout client |
| `tests/portals/test_extension_e2e.py` (modify) | content, worker and panel tests |
| `.claude/rules/portals.md` (modify) | the one-tap rule, in the fact-reading record |

---

### Task 1: The packet carries offers, upload prompts, expiry and document marks

**Files:**
- Modify: `apps/portals/profile.py`
- Modify: `apps/portals/packets.py` (`PacketHint`, `PacketField`, new `PacketOffer`, `mint_packet`, `_record_packet`)
- Test: `tests/portals/test_packet_offers.py`

**Interfaces:**
- Consumes (plan 1 as built):
  - `VerifiedFact` rows with `source_ref="document:<DocumentVersion id>"`;
  - `verification.unsuperseded_facts`, `id_document_groups`, `id_documents` and `disowned_refs`;
  - `profile._id_document_values` and `_document_citizenship`;
  - `DocumentReading.values` why-codes `owner_mismatch` / `owner_unknown`;
  - `fact_reading.KIND_FOR_PREFIX: tuple[tuple[str, str], ...]`;
  - plan 2: `fact_writer.needs_typing(key, value) -> bool` and `fact_labels.FIELD_LABELS`;
  - master: `concierge.models.UPLOAD_REJECTIONS`, and `concierge.documents.register(..., mode="ADD")`
    in tests.
- Produces:
  - `profile.SOURCE_KINDS: dict[str, str]`;
  - `profile._picked(student, groups) -> str | None` (the served ID document's ref);
  - `profile.document_sources(student, values) -> dict[str, str]` (profile field → source kind,
    for the served values a document read proved);
  - `profile.document_offers(student) -> dict[str, Offer]`, where
    `Offer = (fact_id: UUID, value: str, source_kind: str)` is a NamedTuple;
  - `profile.expired_id_document(student) -> str` (an ISO date, or "");
  - `packets.PacketOffer(fact_id, value, method, source_kind)`;
  - `PacketHint.offer: PacketOffer | None`, `PacketHint.upload_kind: str`,
    `PacketHint.expired_on: str`;
  - `PacketField.source_kind: str`;
  - the PACKET step's `detail["hints"][i]["offer_fact_id"]` (a string id or "").

- [ ] **Step 1: Write the failing tests**

```python
# tests/portals/test_packet_offers.py
"""Spec 2026-10-12 §7.2: what a packet says about values read from the student's
own documents."""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.documents.models import VerifiedFact
from apps.tenancy.context import tenant_scope
from tests.portals.test_kit import _application
from tests.portals.test_packet import _clean_upload

pytestmark = pytest.mark.django_db


def _entry(field, selector, sure=True):
    return {"profile_field": field, "sure": sure,
            "action": {"selector": selector, "method": "fill", "arguments": ["%value%"]}}


def _fact(student, document, category, payload, *, confirmed, tier="AUTHORITATIVE_DOCUMENT"):
    return VerifiedFact.objects.create(
        student=student, category=category, payload=payload, source_tier=tier,
        source_ref=f"document:{document.id}", confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None, created_by=student,
    )


def _hint(packet, field):
    return next(h for h in packet.hints if h.profile_field == field)


def _add_upload(agency, student, kind="PASSPORT"):
    """A clean upload added beside the one held (master's replace-or-add form: a dual
    national holds two passports; a plain register would REPLACE the first)."""
    from apps.concierge.documents import register
    from apps.concierge.models import DocumentVersion

    document = register(agency.id, student.id, kind=kind, mode="ADD")
    DocumentVersion.objects.filter(id=document.id).update(
        state="AVAILABLE", scan_result="NO_THREATS_FOUND", promoted_key=f"p/{document.id}",
        content_type="application/pdf",
    )
    return document


def test_a_doubtful_read_is_offered_on_its_hint_and_recorded(agency_a, membership_a):
    from apps.portals.models import ApplicationStep
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        fact = _fact(membership_a, passport, "IDENTITY", {"date_of_birth": "1998-03-14"},
                     confirmed=False)
        application = _application(agency_a, membership_a,
                                   entries=[_entry("identity.date_of_birth", "#dob")])
        packet = mint_packet(application)
        step = ApplicationStep.objects.get(application=application, kind="PACKET")
    hint = _hint(packet, "identity.date_of_birth")
    assert hint.reason == "no_fact" and hint.offer is not None
    assert (hint.offer.fact_id, hint.offer.value, hint.offer.method, hint.offer.source_kind) == (
        fact.id, "1998-03-14", "fill", "passport")
    assert step.detail["hints"][0]["offer_fact_id"] == str(fact.id)
    assert "1998-03-14" not in str(step.detail["hints"])  # the step names the fact, not the value


def test_an_unsure_box_is_never_offered_a_value(agency_a, membership_a):
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "IDENTITY", {"date_of_birth": "1998-03-14"},
              confirmed=False)
        application = _application(
            agency_a, membership_a, entries=[_entry("identity.date_of_birth", "#dob", sure=False)])
        packet = mint_packet(application)
    assert _hint(packet, "identity.date_of_birth").offer is None


def test_nothing_uploaded_asks_for_the_upload_once(agency_a, membership_a):
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=[
            _entry("id_document.number", "#pno"), _entry("identity.phone", "#tel")])
        packet = mint_packet(application)
        _clean_upload(agency_a, membership_a, "PASSPORT")
        again = mint_packet(application)
    assert _hint(packet, "id_document.number").upload_kind == "PASSPORT"
    # identity.* maps to PASSPORT for the hook, but no passport fills a phone box.
    assert _hint(packet, "identity.phone").upload_kind == ""
    assert _hint(again, "id_document.number").upload_kind == ""  # uploaded, reading pending


def test_an_expired_passport_says_so_and_is_never_typed(agency_a, membership_a):
    from apps.portals.packets import mint_packet

    expired = (date.today() - timedelta(days=30)).isoformat()
    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "ID_DOCUMENT",
              {"document_type": "passport", "number": "OLD1", "expiry_date": expired},
              confirmed=True)
        application = _application(agency_a, membership_a,
                                   entries=[_entry("id_document.number", "#pno")])
        packet = mint_packet(application)
    assert packet.entries == ()
    assert _hint(packet, "id_document.number").expired_on == expired


def test_a_value_proven_by_a_document_is_marked_and_a_corrected_one_is_not(agency_a,
                                                                          membership_a):
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "IDENTITY", {"date_of_birth": "1998-03-14"},
              confirmed=True)
        _fact(membership_a, passport, "IDENTITY", {"place_of_birth": "Baku"}, confirmed=True,
              tier="STUDENT_STATEMENT")
        application = _application(agency_a, membership_a, entries=[
            _entry("identity.date_of_birth", "#dob"), _entry("identity.place_of_birth", "#pob")])
        packet = mint_packet(application)
    kinds = {e.profile_field: e.source_kind for e in packet.entries}
    assert kinds == {"identity.date_of_birth": "passport", "identity.place_of_birth": ""}


def _read_as(student, document, why):
    from apps.documents.models import DocumentReading

    return DocumentReading.objects.create(
        student=student, document=document, kind="PASSPORT", reader_version="id-1",
        state="READ", file_sha256=f"sha-{document.id}",
        values=[{"key": "identity.date_of_birth", "value": "1998-03-14", "snippet": "",
                 "proven": False, "why": why}])


@pytest.mark.parametrize("why", ["owner_mismatch", "owner_unknown"])
def test_a_passport_not_tied_to_the_student_offers_nothing(agency_a, membership_a, why):
    """Carried from plan 1: no one-tap path for a value whose reading could not tie the
    passport to this student. owner_mismatch disowns the document (verification.
    disowned_refs), so it is not "held" either and the box asks for the student's own."""
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "IDENTITY", {"date_of_birth": "1998-03-14"},
              confirmed=False)
        _read_as(membership_a, passport, why)
        application = _application(agency_a, membership_a,
                                   entries=[_entry("identity.date_of_birth", "#dob")])
        packet = mint_packet(application)
    hint = _hint(packet, "identity.date_of_birth")
    assert hint.offer is None
    assert hint.upload_kind == ("PASSPORT" if why == "owner_mismatch" else "")


def test_a_passport_value_is_offered_only_from_the_passport_portals_get(agency_a,
                                                                        membership_a):
    """Number, expiry and citizenship travel together (owner, 2026-10-13): a second
    passport's waiting values are never offered beside the served passport's."""
    from apps.portals.packets import mint_packet

    future = (date.today() + timedelta(days=900)).isoformat()
    with tenant_scope(agency_a.id):
        served = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, served, "ID_DOCUMENT",
              {"document_type": "passport", "number": "C01", "expiry_date": future},
              confirmed=True)
        other = _add_upload(agency_a, membership_a)
        _fact(membership_a, other, "ID_DOCUMENT", {"issue_date": "2015-05-05"}, confirmed=False)
        _fact(membership_a, other, "IDENTITY", {"citizenship": "Türkiye"}, confirmed=False)
        _fact(membership_a, served, "ID_DOCUMENT", {"issue_date": "2021-01-01"}, confirmed=False)
        application = _application(agency_a, membership_a, entries=[
            _entry("id_document.issue_date", "#issued"), _entry("identity.citizenship", "#cit")])
        packet = mint_packet(application)
    assert _hint(packet, "id_document.issue_date").offer.value == "2021-01-01"
    assert _hint(packet, "identity.citizenship").offer is None


def test_an_expired_passports_waiting_value_is_never_offered(agency_a, membership_a):
    from apps.portals.packets import mint_packet

    expired = (date.today() - timedelta(days=30)).isoformat()
    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "ID_DOCUMENT",
              {"document_type": "passport", "number": "OLD1", "expiry_date": expired},
              confirmed=True)
        _fact(membership_a, passport, "ID_DOCUMENT", {"issue_date": "2016-01-01"},
              confirmed=False)
        application = _application(agency_a, membership_a,
                                   entries=[_entry("id_document.issue_date", "#issued")])
        packet = mint_packet(application)
    hint = _hint(packet, "id_document.issue_date")
    assert hint.offer is None and hint.expired_on == expired


def test_a_date_the_code_could_not_read_is_never_offered(agency_a, membership_a):
    """Plan 2 ruling (final review I3): no tap writes a date the ledger cannot hold as
    printed (fact_writer.needs_typing); the student types it."""
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "IDENTITY", {"date_of_birth": "14 Mart 1998"},
              confirmed=False)
        application = _application(agency_a, membership_a,
                                   entries=[_entry("identity.date_of_birth", "#dob")])
        packet = mint_packet(application)
    assert _hint(packet, "identity.date_of_birth").offer is None


def test_a_replaced_passport_offers_nothing_and_does_not_count_as_held(agency_a, membership_a):
    """Ruling 2026-10-14: a retired upload (master's Replace) is disowned
    (verification.disowned_refs), so its waiting values are offered nowhere and the
    box asks for the new upload."""
    from apps.concierge.models import DocumentVersion
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "IDENTITY", {"date_of_birth": "1998-03-14"},
              confirmed=False)
        DocumentVersion.objects.filter(id=passport.id).update(retired_at=timezone.now())
        application = _application(agency_a, membership_a,
                                   entries=[_entry("identity.date_of_birth", "#dob")])
        packet = mint_packet(application)
    hint = _hint(packet, "identity.date_of_birth")
    assert hint.offer is None and hint.upload_kind == "PASSPORT"
```

- [ ] **Step 2: Run to see them fail**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/portals/test_packet_offers.py`
Expected: FAIL (`AttributeError: 'PacketHint' object has no attribute 'offer'`).

- [ ] **Step 3: The three ledger readers in `apps/portals/profile.py`.**
  - First, a pure refactor of plan 1's `_id_document_values`. Its choice of document moves into
    `_picked`, so the offers below use the very document portals are served:

```python
def _picked(student: Membership, groups: dict[str, tuple[dict[str, str], frozenset[str]]]) -> str | None:
    """The ID document portals are served (spec §4.2): the student's chosen one if it
    is valid, else the valid passport with the latest expiry, else the valid document
    of any type with the latest expiry. None when none is valid: an expired document
    is never served."""
    today = timezone.localdate().isoformat()
    valid = {ref: doc for ref, (doc, _) in groups.items() if doc.get("expiry_date", "") >= today}
    if not valid:
        return None
    chosen = (
        DocumentReading.objects.filter(student=student, primary_chosen_at__isnull=False)
        .order_by("-primary_chosen_at")
        .values_list("document_id", flat=True)
        .first()
    )
    # A re-upload of the chosen passport is merged into one document under the
    # later ref: the choice holds for any of the merged refs.
    picked = next(
        (ref for ref in valid if chosen is not None and f"document:{chosen}" in groups[ref][1]),
        None,
    )
    if picked is not None:
        return picked
    passports = {r: d for r, d in valid.items() if d.get("document_type") == "passport"}
    pool = passports or valid
    return max(pool, key=lambda r: pool[r].get("expiry_date", ""))
```

    and `_id_document_values` keeps its docstring and becomes:

```python
    groups = id_document_groups(facts)
    ref = _picked(student, groups)
    if ref is None:
        return {}, None
    out = {f"id_document.{key}": value for key, value in groups[ref][0].items()}
    citizenship = _document_citizenship(student, groups[ref][1])
    if citizenship is None:
        return out, None
    out["identity.citizenship"] = citizenship[0]
    return out, citizenship[1]
```

    Run `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/portals tests/documents/test_fact_reading_rereview.py`
    before going on. The refactor must change nothing.
  - Then add, after `verified_values`:

```python
#: Spec 2026-10-12 §7.4: the upload kind a document-read fact came from, as the
#: co-pilot names it on a mark ("From your passport").
SOURCE_KINDS = {"PASSPORT": "passport", "DIPLOMA": "diploma", "LANGUAGE_CERTIFICATE": "certificate"}
_DOCUMENT_REF = "document:"
#: A reading that could not tie the document to this student (spec §5.2.4). Its values
#: are never one tap from a portal (plan 1 rulings: a passport proven not the
#: student's serves nothing; an owner_unknown one is settled only by a clean re-read).
_OWNER_UNCHECKED = frozenset({"owner_mismatch", "owner_unknown"})
#: Number, expiry and citizenship travel together (owner, 2026-10-13): these are
#: offered only from the one document portals are served (or would be).
_ONE_DOCUMENT = ("id_document.", "identity.citizenship")


class Offer(NamedTuple):
    fact_id: UUID
    value: str
    source_kind: str


def _document_kinds(facts: list[VerifiedFact]) -> dict[str, str]:
    from apps.concierge.models import DocumentVersion

    ids = set()
    for fact in facts:
        if fact.source_ref.startswith(_DOCUMENT_REF):
            try:
                ids.add(UUID(fact.source_ref.removeprefix(_DOCUMENT_REF)))
            except ValueError:
                continue
    return {
        str(document_id): SOURCE_KINDS.get(kind, "")
        for document_id, kind in DocumentVersion.objects.filter(id__in=ids).values_list("id", "kind")
    }


def _owned(student: Membership, disowned: set[str]) -> list[VerifiedFact]:
    """Current rows, minus every document read as someone else's (plan 1: a disowned
    document serves nothing, and is offered nothing)."""
    return [f for f in unsuperseded_facts(student) if f.source_ref not in disowned]


def document_sources(student: Membership, values: dict[str, str]) -> dict[str, str]:
    """Profile field -> source kind, for each value in `values` (what verified_values
    serves) that a document read proved: a current, confirmed AUTHORITATIVE_DOCUMENT row
    of a document the student owns holds exactly that value. Matched on the value, so
    the mark follows whatever verified_values picked -- the chosen passport, the latest
    sitting -- and a student's own correction, which differs from every read, is never
    marked "From your passport"."""
    facts = [
        f for f in _owned(student, disowned_refs(student))
        if f.confirmed_at is not None
        and f.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
        and f.source_ref.startswith(_DOCUMENT_REF)
    ]
    kinds = _document_kinds(facts)
    proved: dict[tuple[str, str], str] = {}
    for fact in facts:
        source = kinds.get(fact.source_ref.removeprefix(_DOCUMENT_REF), "")
        for key, value in fact.payload.items():
            if source and isinstance(value, str) and value.strip():
                proved[(f"{fact.category.lower()}.{key}", value)] = source
    return {
        field: proved[(field_class(field), value)]
        for field, value in values.items()
        if (field_class(field), value) in proved
    }


def _offer_refs(
    student: Membership, confirmed: list[VerifiedFact], disowned: set[str]
) -> frozenset[str]:
    """The refs of the one ID document an id_document.* or citizenship offer may come
    from: the document portals are served (_picked), else the latest passport read the
    student owns. Never a second document's value beside the first's."""
    groups = id_document_groups(confirmed)
    picked = _picked(student, groups)
    if picked is not None:
        return groups[picked][1]
    latest = next(
        (
            ref
            for ref in (
                f"{_DOCUMENT_REF}{d}"
                for d in DocumentReading.objects.filter(
                    student=student, kind="PASSPORT", state=DocumentReading.State.READ
                ).order_by("-created_at").values_list("document_id", flat=True)
            )
            if ref not in disowned
        ),
        None,
    )
    if latest is None:
        return frozenset()
    return next((refs for _, refs in groups.values() if latest in refs), frozenset({latest}))


def document_offers(student: Membership) -> dict[str, Offer]:
    """"category.key" -> the newest doubtful value a document read left for it
    (spec 2026-10-12 §7.2): unconfirmed, unsuperseded, one value per row, from a
    document the student owns (never disowned, which includes a replaced upload).
    Never a value whose latest reading could not tie the document to the student
    (_OWNER_UNCHECKED, decided as the dashboard decides it); never one the ledger
    cannot hold as printed (fact_writer.needs_typing: no tap writes an unread
    date); an id_document.* or citizenship value only from the one document
    portals are served (_offer_refs); and no id_document.* value while every ID
    document has expired. mint_packet and ext_api.confirm_offer both ask here, so
    a value offered when the packet was minted and not offered now is refused at
    the tap."""
    disowned = disowned_refs(student)
    owned = _owned(student, disowned)
    waiting = [
        f for f in owned
        if f.confirmed_at is None and f.source_ref.startswith(_DOCUMENT_REF)
        # One value per row, of an ID document. Plan 2's doubtful diploma and
        # certificate values wait on the DocumentReading (adopt_document_value) or
        # as one whole-document row, and one tap on one box must never confirm
        # values the student did not see. Those are settled on the dashboard.
        and f.category in (VerifiedFact.Category.IDENTITY, VerifiedFact.Category.ID_DOCUMENT)
        and len(f.payload) == 1
    ]
    if not waiting:
        return {}
    # The latest reading's why per (document, key), later readings winning, as
    # documents/views.py builds its snippets: a clean re-read of the same file
    # lifts an owner_unknown (plan 1), and the panel never offers what the
    # dashboard hides (plan 2: owner_unknown is offered on no surface).
    why = {
        (f"{_DOCUMENT_REF}{reading.document_id}", entry.get("key")): entry.get("why")
        for reading in DocumentReading.objects.filter(student=student).order_by("created_at")
        for entry in reading.values or []
    }
    one_document = _offer_refs(student, [f for f in owned if f.confirmed_at], disowned)
    # An expired document is never served (spec §4.2), not even through a tap.
    expired = bool(expired_id_document(student))
    kinds = _document_kinds(waiting)
    offers: dict[str, Offer] = {}
    for fact in waiting:
        source = kinds.get(fact.source_ref.removeprefix(_DOCUMENT_REF), "")
        for key, value in fact.payload.items():
            field = f"{fact.category.lower()}.{key}"
            if (
                not source
                or not (isinstance(value, str) and value.strip())
                or why.get((fact.source_ref, field)) in _OWNER_UNCHECKED
                or needs_typing(field, value)
                or (field.startswith(_ONE_DOCUMENT) and fact.source_ref not in one_document)
                or (expired and field.startswith("id_document."))
            ):
                continue
            offers[field] = Offer(fact.id, value, source)
    return offers


def expired_id_document(student: Membership) -> str:
    """The latest expiry among the student's ID documents when every one of them has
    expired, else "" (spec §4.2: an expired document is never served). Documents are
    counted as portals count them -- per document, re-uploads merged
    (verification.id_documents) -- and a disowned one is not the student's."""
    disowned = disowned_refs(student)
    confirmed = [f for f in _owned(student, disowned) if f.confirmed_at is not None]
    expiries = [doc.get("expiry_date", "") for doc in id_documents(confirmed).values()]
    expiries = [e for e in expiries if e]
    today = timezone.localdate().isoformat()
    if not expiries or any(e >= today for e in expiries):
        return ""
    return max(expiries)
```

  Imports to add:
  - `from typing import NamedTuple`;
  - `from apps.documents.fact_writer import needs_typing` (plan 2; `fact_writer` imports nothing
    from `apps.portals`, so there is no cycle);
  - `id_documents` in the existing `from apps.documents.verification import (...)`.

  `UUID`, `timezone`, `DocumentReading`, `unsuperseded_facts`, `disowned_refs`,
  `id_document_groups` and `field_class` are already in this module at HEAD (checked).

- [ ] **Step 4: The packet schema.** In `apps/portals/packets.py`, before `PacketHint`:

```python
class PacketOffer(BaseModel):
    """A value a document read left doubtful (spec 2026-10-12 §7.2): shown to the
    student as "We read X from your passport — use it?" and typed only after their
    tap confirms it through ext_api.confirm_offer. The method is the map's own."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: UUID
    value: str
    method: str
    source_kind: Literal["passport", "diploma", "certificate"]
```

  On `PacketHint`, change the docstring's "No value, ever." to "No value is typed into it unless
  the student taps an offer." Then add:

```python
    offer: PacketOffer | None = None
    #: The upload kind that would supply this field when the student has none
    #: (spec §3: "Upload your passport once…"). "" when one is uploaded.
    upload_kind: str = ""
    #: Every ID document has expired: the latest expiry, so the panel can say when.
    expired_on: str = ""
```

  On `PacketField`, add after `from_answer`:

```python
    #: Filled from a value a document read proved: "passport", "diploma" or
    #: "certificate". The mark says "From your passport". "" for anything else.
    source_kind: str = ""
```

- [ ] **Step 5: `mint_packet` fills them.**
  - Inside the existing `with tenant_transaction(application.tenant_id):` block, after
    `own = _own_answers(application)`, add:
    ```python
            sources = document_sources(application.student, values)
            offers = document_offers(application.student)
            expired_on = expired_id_document(application.student)
            # A passport read as someone else's, or replaced (verification.
            # disowned_refs covers both), does not count as held: the box still
            # asks for the student's own, current upload.
            disowned = [UUID(ref.removeprefix("document:"))
                        for ref in disowned_refs(application.student)]
            held_kinds = set(
                DocumentVersion.objects.filter(student=application.student)
                .exclude(state__in=UPLOAD_REJECTIONS)
                .exclude(id__in=disowned)
                .values_list("kind", flat=True)
            )
    ```
    `values` is the merged dict a few lines above (`values, _, plain_email =
    _merged_with_portal_email(...)`). `document_sources` matches the marks against exactly what
    this packet types. `own = _own_answers(application)` is the last line of that block at HEAD.
  - The hint branch at HEAD first types back the student's own earlier answer (`from_answer`) and
    `continue`s. Replace the `hints.append(PacketHint(...))` call after it with the following.
    `document_offers` already drops an expired document's values:
    ```python
            # Spec §3, §7.2: a no_fact box may carry a document's doubtful value to
            # tap, the upload that would fill it, or that the passport expired. An
            # unsure box gets none of them: the map is not sure what it asks.
            offer = None if unsure else offers.get(field)
            # Only a key a document read writes (fact_labels.FIELD_LABELS): the hook's
            # KIND_FOR_PREFIX maps every identity.* key to PASSPORT, and a passport
            # never fills a phone box.
            wanted = (
                next((kind for prefix, kind in KIND_FOR_PREFIX if field.startswith(prefix)), "")
                if not unsure and field_class(field) in FIELD_LABELS
                else ""
            )
            hints.append(
                PacketHint(
                    selector=action.selector,
                    profile_field=field,
                    reason="unsure" if unsure else "no_fact",
                    offer=(
                        PacketOffer(
                            fact_id=offer.fact_id,
                            value=apply_rules(form, field, offer.value),
                            method=(action.method or "").strip(),
                            source_kind=offer.source_kind,
                        )
                        if offer is not None
                        else None
                    ),
                    upload_kind=wanted if offer is None and wanted not in held_kinds else "",
                    expired_on=(
                        expired_on if not unsure and field.startswith("id_document.") else ""
                    ),
                )
            )
    ```
  - In the final `entries.append(PacketField(...))` (the verified-value one, never the
    `from_answer` one), add `source_kind=sources.get(field, ""),`.
  - Imports:
    - `from apps.concierge.models import UPLOAD_REJECTIONS, DocumentVersion` (extend the existing
      `DocumentVersion` line; `UPLOAD_REJECTIONS` is a dict of rejection states at HEAD, and
      `state__in` takes its keys);
    - `from apps.documents.fact_labels import FIELD_LABELS`;
    - `from apps.documents.verification import disowned_refs`;
    - `from .fact_reading import KIND_FOR_PREFIX, request_fact_reading` (extend the existing line);
    - `from .profile import document_offers, document_sources, expired_id_document, field_class, verified_values`
      (extend the existing line).

    `PacketOffer` is defined in this module. `UUID` is already imported.
  - Many `test_packet.py` / `test_kit.py` tests monkeypatch `packets.verified_values`. The new calls
    are separate names, read the real (empty) ledger and return nothing, so those tests are
    unaffected.
  - An `id_document.*` hint shows the expiry even when nothing else is set, and an expired
    student still has an upload, so `upload_kind` stays "" and the panel's expired line carries
    the upload link (Task 4).
- [ ] **Step 6: Record what was offered.** In `_record_packet`, in the `"hints"` list
  comprehension, add `"offer_fact_id": str(hint.offer.fact_id) if hint.offer else "",`.
  The value is not recorded: the step names the fact, and the ledger holds the value.

- [ ] **Step 6b: The hook's queue call gives up in seconds.** This is carried from plan 1's final
  review (T8), and it must land before `FACT_READING_ENABLED` is on. `request_fact_reading` runs
  inside `mint_packet`, in the web request. Its `enqueue_document_work` builds a default boto3
  SQS client, so an SQS outage stalls the packet request on boto3's default timeouts and
  retries. In `apps/portals/fact_reading.py`:

```python
from functools import cache
from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]

#: The hook runs inside mint_packet, in a web request: an SQS outage must cost a few
#: seconds, never the request (plan 1 final review, T8). One attempt: a QUEUED row
#: whose message never arrived is picked up by the resume sweep.
_SQS_CONFIG = Config(connect_timeout=2, read_timeout=3, retries={"total_max_attempts": 1})


@cache
def _sqs_client() -> Any:
    return boto3.client("sqs", config=_SQS_CONFIG)
```

  and pass `client=_sqs_client()` to the `enqueue_document_work(...)` call in `_request`. The
  client is built only when a reading was actually queued, and the existing `try/except` in
  `request_fact_reading` still keeps any failure out of the packet. In
  `tests/portals/test_fact_reading_hook.py`, give the autouse `_on` fixture a `monkeypatch`
  parameter, `monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")` and
  `fact_reading._sqs_client.cache_clear()`, so building a client never depends on the host's AWS
  configuration. Then add:

```python
def test_the_hooks_queue_client_gives_up_in_seconds():
    """Plan 1 final review T8, before FACT_READING_ENABLED is on."""
    config = fact_reading._sqs_client().meta.config
    assert (config.connect_timeout, config.read_timeout) == (2, 3)
    assert config.retries["total_max_attempts"] == 1


def test_the_queue_call_uses_the_short_timeout_client(agency_a, membership_a, monkeypatch):
    seen = []
    monkeypatch.setattr(fact_reading, "enqueue_document_work",
                        lambda message, **k: seen.append(k["client"]))
    _available(agency_a, membership_a)
    fact_reading.request_fact_reading(_application(agency_a, membership_a),
                                      ["identity.date_of_birth"])
    assert seen == [fact_reading._sqs_client()]
```

- [ ] **Step 7: Run the tests**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/portals/test_packet_offers.py tests/portals/test_packet.py tests/portals/test_kit.py tests/portals/test_answers.py tests/portals/test_fact_reading_hook.py tests/documents/test_fact_reading_rereview.py`
Expected: PASS.
- One test asserts an exact `detail["hints"]` dict:
  `tests/portals/test_packet.py::test_a_fact_the_student_lacks_is_a_hint_and_blocks_nothing`.
  Add `"offer_fact_id": ""` to its expected dict: the step's shape grew by one key, by design.
  `answers.py` reads the same list by `selector`/`profile_field` only, so it is unaffected.
  `test_packet.py`'s `"value" not in packet.hints[0].model_dump()` still holds, because the value
  sits under `offer`, which is `None` there.

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add apps/portals/profile.py apps/portals/packets.py apps/portals/fact_reading.py tests/portals/test_packet_offers.py tests/portals/test_packet.py tests/portals/test_fact_reading_hook.py
git -C /home/orkhan/Desktop/fact-reading commit -m "feat(portals): packets offer a document's doubtful value, ask for the upload once, say when a passport expired"
```

---

### Task 2: The one-tap confirm route

**Files:**
- Modify: `apps/documents/fact_writer.py` (`use_document_value`), `apps/portals/ext_api.py`,
  `apps/portals/urls.py`
- Test: `tests/portals/test_fact_offer_api.py`

**Interfaces:**
- Consumes:
  - `detail["hints"][i]["offer_fact_id"]` on the PACKET step, and `profile.document_offers`
    (Task 1);
  - in `fact_writer` (all already imported there at HEAD): `unsuperseded_facts`, `disowned_refs`,
    `needs_typing` (plan 2), `FactNotFound` and `record_event`;
  - `rules.apply_rules(portal_form, profile_field, value)`.
- Produces:
  - `fact_writer.use_document_value(*, student, fact_id) -> VerifiedFact`, which raises
    `FactNotFound`, and `IntegrityError` on a racing second tap. Plan 2 has no function of this
    name or purpose: its `adopt_document_value` supersedes a confirmed *target* row with a
    reading's value, and a passport's waiting rows have no target;
  - `POST /ext/applications/<uuid:application_id>/facts/<uuid:fact_id>/confirm` →
    `201 {"profile_field": str, "value": str}`, or 404 `not_found`, 429 `rate_limited`, and the
    `_device_endpoint` refusals. URL name `portals-ext-fact-confirm`.
- Ruling, a carry item from plan 1's final review: a Use tap must make the tapped value the one
  served next. `verified_values` (last row of a key wins) and `id_document_groups` (later rows
  win) order by `created_at`. `confirm_facts` confirms in place and keeps the row's old
  `created_at`. So the tap writes a **new** confirmed row that supersedes the waiting one. That is
  plan 1's rule for a proof ("a new row, never confirm in place"). Plan 2 ruled the same, and spec
  §7.3 is amended to say so (this plan's reconcile commit). The audit event is unchanged:
  `fact.confirmed`, with the student as actor.
- Ruling: the spec writes `/ext/facts/<fact_id>/confirm`. The application goes in the path, like
  every other per-application `/ext/` route, because the latest PACKET step of **that**
  application is what decides "offered".

- [ ] **Step 1: Write the failing tests**

```python
# tests/portals/test_fact_offer_api.py
"""Spec 2026-10-12 §7.3: the student's one tap confirms one offered value."""

import pytest
from django.utils import timezone

from apps.documents.models import VerifiedFact
from apps.tenancy.context import tenant_scope
from tests.portals.test_ext_api import _pair
from tests.portals.test_kit import _application
from tests.portals.test_packet import _clean_upload

pytestmark = pytest.mark.django_db

ENTRY = {"profile_field": "identity.date_of_birth", "sure": True,
         "action": {"selector": "#dob", "method": "fill", "arguments": ["%value%"]}}


def _offered(agency, student):
    from apps.portals.packets import mint_packet

    with tenant_scope(agency.id):
        passport = _clean_upload(agency, student, "PASSPORT")
        fact = VerifiedFact.objects.create(
            student=student, category="IDENTITY", payload={"date_of_birth": "1998-03-14"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{passport.id}",
            created_by=student,
        )
        application = _application(agency, student, entries=[ENTRY])
        mint_packet(application)
    return application, fact


def _tap(client, domain, token, application, fact_id):
    return client.post(
        f"/ext/applications/{application.id}/facts/{fact_id}/confirm",
        data="{}", content_type="application/json",
        HTTP_HOST=domain.host, HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def test_a_tap_confirms_the_offered_value_and_returns_it(client, agency_a, domain_a,
                                                         membership_a):
    from apps.funding.models import AuditEvent

    application, fact = _offered(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    response = _tap(client, domain_a, token, application, fact.id)
    assert response.status_code == 201
    assert response.json() == {"profile_field": "identity.date_of_birth", "value": "1998-03-14"}
    with tenant_scope(agency_a.id):
        used = VerifiedFact.objects.get(supersedes=fact)
        assert used.confirmed_by == membership_a and used.payload == fact.payload
        assert (used.source_ref, used.source_tier) == (fact.source_ref, fact.source_tier)
        assert AuditEvent.objects.filter(object_id=used.id, event="fact.confirmed").exists()


def test_the_tapped_value_is_a_new_row_and_the_one_served_next(client, agency_a, domain_a,
                                                               membership_a):
    """Carried from plan 1: a row confirmed in place keeps its old created_at and can
    lose to a row written after it; the tap's row is the newest of the student's."""
    from apps.portals.profile import verified_values

    application, fact = _offered(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    assert _tap(client, domain_a, token, application, fact.id).status_code == 201
    with tenant_scope(agency_a.id):
        newest = VerifiedFact.objects.filter(student=membership_a).latest("created_at")
        assert newest.supersedes_id == fact.id and newest.confirmed_at is not None
        assert verified_values(membership_a)["identity.date_of_birth"] == "1998-03-14"


@pytest.mark.parametrize("why", ["owner_mismatch", "owner_unknown"])
def test_a_passport_disowned_after_the_packet_is_refused(client, agency_a, domain_a,
                                                         membership_a, why):
    """The packet offered it; a later read found the passport is someone else's (plan 1:
    a disowned document serves nothing), or could not tie it to the student (plan 2:
    owner_unknown is offered on no surface). The route re-asks document_offers, so
    the tap confirms nothing."""
    from apps.documents.models import DocumentReading

    application, fact = _offered(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        DocumentReading.objects.create(
            student=membership_a, document_id=fact.source_ref.removeprefix("document:"),
            kind="PASSPORT", reader_version="id-1", state="READ", file_sha256="mum",
            values=[{"key": "identity.date_of_birth", "value": "1998-03-14", "snippet": "",
                     "proven": False, "why": why}])
    token = _pair(client, agency_a, membership_a, domain_a)
    assert _tap(client, domain_a, token, application, fact.id).status_code == 404
    with tenant_scope(agency_a.id):
        assert not VerifiedFact.objects.filter(supersedes=fact).exists()


def test_a_fact_the_latest_packet_did_not_offer_is_refused(client, agency_a, domain_a,
                                                           membership_a):
    application, _fact = _offered(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        other = VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload={"sex": "F"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref="document:x",
            created_by=membership_a,
        )
    token = _pair(client, agency_a, membership_a, domain_a)
    assert _tap(client, domain_a, token, application, other.id).status_code == 404


def test_someone_elses_fact_is_refused_even_if_the_step_names_it(
    client, agency_a, domain_a, membership_a, django_user_model
):
    """The step is our record, but the student filter is the guard: a step naming
    another student's fact still confirms nothing."""
    from apps.portals.models import ApplicationStep
    from tests.portals.test_answers import _student

    application, _fact = _offered(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        stranger = _student(agency_a, django_user_model, "stranger")
        theirs = VerifiedFact.objects.create(
            student=stranger, category="IDENTITY", payload={"date_of_birth": "2001-01-01"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref="document:x", created_by=stranger,
        )
        step = ApplicationStep.objects.get(application=application, kind="PACKET")
        step.detail["hints"][0]["offer_fact_id"] = str(theirs.id)
        step.save(update_fields=["detail"])
    token = _pair(client, agency_a, membership_a, domain_a)
    assert _tap(client, domain_a, token, application, theirs.id).status_code == 404
    with tenant_scope(agency_a.id):
        theirs.refresh_from_db()
        assert theirs.confirmed_at is None


def test_a_second_tap_types_nothing_new(client, agency_a, domain_a, membership_a):
    application, fact = _offered(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    assert _tap(client, domain_a, token, application, fact.id).status_code == 201
    assert _tap(client, domain_a, token, application, fact.id).status_code == 404


def test_a_locked_account_is_refused(client, agency_a, domain_a, membership_a):
    from apps.audit.models import DeletionRequest

    application, fact = _offered(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="APPROVED", reason="PRIVACY"
        )
    response = _tap(client, domain_a, token, application, fact.id)
    assert response.status_code == 403 and response.json()["error"] == "account_locked"


def test_taps_are_rate_limited(client, agency_a, domain_a, membership_a, monkeypatch):
    from apps.portals import ext_api

    monkeypatch.setattr(ext_api, "_FACT_CONFIRM_RATE_LIMIT", 1)
    application, _fact = _offered(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    _tap(client, domain_a, token, application, "00000000-0000-4000-8000-000000000000")
    response = _tap(client, domain_a, token, application, "00000000-0000-4000-8000-000000000000")
    assert response.status_code == 429
```

  Check `tests/portals/test_answers.py::_student(agency, django_user_model, name)` returns a
  `Membership` (it is used that way in `test_erasure_deletes_the_students_answers`). Check the
  `DeletionRequest` fields against `tests/portals/test_ext_api.py` near its `account_locked`
  test, which creates one with `state="APPROVED", reason="PRIVACY"`.

- [ ] **Step 2: Run to see them fail**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/portals/test_fact_offer_api.py`
Expected: FAIL (404 for every tap: no route).

- [ ] **Step 3: The route.** In `apps/portals/ext_api.py`, after the `answers` view:

```python
#: A tap per doubtful value. Thirty an hour is every offered box of several
#: applications; more is a loop.
_FACT_CONFIRM_RATE_LIMIT = 30


@require_POST
@_device_endpoint
def confirm_offer(
    request: HttpRequest, pairing: ExtensionPairing, application_id: UUID, fact_id: UUID
) -> HttpResponse:
    """The student's one tap on "We read X from your passport — use it?" (spec
    2026-10-12 §7.3). Confirms that one fact, as the student, and answers with the
    value to type, formatted for this portal.

    Three guards, all required. The application's latest PACKET step must have
    offered this fact -- the step is the authoritative record of what we prepared,
    as it is for uploads (_named_for). It must still be offered now: the same
    profile.document_offers that minted the packet is asked again, so a passport
    disowned, replaced, read owner_unknown or expired since then offers nothing.
    And use_document_value takes only this student's own waiting one-value row --
    the student filter, not the step, is what keeps another student's fact out.
    The value is written as a new confirmed row, so it is what portals get next.
    A second tap finds the row superseded: 404, nothing new to type."""
    _limit("ext-fact-confirm", pairing, _FACT_CONFIRM_RATE_LIMIT)
    application = _application_for(pairing, application_id)
    assert application.portal_form is not None  # _application_for filters on it
    student = pairing.membership
    try:
        with tenant_transaction(application.tenant_id):
            step = (
                ApplicationStep.objects.filter(
                    application=application, kind=ApplicationStep.Kind.PACKET
                )
                .order_by("-sequence")
                .first()
            )
            hints = (step.detail or {}).get("hints", []) if step is not None else []
            field = next(
                (str(h.get("profile_field") or "") for h in hints
                 if isinstance(h, dict) and h.get("offer_fact_id") == str(fact_id)),
                "",
            )
            offer = document_offers(student).get(field) if field else None
            if offer is None or offer.fact_id != fact_id:
                raise _ApiError(404, "not_found")
            use_document_value(student=student, fact_id=fact_id)
    except (FactNotFound, IntegrityError):
        # Gone between the check and the write, or a second tap racing the first
        # (one superseder per row): it won, so there is nothing new to type.
        raise _ApiError(404, "not_found") from None
    return JsonResponse(
        {"profile_field": field,
         "value": apply_rules(application.portal_form, field, offer.value)},
        status=201,
    )
```

  Imports to add:
  - `from django.db import IntegrityError`;
  - `from apps.documents.confirmation import FactNotFound`;
  - `from apps.documents.fact_writer import use_document_value`;
  - `from .rules import apply_rules`;
  - `document_offers` on the existing `from .profile import LEARNABLE_FIELDS, verified_values` line.

  `tenant_transaction`, `UUID` and `ApplicationStep` are already imported in this module at HEAD
  (checked). An `_ApiError` raised inside the `try` is not caught there; it reaches
  `_json_errors`.

  Also add to `apps/documents/fact_writer.py`, at the end of the module after `correct_fact`. Its
  imports (`unsuperseded_facts`, `disowned_refs`, `FactNotFound`, `record_event`, `timezone`) are
  already there at HEAD, and `needs_typing` is defined above it:

```python
#: What the panel's one tap may confirm: one waiting value of the student's ID
#: document. A diploma's or certificate's doubtful values are answered on the
#: dashboard (adopt_document_value, or the whole row), never by one tap on one box,
#: so a whole-document row (placed_whole_rows, held_whole_rows) cannot reach here.
_ONE_TAP = frozenset({VerifiedFact.Category.IDENTITY, VerifiedFact.Category.ID_DOCUMENT})


def use_document_value(*, student: Membership, fact_id: UUID) -> VerifiedFact:
    """The student's Use on a waiting document-read row (spec 2026-10-12 §7.3, the
    panel's one tap): a new confirmed row carrying it, superseding the waiting one.
    Never confirmed in place: verified_values and id_document_groups let the newest
    row win, and a row confirmed in place keeps its old created_at, so it could lose
    to a row written after it (plan 1 final review; plan 2 ruling). The tier and the
    document ref are the read's: the value is still the document's, and is marked
    so. Only a one-key IDENTITY or ID_DOCUMENT row of a document the student owns,
    and never a value the ledger cannot hold as printed (needs_typing: no tap writes
    an unread date, final review I3). A racing second Use raises IntegrityError (one
    superseder per row)."""
    fact = (
        unsuperseded_facts(student)
        .filter(id=fact_id, confirmed_at__isnull=True, source_ref__startswith="document:",
                category__in=_ONE_TAP)
        .exclude(source_ref__in=disowned_refs(student))
        .first()
    )
    if (
        fact is None
        or len(fact.payload) != 1
        or any(needs_typing(f"{fact.category.lower()}.{k}", v) for k, v in fact.payload.items())
    ):
        raise FactNotFound("no waiting document value of this student")
    used = VerifiedFact.objects.create(
        student=student, category=fact.category, payload=fact.payload,
        source_tier=fact.source_tier, source_ref=fact.source_ref,
        confirmed_by=student, confirmed_at=timezone.now(), supersedes=fact, created_by=student,
    )
    record_event(actor=student, event="fact.confirmed", object_id=used.id)
    return used
```

- [ ] **Step 4: The URL.** In `apps/portals/urls.py`, after the `answers` path:

```python
    path(
        "ext/applications/<uuid:application_id>/facts/<uuid:fact_id>/confirm",
        ext_api.confirm_offer,
        name="portals-ext-fact-confirm",
    ),
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/portals/test_fact_offer_api.py tests/portals/test_ext_api.py tests/portals/test_packet_offers.py tests/documents/test_fact_writer.py tests/documents/test_fact_writer_documents.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add apps/documents/fact_writer.py apps/portals/ext_api.py apps/portals/urls.py tests/portals/test_fact_offer_api.py
git -C /home/orkhan/Desktop/fact-reading commit -m "feat(portals): one tap confirms an offered document value and returns it to type"
```

---

### Task 3: The content script — hint reasons, one-box fill, document marks, label vocabulary

**Files:**
- Modify: `extension/src/types.ts`, `extension/src/content/index.ts`, `extension/src/content/labels.ts`, `extension/src/content/vocabulary.ts`
- Create: `tests/portals/fixtures/passport_form.html`
- Test: `tests/portals/test_extension_e2e.py` (append)

**Interfaces:**
- Consumes: the packet fields from Task 1.
- Produces:
  - `PacketOffer` and the optional `offer`, `upload_kind` and `expired_on` on `PacketHint`;
    `source_kind` on `PacketField`; `offer`, `upload_kind` and `expired_on` on `FieldView`;
  - hint reasons `offer`, `upload_once`, `document_expired`; filled reasons `from_passport`,
    `from_diploma`, `from_certificate`;
  - content message `{type: "offer:fill", key, value}` → `{ok: boolean}`;
  - test hook `window.__elmify_offer(key, value) -> boolean`;
  - `contentLabels(language, step, fromAnswer, fromDocument)`.

- [ ] **Step 1: The fixture page** `tests/portals/fixtures/passport_form.html`:

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Passport details</title></head>
<body><form>
  <label for="dob">Date of birth</label><input id="dob" name="dob">
  <label for="pno">Passport number</label><input id="pno" name="pno">
  <label for="cit">Citizenship</label><input id="cit" name="cit">
  <button type="submit">Next</button>
</form></body></html>
```

- [ ] **Step 2: Write the failing e2e tests** (append to `tests/portals/test_extension_e2e.py`):

```python
FACT_ID = "55555555-5555-4555-8555-555555555555"


def _passport_packet(form_url, *, offer=True, upload_kind="", expired_on=""):
    hint = {"selector": "#dob", "profile_field": "identity.date_of_birth", "reason": "no_fact",
            "upload_kind": upload_kind, "expired_on": expired_on}
    if offer:
        hint["offer"] = {"fact_id": FACT_ID, "value": "1998-03-14", "method": "fill",
                         "source_kind": "passport"}
    return {
        "application_id": "app-1", "portal_form_id": "form-1", "field_map_version": 1,
        "form_url": form_url, "documents": [],
        "entries": [{"selector": "#pno", "method": "fill", "value": "C01X00T47",
                     "profile_field": "id_document.number", "source_kind": "passport"}],
        "hints": [hint],
        "issued_at": "2026-10-12T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z",
        "min_extension_version": "0.1.0", "confirmation_markers": None,
    }


@pytest.mark.extension
def test_an_offered_value_waits_for_the_tap_then_fills_its_one_box(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/passport_form.html"
    page.goto(url)
    sent = _run_with_stubbed_messaging(page, {"packet": {"ok": True,
                                                         "packet": _passport_packet(url)}})
    fields = {f["key"]: f for f in _last_dock_with(sent, "fields")["fields"]}
    assert fields["identity.date_of_birth"]["reason"] == "offer"
    assert page.input_value("#dob") == ""  # nothing typed before the tap
    assert fields["id_document.number"]["reason"] == "from_passport"
    assert page.input_value("#pno") == "C01X00T47"

    assert page.evaluate("() => window.__elmify_offer('identity.date_of_birth', '1998-03-14')")
    assert page.input_value("#dob") == "1998-03-14"
    after = {f["key"]: f for f in _last_dock_with(page.evaluate("() => window.__sent"),
                                                   "fields")["fields"]}
    assert after["identity.date_of_birth"]["state"] == "filled"
    assert after["identity.date_of_birth"]["reason"] == "from_passport"
    page.focus("#dob")  # the why-tag shows on focus (marks.ts)
    assert "From your passport" in page.evaluate("() => window.__elmify_marks_text()")


@pytest.mark.extension
def test_an_offer_never_types_over_what_the_student_typed(browser_context, fixture_server):
    page = browser_context.new_page()
    url = f"{fixture_server}/passport_form.html"
    page.goto(url)
    _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": _passport_packet(url)}})
    page.fill("#dob", "1998-03-15")
    assert page.evaluate(
        "() => window.__elmify_offer('identity.date_of_birth', '1998-03-14')") is False
    assert page.input_value("#dob") == "1998-03-15"


@pytest.mark.extension
def test_an_offer_for_a_field_the_packet_did_not_offer_types_nothing(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/passport_form.html"
    page.goto(url)
    _run_with_stubbed_messaging(page, {"packet": {"ok": True,
                                                  "packet": _passport_packet(url, offer=False)}})
    assert page.evaluate("() => window.__elmify_offer('identity.date_of_birth', 'x')") is False
    assert page.evaluate("() => window.__elmify_offer('identity.citizenship', 'x')") is False
    assert page.input_value("#dob") == "" and page.input_value("#cit") == ""


@pytest.mark.extension
@pytest.mark.parametrize(("upload_kind", "expired_on", "reason"), [
    ("PASSPORT", "", "upload_once"),
    ("", "2026-03-01", "document_expired"),
])
def test_a_box_no_upload_supplies_says_what_to_upload(
    browser_context, fixture_server, upload_kind, expired_on, reason
) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/passport_form.html"
    page.goto(url)
    packet = _passport_packet(url, offer=False, upload_kind=upload_kind, expired_on=expired_on)
    sent = _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": packet}})
    fields = {f["key"]: f for f in _last_dock_with(sent, "fields")["fields"]}
    assert fields["identity.date_of_birth"]["reason"] == reason
```

- [ ] **Step 3: Run to see them fail**

Run: `npm --prefix extension run build:test && POSTGRES_DB=elmify_fact_reading uv run pytest -q -m extension tests/portals/test_extension_e2e.py -k "offer or upload"`
Expected: FAIL (`window.__elmify_offer is not a function`, and the reason is `no_fact`).

- [ ] **Step 4: Types.** In `extension/src/types.ts`:
  - add to `PacketField`, after `from_answer`:
    ```ts
      /** Filled from a value a document read proved: "passport" | "diploma" |
       *  "certificate"; the mark says "From your passport". */
      source_kind?: string;
    ```
  - add before `PacketHint`:
    ```ts
    /** A doubtful value a document read left (spec 2026-10-12 §7.2). Typed only
     *  after the student's tap confirms it on the server. */
    export interface PacketOffer {
      fact_id: string;
      value: string;
      method: string;
      source_kind: "passport" | "diploma" | "certificate";
    }
    ```
  - add to `PacketHint`: `offer?: PacketOffer | null; upload_kind?: string; expired_on?: string;`,
    and change its doc comment to "A control the map is not sure of, or the student holds no fact
    for. Typed into only after the student taps its offer."
  - add to `FieldView`:
    ```ts
      /** Set by the worker from its own cached packet, never by a page (§7.2). */
      offer?: { value: string; source_kind: string };
      upload_kind?: string;
      expired_on?: string;
    ```

- [ ] **Step 5: Label tokens for plan 1's keys.** In `extension/src/content/vocabulary.ts`
  `TOKENS`, after `national_id`, add the following. The keys are the key half of plan 1's new
  profile fields; `sex` and `citizenship` reuse the existing tables:

```ts
  // Spec 2026-10-12 §4: the keys a passport read writes.
  given_names: ["given", "first", "forename", "christian", "vorname", "prenom", "nombre", "ad"],
  surname: ["family", "last", "surname", "nachname", "familienname", "nom", "apellido", "soyad"],
  sex: ["gender", "sex", "geschlecht", "sexe", "cinsiyet"],
  citizenship: ["citizenship", "nationality", "citizen", "staatsangeh", "nationalite",
                "nacionalidad", "uyruk", "vatandaslik"],
  number: ["passport number", "passport no", "document number", "reisepassnummer",
           "numero de passeport", "pasaport no", "pasaport numarasi"],
  expiry_date: ["expiry", "expiration", "valid until", "gultig bis", "date d expiration",
                "son gecerlilik"],
  issue_date: ["date of issue", "issue date", "issued on", "ausstellungsdatum",
               "date de delivrance", "verilis tarihi"],
  issuing_country: ["issuing country", "country of issue", "ausstellungsland",
                    "pays de delivrance", "veren ulke"],
  issuing_authority: ["issuing authority", "authority", "ausstellende behorde", "autorite"],
  document_type: ["document type", "type of document", "dokumententyp", "belge turu"],
```

  Also **replace** the existing `date_of_birth` and `place_of_birth` rows. The bare words
  `birth`, `dogum`, `naissance` and `nacimiento` each occur inside the matching place-of-birth
  label ("Place of birth", "Doğum yeri", "Lieu de naissance", "Lugar de nacimiento"). So a
  place-of-birth box in a packet that also holds the date of birth read as ambiguous and was
  never filled, and a passport fills both. Phrases fix it inside the token table, with the
  whole-word rule untouched:

```ts
  date_of_birth: ["date of birth", "birth date", "birthdate", "birthday", "born", "dob",
                  "geburtsdatum", "date de naissance", "fecha de nacimiento", "dogum tarihi",
                  "dogum tarixi"],
  place_of_birth: ["place of birth", "birthplace", "birth place", "geburtsort",
                   "lieu de naissance", "lugar de nacimiento", "dogum yeri", "dogdugu yer",
                   "anadan oldugu yer"],
```

  (`normalise` lowercases, strips accents and drops every non-Latin character, so Cyrillic labels
  match nothing; that is unchanged.) `extension/` has no vitest, so add this e2e case beside
  `test_certificate_keys_match_only_their_own_boxes` (it uses that test's `_verify_in_page`):

```python
@pytest.mark.extension
def test_a_passport_s_two_birth_boxes_each_verify_as_their_own(browser_context) -> None:
    """Plan 3 Task 3: "Place of birth" no longer also reads as the date of birth, so a
    passport fills both boxes; "Doğum yeri" is the place."""
    page = browser_context.new_page()
    page.set_content('<label for="d">Date of birth</label><input id="d">'
                     '<label for="p">Place of birth</label><input id="p">'
                     '<label for="y">Doğum yeri</label><input id="y">')
    entry = lambda selector, field: {  # noqa: E731
        "selector": selector, "method": "fill", "value": "x", "profile_field": field,
    }
    both = [entry("#d", "identity.date_of_birth"), entry("#p", "identity.place_of_birth")]
    assert [v["ok"] for v in _verify_in_page(page, both)] == [True, True]
    turkish = [entry("#y", "identity.place_of_birth"), entry("#d", "identity.date_of_birth")]
    assert [v["ok"] for v in _verify_in_page(page, turkish)] == [True, True]
```

  No existing test pins the bare `birth` token (checked at HEAD).

  Master added IDENTITY `given_name` (file names) beside the passport's `given_names`. Their
  tokens are equal, so a map naming both on one page refuses both boxes (`ambiguous_name`). That
  fails closed, and is accepted.

  These were missing from plan 1. Without them every new key's entry fails the label check
  (`name_mismatch`) and is never typed. Note the cost: a generic box labelled "Authority"
  matches `issuing_authority`. That is safe, because verify.ts compares only against the
  packet's own fields.

- [ ] **Step 6: Mark text.** In `extension/src/content/labels.ts`:
  - extend `Row` with `fromPassport: string; fromDiploma: string; fromCertificate: string;`;
  - add to each language:
    - en: `fromPassport: "From your passport", fromDiploma: "From your diploma", fromCertificate: "From your language certificate"`;
    - az: `fromPassport: "Pasportunuzdan", fromDiploma: "Diplomunuzdan", fromCertificate: "Dil sertifikatınızdan"`;
    - tr: `fromPassport: "Pasaportunuzdan", fromDiploma: "Diplomanızdan", fromCertificate: "Dil sertifikanızdan"`;
    - ru: `fromPassport: "Из вашего паспорта", fromDiploma: "Из вашего диплома", fromCertificate: "Из вашего языкового сертификата"`;
  - change `contentLabels` to take `fromDocument: ReadonlyMap<string, string> = new Map()` as a
    fourth argument, and `why` to:
    ```ts
           why: (key) => {
             if (fromAnswer.has(key)) return t.fromAnswer;
             const source = fromDocument.get(key);
             if (source === "passport") return t.fromPassport;
             if (source === "diploma") return t.fromDiploma;
             if (source === "certificate") return t.fromCertificate;
             return t.why;
           },
    ```

- [ ] **Step 7: `run()` in `extension/src/content/index.ts`.**
  - In the hint loop, replace the `reason:` expression with:
    ```ts
            reason: held
              ? "held_other"
              : hint.reason === "unsure"
                ? "our_guess"
                : hint.offer
                  ? "offer"
                  : hint.expired_on
                    ? "document_expired"
                    : hint.upload_kind
                      ? "upload_once"
                      : "no_fact",
    ```
  - After the `fromAnswer` loop, add:
    ```ts
      // Proven by the student's own document (spec 2026-10-12 §7.4): marked so.
      const fromDocument = new Map(
        packet.entries
          .filter((e) => e.source_kind && e.from_answer !== true)
          .map((e) => [e.profile_field, e.source_kind as string]),
      );
      for (const [key, source] of fromDocument) {
        const view = records.get(key)?.view;
        if (view && (view.state === "filled" || view.state === "already")) {
          view.reason = `from_${source}`;
        }
      }
    ```
  - Pass `fromDocument` as the fourth argument of `contentLabels(...)` in `draw`.
  - After `const report = () => {...};`, add:
    ```ts
      /** The student tapped Use in our panel; the worker confirmed the fact and sends
       *  the server's value. One box, through verify -> fill -> read back, exactly as
       *  an entry: judged against every entry's field (a label fitting two of the
       *  packet's fields is ambiguous_name, as in the run), never over a value
       *  already there, never into a box the packet did not offer this value for. */
      const useOffer = (key: string, value: string): boolean => {
        if (stale()) return false;
        const record = records.get(key);
        const hint = (packet.hints ?? []).find((h) => h.profile_field === key && h.offer);
        if (!record?.hint || !hint?.offer) return false;
        const entry: PacketField = {
          selector: hint.selector, method: hint.offer.method, value, profile_field: key,
        };
        const checked = verifyEntries([...packet.entries, entry]).slice(-1);
        const { filled } = fillVerified(checked, new Set());
        if (!filled.includes(key) || readBack(checked, packet.equivalences ?? {}).length > 0) {
          return false;
        }
        record.view = { key, state: "filled", reason: `from_${hint.offer.source_kind}`, placed: false };
        record.hint = false;
        fromDocument.set(key, hint.offer.source_kind);
        report();
        return true;
      };
    ```
  - Extend the `lastRun` type with `useOffer: (key: string, value: string) => boolean;`, and the
    assignment to `lastRun = { draw, patch: finalPatch, applicationId, answers: () => typedAnswers(records), useOffer };`.
  - In the `chrome.runtime.onMessage` listener, before `if (message?.type === "record")`, add:
    ```ts
        if (message?.type === "offer:fill") {
          // From the worker only (a page cannot reach this listener), after the
          // server confirmed the fact. The key and value are checked against our
          // own packet inside useOffer.
          const ok = typeof message.key === "string" && typeof message.value === "string"
            && lastRun?.useOffer(message.key, message.value) === true;
          sendResponse({ ok });
          return false;
        }
    ```
  - In the `if (__ELMIFY_TEST__)` block, add
    `(globalThis as Record<string, unknown>)["__elmify_offer"] = (key: string, value: string) => lastRun?.useOffer(key, value) ?? false;`.
  - Note that `useOffer` is defined after `report`, and `report` after `draw`. Keep that order.
    `stale` is `run()`'s own closure (`const stale = () => thisRun !== current;`, top of `run`),
    so it is in scope. `PacketField` is already imported as a type at HEAD.

- [ ] **Step 8: Run the tests**

Run: `npm --prefix extension run typecheck && npm --prefix extension run build:test && POSTGRES_DB=elmify_fact_reading uv run pytest -q -m extension tests/portals/test_extension_e2e.py`
Expected: PASS, including the existing suite (no-click scan, marks, and the "no raw reason codes"
test, which Task 4's strings satisfy). If `test_the_field_list_shows_no_raw_keys_or_reason_codes`
fails here because the panel has no `r_offer` string yet, run it again after Task 4. Do not
weaken it.

- [ ] **Step 9: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add extension/src/types.ts extension/src/content tests/portals/fixtures/passport_form.html tests/portals/test_extension_e2e.py
git -C /home/orkhan/Desktop/fact-reading commit -m "feat(extension): an offered value fills its one box after the tap; document marks; labels for passport fields"
```

---

### Task 4: The worker and the panel — the tap, the upload link, the strings

**Files:**
- Modify: `extension/src/api.ts`, `extension/src/service_worker.ts`, `extension/src/panel/panel.ts`, `extension/src/panel/i18n.ts`
- Test: `tests/portals/test_extension_e2e.py` (append)

**Interfaces:**
- Consumes: `POST /ext/applications/<app>/facts/<fact>/confirm` (Task 2); content `offer:fill`
  (Task 3); `shownActiveBinding`, `cachedPacket`, `dashboardOrigin`, `ExtError`.
- Produces:
  - panel → worker `{type: "offer:use", tabId, key}` and `{type: "open:documents"}`, both
    accepted from the dock only;
  - worker → content `{type: "offer:fill", key, value}`;
  - `api.confirmOffer(origin, applicationId, factId) -> {profile_field, value}`.

- [ ] **Step 1: Write the failing e2e tests** (append):

```python
def _offer_worker(browser_context, confirm_reply):
    packet = _portal_packet()
    packet["hints"] = [{"selector": "#dob", "profile_field": "identity.date_of_birth",
                        "reason": "no_fact", "upload_kind": "", "expired_on": "",
                        "offer": {"fact_id": FACT_ID, "value": "1998-03-14", "method": "fill",
                                  "source_kind": "passport"}}]
    return _load_worker(
        browser_context,
        {"language": "en", "binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/facts/{FACT_ID}/confirm": confirm_reply},
        session={**_binding(), f"packet:{APP_A}": packet},
    )


@pytest.mark.extension
def test_the_tap_confirms_on_the_server_and_sends_the_server_s_value_to_the_tab(
    browser_context,
) -> None:
    page = _offer_worker(browser_context, [201, {"profile_field": "identity.date_of_birth",
                                                 "value": "14.03.1998"}])
    _send(page, {"type": "offer:use", "tabId": 7, "key": "identity.date_of_birth"}, PANEL_SENDER)
    fetched = [key for key, _body in page.evaluate("() => window.__fetched")]
    assert f"POST /ext/applications/{APP_A}/facts/{FACT_ID}/confirm" in fetched
    assert _calls(page, "tabs.sendMessage")[-1] == [
        7, {"type": "offer:fill", "key": "identity.date_of_birth", "value": "14.03.1998"}]


@pytest.mark.extension
def test_a_refused_tap_types_nothing(browser_context) -> None:
    page = _offer_worker(browser_context, [404, {"error": "not_found"}])
    reply = _send(page, {"type": "offer:use", "tabId": 7, "key": "identity.date_of_birth"},
                  PANEL_SENDER)
    assert reply == {"ok": False, "code": "not_found"}
    assert _calls(page, "tabs.sendMessage") == []


@pytest.mark.extension
def test_a_page_cannot_tap_or_forge_an_offer(browser_context) -> None:
    page = _offer_worker(browser_context, [201, {"profile_field": "x", "value": "x"}])
    reply = _send(page, {"type": "offer:use", "tabId": 7, "key": "identity.date_of_birth"},
                  CONTENT)
    assert reply == {"ok": False, "code": "untrusted_sender"}
    forged = {"key": "identity.date_of_birth", "state": "your_turn", "reason": "offer",
              "placed": True, "offer": {"value": "evil", "source_kind": "passport"}}
    assert _send(page, {"type": "dock", "patch": {"fields": [forged]}}, CONTENT) == {"ok": True}
    [row] = page.evaluate("() => window.__session.dock.fields")
    assert row["offer"] == {"value": "1998-03-14", "source_kind": "passport"}  # the packet's own


@pytest.mark.extension
def test_the_panel_offers_the_value_and_sends_the_tap(browser_context) -> None:
    page = _open_panel(browser_context)
    _push_state(page, {
        "status": "blocked", "binding": {"tabId": 7, "origin": PORTAL},
        "fields": [{"key": "identity.date_of_birth", "state": "your_turn", "reason": "offer",
                    "placed": True, "offer": {"value": "1998-03-14", "source_kind": "passport"}}],
        "documents": [],
    })
    text = page.inner_text("#fields")
    assert "1998-03-14" in text and "Pasportunuzdan" in text  # the panel defaults to az here
    page.locator("#fields button").first.click()
    assert page.evaluate("() => window.__sent.at(-1)") == {
        "type": "offer:use", "tabId": 7, "key": "identity.date_of_birth"}


@pytest.mark.extension
def test_the_panel_links_to_the_documents_page_for_an_upload(browser_context) -> None:
    page = _open_panel(browser_context)
    _push_state(page, {
        "status": "blocked", "binding": {"tabId": 7, "origin": PORTAL},
        "fields": [{"key": "id_document.number", "state": "your_turn", "reason": "upload_once",
                    "placed": True, "upload_kind": "PASSPORT"}],
        "documents": [],
    })
    page.locator("#fields button").first.click()
    assert page.evaluate("() => window.__sent.at(-1)") == {"type": "open:documents"}


@pytest.mark.extension
def test_open_documents_opens_the_dashboard_s_documents_page(browser_context) -> None:
    page = _offer_worker(browser_context, [201, {}])
    _send(page, {"type": "open:documents"}, PANEL_SENDER)
    assert _calls(page, "tabs.create")[-1] == [{"url": f"{DASHBOARD}/student/documents/#upload"}]
```

- [ ] **Step 2: Run to see them fail**

Run: `npm --prefix extension run build:test && POSTGRES_DB=elmify_fact_reading uv run pytest -q -m extension tests/portals/test_extension_e2e.py -k "tap or offer or documents_page or forge"`
Expected: FAIL (the worker answers `invalid_message` / no handler; the panel has no button).

- [ ] **Step 3: The API call.** In `extension/src/api.ts`, after `postAnswers`:

```ts
/** The student's one tap on an offered value (spec 2026-10-12 §7.3): the server
 *  confirms the fact and answers with the value to type, formatted for the portal. */
export async function confirmOffer(
  origin: string,
  applicationId: string,
  factId: string,
): Promise<{ profile_field: string; value: string }> {
  return (await call(origin, `/ext/applications/${applicationId}/facts/${factId}/confirm`, {
    method: "POST",
    body: "{}",
  })) as { profile_field: string; value: string };
}
```

- [ ] **Step 4: The worker.** In `extension/src/service_worker.ts`:
  - Import `confirmOffer`, alongside the existing imports from `./api.js`.
  - In `messageRefusal`, after the `review:open` block, add:
    ```ts
      // Using an offered value, and opening the documents page, are the student's
      // presses in our panel; a portal page must not be able to make either.
      if (message["type"] === "offer:use") {
        if (!fromDock(sender)) return "untrusted_sender";
        if (!Number.isInteger(message["tabId"])) return "invalid_message";
        if (typeof message["key"] !== "string") return "invalid_message";
      }
      if (message["type"] === "open:documents" && !fromDock(sender)) return "untrusted_sender";
    ```
  - In `handle()` (the cases run only after `messageRefusal`), next to the `choice:answer` handler,
    add:
    ```ts
      if (message?.type === "offer:use") {
        void (async () => {
          const binding = await shownActiveBinding(message.tabId, sendResponse);
          if (!binding) return;
          // The offer is the cached packet's own: the panel names a field, nothing more.
          const packet = await cachedPacket(binding.applicationId);
          const hint = (packet?.hints ?? []).find((h) => h.profile_field === message.key && h.offer);
          const origin = await dashboardOrigin();
          if (!hint?.offer || !origin) return sendResponse({ ok: false, code: "not_found" });
          try {
            const answer = await confirmOffer(origin, binding.applicationId, hint.offer.fact_id);
            const reply = await chrome.tabs
              .sendMessage(binding.tabId, { type: "offer:fill", key: hint.profile_field, value: answer.value })
              .catch(() => ({ ok: false }));
            sendResponse(reply);
          } catch (error) {
            sendResponse({ ok: false, code: error instanceof ExtError ? error.code : "request_failed" });
          }
        })();
        return true;
      }
      if (message?.type === "open:documents") {
        void (async () => {
          const origin = await dashboardOrigin();
          if (origin) await chrome.tabs.create({ url: `${origin}/student/documents/#upload` });
          sendResponse({ ok: Boolean(origin) });
        })();
        return true;
      }
    ```
  - In the `dock` handler's `fields` filter, attach each row's offer, upload kind and expiry from
    the cached packet and drop whatever the page sent for them:
    ```ts
          const hintsByKey = new Map((packet?.hints ?? []).map((hint) => [hint.profile_field, hint]));
          if ("fields" in patch) {
            patch["fields"] = Array.isArray(patch["fields"])
              ? patch["fields"]
                  .filter((row) => keys.has(row?.key))
                  .map((row) => {
                    const { offer: _offer, upload_kind: _kind, expired_on: _expired, ...rest } = row;
                    const hint = hintsByKey.get(row.key);
                    return {
                      ...rest,
                      ...(hint?.offer
                        ? { offer: { value: hint.offer.value, source_kind: hint.offer.source_kind } }
                        : {}),
                      ...(hint?.upload_kind ? { upload_kind: hint.upload_kind } : {}),
                      ...(hint?.expired_on ? { expired_on: hint.expired_on } : {}),
                    };
                  })
              : [];
          }
    ```
    This replaces the existing one-line `patch["fields"] = ...filter(...)`. Build `hintsByKey`
    right after `const keys = new Set([...])`, where `packet` is already the cached packet. There
    is no eslint in `extension/`. tsc does not flag names destructured beside a rest element, and
    the `_` prefixes stay for readers.
  - Opening the documents page is `#upload`, the dashboard section holding the upload form
    (`templates/student/_documents.html`). The prompt asks for an upload, and `#details` only lists
    values. The origin is `dashboardOrigin()`, the paired dashboard's, never a page's, so
    `test_a_queued_link_is_scheme_checked_before_it_becomes_a_tab` is unaffected.

- [ ] **Step 5: The strings and field labels.** In `extension/src/panel/i18n.ts`, add to `EN`
  (and to `AZ`, `TR` and `RU`, in the same position). `test_every_panel_string_exists_in_all_four_languages`
  checks that each key carries the same placeholders in every language:

| key | en | az | tr | ru |
|---|---|---|---|---|
| `r_offer` | `We read {value} from {source} — use it?` | `{source}: {value} — istifadə edək?` | `{source}: {value} — kullanalım mı?` | `{source}: {value} — использовать?` |
| `r_upload_once` | `Upload your {kind} once and we'll fill this on every portal` | `{kind} bir dəfə yükləyin — bunu hər portalda dolduraq` | `{kind} bir kez yükleyin — bunu her portalda dolduralım` | `Загрузите {kind} один раз — мы заполним это на каждом портале` |
| `r_document_expired` | `Your passport expired on {date} — upload the new one` | `Pasportunuzun müddəti {date} tarixində bitib — yenisini yükləyin` | `Pasaportunuzun süresi {date} tarihinde doldu — yenisini yükleyin` | `Срок действия паспорта истёк {date} — загрузите новый` |
| `r_from_passport` | `From your passport` | `Pasportunuzdan` | `Pasaportunuzdan` | `Из вашего паспорта` |
| `r_from_diploma` | `From your diploma` | `Diplomunuzdan` | `Diplomanızdan` | `Из вашего диплома` |
| `r_from_certificate` | `From your language certificate` | `Dil sertifikatınızdan` | `Dil sertifikanızdan` | `Из вашего языкового сертификата` |
| `src_passport` | `your passport` | `Pasportunuzdan` | `Pasaportunuzdan` | `Из вашего паспорта` |
| `src_diploma` | `your diploma` | `Diplomunuzdan` | `Diplomanızdan` | `Из вашего диплома` |
| `src_certificate` | `your language certificate` | `Dil sertifikatınızdan` | `Dil sertifikanızdan` | `Из вашего языкового сертификата` |
| `u_PASSPORT` | `passport` | `pasportunuzu` | `pasaportunuzu` | `свой паспорт` |
| `u_DIPLOMA` | `diploma` | `diplomunuzu` | `diplomanızı` | `свой диплом` |
| `u_LANGUAGE_CERTIFICATE` | `language certificate` | `dil sertifikatınızı` | `dil sertifikanızı` | `свой языковой сертификат` |
| `b_use` | `Use it` | `İstifadə et` | `Kullan` | `Использовать` |
| `b_open_documents` | `Open my documents` | `Sənədlərimi aç` | `Belgelerimi aç` | `Открыть мои документы` |

  `k_PASSPORT`, `k_DIPLOMA` and `k_LANGUAGE_CERTIFICATE` already exist at HEAD: they are master's
  `kindLabel` nouns ("Passport", "Pasport"). So the upload-sentence nouns are `u_*`, never `k_*`.
  A second `k_PASSPORT` in one object literal is a tsc error. None of the other keys above exists
  at HEAD (checked).

  In the same file, add plan 1's passport keys to `LABELS` (`[en, az, tr, ru]` per key half),
  after `grade`. Without them `fieldLabel` prints the bare key ("number", "expiry date") in every
  language on every row this plan adds:

```ts
  // Spec 2026-10-12 §4.1-4.2: the keys a passport read writes.
  given_names: ["Given names", "Ad", "Ad", "Имя"],
  surname: ["Surname", "Soyad", "Soyadı", "Фамилия"],
  sex: ["Sex", "Cins", "Cinsiyet", "Пол"],
  citizenship: ["Citizenship", "Vətəndaşlıq", "Vatandaşlık", "Гражданство"],
  number: ["Document number", "Sənədin nömrəsi", "Belge numarası", "Номер документа"],
  expiry_date: ["Expiry date", "Etibarlılıq müddəti", "Son geçerlilik tarihi", "Срок действия"],
  issue_date: ["Date of issue", "Verilmə tarixi", "Veriliş tarihi", "Дата выдачи"],
  issuing_country: ["Issuing country", "Verən ölkə", "Veren ülke", "Страна выдачи"],
  issuing_authority: ["Issuing authority", "Verən orqan", "Veren makam", "Орган выдачи"],
  document_type: ["Document type", "Sənədin növü", "Belge türü", "Тип документа"],
```

- [ ] **Step 6: The panel.** In `extension/src/panel/panel.ts`:
  - Change `reasonText(reason, theirs, key)` to take the row:
    ```ts
    function reasonText(row: FieldView): string {
      const { reason, theirs, key } = row;
      if (reason.startsWith("portal:")) {
        return t(lang, theirs ? "portal_says_yours" : "portal_says", { text: reason.slice(7) });
      }
      if (reason === "") return "";
      const code = `r_${reason}` as StringKey;
      const source = row.offer ? (`src_${row.offer.source_kind}` as StringKey) : null;
      const kind = row.upload_kind ? (`u_${row.upload_kind}` as StringKey) : null;
      const vars = {
        field: fieldLabel(lang, key),
        value: row.offer?.value ?? "",
        source: source && Object.hasOwn(STRINGS[lang], source) ? t(lang, source) : "",
        kind: kind && Object.hasOwn(STRINGS[lang], kind) ? t(lang, kind) : "",
        date: row.expired_on ?? "",
      };
      return Object.hasOwn(STRINGS[lang], code) ? t(lang, code, vars) : t(lang, "r_other");
    }
    ```
    and update `fieldLine` to call `reasonText(row)`.
  - In `render`, change the field-row loop body to:
    ```ts
            const item = document.createElement("li");
            item.textContent = fieldLine(row);
            if (row.reason === "offer" && row.offer) {
              item.append(" ", button(t(lang, "b_use"), () => useOffer(row.key)));
            } else if (row.reason === "upload_once" || row.reason === "document_expired") {
              item.append(" ", button(t(lang, "b_open_documents"), openDocuments));
            }
            ul.append(item);
    ```
  - Add, next to `pick`:
    ```ts
    function button(text: string, onClick: () => void): HTMLButtonElement {
      const node = document.createElement("button");
      node.type = "button";
      node.textContent = text;
      node.addEventListener("click", onClick);
      return node;
    }

    /** The student's tap on an offered value; the worker confirms it and the
     *  content script types the server's value into the one box (spec §7.3). */
    function useOffer(key: string): void {
      if (!state.binding) return;
      void chrome.runtime.sendMessage({ type: "offer:use", tabId: state.binding.tabId, key });
    }

    function openDocuments(): void {
      void chrome.runtime.sendMessage({ type: "open:documents" });
    }
    ```
  - The value is set as text only (`textContent` and `t()` interpolation), like every other
    panel line.

- [ ] **Step 7: Run every extension check**

Run: `npm --prefix extension run typecheck && npm --prefix extension run build && npm --prefix extension run build:test && POSTGRES_DB=elmify_fact_reading uv run pytest -q -m extension tests/portals/test_extension_e2e.py`
Expected: PASS, including `test_every_panel_string_exists_in_all_four_languages`,
`test_the_field_list_shows_no_raw_keys_or_reason_codes` and the no-click scan.

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add extension/src tests/portals/test_extension_e2e.py
git -C /home/orkhan/Desktop/fact-reading commit -m "feat(extension): Use it in the panel confirms and types one offered value; upload and expiry lines link to the documents page"
```

---

### Task 5: Gates and the record

**Files:**
- Modify: `.claude/rules/portals.md`. Master split `CLAUDE.md` into `.claude/rules/` (#206), and
  the merge moved the fact-reading record there: the block "**Built, 2026-10-12: reading a
  student's documents into facts**". Add the bullet last in that block's list, after "**Every
  Azure answer counts toward the shared daily page ceiling**", and before the line "Full
  reasoning in `docs/superpowers/specs/2026-08-25-application-automation-decisions-design.md`."
  The file's `paths:` already cover `apps/portals/**`, `extension/**` and
  `apps/documents/fact_writer.py`, so the rule loads where it applies.

- [ ] **Step 1: Add the rule**

```markdown
- **An offered value is typed only after the student's tap, and only the server's.** A packet hint
  may carry a doubtful document value (`PacketHint.offer`). The panel's Use goes panel → worker →
  `ext_api.confirm_offer` → the bound tab. `profile.document_offers` is the one gate: `mint_packet`
  and the route both ask it. The route accepts only a fact the application's latest PACKET step
  offered *and* that `document_offers` still offers now. That means one value per row, of an ID
  document the student owns: never disowned or replaced, never `owner_mismatch` / `owner_unknown`,
  never an unread date (`fact_writer.needs_typing`), never an expired passport's, and a passport
  value only from the one passport portals are served (`profile._picked`). It writes the value as
  a new confirmed row (`fact_writer.use_document_value`), never confirms in place, so the tapped
  value is the one portals get next. The worker takes the offer from its cached packet and the
  value from the route's answer; nothing a page sends names either. The content script types it
  through verify → fill → read-back, judged against the whole packet, and never over a held value.
  Diploma and certificate values are never one tap away: they are answered on the dashboard.
```

- [ ] **Step 2: Run every gate**
  - `POSTGRES_DB=elmify_fact_reading uv run pytest -q`
  - `POSTGRES_DB=elmify_fact_reading uv run pytest -q -m extension`
  - `uv run ruff check .`
  - `uv run mypy apps config`
  - `uv run bandit -c pyproject.toml -r apps config`
  - `npm --prefix extension run typecheck && npm --prefix extension run build && npm --prefix extension run build:test`
    (before the `-m extension` run, which reads `extension/dist`)
  - `uv run python manage.py check`
  - `uv run python manage.py makemigrations --check --dry-run` (this plan adds no migration)

  Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add .claude/rules/portals.md
git -C /home/orkhan/Desktop/fact-reading commit -m "docs: the one-tap offer rule in .claude/rules/portals.md"
```

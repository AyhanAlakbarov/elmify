# Consent and privacy notice — one box at signup, anonymised data kept after the service

Status: design, awaiting owner review (2026-10-03). Branch `claude/requirements-owner-2026-10-03`.
Legal basis for every rule below: `docs/legal/2026-10-03-consent-and-privacy-memo.md` (a model-written
research memo, not legal advice).

## 0. Owner decisions this rests on (2026-10-03)

1. **Laws in scope: Azerbaijan's Law on Personal Data and the GDPR.** The memo finds that for an
   Azerbaijani company serving students located in Azerbaijan, the Azerbaijani law binds and the GDPR
   does not, until one of the §9 triggers happens.
2. **Signup works like a standard SaaS signup: one required, unticked checkbox.** The owner accepts
   the memo's finding that a ticked box may not meet the Azerbaijani "written consent" standard
   (Art. 8.1) and decides to use the checkbox for now. A local lawyer's confirmation is recorded as
   an open item (§10), not a launch gate.
3. **What is kept after the service ends is anonymised data only** — irreversibly unlinkable to the
   student, including by us. Azerbaijani law permits statistics on anonymised data (Art. 9.6.3, 9.13)
   and has no legitimate-interests basis, so nothing identifiable outlives the purpose it was
   collected for.
4. **No privacy-settings page.** The notice states that a student objects or withdraws by emailing
   us. §6 records the requests we still have to honour when they arrive another way.
5. **No age check** (owner, 2026-10-04: nothing on the platform is age-restricted). Signup asks no date of
   birth and stores no age. Azerbaijan's Law on Personal Data Art. 8.3 requires a parent's or guardian's
   consent for a minor; a minor's own tick is therefore not valid consent there — accepted by the owner,
   listed in §10 for the lawyer.
6. **Students pay application fees themselves** (requirements §5.3 amendment), so the notice carries
   no payment-data processing.

## 1. What a student sees

**At signup** (plain HTML for now; the team designs it later — requirements P1-9 amendment):

- Name, e-mail, password.
- One unticked, required checkbox:
  > ☐ I agree to the **Terms of Service** and consent to the processing of my personal data as
  > described in the **Privacy Notice**, including its transfer to the countries it lists.
- Both documents are links, opening the exact versions being accepted, in the student's language
  (Azerbaijani, English, Russian at launch).
- The account is not created without the tick. There is no age check (§0.5).

**When a document changes materially:** at the next login, one screen lists the new versions (each a
link to its text, in the student's language) with the same checkbox. Until it is ticked every other
page redirects to that screen: only the legal pages, sign-out and the account-deletion pages stay
reachable, and no new processing runs for them (no new searches, no documents generated). The
student cannot browse their data in the meantime. (As built; an earlier draft said they could.)

**Agency (white-label) students** see the same screen in the agency's branding; the notice they
accept is the agency template (§5).

## 2. The Privacy Notice — what it must say

One document per audience (direct students; agency students). It carries what Azerbaijani law
requires of consent (Art. 8.2) and what the GDPR requires of a notice (Art. 13), so it does not need
rewriting when the GDPR starts to apply:

- Who we are and how to reach us: company name, address, `privacy@` mailbox.
- **What we process:** identity basics, contact, education history, transcripts and grades, CV,
  motivation letters and the facts behind them, programme and funding choices, application status
  and outcomes, messages the student connects (mailbox feature), technical logs.
- **Why**, each purpose on its own line: running the service; sending application data to the
  universities and funders the student chooses; improving recommendations, aggregate statistics and
  testing our models **on anonymised data only**; service and, for direct students, marketing
  e-mails (§7).
- **Sensitive information:** letters and CVs can reveal health, family or religious facts; we use
  them only to produce the student's own documents and never in what we keep after the service.
- **Who receives it:** the universities and funders the student applies to; the AI model providers
  that process text for us (names and countries, Chinese hosts included); hosting and e-mail
  providers; for agency students, the agency.
- **Transfers abroad:** the countries above, and that the student's consent is what permits them.
- **How long:** personal data for as long as the account is active plus **12 months** (so a late
  admission result can still be recorded), then deleted; anonymised data indefinitely (§4).
- **Rights:** access, correction, deletion, stopping processing, objecting without giving reasons,
  withdrawing consent — **by e-mail to `privacy@`**; we reply within **7 working days** (§6).
- How the student is told about changes (§1).

## 3. Records

Two new tables and one shared one. All per-student rows are tenant-scoped. On erasure (§4) the existing
erasure scrubs the link to the student, and `Acceptance` and `PrivacyRequest` rows are kept de-identified
(`apps/audit/redaction.py` KEEP lists) as proof of what was accepted and when a request was handled.

| model | scope | holds |
|---|---|---|
| `LegalDocument` | shared (platform), like catalogue tables | kind (`terms`, `privacy_notice_direct`, `privacy_notice_agency`), language, version, `sha256` of the exact text, `effective_at`, `material` (bool) |
| `Acceptance` | tenant | student membership, the document rows accepted, `accepted_at`, surface (`signup` / `reacceptance`), language shown |
| `PrivacyRequest` | tenant | student membership, kind (`access`, `correction`, `deletion`, `objection`, `withdrawal`), channel (`email`, `paper_with_id`, `e_signature`), `received_at`, `due_at` (7 working days), `handled_at`, `handled_by`, outcome |

- An `Acceptance` names exact document versions by `sha256`, so "which text did this student agree
  to" has one answer.
- A withdrawal or objection stops processing for that student at once (Art. 7.2): every job that
  runs for a student checks for an open one, the same way it checks the deletion lock today.
- `AgencyDataUseAgreementVersion` stays the agency-side record (§5).

## 4. What is kept, and how it is anonymised

- **During the service:** full data, as today.
- **On erasure or 12 months after the account goes inactive:** the existing erasure path
  (`advance_deletion`) runs, and before it deletes, an **anonymiser** writes the student's
  contribution to the anonymised store.
- **The anonymised store holds no free text and nothing that singles out one person**: banded
  features (field of study, degree level, grade band on the awarded scale's own bands, destination
  country, intake year band, award type) and the outcome (admitted / rejected / funded / not funded).
  No name, no institution name, no exact dates, no CV or letter text. Any combination of fields
  shared by **fewer than 5 students is not stored at row level**; it is added only to aggregate
  counts with small cells suppressed.
- **Why the threshold:** an exact institution plus degree plus intake year can describe one person
  (CLAUDE.md, "Derived data"); data that can be linked back is not anonymous, and only anonymised
  data may outlive its purpose under Art. 9.4.
- **This replaces, for retention, the pseudonymised design in CLAUDE.md "Derived data":** `Pseudonym`
  stays the deletion-propagation rule for derived data *during* the service; nothing pseudonymised
  survives erasure.
- **Model training and testing on CVs and letters** happens only on live data during the service
  (covered by the consent's "testing our models" purpose) or on anonymised features afterwards.
  Raw documents are never kept for training after the service.

## 5. Agency (B2B) students

- **The agency is the controller for its students; we process on its behalf.** The memo finds this
  the correct model for delivering the service, and with only anonymised data kept afterwards we
  hold no personal data for our own purposes, so the joint-controller model is not needed.
- At agency onboarding the agency signs a **data-processing agreement**: our processing on its
  instructions, the sub-processor list (model and hosting providers, with countries), the
  anonymisation step in §4 as an agreed instruction, and help with student requests. Its version is
  recorded on `AgencyDataUseAgreementVersion`.
- The agency's students see `privacy_notice_agency`, which names the agency as controller and us as
  its processor; the agency may replace the template with its own, which must carry the §2 contents.
- Agency students receive no marketing from us (§7).

## 6. Requests about data

- The notice names one route: **e-mail to `privacy@`**. There is no settings page.
- **What we still honour when it arrives:** Azerbaijani law lets a student make a request in writing
  on paper with ID or electronically with an enhanced e-signature (Art. 7.5). Such a request is
  logged as a `PrivacyRequest` with its channel and handled the same way. The notice does not
  advertise these routes; it does not refuse them either.
- **Deadline:** 7 working days (extendable by 7 with notice); a refusal must be reasoned within 5.
  `due_at` drives a task for whoever handles privacy requests.
- **Identity check:** an e-mail request is accepted from the account's own e-mail address; anything
  else gets one reply asking the student to write from it.

## 7. E-mails after the service

- **Direct students:** service and product e-mails by default after the service ends, each with a
  note on how to stop them. As built, stopping them means writing to `privacy@`, logged and honoured
  by hand; there is no one-click unsubscribe link yet. Azerbaijan's E-Commerce Law Art. 6.2 asks for
  an opt-out that is honoured; a working link in every message is owed before these e-mails are
  sent at volume, and is not built.
- These e-mails stop when the personal data is deleted (§4): an anonymised record has no address.
- **Agency students:** none from us.

## 8. Deliberately not built

- A privacy-settings page or per-purpose toggles (owner).
- An age check or a parental-consent path (§0.5).
- E-signature (ASAN İmza / SİMA) consent; revisit if the lawyer says the checkbox is not enough.
- An EU/UK representative, SCCs and transfer impact assessments: needed only after a §9 trigger.

## 9. What would bring the GDPR in, and what changes then

Triggers: marketing to or targeting people in the EU/UK; keeping a profile of students after they
move to the EU; an EU or UK entity. Then: appoint an Art. 27 representative; the checkbox wording
changes to "I agree to the Terms" with the notice linked, not agreed to; SCCs and a transfer impact
assessment for non-adequate countries (China); an in-product way to object becomes strongly
advisable for model use (memo §4). The notice contents in §2 already cover Art. 13.

## 10. Open, owned by a licensed Azerbaijani lawyer (not launch gates by owner decision)

- Consent from a student under 18: there is no age check (§0.5), and Art. 8.3 requires a parent's or
  guardian's consent for a minor.
- Whether the checkbox meets Art. 8.1 "written" consent; whether Art. 8.6's E-Government consent
  route applies to private companies.
- Whether our information system must be registered (Cabinet Decision No. 237's reported
  1,000-subject threshold) and whether the Art. 9.14 licence still exists.
- Whether China meets Art. 14 or consent alone covers the transfer (the notice relies on consent).
- The reported draft new data law.

## 11. Testing

- A test that the signup form refuses an unticked box and a stale
  document version.
- A test that an open objection or withdrawal stops every per-student job, mirroring the deletion
  lock tests.
- A test that the anonymised store has no field able to carry free text, no FK to any per-student
  table, and that a combination below 5 students is never written at row level.
- A test that `advance_deletion` keeps `Acceptance` and `PrivacyRequest` rows de-identified (no student link, no name).
- RLS: the new tenant tables follow the tenancy pattern and are covered by the existing isolation
  tests; `LegalDocument` joins the shared-table list.

## 12. Build order

1. `LegalDocument`, `Acceptance`, the signup checkbox and age gate, re-acceptance (plain HTML).
2. `PrivacyRequest`, the per-student stop, the `privacy@` handling task with its 7-working-day due
   date.
3. The anonymiser and anonymised store, run inside the erasure path.
4. The agency processing agreement on `AgencyDataUseAgreementVersion`, and the agency notice template.
5. Notice texts in Azerbaijani, English and Russian (drafted for the lawyer to review).

# Runbook: privacy

Who does what for the consent screen, the legal texts and students' privacy requests. Spec:
`docs/superpowers/specs/2026-10-03-consent-and-privacy-notice-design.md`. Legal position:
`docs/legal/2026-10-03-consent-and-privacy-memo.md` (a model-written memo; a licensed Azerbaijani
lawyer's confirmation is still open, spec §10).

## Publishing the legal texts

The texts live in `apps/privacy/legal/<kind>.<lang>.md` (kinds `terms`, `privacy_notice_direct`,
`privacy_notice_agency`; languages `az`, `en`, `ru`; nine files). Editing a file does nothing until
it is published. At every deploy, after migrations:

```bash
DATABASE_ROLE=migration uv run python manage.py publish_legal_documents [--minor]
```

(With `POSTGRES_MIGRATION_USER` / `POSTGRES_MIGRATION_PASSWORD` set, the same credentials
`MigrationTaskDefinition` runs with.) Under `runtime_engine` or `runtime_web` it fails: the runtime
roles may only read `privacy_legaldocument`.

- It adds a new version for each file whose text changed and reports `unchanged` for the rest, so
  running it again is safe.
- **Without `--minor`, a changed text is a material version**: every student who accepted the
  previous one is shown the new text at their next login and cannot start new work until they accept.
- **`--minor`** marks the new versions as not material (a typo, a link, a phone number): nobody is
  asked again. Use it only when the meaning is unchanged. When unsure, publish as material.
- **Publish every language together.** A material change goes live in az, en and ru in the same
  run. Then a student who accepted the az text is asked again only when a material az version
  appears, and never sees a version that differs in meaning from the others.
- The az and ru files start with `DRAFT — translation for legal review, not yet approved.`. That
  line is part of the text students see. Remove it, in a material publish, once the lawyer has
  approved the translation.
- The English texts say "Company name and address: to be completed before launch" and use the
  placeholder address `privacy@tehsil.example`. Replace both before the first real student signs up.
- The agency notice contains the literal `{{ agency }}`; the legal page fills in the agency's name.

## The `privacy@` mailbox

Read it every working day. An e-mail from a student asking for access, correction, deletion, to
stop processing, to object, or to withdraw consent is a request with a legal deadline.

1. **Check the sender.** Accept a request from the e-mail address of the student's account. From
   any other address, send one reply asking the student to write from the account's address, and
   log nothing until they do.
2. **Log it the same day**, so the clock and the stop are on record:

   ```bash
   DATABASE_ROLE=runtime_engine uv run python manage.py record_privacy_request \
       --host <tenant host> --email <student's account e-mail> \
       --kind access|correction|deletion|objection|withdrawal \
       --channel email|paper_with_id|e_signature \
       [--received 2026-10-03T10:00:00+04:00]
   ```

   `--received` is when the request reached us (ISO 8601 with a time zone), not today, for a request
   that sat unread. The command prints the reply deadline. Run it on `WorkerTaskDefinition`, like the other operator
   commands.
3. **Never refuse a channel.** The notice advertises e-mail only, but Azerbaijani law (Art. 7.5) also
   lets a student write on paper with ID, or electronically with an enhanced e-signature. Log such a
   request with `--channel paper_with_id` or `--channel e_signature` and handle it exactly like an
   e-mail one.
4. **Reply within 7 working days** of receipt. If more time is needed, tell the student and take at
   most 7 more working days. A refusal needs a reason, sent within 5 working days. Weekends are
   skipped in the deadline; public holidays are not, so count them by hand.

## Checking the queue

Every working day:

```bash
DATABASE_ROLE=runtime_engine uv run python manage.py list_privacy_requests
```

It prints each open request across all tenants, soonest deadline first:
`host  id  e-mail  kind  channel  due <date>  open|OVERDUE`; the id is what
`close_privacy_request` takes. Handle `OVERDUE` first.

**Closing a request.** When it is handled, record the outcome:

```bash
DATABASE_ROLE=runtime_engine uv run python manage.py close_privacy_request \
    --host <tenant host> --id <request id from the list> \
    --outcome done|declined|resumed [--handled-by-email <your staff e-mail>]
```

It sets `outcome` and `handled_at` (and `handled_by`, the staff member named) and refuses a request
that is already closed. A request left open keeps showing in the list.

## What each kind does

- **Objection or withdrawal of consent: the student's account is paused as soon as the request is
  logged.** No new processing runs for them (the same way the deletion lock works), and every page
  they open redirects to `/privacy/stopped/`; only the legal pages, sign-out and the account-deletion
  pages stay reachable, so they cannot browse their data while paused. The pause lasts until the request is handled, and it **stays** when
  the outcome is `done`: an honoured objection or withdrawal means processing stays stopped. Two
  outcomes lift it: `declined` (a reasoned refusal) and `resumed` (the student asked, from the
  account's own address, to resume). Logging the request late means the stop starts
  late, so log it the same day.
- **Deletion:** log it, then use the existing erasure flow. The student's own route is
  `/student/account/deletion/`; the owner console is `/owner/deletions/`. After the thirty-day window
  `manage.py execute_due_erasures` executes it (see `docs/runbooks/deploy.md` and CLAUDE.md, "Erasure:
  the schedule is deferred"). Acceptances and privacy requests are not deleted: the erasure scrubs their link to the student (`apps/audit/redaction.py` keeps
  only `accepted_at`, surface, language and the age flag on an acceptance, and kind, channel, dates and outcome on a request), so
  they stay as de-identified proof of what was accepted and when a request was handled.
- **Access and correction:** answer from the student's data under a support grant
  (`docs/runbooks/support-access.md`); never from a cross-tenant query.

## Open items

Whether a signup checkbox counts as "written" consent, whether the information system must be
registered, and whether China meets Art. 14 are with the lawyer (spec §10). They are not launch gates
by owner decision, but the answers can change the texts, and a changed text is a new material
publish.

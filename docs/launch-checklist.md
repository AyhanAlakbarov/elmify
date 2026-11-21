# Launch checklist: owner actions before real students

Things no test can check, recorded so they are not lost. Tick an item by
deleting it in the PR that closes it, and say in that PR who checked it and when.

## Before publishing the staff-access wording

- [ ] **Lawyer review.** Agency data-processing agreement clause 6.2
  (`docs/legal/2026-10-03-agency-data-processing-agreement.md`) and the privacy-notice
  draft `docs/legal/2026-10-11-privacy-notice-staff-access.draft.md` (en/az/ru), which tell
  agencies and students that Elmify staff can view and download files and that every
  access is recorded. The draft sits outside `apps/privacy/legal/` on purpose, so it is not
  live; publishing it as a new notice version is the owner's step after the review.
  *(PR #194, owner decision 2026-10-11.)*

## Before students see the extension panel

- [ ] **Language check by a native speaker.** The Azerbaijani, Turkish and Russian panel
  messages in `extension/src/panel/i18n.ts` (the `n_*`, `k_*` and `nb_*` keys: what happened
  to each prepared file and document kind) and the az/ru text of the privacy-notice draft
  above. Both are first drafts written by Claude. *(PR #194.)*

## At the first deploy, and every deploy that changes `ocr/`

- [ ] **Ship the document parser with or before the worker.** Push the new `ocr/` image and
  set `OcrImage` in `infra/parameters/<env>.json` in the same deploy as, or before, the
  web/worker images (`docs/runbooks/deploy.md`). A worker paired with an older parser gets
  whole transcripts merged instead of only their current pages. *(PR #194.)*

## Standing rule, never ticked

- **Only Elmify creates Elmify-staff accounts.** A `PLATFORM_ADMIN` membership can view and
  download every active student's files in its agency without a support grant
  (`docs/runbooks/support-access.md`). It is created only through Django admin or a
  management command run by Elmify. Never add a way for an agency (owner, counsellor or
  invitation) to create or grant one. *(PR #194 security review.)*

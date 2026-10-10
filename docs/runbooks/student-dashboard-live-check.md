# Student dashboard: the live check

A manual end-to-end check that real mail reaches a student's board. Run it on a
local stack or a staging environment, never against a real student. About 30
minutes; it spends a handful of model calls.

## You need

- The app running with `MAILBOX_PROVIDERS=MICROSOFT`, the Microsoft OAuth client
  configured (`docs/runbooks/deploy.md`), `OPENAI_API_KEY` set
  (`source ~/.config/tehsil_agent/openai.env`), and an agency with a verified
  `TenantDomain` you can reach in a browser.
- `OPENROUTER_API_KEY` in the environment of the process that runs `sync_mailboxes`
  (Jev, the reader of decision mail, is reached through OpenRouter). The deployed
  `MailboxWorkerTaskDefinition` does not carry it yet: add it before running this on
  AWS. Without it every Jev reading is `not_configured` and abstains, so step 10 can
  only ask a person.
- Know before you start: no outcome is recorded automatically yet. Decision bars stay
  unmeasured until the paid `decision_eval score` run (without `--trust-corpus`) is
  written into `decision_bars.py`. Until then step 10 shows the reading and asks; it
  does not move the card by itself. An outcome is only ever recorded automatically
  from mail whose sender the provider authenticated (`MailSignal.sender_authenticated`).
- A personal Outlook.com inbox created for this check.
- A second mailbox on a domain whose DMARC passes at Outlook (your own domain),
  to send from.

## Steps

1. Create the student:
   `uv run python manage.py create_student --agency <agency-uuid> --host <host> --username live-check`
   (type the password twice when asked). Self-signup also exists at `/signup/`, but
   this check uses the command.
2. Log in at `https://<host>/accounts/login/`. A student made by `create_student` is
   first sent to `/privacy/accept/`; accept, then `/` lands on the board (`/student/`).
3. Complete the profile (Settings, Profile) and wait for Programmes & funding to
   stop reloading itself.
4. Press **Add to my applications** on one programme. The card appears in **To start**
   with **Open programme page** (no portal known yet).
5. As the counsellor (or with `record_portal` in a shell), record the card's portal as
   `https://<your-sending-domain>/apply`, so mail from that domain is vouched for
   this application.
6. Settings, Mailbox: connect the Outlook inbox, tier **Headers and body**, kind
   **Application inbox**. You land back on the mailbox page with "… is connected."
7. From your own domain, mail the Outlook address:
   subject "Missing document", body "Please upload a certified copy of your
   Bachelor's degree certificate by 15 June 2027."
8. Run `uv run python manage.py sync_mailboxes` (or wait for push, if enabled).
9. Check:
   - Messages lists the mail under the programme with "asks for: … degree certificate by 15 Jun 2027";
     the signal's `sender_authenticated` is true (DMARC passed at Outlook);
   - Documents shows **certified copy needed** in the Diploma row for that application;
   - Home: **Needs you now** has "Diploma — needed for …" with **Submit document**, and
     the card lists it under Missing.
10. Mail "We are pleased to inform you that you have been admitted to …" and sync
    again. Before the bars are measured (see "You need"): the card does not move; the
    reading is shown and the card asks, and **Record a decision** lets the student
    choose the outcome. After the bars are measured: the card moves to **Decision** and
    reads "Admitted — from <domain>'s email"; press **Not right?**, choose "No decision
    yet": the card leaves Decision. Either way an `application.outcome_recorded` audit
    event names the student.
11. Clean up: Settings, Mailbox, **Disconnect**; Settings, Account, delete the account.

## First deploy: the upload checks

Run once on the first real AWS deployment, **before the first real student uploads
anything**, and again whenever `EvidenceBucket`, the GuardDuty plan, `OcrFunction` or the
scan-result queue changes. The GuardDuty Malware Protection plan has never run on real AWS:
until this passes, "GuardDuty blocks malware" is a design statement, not a measured one.
About 20 minutes.

You need the test student from step 1 above, logged in, and a device token for them:
in `uv run python manage.py shell`, inside `tenant_scope(<agency-uuid>)`,
`token = redeem_pairing_code(issue_pairing_code(membership), "live-check")[1]`
(`apps.portals.pairing`). Never keep the token past this check.

1. Download the standard EICAR anti-malware test file (`eicar.com.txt`, from
   https://www.eicar.org). It is harmless by design; every scanner reports it as malware.
   Never commit it, and never paste its text into a file in this repository.
2. Documents, **Upload**, kind **Passport**, choose `eicar.com.txt`. This goes through the
   real presigned form (`/api/documents/uploads`), straight to `quarantine/`. The page must
   say "Uploaded. We are checking the file"; "Upload failed" with the object present in
   `quarantine/` means `EvidenceBucket`'s CORS rule (POST from any origin) is missing.
3. Within a few minutes, check every one of these:
   - the GuardDuty scan event carried a non-empty `versionId` (the worker reads exactly
     that version; with no `versionId` a clean verdict ends `REVIEW_REQUIRED`, never
     `AVAILABLE`): look at the scan-result queue message or the document worker's log;
   - `aws s3api get-object-tagging --bucket <EvidenceBucketName> --key quarantine/<agency-uuid>/<document-uuid>`
     shows `GuardDutyMalwareScanStatus` = `THREATS_FOUND`;
   - `GET /api/documents/uploads/<document-uuid>` answers `"state": "BLOCKED"`,
     `"scan_result": "THREATS_FOUND"`, and the Documents page lists the upload as blocked;
   - nothing was promoted: `DocumentVersion.promoted_key` is empty and
     `aws s3 ls s3://<EvidenceBucketName>/tenants/<agency-uuid>/students/<student-uuid>/uploads/`
     lists nothing for that document;
   - `curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer <token>" https://<host>/ext/documents/<document-uuid>`
     prints `404`.
4. Controls for the upload check (the isolated function's `inspect`, also never run on
   real AWS; it returns a sha256 of the bytes it read and promotion requires it to equal
   the bytes copied). Before this step confirm the roles can read the scanned version:
   `s3:GetObjectVersion` on `quarantine/*` for `DocumentWorkerTaskRole` and
   `OcrFunctionRole`, and in the OCR S3 VPC endpoint policy. Write two files from a checkout:
   `uv run --project ocr python -c "import sys; sys.path.insert(0, 'ocr'); import pdf_fixtures as f; open('/tmp/plain.pdf','wb').write(f.written()); open('/tmp/launch.pdf','wb').write(f.written(f.launch))"`.
   Upload `/tmp/plain.pdf` as a Passport: it reads "checking…" briefly, then ends `AVAILABLE`
   with a `promoted_key` (a real object under `tenants/<agency-uuid>/students/<student-uuid>/uploads/`).
   Upload `/tmp/launch.pdf`: it ends `REJECTED_ACTIVE_CONTENT` and the Documents page shows
   "This PDF contains active content; save it again as a plain PDF (Print → Save as PDF) and
   upload that". Upload any `.txt` file renamed `passport.pdf`: `REJECTED_TYPE`, "Upload a
   PDF, JPEG or PNG".
5. Clean up: Settings, Account, delete the test account; revoke the pairing if it is not
   already revoked.

If the EICAR upload is promoted, reaches `AVAILABLE`, or `/ext/documents/<id>` returns
anything but 404: **stop — no student uploads until it is fixed.** Check, in order, that the
GuardDuty plan is enabled on `EvidenceBucket` with the `quarantine/` prefix, that the
scan-result EventBridge rule reaches the queue, and that the document worker is draining it.
If the upload stays `QUARANTINED`, the verdict never arrived (the same checks); if a control
in step 4 stays `CHECKING` and later becomes `REVIEW_REQUIRED`, the document worker could not
invoke `OcrFunction`.

## If a step fails

- No signal at step 8: the sender's domain is not vouched (step 5) or the sync
  refused the grant (`MailboxConnection.status`).
- A signal without a label: the connection is on the headers-only tier, or
  classification failed (`MailSignal.classify_attempts`).
- Step 10 does not move the card: expected until the bars are measured; also check
  `MailSignal.sender_authenticated` and that `OPENROUTER_API_KEY` is set.
- A label but no card change: the message was not trusted (`MailSignal.trusted`
  false: DMARC did not pass), which is the designed behaviour for an unverified sender.

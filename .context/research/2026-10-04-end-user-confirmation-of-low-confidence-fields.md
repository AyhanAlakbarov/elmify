# Asking the uploader to confirm only the doubtful fields: is it normal, and what makes it work?

Date: 2026-10-04. Purpose: design input for the transcript reader's confirmation step. The reader extracts course rows (credits, grades), runs arithmetic checks, and asks the student to confirm only the cells that have low reader confidence or that fail a check. The target is 0–3 cells per transcript.

Builds on `2026-10-03-document-capture-quality-gates.md`, which covers capture, retake, Veryfi/ABBYY thresholds and Ocrolus reconciliation. That material is not repeated here.

## Direct answer

**Yes, it is an accepted pattern, but it is rarely used on its own.** What the evidence shows:

- **What each product family does by default:**
  - Consumer products that pre-fill from a document usually show *every* field, editable, with a general "please review" warning: Greenhouse résumé autofill, Entrust ID autofill, the GOV.UK "check answers" pattern and TurboTax.
  - Document-processing platforms use confidence routing. Confident fields are accepted without review, and doubtful fields go to a *staff* reviewer: Azure, UiPath, Hyperscience, AWS A2I.
- **Selective, flagged-only prompts to the end user exist in production:**
  - Expensify notifies the user only "if a receipt needs attention".
  - Identomat skips the applicant review page when every field came from a trusted source.
  - IDWise offers a data-confirmation screen for cases where image quality limited extraction.
  - UiPath's reviewer UI can hide every field that has no flagged issue.
- **So the design is a hybrid of known parts.** Confident and reconciled cells are accepted without review (b). Doubtful cells go to the person who owns the document (a, narrowed). Unresolved cells, plus a random audit sample, go to a staff queue (c).

**The closest education analogue supports putting the student in the loop.** On STARS (formerly SRAR/SSAR), US admissions offices accept grades the student self-reports from the transcript. They verify those grades against the official transcript later and penalise discrepancies.

**What makes it work or fail is mostly the risk the research documents.** Highlighting some items makes people find the highlighted errors and *miss the unhighlighted ones*. It helps only when the flagging signal is accurate. With 0–3 flags per transcript, everything rests on the flagger's recall: confidence scores plus arithmetic checks. That recall has to be measured with an audit sample of unflagged cells.

## Scope (sub-questions)

1. In end-user flows that pre-fill from a document, does the user see all fields or only the flagged ones, and how are they flagged?
2. What do document-processing platforms document about confidence-threshold routing, who reviews, and what calibration advice do they give?
3. What does the research say about automation bias, highlighting a subset of fields, and confidence calibration?
4. Do admissions systems let applicants self-report transcript data and verify it later?

## How sources were found

- **Discovery:** Exa open searches (`web_search_exa`) for each product family and for the research. Then Exa `includeDomains` limited to each owner: learn.microsoft.com, docs.uipath.com, cloud.google.com, support.greenhouse.io, commonapp.org/ucas.com, expensify.com and arxiv.org.
- **Brave:** one exact-title search, used to find an open copy of Vertanen & Kristensson (2008).
- **Product list:** the candidate products came from the caller's list. The products actually documented came from what those searches returned, not from memory.
- **Citations:** every cited page was fetched with scrapling `get` or `bulk_get`.
- **Not used:** Tavily and Context7 (not needed). The `ide` MCP server failed to connect; it was not needed.
- **Pages that would not load as plain HTML:**
  - TurboTax help rendered only in a browser (scrapling `fetch`). It is quoted below without a footnote.
  - The Common App support pages are client-rendered, and the LSU STARS page returned nothing. Neither is cited.
  - PubMed Central and OUP blocked bots. The Goddard et al. review is cited through the Europe PMC REST API instead.
- **Not covered (no primary page fetched):** H&R Block, FreeTaxUSA, Ramp, Brex, Dext, Stripe Identity, Onfido, Persona and Veriff pre-fill screens, Workday and Lever candidate flows, insurance claims apps, UCAS, Coalition/Scoir, Rossum, ABBYY Vantage, and the full text of Parasuraman & Manzey (2010).

---

## 1. End-user flows that pre-fill from a document

| Product | What the user sees | How doubt is surfaced | Who is responsible |
|---|---|---|---|
| Greenhouse (MyGreenhouse, résumé parse and Quick Apply) | All parsed fields, editable | Blanket warning: "Resume parsing is designed to save time, but can make mistakes. Be sure to review and edit…"[^14] Autofilled answers stay editable before submitting.[^15] | Candidate |
| TurboTax (W-2 import) | All boxes on the W-2 screen | None documented. A 2026 help page about a duplicate-import bug says "when using import services, the customer is responsible for verifying the accuracy of the information that is imported". (Page renders only in a browser, so no footnote. Fetched 2026-10-04 at ttlc.intuit.com, "How do I check my 2025 tax return for duplicate W-2 data?") | User, by terms of service |
| Entrust Autofill (ID → sign-up form) | Pre-populated form | "The user can then check and edit the form if needed, before being onboarded".[^16] Entrust warns Autofill "should not be used for critical decision making or instances where a high level of accuracy is required."[^17] | User; vendor disclaims accuracy |
| Identomat (ID verification) | **Only when needed.** The review page appears "only… if at least one field is editable and at least one of those fields is either empty or not sourced from MRZ, NFC, or QR"[^18] | Trusted-source fields are "permanently read-only regardless of configuration".[^19] Every edit is logged with the original OCR value, the edits and the actor.[^20] | Applicant and/or operator (configurable) |
| IDWise (ID verification) | Optional data-confirmation screen "when extraction is affected by image quality, capture quality, or other limitations"[^21] | An "Editing Threshold" caps how much editing is allowed: "10%, 20%, 30%, 40%, 50%, and 100%".[^22] | End user, bounded |
| Expensify SmartScan | Nothing by default; the expense is created automatically | "You'll get a notification if a receipt needs attention, and Concierge may even ask follow-up questions".[^23] | User, prompted only on doubt |
| Capital One mobile deposit | User types the amount; the bank reads the cheque | **The document wins:** "If the amount you enter is different from the one on the check, we'll automatically adjust the amount to match what is on the check."[^24] | Bank |
| GOV.UK Design System ("check answers") | Every answer before submission, each with a "Change" link | The page exists to "reduce error rates as users are given a second chance to notice and correct errors before submitting data",[^25] and must "make it clear the transaction will not be complete until a user confirms their information is correct".[^26] | User |

**Reading the table:**
- Show-all with a blanket warning is the most common consumer default.
- Flag-only prompting appears where the vendor has an independent trust signal: MRZ/NFC/QR provenance for Identomat, quality limits for IDWise, a needs-attention state for Expensify.
- Two guardrails recur:
  - The user's edits are bounded or audited (IDWise cap, Identomat history).
  - The document, not the user, is the final authority (Capital One).

## 2. Platforms that document confidence-threshold routing

| Platform | Who reviews | What the docs say |
|---|---|---|
| Azure Document Intelligence | Customer's staff ("human-in-the-loop") | "For scenarios where accuracy is critical, confidence can be used to determine whether to automatically accept the prediction or flag it for human review."[^1] Example threshold: ≥ .80 straight-through, < .80 human review.[^2] Calibrate on your own pilot first.[^3] |
| Azure Content Understanding | Staff | Per-field routing: post the confident billing address and send the 0.52-confidence amount "to a human for verification".[^5] Grounding (page and coordinates) lets the reviewer "validate the results quickly by reviewing the specific location in the document".[^4] |
| UiPath Document Understanding (Validation Station) | "knowledge workers" (staff)[^6] | Validation is recommended when you lack other sources of truth or "sufficient synthetic checks you can use on data consistency".[^7] The compact view can hide every field "with no flagged issues".[^8] Default threshold is 0.9 where none is set.[^9] Submitting still covers hidden fields.[^10] |
| Hyperscience | Staff data keyers | Fields below threshold go "to a data keyer for Transcription Supervision".[^12] |
| AWS A2I + Textract | Staff or vendor workforce | Supports confidence-range triggers and "Randomly send a sample of forms to humans for review."[^13] |
| Google Document AI | n/a | Its Human-in-the-Loop feature is deprecated: "Human in the Loop (HITL) January 16, 2024".[^11] |
| Ocrolus (from the prior file) | Staff | Arithmetic reconciliation is a rejection reason: "The sum of the transactions does not match the beginning and ending balances stated on the statement."[^47] |

**What these platforms share:**
- Every one of them puts *staff*, not the document's owner, in the doubtful-field queue. None found describes routing low-confidence fields to the person who uploaded the document.
- That step is the end-user products' territory (section 1).
- Calibration advice is the same everywhere: set the threshold from your own pilot data, not a vendor default.

## 3. Evidence: automation bias, partial highlighting and calibration

- **Highlighting a subset shifts attention away from the rest.** Vertanen & Kristensson (CHI 2008) underlined low-confidence words in speech-recognition output:
  - Underlining "did not increase user's speed or accuracy in detecting errors" overall.[^34]
  - When errors were *not* underlined, "they were discovered less often".[^35]
  - Users "tend to trust confidence visualization", so designers should be careful without a high-accuracy confidence measure.[^36]
- **The same result in radiology and visual search.** Kneusel & Mozer's review:
  - With weaker classifiers, highlights "decreased performance, mainly in terms of increased failure to detect non-highlighted targets".[^39]
  - Highlighting the wrong location "resulted in twice as many missed targets as failing to highlight any location".[^40]
  - Highlights "improved sensitivity at the highlighted locations but decreased sensitivity in non-highlighted locations".[^41]
  - When the aid seems reliable, people "may become overly reliant and overlook non-highlighted targets".[^48]
- **Raw confidence scores are a weak flagger on their own.** Kuhn et al. (CHI EA 2025, end-to-end ASR):
  - Confidence classifiers "frequently miss errors or generate many false positives".[^38]
  - "Confidence-based error detection neither improved correction efficiency nor was perceived as helpful by participants."[^37]
  - This is speech recognition, not table OCR, so it transfers by analogy only.
- **Making correction costly increases rubber-stamping.** Beck et al. (2025 preprint, 2,784 participants):
  - "requiring corrections for flagged AI errors reduced engagement and increased the tendency to accept incorrect suggestions".[^42]
  - Reviewers sceptical of AI "detected errors more reliably and achieved higher accuracy".[^43]
- **Size of the effect, and known mitigators.**
  - Goddard's empirical study (26 GPs, 70%-accurate advice) found automation bias in 5.2% of cases.[^46]
  - Goddard et al.'s systematic review lists these mitigators:
    - "emphasizing user accountability".[^44]
    - Per-item "updated confidence levels attached to DSS output, and the provision of information versus recommendation".[^45]
- **Research on how often end users correct pre-filled document data:** none was found. This is **Unverified / no evidence located**.

**What this means for 0–3 cells.** The 0–3 design is the Vertanen/Kneusel setup: a few highlighted cells and many unhighlighted ones.

- It helps only if the flagger catches nearly all real errors.
- Arithmetic reconciliation is an independent signal, not the reader's own self-assessment, so it is the stronger half of the flagger.
- How many errors slip through in unflagged cells has to be measured, not assumed.

## 4. Education: self-report, then verify against the document

- **What STARS asks of applicants.** The applicant types every course and grade from the transcript.
  - SRAR support: "you should never enter courses or grades from memory".[^32]
  - UT Knoxville requires an unofficial transcript upload alongside it.[^31]
  - UTSA's form blocks submission while warnings remain: "You cannot submit your STARS until you no longer see any warning messages."[^33]
- **How it is verified later.** After admission, the university compares STARS with the final official transcript.[^27]
  - "Any discrepancies found can affect your original admission decision or financial aid offer."[^28]
  - UT Knoxville: inaccurate data may lead to denial, rescinded admission or cancelled registration.[^30]
  - UTSA also commits that "Malice-free errors will occur, and every effort will be made to fairly judge intent."[^29]
- **Common App's "Courses & Grades"** follows the same self-report pattern. Its support pages are client-rendered and were not fetched, so details are **Unverified**.

**Lesson for our design:**
- Admissions treats the student's entry as an *attestation*, checked later against an authoritative document, with consequences.
- Our flow reverses who types (the machine reads, the student confirms), but should keep the same structure:
  - an attestation by the student,
  - an independent check against the document,
  - a human who judges intent on discrepancies.

---

## The pattern the best products share

Each layer below combines elements documented separately in the sections above. No single product found does all of them.

1. **Straight-through for confident, reconciled cells** (Azure, Content Understanding, UiPath thresholds).
2. **Targeted prompt to the document owner for the few doubtful cells:**
   - Show the source region next to the value (Content Understanding grounding, UiPath document view).
   - Skip the prompt entirely when nothing is doubtful (Identomat, Expensify).
3. **Guardrails on the owner's edits:**
   - Cap the amount of editing (IDWise).
   - Keep a full edit history with the original machine value (Identomat).
   - Let the document override the typed value (Capital One).
4. **A final "check your answers" page** that makes completion conditional on explicit confirmation (GOV.UK).
5. **Staff queue for anything unresolved, plus a random sample of unflagged items** (Hyperscience, A2I).

## Do / don't for the 0–3 cell confirmation

### Do
1. **Show the cropped image of the original cell beside the extracted value.** Add the row context (course name) so the student compares against the source, not against memory.[^4][^32]
2. **Say why each cell is flagged, in plain words.** For example: "credits on this page add up to 238; the transcript total says 240". A reason gives the student information rather than a bare instruction, which is the "information versus recommendation" mitigator.[^45]
3. **Require an explicit choice per flagged cell: "matches", "fix" or "can't read".** Nothing is pre-selected, and there is no "confirm all".
   - Pre-selecting nothing is a design inference from the accountability and burden findings,[^44][^42] not a documented product practice (**Unverified** as a published pattern).
4. **Keep correcting cheap.**
   - The input sits inline next to the crop.
   - "Can't read" is accepted without typing and routes the cell to a counsellor.
   - Beck et al. found that adding correction effort increased acceptance of wrong values.[^42]
5. **Re-run the arithmetic after every edit.** An edit that breaks reconciliation is flagged again (Ocrolus-style reconciliation[^47]; UiPath's flagged-issue rules[^8]).
6. **Store the original reader value, the student's value, a timestamp and the actor for every edit**[^20], and treat the document as authority. A counsellor can see when a student's value contradicts the crop (the Capital One principle[^24]).
7. **Bound the edits.** If a student changes more than a set share of cells, or any trusted-source field, route the transcript to counsellor review instead of accepting it (IDWise editing threshold[^22], Identomat read-only trusted fields[^19]).
8. **End with a read-only summary of the whole table and a clear attestation.** Completion is conditional on confirmation[^26], with an attestation in the STARS style[^28]. Give an obvious "something else is wrong" link, so unflagged cells are not presented as verified.
9. **Send a small random sample of transcripts with zero flags to counsellor audit.** This measures how many errors slip through in unflagged cells (A2I random sampling[^13]). Set and adjust the confidence threshold from that data, not from a vendor default (Azure pilot advice[^3]; UiPath's 0.9 is only a default[^9]).
10. **Route to a counsellor queue** any cell marked "can't read", any reconciliation that still fails after the student acts, and any transcript over the edit cap (the staff queue in Hyperscience and UiPath[^12][^6]).

### Don't
1. **Don't let confidence alone decide what is flagged.** Uncalibrated confidence flags miss errors and make the unflagged ones less likely to be found.[^35][^38][^39] Pair confidence with arithmetic checks, and measure the flagger's recall.
2. **Don't flag many cells to be safe.** Inaccurate highlighting is worse than none.[^40] If a transcript produces many flags, the reading is bad: retake or send to a counsellor rather than showing a wall of yellow.
3. **Don't treat the student's "matches" as verification.** It is an attestation, like STARS, and the document stays the authority.[^27][^24]
4. **Don't show raw confidence percentages to students.** Show the reason and the crop instead. This is a judgement, not a sourced rule; Goddard's per-item confidence finding came from expert users.[^45]
5. **Don't word unflagged cells as "verified".** Users overtrust confidence displays.[^36][^48]
6. **Don't build on Google Document AI HITL.** It is deprecated.[^11]

## Open questions
- **Who confirms when the student is a minor or a counsellor drives the session?** Not researched.
- **No published correction-rate data for end users confirming pre-filled document fields** was found. Our own audit sample (Do 9) is the only way to get it.
- **Not checked:**
  - Whether Stripe Identity, Onfido, Persona or Veriff offer a flag-only end-user confirmation screen (no first-party page fetched).
  - What uni-assist, UCAS and Common App actually do with self-reported grades. Common App's client-rendered support pages were not fetched.
  - H&R Block, FreeTaxUSA, Workday and Lever candidate flows.
- **Beck et al. is a preprint and Kuhn et al. is an extended abstract.** Both point the same way as the peer-reviewed CHI 2008 and radiology findings, but neither studied transcript tables.

## Sources
[^1]: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/concept/accuracy-confidence?view=doc-intel-4.0.0 "For scenarios where accuracy is critical, confidence can be used to determine whether to automatically accept the prediction or flag it for human review."
[^2]: https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/document-intelligence/transparency-note "the customer might submit results with confidence values greater than or equal to .80 for straight-through processing and apply human review to results with confidence values less than .80"
[^3]: https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/document-intelligence/transparency-note "Customers should run a pilot or a proof of concept representing their use case to understand the range of confidence values and the extraction quality from Document Intelligence."
[^4]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/document/analyzer-improvement "When seeing lower than expected confidence scores, validate the results quickly by reviewing the specific location in the document."
[^5]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/document/analyzer-improvement "your automation pipeline can post the billing address directly to your downstream application while routing the amount due to a human for verification"
[^6]: https://docs.uipath.com/document-understanding/automation-cloud/latest/classic-user-guide/data-extraction-validation-overview "This refers to a human review step, in which knowledge workers can review the automatically extracted results and correct them when necessary."
[^7]: https://docs.uipath.com/document-understanding/automation-cloud/latest/classic-user-guide/data-extraction-validation-overview "you do not have sufficient synthetic checks you can use on data consistency"
[^8]: https://docs.uipath.com/action-center/automation-cloud/latest/user-guide/validation-station-field-filters "hides the fields that the Validation Station is not flagging, leaving only the fields with something to resolve"
[^9]: https://docs.uipath.com/action-center/automation-cloud/latest/user-guide/validation-station-field-filters "Where a threshold is not set, 0.9 applies."
[^10]: https://docs.uipath.com/action-center/automation-cloud/latest/user-guide/validation-station-field-filters "Confirming all values and submitting the action cover every field, including the ones the active filters hide."
[^11]: https://cloud.google.com/document-ai/docs/deprecation "Human in the Loop (HITL) January 16, 2024"
[^12]: https://help.hyperscience.com/v41/docs/transcription-settings "send all fields below the corresponding threshold to a data keyer for Transcription Supervision"
[^13]: https://docs.aws.amazon.com/sagemaker/latest/dg/a2i-textract-task-type.html "Randomly send a sample of forms to humans for review."
[^14]: https://support.greenhouse.io/hc/en-us/articles/43418495049499-MyGreenhouse-FAQ-for-Candidates "Resume parsing is designed to save time, but can make mistakes. Be sure to review and edit your information before saving your profile and before submitting all applications."
[^15]: https://support.greenhouse.io/hc/en-us/articles/43418495049499-MyGreenhouse-FAQ-for-Candidates "You can always change your Quick Apply profile or edit autofilled answers before submitting."
[^16]: https://documentation.identity.entrust.com/guide/autofill/ "The user can then check and edit the form if needed, before being onboarded"
[^17]: https://documentation.identity.entrust.com/guide/autofill/ "Autofill should not be used for critical decision making or instances where a high level of accuracy is required."
[^18]: https://docs.identomat.com/platform-concepts/document-data-review "The review page is only presented if at least one field is editable and at least one of those fields is either empty or not sourced from MRZ, NFC, or QR."
[^19]: https://docs.identomat.com/platform-concepts/document-data-review "Fields populated from NFC, QR, or MRZ are permanently read-only regardless of configuration."
[^20]: https://docs.identomat.com/platform-concepts/document-data-review "Every field stores a full history of changes including the original OCR value, any user or operator edits, the final value, and timestamps with actor information for each change."
[^21]: https://docs.idwise.com/docs/id-document-module-configuration "Lets end users review, validate, and correct data extracted from the document when extraction is affected by image quality, capture quality, or other limitations."
[^22]: https://docs.idwise.com/docs/id-document-module-configuration "Defines how much editing is allowed. Supported thresholds are 10%, 20%, 30%, 40%, 50%, and 100%."
[^23]: https://use.expensify.com/receipt-scanning-app "You’ll get a notification if a receipt needs attention, and Concierge may even ask follow-up questions to make sure everything’s accurate."
[^24]: https://www.capitalone.com/help-center/checking-savings/mobile-deposits/ "If the amount you enter is different from the one on the check, we’ll automatically adjust the amount to match what is on the check."
[^25]: https://design-system.service.gov.uk/patterns/check-answers/ "reduce error rates as users are given a second chance to notice and correct errors before submitting data"
[^26]: https://design-system.service.gov.uk/patterns/check-answers/ "make it clear the transaction will not be complete until a user confirms their information is correct"
[^27]: https://future.utsa.edu/freshman/stars/ "The university will compare the applicant’s academic record from STARS and final high school transcript once the applicant has been accepted."
[^28]: https://future.utsa.edu/freshman/stars/ "Any discrepancies found can affect your original admission decision or financial aid offer."
[^29]: https://future.utsa.edu/freshman/stars/ "Malice-free errors will occur, and every effort will be made to fairly judge intent."
[^30]: https://admissions.utk.edu/undergraduate-application/self-reported-academic-record-information/ "Students with inaccurate data on the STARS may be denied admission to the University, have their admission rescinded, and have their registration cancelled if enrolled."
[^31]: https://admissions.utk.edu/undergraduate-application/self-reported-academic-record-information/ "We require an unofficial copy of your transcript to be uploaded along with your STARS."
[^32]: https://srarsupport.zendesk.com/hc/en-us/articles/4408743335067-What-do-I-need-to-complete-the-SRAR-SSAR "Since accuracy is crucial, you should never enter courses or grades from memory."
[^33]: https://future.utsa.edu/freshman/stars/ "You cannot submit your STARS until you no longer see any warning messages."
[^34]: https://www.keithv.com/pub/confshade/ "underlining low-confidence areas did not increase user's speed or accuracy in detecting errors"
[^35]: https://www.keithv.com/pub/confshade/ "Conversely, when errors failed to be underlined, they were discovered less often."
[^36]: https://www.keithv.com/pub/confshade/ "users tend to trust confidence visualization, designers should be careful in its application if a high accuracy confidence measure is not available"
[^37]: https://arxiv.org/abs/2503.15124 "Confidence-based error detection neither improved correction efficiency nor was perceived as helpful by participants."
[^38]: https://arxiv.org/abs/2503.15124 "Classifiers frequently miss errors or generate many false positives, undermining their practical utility."
[^39]: https://ar5iv.labs.arxiv.org/html/1612.08117 "highlights decreased performance, mainly in terms of increased failure to detect non-highlighted targets"
[^40]: https://ar5iv.labs.arxiv.org/html/1612.08117 "highlighting the wrong location resulted in twice as many missed targets as failing to highlight any location"
[^41]: https://ar5iv.labs.arxiv.org/html/1612.08117 "highlights improved sensitivity at the highlighted locations but decreased sensitivity in non-highlighted locations"
[^42]: https://arxiv.org/abs/2509.08514 "requiring corrections for flagged AI errors reduced engagement and increased the tendency to accept incorrect suggestions"
[^43]: https://arxiv.org/abs/2509.08514 "Participants skeptical of AI detected errors more reliably and achieved higher accuracy"
[^44]: https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:10.1136/amiajnl-2011-000089&resultType=core&format=json "Mitigators of AB included implementation factors such as training and emphasizing user accountability"
[^45]: https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:10.1136/amiajnl-2011-000089&resultType=core&format=json "updated confidence levels attached to DSS output, and the provision of information versus recommendation"
[^46]: https://openaccess.city.ac.uk/id/eprint/3005/ "The rate of AB, as measured by decision switches from correct pre advice, to incorrect post advice was 5.2% of all cases at a CDSS accuracy rate of 70%"
[^47]: https://docs.ocrolus.com/docs/rejection-reasons "The sum of the transactions does not match the beginning and ending balances stated on the statement."
[^48]: https://ar5iv.labs.arxiv.org/html/1612.08117 "when the CAD seems reliable, individuals may become overly reliant and overlook non-highlighted targets"

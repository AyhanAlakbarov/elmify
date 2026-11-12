# Document capture quality gates: how SaaS products decide "retake", say why, and verify what they read

Date: 2026-10-03. Purpose: design input for the transcript capture flow (owner requirement: when the scan/photo is bad or unsatisfactory, show "retake" plus the reason).

## Answer in one paragraph

Every product looked at splits the job into the same four stages. First, live guidance in the camera that refuses to fire until the page is found, large enough, flat enough, bright enough and sharp. Second, a per-page check after capture that blocks the image or warns about it, with a short list of fixed reason codes. Third, a retry budget: two retries is common, after which the user may continue and the case is flagged for review, or is handed another route (upload a file, switch device, human review). Fourth, after reading, a check of the extracted data itself: field confidence thresholds that route to a human, required fields that are missing, and arithmetic reconciliation (totals that must add up). For transcripts, stages 1, 3 and 4 transfer almost unchanged. Stage 2 transfers only in part: the ID-document checks for glare on security features, black-and-white rejection, aspect ratio, face/MRZ and photocopy do not apply.

## Scope (sub-questions answered)

1. Which checks do mobile capture SDKs run live, what thresholds or knobs do they expose, and what feedback do they give?
2. What retake/rejection reasons do identity-verification (IDV) vendors return, which run on the device and which on the server, and how many retries before a fallback?
3. What do receipt, bank-statement and IDP vendors do after reading (confidence routing, reconciliation, human review)?
4. What do credential evaluators and admissions platforms require of uploaded transcript scans, and do they reject bad uploads automatically?
5. What numeric resolution and text-size floors do OCR vendors and digitisation standards publish?

## How sources were found

- Tools used: Exa (discovery, plus owner-domain searches using `includeDomains`) and scrapling `get` / `bulk_get` (every cited page). Not used: Brave, Tavily, Context7. Not needed: the vendor list came from the caller's question, not from memory. Exa searches were then limited to each owner's domain (scanbot.io, microblink.com, github.com/Mitek-Systems, github.com/onfido, docs.sumsub.com, docs.stripe.com, withpersona.com, docs.ocrolus.com, veryfi.com, hyperscience.com, docs.aws.amazon.com, learn.microsoft.com, uni-assist.de, wes.org, commonapp.org, digitizationguidelines.gov).
- One session problem: the `ide` MCP server did not connect. It was not needed.
- Not covered (no primary page fetched): Dynamsoft, Anyline, Expensify, Ramp, Docsumo, Mitek cheque IQA, ECE, Parchment, UCAS, ISO/AIIM standards. Yoti and Argos came up in searches and were left out of the citations because their pages did not load as plain HTML or were not fetched.

---

## (a) The common pipeline, stage by stage

### Stage 0. Choose the input route
- Camera capture is the default. Most vendors also allow a file upload, and some offer a switch to a phone. Persona's documented capture methods are guided capture, unguided capture, file upload and device handoff. **Unverified:** that list comes from a Persona help page seen only in search results.
- Admissions bodies prefer documents issued electronically by the institution. uni-assist counts a document as official if it carries a signature and stamp, or "a reference to their automatic issuance or a verification code".[^54]

### Stage 1. Live guidance in the camera (on the device, before any upload)
- **Find the page and its corners.** Scanbot reports a fixed set of statuses: `ERROR_NOTHING_DETECTED`, `OK_BUT_TOO_SMALL`, `OK_BUT_BAD_ANGLES` ("A document was detected, but it has too much perspective distortion."[^1]), `OK_BUT_BAD_ASPECT_RATIO`, `OK_BUT_OFF_CENTER`, `OK_BUT_TOO_DARK` and `ERROR_TOO_DARK` ("No document was detected, likely because the input image is too dark."[^2]). Each status has its own text hint that you can override.[^7]
- **Thresholds are exposed as settings.** Scanbot's defaults are: size score ≥ 80 % of the screen ("Default is 80.0"[^3]), perspective score ≥ 75 ("Default is 75.0"[^4]), and a brightness threshold on a 0–255 scale below which the status becomes `ERROR_TOO_DARK`.[^6]
- **Blur, glare and lighting are handled by dropping frames.** BlinkID can reject frames with blur, glare or poor lighting ("frames with detected blur are skipped, so only sharp frames are processed"[^12]). Its UI prompts the user "to move closer, hold steady, or avoid glare".[^13] The trade-off is stated: in bad conditions "fewer frames qualify, so scanning can take longer before a usable frame arrives".[^14] MiSnap shows live hints "whenever there are improvements that can be made for a better image quality".[^16]
- **Auto-capture fires once conditions hold for a short time.** Scanbot's auto-snap delay runs from immediate to 3 s, with a default of 0.66, which is about 2 s.[^5] Google ML Kit's scanner offers "Automatic capture with document detection."[^8] It runs fully on the device[^9] and lets the app cap the number of pages.[^10]
- **Some platform scanners expose no quality codes at all.** Apple's `VNDocumentCameraViewController` is a closed UI that returns page images ("The results of a scan include images, by page number."[^11]). Its reference page documents no quality-status API. ML Kit's overview likewise describes a fixed UI flow and no per-frame quality codes. If you use either one, you must run your own stage-2 checks.

### Stage 2. Per-page check after capture (on the device or the server)
- **Readability score per page.** ABBYY Mobile Web Capture returns an OCR-suitability confidence from 0 to 1, and treats the image as "ready for OCR, if confidence value is 0.6 and larger".[^23] Genius Scan computes a readability level (lowest to highest), tuned for text-heavy pages ("will not work optimally for documents with little text"[^20]). It "triggers a prompt for any document estimated to be below this quality level".[^21]
- **Block or warn: vendors choose differently.** Genius Scan only warns ("this will never be blocking for the user"[^22]). Onfido forces retakes for cut-off, glare or blur, but only up to a limit (see stage 3).[^24]
- **Server-side image assessment backs up the device.** Microblink Verify reports an `imageQualityCheck`, described as "the combined output of the heuristics and models that decide whether the captured images are good enough to verify".[^15] Stripe analyses images "in real-time to check for legibility and warn the user".[^36] Veryfi returns an `is_blurry` flag for every page of a multi-page upload.[^40]
- **A review screen for borderline captures.** MiSnap shows a review screen "suitable for situations where there might be a potential low quality on the acquired image".[^19] WES asks the user to preview the file and judge the quality themselves.[^49]

### Stage 3. Retry budget, then a fallback
See section (c).

### Stage 4. Verify what was read (server)
See section (d).

---

## (b) Checks: signal or threshold, user message, and who does it

| Check | Typical signal / threshold (as published) | User-facing message pattern | Vendors (cited) |
|---|---|---|---|
| No document in frame | detector finds no quadrilateral | "Point the camera at the page" | Scanbot `ERROR_NOTHING_DETECTED`[^7]; Veriff 211 (not visible) |
| Page cut off / out of frame | corners outside frame | "Part of the page is cut off, fit the whole page in the frame" | Veriff 212 "Document Framing: part of the document is out of the image"[^28]; Jumio `PART_OF_DOCUMENT_MISSING`[^30]; Onfido cut-off warning[^25] |
| Too small / too far | doc width or height vs. frame, Scanbot default ≥ 80 %[^3] | "Move closer" | Scanbot `OK_BUT_TOO_SMALL`[^7]; BlinkID "move closer"[^13] |
| Perspective / skew | angle score, Scanbot default ≥ 75[^4] | "Hold the phone parallel to the page" | Scanbot `OK_BUT_BAD_ANGLES`[^1] |
| Too dark | mean brightness below a 0–255 threshold[^6] | "Too dark, move to better light" | Scanbot `ERROR_TOO_DARK`[^2]; BlinkID poor-lighting rejection[^12] |
| Blur / motion | frame-level blur detector; sensitivity off/low/mid/high (BlinkID) | "Hold steady" / "Image is blurry, retake" | BlinkID[^12]; Onfido[^24]; Veriff 215[^27]; Genius Scan readability[^20] |
| Glare | glare detector | "Glare detected, tilt the page or move away from the light" | BlinkID[^13]; Onfido[^24]; Veriff 216 "Document Poor Quality: glare" |
| Low OCR readability | ABBYY confidence ≥ 0.6[^23]; Veryfi field `ocr_score` < 0.8 → review[^42] | "We can't read this page clearly, retake it" | ABBYY[^23]; Genius Scan[^21]; Veryfi[^42] |
| Low resolution | text height floor 12–15 px (see section (e)); Veryfi flags pages with a side ≤ 500 px[^41] | "Image resolution too low, retake closer or upload the PDF" | Veryfi[^41]; Textract/Azure limits[^58][^60] |
| Missing page / side | expected page count or side not present | "Page N is missing" / "Upload the other side" | Jumio `MISSING_PAGE`[^32]; Sumsub `DOCUMENT_PAGE_MISSING`; Ocrolus "only a summary page without the full statement pages"[^39] |
| Wrong document | classifier fails to match the expected type | "This doesn't look like a transcript" | Jumio `NOT_A_DOCUMENT`, `DOCUMENT_CONTENT_NOT_SUPPORTED`; Veriff 206 |
| Black and white / photocopy / screen | colour and liveness models | (IDV only, see section (e)) | Jumio `BLACK_WHITE`[^31], `PHOTOCOPY`, `DIGITAL_COPY` |

Two message-design patterns recur:
- **A closed reason code plus localisable text.** Scanbot has one text hint per status[^7]. Veriff pairs a numeric `reasonCode` with a reason string. MiSnap and BlinkID ship localisable hint strings.
- **Separate user-facing text from internal text.** Sumsub returns a `moderationComment` that "can be shown to the applicant"[^34] alongside a `clientComment` that must not be shown. Persona classes quality failures as "user behavior" checks, for which it "gives hints to the end user in the inquiry flow to help them fix the issue".[^35]

## (c) Retry and fallback policies

| Product | Published policy |
|---|---|
| Onfido Web SDK | "When the uploaded image is either cut-off, glary or blurry, the end-user must retry at most 2 times prior to proceeding further."[^24] A later change: "Stop rendering the fallback message after two blurry document upload tries."[^26] |
| Veriff | "One user can resubmit their data up to 9 times." On the 10th attempt the session is declined automatically (code 539).[^29] |
| Sumsub | Two rejection types. `RETRY` is the "Resubmission requested status in case of minor violations"[^33] (screenshot, part of the document invisible). `FINAL` covers fraud. |
| MiSnap | A session timeout leads to a failover screen with "tips to successfully complete the session in the next attempt".[^17] Mitek warns that timeouts set too short lead to repeated failovers, and that users may then switch to manual capture and return "a non-optimal image".[^18] |
| Genius Scan | Warns only. The user can always continue.[^22] |
| Persona / Onfido | Hand off to another device (QR code or link) because a phone camera is better than a webcam. **Unverified** for Persona (help page seen only in search); Onfido documents a cross-device flow in its SDK README (seen only in search, not cited). |

Common pattern: (1) live hints, (2) 1–2 forced retakes that each show a specific reason, (3) after that, let the user continue, mark the item low-quality, and route it to human review, or (4) offer another route (upload a file, switch to a phone). A hard cap on total attempts protects against abuse.

## (d) Verification after reading

- **Field-level confidence routing to humans.** Hyperscience processes fields above a confidence threshold automatically and sends "all fields below the corresponding threshold to a data keyer for Transcription Supervision".[^43] Thresholds are set from a target accuracy, and QA samples are used to tune them. Amazon A2I with Textract can start a human review on form-key confidence ranges, "when specific form keys are missing"[^46], and on a random sample: "Randomly send a sample of forms to humans for review."[^47]
- **Tables with blank cells go to a human by default.** Hyperscience: "It is enabled by default to ensure that blank cells always go to Transcription Supervision in order to avoid potential data loss."[^44] This applies directly to grade tables, where an empty grade cell is ambiguous.
- **Arithmetic reconciliation as a rejection reason.** Ocrolus rejects a bank statement as `STATEMENT_UNRECONCILED` when "The sum of the transactions does not match the beginning and ending balances stated on the statement."[^38] It also rejects a statement with no period summary, or a submission that is only a summary page.[^39]
- **Per-field OCR confidence.** Veryfi says a field `ocr_score` "lower than 0.8, it's a signal that the extraction results may not be as stable".[^42] Its blur flag is reported per page.[^40]

## (e) What to adopt for transcripts, and what does not transfer

### Numeric floors that apply to transcripts
- **Text size and resolution.**
  - Textract: "The minimum height for text to be detected is 15 pixels", which equals 8 pt at 150 DPI.[^58]
  - Azure Document Intelligence: 12 px for a 1024 × 768 image[^60], "about 8-point text at 150 dots per inch".[^61]
  - Tesseract: works best at "a DPI of at least 300 dpi".[^56]
  - FADGI (US federal digitisation guidelines), for clean typed documents meant for OCR at 95 %+ accuracy[^63]: "8-bit grayscale mode - 300 ppi for documents with smallest significant character of 1.5 mm or larger".[^62]
- **Derived figure (arithmetic, not a vendor claim).** An A4 page at 300 DPI is about 2480 × 3508 px, and the 150 DPI floor is about 1240 × 1754 px. A transcript's dense grade table often uses 7–8 pt type, so a capture that only clears the 150 DPI floor is marginal for it. Aim for the 300 DPI equivalent on the page area after cropping.
- **Tables are hard for generic OCR.** Tesseract: "It is known tesseract has a problem to recognize text/data from tables".[^57]
- **Language coverage is a real constraint.**
  - Textract lists only "English, French, German, Italian, Portuguese, and Spanish text detection"[^59], so Russian Cyrillic is out. Turkish and Azerbaijani characters (ə, ğ, ş, ı) are not in its documented character list.
  - Stripe Identity does not support extraction of fields written in Cyrillic.[^37]

### Practices to adopt
1. **Born-digital first.** Ask for the institution's electronic PDF or verification-code document before falling back to the camera. uni-assist counts a verification code as official[^54]; WES keeps transcripts out of applicant uploads entirely[^50]. For a vector PDF with a text layer, skip image-quality checks and go straight to stage 4.
2. **Page-by-page multi-page capture with live gates.**
   - Gates: page found with all four corners, size ≥ ~80 % of frame, perspective score ≥ ~75, brightness above a floor, blur and glare frame rejection. Use the Scanbot and BlinkID defaults as starting values.[^3][^4][^6][^12]
   - Auto-capture after about 2 s of stability.[^5]
   - A manual shutter, so a failed detector never traps the user.
3. **A fixed reason list with one message each, localised for az/tr/ru/en.** Suggested codes: `no_page`, `cut_off`, `too_far`, `tilted`, `too_dark`, `blurry`, `glare`, `low_resolution`, `unreadable_text`, `page_missing`, `not_a_transcript`. Keep student-facing text separate from internal reviewer notes (the Sumsub pattern).[^34]
4. **A readability gate after capture, on the server.** Run OCR per page and gate on recognition confidence. ABBYY's 0.6 and Veryfi's 0.8 field level are published starting points[^23][^42]. Calibrate on our own transcripts, because these scores are engine-specific.
5. **Retry budget.** Allow two forced retakes per page, each with the specific reason (Onfido pattern).[^24] After that, let the student continue with a "low quality" flag that routes to counsellor review. Offer "upload the PDF instead" and "continue on your phone". Cap total attempts (Veriff caps at 9 resubmissions).[^29]
6. **Completeness checks for transcripts.**
   - Ask for the expected page count up front, and detect "page X of Y" footers.
   - Require every page, including the grading-scale page and any Diploma Supplement. uni-assist: "Do not omit any parts of the certificate"[^53], and it needs the official grading system for the degree.[^55]
   - Treat a missing page as a retake reason, like Jumio `MISSING_PAGE`[^32] and the Ocrolus "summary page only" rejection.[^39]
7. **Arithmetic reconciliation after reading.** Sum of course credits = stated total credits. Recomputed GPA or average = stated GPA. Semester count matches the years attended. A mismatch means either an OCR error or a missing page, the same logic as Ocrolus `STATEMENT_UNRECONCILED`.[^38]
8. **Human review routing.** Low field confidence, empty grade cells[^44], missing required fields[^46], failed reconciliation, plus a small random QA sample.[^47] Show the student the extracted table next to the page image to confirm, as the WES preview and the MiSnap review screen do.[^49][^19]

### Practices that do not transfer (ID-document specific)
- Black-and-white rejection (Jumio `BLACK_WHITE`[^31], Sumsub `BLACK_AND_WHITE`). Many transcripts are printed in monochrome.
- Glare on holograms and security features, face/portrait detection, MRZ/barcode decoding, NFC, document expiry.
- A fixed ID-card aspect ratio (Scanbot `OK_BUT_BAD_ASPECT_RATIO`). Transcripts are A4 or Letter, and sometimes landscape.
- Photocopy and screen-capture checks as automatic rejections. uni-assist accepts scans of official documents[^52]. Keep these signals as fraud flags for a reviewer, not as retake reasons.
- Front/back logic should be generalised to N pages, not two sides.

## Open questions
- Which OCR engine covers Azerbaijani Latin (ə), Turkish and Russian Cyrillic dense tables well enough? The Textract and Stripe limits rule those two out[^59][^37]. Azure, Google Document AI and ABBYY language lists were not fetched.
- Do ECE, Parchment, UCAS or Common App reject bad uploads automatically? Not verified. WES describes only a self-check preview[^49], and uni-assist publishes only "complete and clearly legible".[^51]
- The SmartDoc-QA (ICDAR 2015) and DocImg-QA research datasets were found in search but not fetched. Thresholds from that literature are **Unverified**.
- Yoti's documented in-session feedback ("2 extra attempts" by default) was seen only in a search snippet. **Unverified.**
- Dynamsoft, Anyline, Expensify, Ramp, Docsumo, and the Mitek cheque-IQA specifics were not investigated.

## Sources
[^1]: https://api-docs.scanbot.io/document-scanner-sdk/react-native/v7.0.0/types/index.DocumentDetectionStatus.html "A document was detected, but it has too much perspective distortion."
[^2]: https://api-docs.scanbot.io/document-scanner-sdk/react-native/v7.0.0/types/index.DocumentDetectionStatus.html "No document was detected, likely because the input image is too dark."
[^3]: https://api-docs.scanbot.io/document-scanner-sdk/react-native/v7.0.0/interfaces/index.FinderDocumentScannerConfiguration.html "accepted document width or height to screen size ratio of the detected document. Default is 80.0."
[^4]: https://api-docs.scanbot.io/document-scanner-sdk/react-native/v7.0.0/interfaces/index.FinderDocumentScannerConfiguration.html "of the accepted perspective distortion of the detected document. Default is 75.0."
[^5]: https://api-docs.scanbot.io/document-scanner-sdk/react-native/v7.0.0/interfaces/index.FinderDocumentScannerConfiguration.html "a value of 0.0 delays the automatic capturing by 3 seconds. Default value is 0.66 (2 seconds)."
[^6]: https://api-docs.scanbot.io/document-scanner-sdk/react-native/v7.0.0/interfaces/index.FinderDocumentScannerConfiguration.html "If the average brightness value of the detectors input image is below this value, the status of the detection will be set to ERROR_TOO_DARK."
[^7]: https://api-docs.scanbot.io/document-scanner-sdk/react-native/v7.0.0/interfaces/index.FinderDocumentScannerConfiguration.html "Text hint that will be shown when the current detection status is OK_BUT_TOO_SMALL."
[^8]: https://developers.google.com/ml-kit/vision/doc-scanner "Automatic capture with document detection."
[^9]: https://developers.google.com/ml-kit/vision/doc-scanner "The entire document scanner flow operates on-device."
[^10]: https://developers.google.com/ml-kit/vision/doc-scanner "Set a limit to the number of pages scanned."
[^11]: https://developer.apple.com/tutorials/data/documentation/visionkit/vndocumentcameraviewcontroller.json "The results of a scan include images, by page number."
[^12]: https://docs.microblink.com/blinkid/image-quality "frames with detected blur are skipped, so only sharp frames are processed."
[^13]: https://docs.microblink.com/blinkid/image-quality "prompting them to move closer, hold steady, or avoid glare."
[^14]: https://docs.microblink.com/blinkid/image-quality "fewer frames qualify, so scanning can take longer before a usable frame arrives."
[^15]: https://docs.microblink.com/verify/check "the combined output of the heuristics and models that decide whether the captured images are good enough to verify"
[^16]: https://raw.githubusercontent.com/Mitek-Systems/MiSnap-Android/main/documentation/customization_guide.md "The MiSnap SDK will display on-screen live hints whenever there are improvements that can be made for a better image quality"
[^17]: https://raw.githubusercontent.com/Mitek-Systems/MiSnap-Android/main/documentation/customization_guide.md "The MiSnap SDK features a failover screen that displays useful information about the session and tips to successfully complete the session in the next attempt."
[^18]: https://raw.githubusercontent.com/Mitek-Systems/MiSnap-Android/main/documentation/customization_guide.md "Making the session timeout duration too short might result in multiple fail-overs and users might opt to complete the session manually, thereby resulting in a non-optimal image being returned."
[^19]: https://raw.githubusercontent.com/Mitek-Systems/MiSnap-Android/main/documentation/customization_guide.md "The MiSnap SDK features a review screen that is suitable for situations where there might be a potential low quality on the acquired image."
[^20]: https://geniusscansdk.com/docs/v6/document-scanning/blur-detection/ "The detection has been specifically tuned for textual documents and will not work optimally for documents with little text."
[^21]: https://geniusscansdk.com/docs/v6/document-scanning/blur-detection/ "triggers a prompt for any document estimated to be below this quality level"
[^22]: https://geniusscansdk.com/docs/v6/document-scanning/blur-detection/ "this will never be blocking for the user"
[^23]: https://help.abbyy.com/en-us/mobilewebcapturesdk/1/mobilewebcapturesdk/apireference_ocrquality/ "The image is considered to be ready for OCR, if confidence value is 0.6 and larger."
[^24]: https://github.com/onfido/onfido-sdk-ui/releases/tag/6.0.0 "When the uploaded image is either cut-off, glary or blurry, the end-user must retry at most 2 times prior to proceeding further."
[^25]: https://github.com/onfido/onfido-sdk-ui/releases/tag/6.0.0 "New warnings for cut-off & blurry images detection."
[^26]: https://github.com/onfido/onfido-sdk-ui/releases/tag/13.4.0 "Stop rendering the fallback message after two blurry document upload tries."
[^27]: https://devdocs.veriff.com/docs/verification-session-decision-codes-table "Document Poor Quality: document is not readable e.g. too blurry, dark etc"
[^28]: https://devdocs.veriff.com/docs/verification-session-decision-codes-table "Document Framing: part of the document is out of the image"
[^29]: https://devdocs.veriff.com/docs/verification-session-decision-codes-table "One user can resubmit their data up to 9 times."
[^30]: https://documentation.jumio.ai/docs/references/capabilities/usability "Part of the document was excluded from the image."
[^31]: https://documentation.jumio.ai/docs/references/capabilities/usability "Black and white images are not supported."
[^32]: https://documentation.jumio.ai/docs/references/capabilities/usability "The front and back pages of the document were required, but the user uploaded only one of them."
[^33]: https://docs.sumsub.com/reference/get-status-of-verification-steps "Resubmission requested status in case of minor violations"
[^34]: https://docs.sumsub.com/reference/get-status-of-verification-steps "A human-readable comment that explains the reasons for rejection, and that can be shown to the applicant."
[^35]: https://docs.withpersona.com/2023-01-05/verification-checks.md "For these checks, Persona gives hints to the end user in the inquiry flow to help them fix the issue."
[^36]: https://docs.stripe.com/identity/verification-checks?type=document "The document images are analyzed in real-time to check for legibility and warn the user if the document is expired or unlikely to be verified."
[^37]: https://docs.stripe.com/identity/verification-checks?type=document "support extraction of document fields written in Arabic, Chinese, Cyrillic"
[^38]: https://docs.ocrolus.com/docs/rejection-reasons "The sum of the transactions does not match the beginning and ending balances stated on the statement."
[^39]: https://docs.ocrolus.com/docs/rejection-reasons "or the submission of only a summary page without the full statement pages"
[^40]: https://faq.veryfi.com/en/articles/5429636-blur-detection-and-image-quality "Each flag corresponds to a specific page, allowing you to assess the status individually for each page in the response."
[^41]: https://faq.veryfi.com/en/articles/5429636-blur-detection-and-image-quality "If either the width or height is equal to or less than 500 pixels"
[^42]: https://faq.veryfi.com/en/articles/5429636-blur-detection-and-image-quality "lower than 0.8, it's a signal that the extraction results may not be as stable"
[^43]: https://help.hyperscience.com/v41/docs/transcription-settings "send all fields below the corresponding threshold to a data keyer for Transcription Supervision"
[^44]: https://help.hyperscience.com/v41/docs/transcription-settings "It is enabled by default to ensure that blank cells always go to Transcription Supervision in order to avoid potential data loss."
[^46]: https://docs.aws.amazon.com/sagemaker/latest/dg/a2i-textract-task-type.html "Initiate a human review when specific form keys are missing."
[^47]: https://docs.aws.amazon.com/sagemaker/latest/dg/a2i-textract-task-type.html "Randomly send a sample of forms to humans for review."
[^49]: https://www.wes.org/resource-library/blog/credential-advice/upload-degree-certificates-and-translations/ "If you can see a preview of your file and there is no error message, then proceed to upload it, confirming the image quality yourself."
[^50]: https://www.wes.org/resource-library/blog/credential-advice/upload-degree-certificates-and-translations/ "upload academic transcripts or mark sheets here"
[^51]: https://www.uni-assist.de/en/how-to-apply/send-track/uploading-documents/ "The scans must be complete and clearly legible."
[^52]: https://www.uni-assist.de/en/how-to-apply/send-track/uploading-documents/ "Create scans of your documents and save them as PDF files."
[^53]: https://www.uni-assist.de/en/how-to-apply/assemble-your-documents/educational-certificates "Do not omit any parts of the certificate"
[^54]: https://www.uni-assist.de/en/how-to-apply/send-track/uploading-documents/ "a reference to their automatic issuance or a verification code"
[^55]: https://www.uni-assist.de/en/how-to-apply/assemble-your-documents/educational-certificates "used for the award of your degree"
[^56]: https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html "Tesseract works best on images which have a DPI of at least 300 dpi"
[^57]: https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html "It is known tesseract has a problem to recognize text/data from tables"
[^58]: https://docs.aws.amazon.com/textract/latest/dg/limits-document.html "The minimum height for text to be detected is 15 pixels."
[^59]: https://docs.aws.amazon.com/textract/latest/dg/limits-document.html "Amazon Textract supports English, French, German, Italian, Portuguese, and Spanish text detection."
[^60]: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/read?view=doc-intel-4.0.0 "The minimum height of the text to be extracted is 12 pixels for a 1024 x 768-pixel image."
[^61]: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/read?view=doc-intel-4.0.0 "This dimension corresponds to about 8-point text at 150 dots per inch."
[^62]: https://www.digitizationguidelines.gov/guidelines/ccdo-subcat-T1.html "8-bit grayscale mode - 300 ppi for documents with smallest significant character of 1.5 mm or larger"
[^63]: https://www.digitizationguidelines.gov/guidelines/ccdo-subcat-T1.html "Produce text at accuracy of 95 percent or higher."

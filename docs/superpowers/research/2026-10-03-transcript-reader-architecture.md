# Transcript reader: architecture options (2026-10-03)

Question: what is the best architecture for reading transcripts and diploma supplements into course
rows (title, credits + unit, grade, grading scale, status) across born-digital PDFs, scans and phone
photos in Azerbaijani, Turkish, Russian and English? Which open-source and commercial options exist,
and is the rule "no generative model writes a stored value" worth what it costs?

## Answer

**Recommended (design A): route by input kind, combine OCR engines per cell, and let no model write a value.**

1. **Born-digital PDF with a usable text layer → read the layer, not pixels.** Take the characters and
   their boxes from `pdfplumber` (MIT). Use PyMuPDF only if you buy a commercial licence, because it is
   AGPL. Run a gate before trusting a layer (below). Table structure comes from ruling lines
   (`pdfplumber`). For borderless tables, run the scan path's layout step on the rendered page and keep
   only its cell geometry, while the text still comes from the layer.
2. **Scan or photo → Azure Document Intelligence Layout for structure, numbers and confidence. A second
   engine supplies the letters in titles.** For each Azure table cell, take the Paddle (or PaddleOCR-VL)
   text whose box overlaps it, and keep it where the two engines differ only by the
   ə/e/a, ı/i, İ/I, ş/s, ğ/g confusion set. Any other disagreement goes to review. This targets the two
   failures we measured: Azure turns ə into e/a, and Paddle fuses rows. Both readings are still copied
   from OCR output, so the owner's rule holds.
3. **Keep Jev as the column/row classifier.** It still picks which column is credits, grade or title.
4. **Verify in code. Every row must pass these checks or go to review:**
   - each value is the exact token span inside its cell box;
   - credits and grade parse under the declared unit and scale;
   - the per-term or total credits printed on the page equal the sum of the rows;
   - the number of rows equals the number of course-code-like tokens, where codes exist;
   - no OCR token is used by two rows (catches fused rows);
   - low Azure word confidence sends the row to review. Our run measured Azure confidence as useful;
     Paddle's was useless.

**Alternative (design B): a grounded VLM extractor that bends the rule safely.** A VLM reads the page
and proposes rows. Self-hosted options are PaddleOCR-VL-1.6 or dots.ocr; hosted options are Gemini or
Claude. Each proposed value must point to OCR evidence:
- Gemini returns `box_2d` boxes;
- Claude can cite indices into a "custom content" document built from our OCR cells, and the API's
  `cited_text` is copied from that document, not generated;
- dots.ocr and PaddleOCR-VL emit a bbox for each element.

Code then accepts a value only if it matches the OCR tokens inside that box, either exactly or modulo
the diacritic confusion set. Numbers must always match exactly. A title may differ from OCR only by
whitelisted letter swaps, and only if a second source agrees: a lexicon or a second OCR engine.
Anything else goes to review.

**Is the rule worth its cost?**
- **Numbers:** yes. Every engine we measured reads digits well when the rows pair correctly.
- **Titles, as currently enforced:** no. Copying from a single OCR engine imports its letter errors.
  Strict title accuracy on Azerbaijani was:

  | Engine | Strict title accuracy (az) | Kind |
  |---|---|---|
  | Azure | 46% (57% with `locale=az`) | OCR |
  | Paddle | 92% | OCR |
  | PP-StructureV3 | 91% | OCR |
  | Surya | 98% | generative |

  (Local reports: `out/azure/REPORT.md`, `out/paddle_rescore_2026-09-26.md`,
  `out/ppstructure/REPORT.md`, `out/surya/REPORT.md`.)
- **A narrower rule keeps the safety property at much lower cost.** The safety property is "no
  invented course, number or grade". The narrower rule: a stored value must be grounded to a span of
  OCR or text-layer evidence, and only bounded letter repairs are allowed. Design A meets the
  narrower rule with no generative write at all; design B meets it with one.

## Scope (sub-questions)

1. Text layers: which libraries read them with geometry, and how do you tell a usable layer from a garbled one?
2. Open-source parsers: language coverage (ə/ı/Cyrillic), table output, boxes or confidence, licence.
3. Commercial APIs and transcript-specific vendors: languages, grounding, price.
4. Frontier multimodal LLMs: which grounding mechanisms exist (boxes, citations)?
5. Public benchmarks: do any cover multilingual table scans?

**How the candidate list was built:**
- Exa search for open-source VLM document parsers. It returned the `vlmparse` converter registry,
  which lists LightOnOCR, MinerU2.5, HunyuanOCR, PaddleOCR-VL-1.5, granite-docling, olmOCR-2,
  dots.ocr, chandra, DeepSeek-OCR, Nanonets-OCR2, GLM-OCR, Docling, Gemini and GPT, plus
  OCRFlux and docext.
- Exa search for transcript-extraction products. It returned MyDocs MAPit, TondroAI Extract,
  Transcript Genie, EDMO, ParserBee, Scholaro Premium and INDIMA.
- Brave keyword search for transcript extraction APIs. It returned only university pages; nothing
  usable.
- Brave `site:` searches for PyMuPDF and AWS documentation.
- Context7 and Tavily were available but not used.

## 1. Born-digital PDFs: read the text layer

- `pdfplumber` exposes each character, rectangle and line with its position.[^16] It "works best on
  machine-generated, rather than scanned, PDFs".[^17] It is MIT-licensed through pdfminer.six. It finds
  tables from ruling lines and word alignment. It lists strong table extraction from OCR'ed documents
  among the things it does **not** provide.[^18]
- PyMuPDF is faster. Its table finder is a port of pdfplumber's. Its licence is "either GNU AGPL or a
  commercial license from Artifex",[^19] which is a cost for a closed SaaS.
- Docling (IBM, MIT code) reads PDFs with layout, reading-order and table-structure models.[^14] Its
  model weights carry their own licences.[^15] We have not measured Docling, and its OmniDocBench
  numbers are weak on non-English text (dots.ocr README table). **Unverified** for our pages.
- **Telling a broken layer from a good one.** PyMuPDF's own FAQ names three failure causes:
  - a scanned page (no text at all);
  - scrambled encoding, where "there is no reliable way to detect this programmatically";[^22]
  - a missing `/ToUnicode` map, where "the information simply cannot be recovered".[^21]

  Its only heuristic is "checking for high rates of U+FFFD replacement characters".[^20] So the gate
  has to be ours:
  - (a) characters per page above a floor;
  - (b) U+FFFD rate near 0;
  - (c) for az/tr pages, the expected letters (ə, ı, ş, ğ) actually occur;
  - (d) the layer's text roughly matches a cheap OCR of the same rendered page (character error rate
    under a threshold). Check (d) is the one that catches scrambled encoding.

  A failed gate sends the page down the scan path.

## 2. Open-source parsers

| Candidate | ə / ı / Cyrillic | Tables | Grounding / confidence | Licence | Hardware, our timing |
|---|---|---|---|---|---|
| PaddleOCR / PP-StructureV3 (current) | Our run: ə fine (az strict 91–92%), 7 ı→i substitutions | Yes; row pairing 0% → 22% on BEUN, 0% → 62% on NKU (Turkish scans) | Line boxes; confidence useless in our run | Apache-2.0 (local `LICENCE.md`) | CPU, ~27 s/page |
| PaddleOCR-VL (0.9B VLM) | "supports 109 languages",[^1] including Russian (Cyrillic);[^3] az/tr not named | Tables, formulas, charts | Layout boxes per element; per-token confidence **Unverified** | Apache-2.0[^2] | GPU recommended (vLLM server). Not measured by us |
| dots.ocr (1.7B) | Claims strength on low-resource languages; in-house bench of "1493 pdf images with 100 languages"[^7] | HTML tables | Its prompt asks for each element's bbox[^6] | MIT[^5] | GPU (vLLM). Not measured |
| Surya / Marker / Chandra (Datalab) | Our run: Surya az strict 98%, ru 100%, tr 84%. Chandra 2 claims "90+ languages"[^11] | Our run: Surya pairing 100% on most pages | Generative, so it can invent; Surya confidence not informative in our run | Weights "modified OpenRAIL-M": free under $2M funding/revenue, no competing use[^10] (our record for Surya: $5M cap + share-alike) | Surya on CPU: 150–410 s/page (our run). GPU needed in production |
| MinerU | **Unverified** | Yes | Block locators | "MinerU Open Source License, based on Apache 2.0 with additional conditions"[^13] | CPU (ONNX) or GPU |
| Docling | Depends on its OCR plug-in | TableFormer | Cell boxes | MIT code; models licensed separately[^14][^15] | CPU works |
| Qwen3-VL | OCR in "32 languages (up from 19)"; az/tr not named[^36] | Via prompting | 2D grounding (boxes) | Apache-2.0 **Unverified** (not fetched) | GPU |
| Tesseract | Our run: az strict 74%; low confidence was a *useful* error flag | No table model | Word boxes and confidence | Apache-2.0 | CPU, 2–7 s/page |
| docTR (community multilingual recogniser) | Our run: no ə ı İ ş ğ, no Cyrillic | — | Confidence useless | Apache-2.0 | Ruled out |
| olmOCR-2, GOT-OCR, Nougat, Florence-2, DeepSeek-OCR, granite-docling | Benchmarks are English/Chinese only (§5) | — | — | **Unverified** individually | Not pursued: no evidence for az/tr |

## 3. Commercial

| Service | Languages | Tables | Grounding / confidence | Price | Notes |
|---|---|---|---|---|---|
| Azure Document Intelligence Layout | Our run: ə→e/a on 75 characters; az strict 46%, 57% with `locale=az`; ru 98%; tr 87% | Best row pairing among OCR engines (Turkish scans 91–100%, except Mersin 0%) | Word polygons and confidence; confidence < 0.8 flagged 71–100% of wrong az lines | **Unverified** (not fetched) | West Europe region used in our run |
| Google Document AI, Enterprise OCR | "more than 200 languages";[^23] the explicit table we fetched lists Russian and Turkish but **not Azerbaijani** | Separate Form Parser and Layout Parser | Token boxes and confidence (**Unverified**, not fetched) | Enterprise OCR row: "1,000 count to 5,000,000 count $1.50"; Form Parser $30.00 for the first 1,000,000 count[^26][^27]. Unit per 1,000 pages **Unverified** (not in the quoted row) | Not measured by us; candidate to replace Azure for ə |
| Google Custom Extractor (generative) | Its language table lists Azerbaijani, but "Only the English language is officially supported" for generative extraction[^24] | — | — | as Form Parser | Gemini 3 preview versions use a global endpoint and are "not compliant with" data residency[^25] |
| Mistral OCR | "performs strongly across more than 40 languages"[^29] | HTML/Markdown tables | Confidence at "page, block, or word granularity";[^28] paragraph-level block boxes[^30] | **Unverified** | Word confidence but no word boxes: weaker grounding than Azure |
| AWS Textract | English + 5 Latin-script languages (our prior finding) | — | — | — | Ruled out |
| AWS Bedrock Data Automation | The limits page we fetched shows audio languages only; document languages **Unverified** | — | — | — | — |
| Reducto, LlamaParse, Unstructured, ABBYY | Not fetched: **Unverified** | | | | Not pursued |
| Transcript vendors: MyDocs MAPit,[^41] TondroAI Extract, Scholaro, EDMO, ParserBee | No vendor page names az/tr/ru support or per-value grounding | — | Tondro advertises confidence-flagged review | Tondro: "$2.50 per transcript, regardless of page count"[^37] | All are evaluator workflows with human review ("AI extracts data. Faculty make academic decisions."[^38]). None is an API we could verify |

## 4. Frontier multimodal LLMs as extractors

- **Gemini** returns object boxes as `box_2d`; "the coordinates, relative to image dimensions, scale
  to [0, 1000]".[^31] That makes it possible to require one box per extracted value and check the box
  against OCR tokens.
- **Claude citations** work on text documents only: "Only text citations are currently supported.
  Image citations are not yet possible."[^32] A scanned PDF therefore cannot be cited directly.
  - A *custom content* document is cited by block index, and "your provided content blocks are used
    as-is and no further chunking is done".[^33] We can pass one block per OCR cell.
  - Citations "are guaranteed to contain valid pointers to the provided documents",[^34] and
    `cited_text` is extracted by the API rather than written by the model.[^35]
  - That gives a classifier-like design: the model chooses *which cell*, and the stored value comes
    from our OCR.
  - Whether citations combine with structured outputs is **Unverified**.
- **Accuracy:** the only multi-model numbers we found are self-reported in vendor READMEs. dots.ocr's
  OmniDocBench table puts GPT-4o table TEDS at 72.0 (English) and Gemini 2.5 Pro at 85.8, against
  dots.ocr's 88.6. These are English/Chinese pages only. No source measured hallucination on
  transcripts. Our own Surya run is the only evidence on our languages.

## 5. Benchmarks

- **OmniDocBench:** 1,651 pages "covering 10 document types, 5 layout types, and 5 language types",[^9]
  but "only Chinese and English text are included in text evaluation".[^8] It says nothing about ə or ı.
- **olmOCR-bench:** English sources. Its numbers appear in the dots.ocr README (dots.ocr 79.1 overall,
  Mistral OCR 72.0, Marker 70.1). The English-only scope is **Unverified** (benchmark page not fetched).
- **Multilingual benchmarks are vendor-built:** dots.ocr-bench (100 languages) and Chandra's own
  90-language bench. Chandra's authors say "there isn't a good public multilingual OCR benchmark, so
  we made our own".[^12]
- **Conclusion:** no public benchmark ranks these tools on Azerbaijani or Turkish tables. Our page set
  is the only evidence that counts.

## What must be measured on our pages before choosing

Page set: `.superpowers/ocr-eval/ (git-ignored eval harness) pages/`

1. **Text-layer gate.** For every "clean" PDF, does a text layer exist? Score it as-is (title strict,
   numbers-in-row, row pairing) with `pdfplumber`. Check that the gate's four checks reject the bad ones.
2. **Design A's per-cell merge.** Azure structure plus Paddle letters, scored with `score.py`.
   Targets: az title strict ≥ 95% while keeping Azure's Turkish row pairing (91–100%).
3. **Google Enterprise OCR + Layout Parser** on the same pages. Its table does not list az, so ə is the
   open question.
4. **Self-hosted VLMs:** PaddleOCR-VL-1.6 and dots.ocr on one GPU instance. Measure ə/ı, row pairing,
   whether their bboxes let us ground each value, and seconds per page.
5. **Design B's grounding rejection rate.** How often a grounded VLM value fails the "matches OCR
   tokens in box" check, and how many of those failures were the VLM being *right*.
6. **The arithmetic and row-count checks.** On the known-bad outputs (Paddle BEUN/NKU, PP-StructureV3's
   fused BEUN rows), do they actually catch them?
7. **The Mersin 129 ppi floor.** Every engine fails this page. Measure the minimum DPI and photo
   quality we accept, so the reader refuses a page instead of mis-reading it.
8. **Cost per page** for each finalist: API price, or GPU-hours on AWS.

## Sources

[^1]: https://huggingface.co/PaddlePaddle/PaddleOCR-VL/raw/main/README.md "This innovative model efficiently supports 109 languages"
[^2]: https://huggingface.co/PaddlePaddle/PaddleOCR-VL/raw/main/README.md "license: apache-2.0 pipeline_tag: image-text-to-text"
[^3]: https://huggingface.co/PaddlePaddle/PaddleOCR-VL/raw/main/README.md "such as Russian (Cyrillic script), Arabic, Hindi (Devanagari script), and Thai"
[^5]: https://huggingface.co/rednote-hilab/dots.ocr/raw/main/README.md "license: mit library_name: dots_ocr"
[^6]: https://huggingface.co/rednote-hilab/dots.ocr/raw/main/README.md "Please output the layout information from the PDF image, including each layout element's bbox"
[^7]: https://huggingface.co/rednote-hilab/dots.ocr/raw/main/README.md "This is an inhouse benchmark which contain 1493 pdf images with 100 languages."
[^8]: https://github.com/opendatalab/OmniDocBench "Currently, only Chinese and English text are included in text evaluation."
[^9]: https://github.com/opendatalab/OmniDocBench "This benchmark includes 1651 PDF pages, covering 10 document types, 5 layout types, and 5 language types."
[^10]: https://github.com/datalab-to/chandra "our model weights use a modified OpenRAIL-M license (free for research, personal use, and startups under $2M funding/revenue, cannot be used competitively with our API)"
[^11]: https://github.com/datalab-to/chandra "Support for 90+ languages"
[^12]: https://github.com/datalab-to/chandra "There isn't a good public multilingual OCR benchmark, so we made our own."
[^13]: https://github.com/opendatalab/MinerU "MinerU Open Source License, based on Apache 2.0 with additional conditions."
[^14]: https://github.com/docling-project/docling "The Docling codebase is under MIT license."
[^15]: https://github.com/docling-project/docling "For individual model usage, please refer to the model licenses found in the original packages."
[^16]: https://github.com/jsvine/pdfplumber "Plumb a PDF for detailed information about each text character, rectangle, and line."
[^17]: https://github.com/jsvine/pdfplumber "Works best on machine-generated, rather than scanned, PDFs."
[^18]: https://github.com/jsvine/pdfplumber "Strong support for extracting tables from OCR'ed documents"
[^19]: https://pymupdf.readthedocs.io/en/latest/faq/index.html "PyMuPDF4LLM has the same license as PyMuPDF and MuPDF: either GNU AGPL or a commercial license from Artifex."
[^20]: https://pymupdf.readthedocs.io/en/latest/faq/index.html "Checking for high rates of U+FFFD replacement characters can help detect this."
[^21]: https://pymupdf.readthedocs.io/en/latest/faq/index.html "map is missing, the information simply cannot be recovered."
[^22]: https://pymupdf.readthedocs.io/en/latest/faq/index.html "There is no reliable way to detect this programmatically."
[^23]: https://cloud.google.com/document-ai/docs/languages "from documents in more than 200 languages"
[^24]: https://cloud.google.com/document-ai/docs/languages "Only the English language is officially supported."
[^25]: https://cloud.google.com/document-ai/docs/languages "This processor version uses the Vertex AI Gemini global endpoint and is not compliant with"
[^26]: https://cloud.google.com/products/document-ai/pricing "1,000 count to 5,000,000 count $1.50"
[^27]: https://cloud.google.com/products/document-ai/pricing "Form Parser 0 count to 1,000,000 count $30.00"
[^28]: https://docs.mistral.ai/studio/document-processing/basic_ocr "are available for extracted content at page, block, or word granularity"
[^29]: https://docs.mistral.ai/studio/document-processing/basic_ocr "performs strongly across more than 40 languages"
[^30]: https://docs.mistral.ai/studio/document-processing/basic_ocr "array with paragraph-level bounding boxes, structural block labels, and extracted content in reading order"
[^31]: https://ai.google.dev/gemini-api/docs/image-understanding "The coordinates, relative to image dimensions, scale to [0, 1000]."
[^32]: https://platform.claude.com/docs/en/build-with-claude/citations "Only text citations are currently supported. Image citations are not yet possible."
[^33]: https://platform.claude.com/docs/en/build-with-claude/citations "Your provided content blocks are used as-is and no further chunking is done."
[^34]: https://platform.claude.com/docs/en/build-with-claude/citations "citations are guaranteed to contain valid pointers to the provided documents"
[^35]: https://platform.claude.com/docs/en/build-with-claude/citations "field is provided for convenience and does not count toward output tokens"
[^36]: https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct "Supports 32 languages (up from 19); robust in low light, blur, and tilt"
[^37]: https://www.tondroconsulting.com/ai/extract/transcripts "$2.50 per transcript, regardless of page count."
[^38]: https://www.tondroconsulting.com/ai/extract/transcripts "AI extracts data. Faculty make academic decisions."
[^41]: https://mydocs.global/mapit "Turn unstructured transcripts into standardized, AI-driven insights without template-based limitations"

Local measurements (no URL): `.superpowers/ocr-eval/ (git-ignored eval harness) out/{azure,surya,ppstructure,doctr,tesseract}/REPORT.md` and `out/paddle_rescore_2026-09-26.md`.

## Open questions

- Azure DI pricing, data-retention terms and its Azerbaijani entry: not fetched.
- Google OCR's handling of ə: the 200+ language claim versus a table that omits az. Settle it by measurement.
- Mistral OCR and Bedrock Data Automation: language lists not confirmed; Mistral price not confirmed.
- Whether Claude citations can be combined with structured outputs.
- GPU cost per page on AWS for PaddleOCR-VL-1.6 and dots.ocr: not measured.
- Reducto, LlamaParse, Unstructured, ABBYY: not investigated (scope).
- Whether Docling's text-layer path handles our born-digital Turkish pages: not measured.

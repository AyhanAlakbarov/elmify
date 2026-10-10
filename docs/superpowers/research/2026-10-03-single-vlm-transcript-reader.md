# Can one self-hosted VLM be the whole transcript reader? (2026-10-03)

Question: which open-weight vision-language models (VLMs) lead document OCR and table extraction in
late 2026, and could one of them replace our OCR + Jev pipeline, reading a transcript page image
straight into course rows (title, credits, credit unit, grade, status)?

Builds on `2026-10-03-transcript-reader-architecture.md` (same folder) and our own measurements in
`.superpowers/ocr-eval/ (git-ignored eval harness) out/*/REPORT.md`. Neither is
repeated here.

## Answer

**Verdict: one VLM can replace the OCR engines. It should not be the only thing standing between
the page and a stored value. Build "VLM + grounding check", not "single VLM".**

- **What a single VLM can now do.** A self-hosted model under 10B parameters can read a page image
  into table HTML or JSON with no separate OCR engine. The top parsers score 95–97 on OmniDocBench
  v1.6, ahead of Gemini 3 Pro and GPT-5.2 on the same tables.[^7][^8] Azure + Paddle could be
  replaced by one GPU service.
- **Why it cannot write stored values unchecked:**
  1. **No public benchmark covers our languages.** OmniDocBench scores Chinese and English text
     only.[^28] No candidate names Azerbaijani on its card. The only published Turkish number is
     Chandra 2's own benchmark.[^22]
  2. **The documented failure modes are the ones we fear.** VLM OCR errors include "orthographic
     normalization, spurious content generation, and semantic substitutions". These cost little
     CER, so a good CER score hides them.[^30][^31] That is ə→e, a fused row or an invented grade.
     Under degradation, models over-rely on linguistic priors and produce "hallucinatory
     content".[^32]
  3. **Benchmark leads shrink on harder pages.** In one vendor's run on the Dr.DocBench challenge
     set, PaddleOCR-VL-1.6 dropped from 96.33 (OmniDocBench v1.6) to 55.11 overall.[^9][^10] Our own
     data agrees: Surya, a generative reader, scored 98% strict on Azerbaijani titles but 52% on the
     Mersin scan and 72% on NKU (`out/surya/REPORT.md`). Bad scans are where a generative reader
     guesses.
  4. **A VLM does not tell you which value it guessed.** None of the shortlisted cards documents a
     per-value confidence. Token log-probs are the only signal, and their usefulness on our pages is
     **Unverified**.
- **The design that is defensible:**
  - Born-digital PDFs keep the text-layer path from the earlier survey.
  - Scans and photos: run **two independent readings**, (a) a specialist parser and (b) a general VLM
    that returns JSON rows. Code accepts a value only when both agree, the value sits inside the
    cited box, and the credit and row-count checks pass. Numbers must match exactly; titles may
    differ only by the ə/e, ı/i, İ/I, ş/s, ğ/g confusion set. Everything else goes to review.
  - Jev's column classification can retire if the JSON reader maps columns reliably. That has to
    be measured, not assumed.

### Ranked shortlist

| # | Model | Role in our design | Why it is on the list | Main risk |
|---|---|---|---|---|
| 1 | **PaddleOCR-VL-1.6** (0.9B) | Specialist parser: page → table HTML + element boxes | Top of OmniDocBench v1.6 among releases with our language family covered (109 languages incl. Cyrillic); Apache-2.0; tiny; spotting mode gives text with location | az/tr not named; Dr.DocBench drop |
| 2 | **Qwen3.5-9B / 4B** | General reader: page → JSON rows (+ boxes) under a schema | Apache-2.0; "201 languages and dialects"; grounding ability; JSON via vLLM structured outputs | Lower parsing scores than specialists; thinks by default |
| 3 | **OvisOCR2** (0.8B) | Cheap second specialist reading | Apache-2.0; 96.58 on OmniDocBench v1.6; best end-to-end on PureDocBench *real-degraded* in TeleOCR's table | Released 2026; languages not stated; boxes only for image regions |
| 4 | **Chandra 2** (Datalab) | Upper-bound reference | Only candidate with published **tr** and **ru** accuracy; tops olmOCR-bench (85.8, self-run) | Weights licence: free only under $2M funding/revenue, no use competing with Datalab's API |

Runners-up and why they lost (details in §2): **Qianfan-OCR** (4B, Apache-2.0, 192 languages, JSON
KIE) is weak on degraded pages in TeleOCR's table (45.06 real-degraded vs 60–67 for the others).
**GLM-OCR** (MIT) lists only zh/en/fr/es/ru/de/ja/ko. **MinerU2.5-Pro** weights list zh/en only.
**HunyuanOCR** is ruled out: its licence excludes the EU.

## Scope (sub-questions)

1. Who leads document-parsing benchmarks (OmniDocBench v1.5/v1.6, olmOCR-bench, degraded-page
   benchmarks), and who ran each number?
2. For each serious candidate: parameters, licence, stated languages, table format, grounding, JSON
   output, GPU need.
3. What published evidence exists on VLMs inventing or normalising text, and what mitigations exist?
4. On-demand AWS deployment: smallest GPU, scale to zero.
5. Which candidates fit a 12 GB RTX 4070 for a local measurement run?

**How the candidate list was built:**
- Exa: "Hugging Face model card of an open-weight document parsing VLM reporting OmniDocBench v1.5".
  It returned Qianfan-OCR, OvisOCR, GLM-OCR, PaddleOCR-VL-1.5 and the OmniDocBench README, whose
  v1.6 leaderboard lists PaddleOCR-VL-1.6, MinerU2.5-Pro, GLM-OCR, Youtu-Parsing, Qianfan-OCR,
  Ovis2.6, Logics-Parsing-v2, FireRed-OCR, dots.ocr, DeepSeek-OCR 2, HunyuanOCR, Qwen3-VL-235B,
  Dolphin-v2, olmOCR, Mistral OCR, Kimi K2.5, InternVL3.5, Nanonets-OCR-s and Marker.
- Exa with `includeDomains` huggingface.co/github.com: PaddleOCR-VL-1.6, MinerU2.5-Pro-2605, and
  Qwen (found Qwen3.5 and Qwen3.6).
- Brave `"OmniDocBench" v1.6 site:huggingface.co`: added OvisOCR2 (96.58) and TeleOCR/NaviDC-OCR
  (96.87, zh/en only).
- Exa on arxiv.org: hallucination papers.
- Tools: Context7 and Tavily were available but not used.

## 1. Benchmarks: who leads, and who ran it

**OmniDocBench v1.6** (maintainers: opendatalab, the same lab that builds MinerU). v1.6 "Added 296
new pages".[^29] Overall = mean of (1 − text edit) × 100, table TEDS and formula CDM.

| Model | Params | Overall v1.6 | Source |
|---|---|---|---|
| TeleOCR | 1.2B | 96.87 | TeleOCR card (self) |
| OvisOCR2 | 0.8B | 96.58 | OvisOCR2 card (self)[^16] |
| PaddleOCR-VL-1.6 | 0.9B | 96.33 | Paddle card (self)[^1]; TeleOCR table[^8] |
| MinerU2.5-Pro | 1.2B | 95.75 | TeleOCR table[^7]; MinerU card's own 95.69–95.72 is **Unverified** (HTML table, not quotable) |
| GLM-OCR | 0.9B | 95.22 | TeleOCR table[^11] |
| Gemini 3 Pro | – | 92.85 | TeleOCR table |
| Qwen3-VL-235B | 235B | 89.78 | TeleOCR table |
| GPT-5.2 | – | 86.52 | TeleOCR table |

Every number here is either self-reported or copied by a competing vendor. The OmniDocBench README
carries its own v1.6 table: PaddleOCR-VL-1.6 96.34, MinerU2.5-Pro 95.75, GLM-OCR 95.22, Qianfan-OCR
93.90. Those values are **Unverified** here, because the page was too large to quote. Paddle's own
note says its own row and Gemini/Qwen rows "were evaluated independently".[^2]

**OmniDocBench v1.5 (older):**
- GLM-OCR: 94.62.[^12]
- Qianfan-OCR: 93.12.[^13]
- Qwen3.5-9B: 87.7. Qwen3.5-4B: 86.2. Qwen3-VL-30B-A3B: 86.8. All self-reported, and
  **Unverified** here: the Qwen card's table is HTML and yields no quotable label+value string.

**olmOCR-bench (English):** this table is compiled by Datalab, and its "Source" column marks which
rows Datalab ran itself.
- Chandra 2 overall: 85.8.[^21]
- Table sub-scores: olmOCR 2 = 84.9, dots.ocr 1.5 = 90.7, Qwen3-VL-8B = 45.6.[^23] The last figure
  is a warning for using a general VLM on tables.

**Degraded and real-world pages.** This is closest to phone photos.
- **Real5-OmniDocBench** (Paddle-built) covers "Scanning, Warping, Screen-photography, Illumination,
  and Skew".[^3]
- **PureDocBench** "Real Degraded Overall", from TeleOCR's compiled table: Qwen3-VL-8B 62.73,
  PaddleOCR-VL-1.5 60.50, Qianfan-OCR 45.06.[^17][^18][^19]
- **Dr.DocBench challenge**: PaddleOCR-VL-1.6 55.11 overall.[^10] The scores fall hard on unseen,
  harder data.

**Multilingual.**
- **Chandra 2's own 43-language benchmark:** tr 84.1% (Gemini 2.5 Flash also 84.1%), ru 85.5%.
  Azerbaijani is not in the 43-language table.[^22]
- **CC-OCR:** Qwen3.5-9B 79.3, self-reported (**Unverified**, same reason as above).
- **Conclusion:** no third-party multilingual table benchmark exists. Our page set remains the only
  evidence for az/tr.

## 2. Facts table

| Model | Params | Licence (commercial?) | Languages stated | Tables out | Grounding | JSON | Fits RTX 4070 12 GB? |
|---|---|---|---|---|---|---|---|
| PaddleOCR-VL-1.6 | 0.9B | Apache-2.0, free[^4] | "109 languages"; Cyrillic named; az/tr not named[^5] | HTML/Markdown via pipeline | Layout boxes per element (pipeline JSON); "text spotting" task[^6] | Pipeline JSON (blocks), not a row schema | Yes (≈2 GB bf16 by arithmetic) |
| OvisOCR2 | 0.8B | Apache-2.0, free[^15] | Not stated (base Qwen3.5-0.8B) | HTML tables in Markdown | Boxes for image regions only[^34] | No | Yes |
| Qwen3.5-9B / 4B | 9B / 4B | Apache-2.0, free[^14] | "201 languages and dialects"[^24] | Prompted | 2D grounding (RefCOCO avg 89.7, self-reported, **Unverified**) | Yes, via vLLM structured outputs[^35][^36] | 4B: yes in bf16. 9B: only quantised (**Unverified** quality) |
| Chandra 2 | **Unverified** (credits Qwen 3.5) | Modified OpenRAIL-M: free under $2M funding/revenue, no competing use[^26] | "90+ languages"; tr/ru measured[^22] | HTML/Markdown/JSON | Layout blocks | JSON layout | **Unverified** |
| Qianfan-OCR | 4B | Apache-2.0[^37] | "192 languages including Latin, Cyrillic"[^38] | HTML | Layout-as-Thought emits boxes[^39] | "structured output (JSON/HTML)"[^40] | Tight in bf16 (≈8 GB weights); W8A8 helps |
| GLM-OCR | 0.9B (+ PP-DocLayoutV3) | MIT; layout model Apache-2.0[^41] | zh, en, fr, es, ru, de, ja, ko[^42] | HTML | Layout boxes (SDK) | JSON-schema prompts for extraction[^43] | Yes |
| MinerU2.5-Pro-2605 | 1.2B | Weights Apache-2.0; MinerU code has "additional conditions"[^27][^44] | zh, en[^27] | HTML | Block boxes (`two_step_extract`) | Content list | Yes |
| HunyuanOCR | 1B | **Ruled out:** "does not apply in the European Union"[^45]; its AUP also bars high-stakes automated decisions in education[^46] | – | – | – | – | – |

Throughput (vendor-measured, A100 or H100; not comparable to an L4):
- GLM-OCR: 1.86 PDF pages/s.[^47]
- Qianfan-OCR: 0.503 pages/s at W16A16.[^48]
- Chandra 2: 1.44 pages/s on an H100 at 96 concurrency.[^49]

Not investigated in depth (scope): granite-docling, LightOnOCR-2, Nanonets-OCR2, DeepSeek-OCR 2,
olmOCR-2 (English-focused), InternVL3.5, MiniCPM-V, Gemma, Pixtral, Kimi-VL, dots.ocr 1.5 and
TeleOCR (zh/en). On the leaderboards above none beats the shortlist; their language coverage for
az/tr is **Unverified**.

## 3. Hallucination: evidence and mitigations

- **Evidence.**
  - On microfilm scans, VLMs beat traditional OCR on CER and WER. Qualitatively, though, they showed
    "orthographic normalization, spurious content generation, and semantic substitutions".[^30]
    Named-entity errors cause "substantial semantic distortions with minimal impact on CER and
    WER".[^31]
  - On degraded IDs and invoices, the inability to recognise uncertainty "frequently results in the
    generation of hallucinatory content".[^32]
  - Even the vendors say so. OvisOCR2's card: "Please manually verify results in critical
    applications."[^33] Its prompt has to instruct "Preserve the original text without translation
    or paraphrasing."[^34]
- **Mitigations available to us:**
  1. **Constrained decoding.** vLLM structured outputs (xgrammar or guidance backends) guarantee the
     *shape* of the JSON.[^35][^36] They do not guarantee the *values*.
  2. **Grounding.** Require a box for each value. Code checks the box against an independent
     reading of the same region.
  3. **Second reader.** Two models from different families must agree (same idea as our CV-format
     judge).
  4. **Arithmetic.** Credit sums and row counts against codes.
  5. **Training for refusal.** A refusal-trained 7B model improved hallucination-free accuracy over
     GPT-4o.[^32] That model is not available off the shelf.
  6. **Token log-probs** as an error flag: **Unverified** on our pages, so it must be measured.

## 4. Deployment on AWS, on demand

- **Smallest GPU.**
  - G6 instances carry NVIDIA L4 GPUs "with 24 GB of memory per GPU". Fractional sizes start at
    "1/8 of an L4 GPU with 3 GB".[^50]
  - One L4 (g6.xlarge) holds every shortlisted model, including Qwen3.5-9B in bf16 (≈18 GB of
    weights by arithmetic).
  - A 3 GB fractional slice might hold the 0.8–0.9B parsers. That is **Unverified**; KV cache and
    the vision encoder need room too.
- **Scale to zero.**
  - SageMaker asynchronous inference "can also scale down your asynchronous endpoints instances to
    zero", and requests that arrive at zero instances "are queued".[^51][^52] It fits our
    upload-then-wait flow.
  - Cold-start time is **Unverified**: an instance launch plus a model load.
  - ECS on a GPU Auto Scaling group with minimum 0 is the alternative (**Unverified**, not fetched).
  - Lambda has no GPU.
- **Cost per page:** **Unverified**, since prices were not fetched. The formula is the instance
  price per hour ÷ (pages/s × 3600), plus cold-start minutes per burst. With bursty, low volume,
  the cold start dominates; the per-page compute is a fraction of a cent.
- **CPU.**
  - A llama.cpp/GGUF build of PaddleOCR-VL-1.6 is published (`PaddlePaddle/PaddleOCR-VL-1.6-GGUF`);
    CPU speed is **Unverified**.
  - A third-party LiteRT conversion reports that the 0.36B decoder is "quantization-sensitive":
    int4/int8 corrupted transcription (**Unverified**, search snippet only).
  - The 4–9B models are not practical on CPU for interactive use (**Unverified**).

## 5. Measurement plan (local RTX 4070, 12 GB)

Run everything over `.superpowers/ocr-eval/ (git-ignored eval harness) pages/` (the 16
documents in `out/surya/REPORT.md`) and score with the existing `score.py`.

**What fits on the 4070:**
- In bf16: PaddleOCR-VL-1.6, OvisOCR2, GLM-OCR, MinerU2.5-Pro, Qwen3.5-4B.
- Tight: Qianfan-OCR (bf16 with a short `max-model-len`, or W8A8).
- Quantised only: Qwen3.5-9B (AWQ/GGUF 4-bit). Score it separately, because quantisation can change
  characters.
- Chandra 2: size **Unverified**; check it before running.

**Runs:**
1. **PaddleOCR-VL-1.6:** `paddleocr doc_parser --pipeline_version v1.6`. Convert table HTML to rows
   in code. Also run the `spotting` task to get line text with boxes.
2. **OvisOCR2:** page → Markdown/HTML at temperature 0, then table HTML → rows.
3. **Qwen3.5-4B (bf16) and 9B (4-bit):** non-thinking mode, with a vLLM `json` schema of
   `{rows:[{title, credits, credit_unit, grade, status, bbox}]}`. Also run thinking mode once to see
   whether it helps.
4. **Chandra 2:** as a reference, with the licence caveat noted.
5. **Optional:** Qianfan-OCR KIE with the same schema, to test its weak degraded score on our scans.

**Metrics (existing):** title strict/lenient, numbers in row, special letters ok/bad, row pairing,
s/page. Add peak VRAM.

**Metrics (new, the ones that decide the design):**
- **Invented rows** (no ground-truth match) and **dropped rows**.
- **Normalisations:** count of ə→e/a, ı→i, İ→I, ş→s, ğ→g.
- **Digit changes** in credits and grades, even when the row pairs correctly.
- **Filled blanks.** Perturbation test: erase one grade cell and blur one title in three images.
  Does the model leave the field empty or invent a value?
- **Low-resolution behaviour.** On Mersin (129 ppi), does it refuse, degrade visibly, or produce
  fluent wrong rows?
- **Agreement.** For each pair of readers, the share of values on which they agree, and the error
  rate *within* the agreed set. This number decides whether "accept on agreement" is safe.
- **Grounding pass rate.** The share of Qwen values whose bbox overlaps the specialist's text with
  the same value.
- **Log-prob flag.** Does the minimum token log-prob of a value separate wrong values from right
  ones (as Azure confidence < 0.8 did)?
- **Determinism.** Three runs at temperature 0; any drift counts as a defect.

**Decision rule (proposed):**
- **Single VLM allowed** only if, on every page (including Mersin and NKU): invented rows = 0,
  digit changes = 0, normalisations = 0, and every perturbed blank stays blank.
- **Otherwise, VLM + grounding check:** two readers, accept on agreement plus arithmetic, review the
  rest. The plan's goal is to measure the review rate this produces.

## Sources

[^1]: https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/raw/main/README.md "PaddleOCR-VL-1.6 achieves a new state-of-the-art score of 96.33% on OmniDocBench v1.6"
[^2]: https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/raw/main/README.md "except for Gemini-3 Pro, Qwen3-VL-235B-A22B-Instruct and our model, which were evaluated independently"
[^3]: https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/raw/main/README.md "The dataset comprises five distinct scenarios: Scanning, Warping, Screen-photography, Illumination, and Skew."
[^4]: https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/raw/main/README.md "license: apache-2.0 pipeline_tag: image-text-to-text"
[^5]: https://huggingface.co/PaddlePaddle/PaddleOCR-VL/raw/main/README.md "This innovative model efficiently supports 109 languages"
[^6]: https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/raw/main/README.md "The example code below only supports element-level recognition and text spotting."
[^7]: https://huggingface.co/XingChen-AGI/TeleOCR/raw/main/README.md "MinerU2.5-Pro | 1.2B | 95.75 | 0.036 | 97.45 | 93.42"
[^8]: https://huggingface.co/XingChen-AGI/TeleOCR/raw/main/README.md "PaddleOCR-VL-1.6 | 0.9B | 96.33 | 0.033"
[^9]: https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/raw/main/README.md "PaddleOCR-VL-1.6 achieves a new state-of-the-art score of 96.33% on OmniDocBench v1.6"
[^10]: https://huggingface.co/XingChen-AGI/TeleOCR/raw/main/README.md "PaddleOCRvl 1.6|55.11 | 0.4364 | 0.21 | 51.34"
[^11]: https://huggingface.co/XingChen-AGI/TeleOCR/raw/main/README.md "GLM-OCR | 0.9B | 95.22 | 0.044 | 97.18"
[^12]: https://huggingface.co/zai-org/GLM-OCR/raw/main/README.md "Achieves a score of 94.62 on OmniDocBench V1.5, ranking #1 overall"
[^13]: https://huggingface.co/baidu/Qianfan-OCR/raw/main/README.md "value: 93.12 name: Overall Score"
[^14]: https://huggingface.co/Qwen/Qwen3.5-9B/raw/main/README.md "license: apache-2.0 license_link: https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/LICENSE"
[^15]: https://huggingface.co/ATH-MaaS/OvisOCR2/raw/main/README.md "license: apache-2.0 library_name: transformers pipeline_tag: image-text-to-text base_model: Qwen/Qwen3.5-0.8B"
[^16]: https://huggingface.co/ATH-MaaS/OvisOCR2/raw/main/README.md "OvisOCR2 achieves an overall score of 96.58 on OmniDocBench v1.6"
[^17]: https://huggingface.co/XingChen-AGI/TeleOCR/raw/main/README.md "Qwen3-VL-8B | 72.44 | 0.261 | 65.10 | 78.35 | 72.03 | 0.266 | 64.88 | 77.82 | 62.73"
[^18]: https://huggingface.co/XingChen-AGI/TeleOCR/raw/main/README.md "PaddleOCR-VL-1.5 | 73.01 | 0.266 | 63.53 | 82.12 | 66.73 | 0.339 | 58.03 | 76.07 | 60.50"
[^19]: https://huggingface.co/XingChen-AGI/TeleOCR/raw/main/README.md "Qianfan-OCR | 57.22 | 0.370 | 49.79 | 58.83 | 50.85 | 0.438 | 44.41 | 51.96 | 45.06"
[^21]: https://huggingface.co/datalab-to/chandra-ocr-2/raw/main/README.md "85.8% olmocr bench score (sota), 77.8% multilingual bench score"
[^22]: https://huggingface.co/datalab-to/chandra-ocr-2/raw/main/README.md "tr | 88.9% | 84.1% | 68.1% | 84.1% | 78.2%"
[^23]: https://huggingface.co/datalab-to/chandra-ocr-2/raw/main/README.md "Qwen 3 VL 8B | 70.2 | 75.1 | 45.6"
[^24]: https://huggingface.co/Qwen/Qwen3.5-9B/raw/main/README.md "Expanded support to 201 languages and dialects"
[^26]: https://huggingface.co/datalab-to/chandra-ocr-2/raw/main/README.md "Model weights use a modified OpenRAIL-M license: free for research, personal use, and startups under $2M funding/revenue."
[^27]: https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B/raw/main/README.md "license: apache-2.0 language: - zh - en"
[^28]: https://github.com/opendatalab/OmniDocBench "Currently, only Chinese and English text are included in text evaluation."
[^29]: https://github.com/opendatalab/OmniDocBench "Added 296 new pages"
[^30]: https://arxiv.org/abs/2607.24077 "including orthographic normalization, spurious content generation, and semantic substitutions that preserve fluency while altering meaning"
[^31]: https://arxiv.org/abs/2607.24077 "Errors affecting named entities are particularly critical, as they can introduce substantial semantic distortions with minimal impact on CER and WER."
[^32]: https://arxiv.org/abs/2506.20168 "This difficulty in recognizing uncertainty frequently results in the generation of hallucinatory content"
[^33]: https://huggingface.co/ATH-MaaS/OvisOCR2/raw/main/README.md "Please manually verify results in critical applications."
[^34]: https://huggingface.co/ATH-MaaS/OvisOCR2/raw/main/README.md "Preserve the original text without translation or paraphrasing."
[^35]: https://docs.vllm.ai/en/latest/features/structured_outputs/ "vLLM supports the generation of structured outputs using xgrammar or guidance as backends."
[^36]: https://docs.vllm.ai/en/latest/features/structured_outputs/ "the option to generate a valid JSON with pre-defined fields and formats"
[^37]: https://huggingface.co/baidu/Qianfan-OCR/raw/main/README.md "This project is licensed under the Apache License 2.0."
[^38]: https://huggingface.co/baidu/Qianfan-OCR/raw/main/README.md "192 languages including Latin, Cyrillic, Arabic, South/Southeast Asian, CJK scripts"
[^39]: https://huggingface.co/baidu/Qianfan-OCR/raw/main/README.md "the model generates structured layout representations (bounding boxes, element types, reading order) before producing final outputs"
[^40]: https://huggingface.co/baidu/Qianfan-OCR/raw/main/README.md "Image-to-Markdown conversion, multi-page parsing, structured output (JSON/HTML)"
[^41]: https://huggingface.co/zai-org/GLM-OCR/raw/main/README.md "The GLM-OCR model is released under the MIT License."
[^42]: https://huggingface.co/zai-org/GLM-OCR/raw/main/README.md "- ru - de - ja - ko"
[^43]: https://huggingface.co/zai-org/GLM-OCR/raw/main/README.md "Prompts must follow a strict JSON schema."
[^44]: https://github.com/opendatalab/MinerU "MinerU Open Source License, based on Apache 2.0 with additional conditions."
[^45]: https://huggingface.co/tencent/HunyuanOCR/raw/main/LICENSE "THIS LICENSE AGREEMENT DOES NOT APPLY IN THE EUROPEAN UNION, UNITED KINGDOM AND SOUTH KOREA"
[^46]: https://huggingface.co/tencent/HunyuanOCR/raw/main/LICENSE "employment, housing, education, social scoring, or insurance"
[^47]: https://huggingface.co/zai-org/GLM-OCR/raw/main/README.md "GLM-OCR achieves a throughput of 1.86 pages/second for PDF documents"
[^48]: https://huggingface.co/baidu/Qianfan-OCR/raw/main/README.md "Qianfan-OCR (W16A16) | 0.503 |"
[^49]: https://huggingface.co/datalab-to/chandra-ocr-2/raw/main/README.md "vLLM, 96 concurrent sequences | 1.44 | 60s | 156s | 0%"
[^50]: https://aws.amazon.com/ec2/instance-types/g6/ "G6 instances feature up to 8 NVIDIA L4 Tensor Core GPUs with 24 GB of memory per GPU"
[^51]: https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference-autoscale.html "with Asynchronous Inference you can also scale down your asynchronous endpoints instances to zero"
[^52]: https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference-autoscale.html "Requests that are received when there are zero instances are queued for processing once the endpoint scales up."

Local evidence (no URL): `.superpowers/ocr-eval/ (git-ignored eval harness) out/surya/REPORT.md` (Mersin 52%, NKU 72% strict titles; az 98%).

## Open questions

- No candidate's az/tr title accuracy on transcripts is published. Only our page set can settle it.
- The OmniDocBench maintainers' own v1.6 table was not quotable (page too large); the numbers above
  come from vendor cards.
- Chandra 2 parameter count and VRAM; whether a <$2M-revenue startup's later growth triggers a paid
  licence.
- Per-value confidence: whether vLLM token log-probs flag wrong values on our pages.
- LoRA fine-tuning paths for PaddleOCR-VL-1.6 (ERNIEKit/PaddleFormers) and Qwen3.5: not fetched.
- g6/g6f prices, SageMaker async cold-start time, and whether a 3 GB g6f slice runs a 0.9B parser.
- Whether 4-bit Qwen3.5-9B keeps diacritics (ə, ı, ğ) intact; quantisation sensitivity is reported
  for the PaddleOCR-VL decoder but **Unverified**.
- Granite-docling, LightOnOCR-2, Nanonets-OCR2, DeepSeek-OCR 2, Gemma, Pixtral, Kimi-VL, MiniCPM-V:
  not investigated in depth.

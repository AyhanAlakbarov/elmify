# CV text + link extraction: pypdf and a hand-rolled DOCX reader, or switch?

Date: 2026-10-14. Question: for student CVs (PDF, DOCX) on a Python 3.14 Django server, is pypdf
plus a zipfile + defusedxml DOCX reader the right choice, or is another open-source library clearly
better at reading CV layouts, without an AGPL problem, a heavy ML dependency or a worse security record?

## Answer

**Keep pypdf. No candidate is clearly better.** No published benchmark tests CV layouts. On the one
published benchmark that includes the lightweight libraries, pypdf ties for first place on text
quality. Every tool that scores higher on reading order is blocked by one of the stated constraints.

- **pypdf** ties pypdfium2 for the best average text-extraction quality (95%) in py-pdf/benchmarks,
  ahead of PyMuPDF (94%), pdfminer.six (88%) and pdfplumber (74%). It is BSD-3-Clause, pure Python,
  declares Python 3.14 and released on 2026-10-12. Its weak points are speed (about 3.3 s average
  against 0.1 s for pypdfium2) and a long run of denial-of-service advisories. Both are reasons to run
  it in a subprocess with a time and memory cap. Neither is a reason to switch.
- **pypdfium2** is the only light, permissively licensed option that matches pypdf's quality, and it
  is about 30 times faster. The catch is that it puts a C engine (PDFium) inside the Django process,
  and its documented helpers do not cover link extraction. It is worth adopting for speed. It does not
  improve quality.
- **PyMuPDF** is not better on the published benchmark (94%). It is AGPL-3.0 or commercial, and it
  does not support multithreaded use. It is blocked unless it runs as a separate service.
- **docling, marker and unstructured** are the only tools with measured reading-order gains, and the
  gains are small. Each is blocked. docling and marker need PyTorch. unstructured does not install on
  Python 3.14.
- **DOCX**: no published quality benchmark exists for python-docx, docx2python or mammoth. The
  hand-rolled reader is defensible. Before keeping it, check it against two failure modes that the
  libraries' changelogs document: hyperlinks stored as Word *complex fields* (not `w:hyperlink`), and
  one link split across several `w:hyperlink` elements.

## Sub-questions

1. Licence, latest release and Python 3.14 support for each candidate.
2. Published text-extraction quality numbers with methodology (py-pdf/benchmarks, opendataloader-bench,
   olmocr-bench as reported by marker, OmniDocBench).
3. Documented handling of CV failure modes: reading order and layout, ligatures, dehyphenation,
   hyperlink URL extraction.
4. Weight (PyTorch or models) and the security record for untrusted files.

## How the candidate list was built

The fixed list came from the question. Searches confirmed it and added two benchmark sources:

- Exa: "open-source Python library that extracts text and hyperlinks from PDF resumes, GitHub
  repository". It returned pdfplumber, PyMuPDF and pypdf-based resume parsers.
- Brave: `"opendataloader" OR "OmniDocBench" PDF extraction benchmark docling marker pymupdf4llm`.
  It returned opendataloader-bench, OmniDocBench and opendataloader-pdf.

Search also surfaced **opendataloader-pdf** (Apache-2.0, 0.831 overall in its own benchmark). It is
noted but not evaluated: its runtime needs were not checked from a primary source.

## Comparison table

| Library | Licence | Latest release | Python 3.14 | Heavy dependencies | Link URLs |
|---|---|---|---|---|---|
| pypdf | BSD-3-Clause[^1] | 6.20.1, 2026-10-12[^2] | declared[^3] | none (pure Python) | yes, by reading `/Annots`[^4] |
| pdfminer.six | MIT[^5] | 20260107, 2026-01-07[^6] | declared[^7] | none | no high-level API found (Unverified) |
| pdfplumber | MIT[^8] | 0.11.10, 2026-06-15[^9] | tested on 3.14[^10] | pdfminer.six | `.hyperlinks`[^11] |
| pypdfium2 | BSD-3-Clause or Apache-2.0[^12] | 5.14.0, 2026-10-04[^13] | ctypes binding, so not tied to a CPython version[^14] | bundled PDFium (C) | raw PDFium API only[^15] |
| PyMuPDF | AGPL-3.0 or commercial[^16] | 1.28.2, 2026-08-06[^17] | wheels for 3.10–3.14[^18] | bundled MuPDF (C) | yes[^19] |
| docling | MIT code; models under their own licences[^20] | 2.138.0, 2026-10-12[^21] | declared[^22] | **PyTorch**[^23] | not checked |
| marker | Apache-2.0 code; model weights restricted[^24] | 2.0.0, 2026-07-20[^25] | not checked | **PyTorch**[^26] | not checked |
| unstructured | Apache-2.0[^27] | 0.27.25, 2026-10-10[^28] | **no: `<3.14`**[^29] | heavy with extras (Unverified) | not checked |
| python-docx | MIT[^30] | 1.2.0, 2025-06-16[^31] | tested only up to 3.13[^32] | lxml | `Hyperlink.url`[^33] |
| docx2python | MIT[^34] | 3.7.1, 2026-08-06[^35] | declared[^36] | lxml | inline `<a href>`[^37] |
| mammoth | BSD-2-Clause[^38] | 1.13.0, 2026-09-26[^39] | classifiers stop at 3.12[^40] | none heavy | converted to HTML links |

pypdfium2 wheels: the PyPI file list for 5.14.0 shows only `py3-none-<platform>` wheels, which work on
any Python 3 version. This was seen on 2026-10-14 and has no footnote, because file names are too
short for the citation check.

## Published quality evidence

### py-pdf/benchmarks: the only benchmark that includes pypdf, pypdfium2, pdfminer.six and pdfplumber

**Method.** Each library's output is scored by Levenshtein `ratio` against a ground-truth text file
for each document[^41]. The corpus is 14 born-digital PDFs, mostly arXiv papers, so mostly
LaTeX-produced. That makes ligatures and accents relevant, but it is not a CV corpus.

**Bias.** The benchmark is published by the py-pdf organisation, which also maintains pypdf. The
scoring code is public. Who produced the ground-truth files is not documented.

**Average text-extraction quality:**

- pypdfium2: 95%[^42]
- pypdf: 95%[^43]
- PyMuPDF: 94%[^44]
- pdfminer.six: 88%[^45]
- pdfplumber: 74%[^46]

**Average text-extraction time:**

- pypdfium2: 0.1 s[^47]
- pypdf: 3.3 s[^48]

### opendataloader-bench: reading order (NID), tables and headings on 200 PDFs[^49]

This benchmark is published by the opendataloader project, which sells one of the engines it ranks.
The lightweight libraries are not in it.

| Engine | Overall | Reading order (NID) |
|---|---|---|
| docling | 0.882 | 0.898[^50] |
| marker | 0.861 | 0.890[^51] |
| pymupdf4llm | 0.732 | 0.885[^52] |
| unstructured (default strategy) | 0.686 | 0.882[^53] |

The reading-order spread between the heavy ML tools and the light ones is about 0.016 NID, which is
small. Most of the ML advantage is in tables and headings, and CV text extraction does not need either.

The benchmark lists marker as GPL-3.0[^51]. marker's own README now says the code is Apache 2.0[^24].
The project owns that fact, so the README wins. The benchmark's licence column is out of date.

### olmocr-bench, as reported in marker's README (vendor-run)

- With no OCR, on CPU, marker scores 43.6 overall[^54] and 67.0 on the multi-column category[^55].
- docling (GPU) scores 50.3 overall[^56].
- Neither number is CV-specific, and no pypdf or pypdfium2 row exists.

### OmniDocBench

This benchmark gives page images to each system, not the PDF text layer, so it does not apply to
text-layer libraries. Its only relevant row is Marker 1.8.2: 78.44 overall and 0.157 text edit
distance[^57].

### CV layouts

**No published evidence.** No benchmark found measures CVs: two-column layouts, right-aligned dates,
LaTeX accents or link annotations. Any switch would need a local gold set of real CVs.

## CV failure modes, by what each library documents

- **Layout and right-aligned dates.** pypdf has `extraction_mode="layout"`, which gives "a fixed width
  format that closely adheres to the rendered layout"[^58]. pdfplumber's `layout=True` is marked
  experimental[^59].
- **Ligatures (ﬁ/ﬂ).**
  - pypdf documents ligatures only as an open question[^60].
  - PyMuPDF *keeps* ligatures by default. The flag `TEXT_PRESERVE_LIGATURES` is on unless you turn it
    off[^61].
  - pdfplumber can normalise Unicode on open (`unicode_norm`, including NFKC)[^62].
  - With any library, NFKC normalisation in our own code expands ligatures. This is standard Unicode
    behaviour, not checked against a page here.
- **LaTeX accents (´e).** **No published evidence** for any candidate. A spacing acute (U+00B4)
  followed by a letter is not composed by NFC. Only a combining accent (U+0301) is. So a small custom
  fold step is needed whichever library is used. (Unverified: reasoning from Unicode, not a fetched
  source.)
- **Hyphenated line ends.** Only PyMuPDF documents dehyphenation (`TEXT_DEHYPHENATE`)[^63].
- **Bullets.** **No published evidence** for any PDF library. docx2python converts DOCX bullets to
  ASCII with indentation[^64].
- **DOCX links.** Word can store a hyperlink as a complex field rather than a `w:hyperlink` element:
  mammoth added "Handle hyperlinks created with complex fields"[^65]. Word also splits one link across
  several `w:hyperlink` elements with different relationship IDs, which docx2python merges[^66].

## Security record for untrusted files

- **pypdf.** Its advisory list runs to six pages[^67]. The newest are denial-of-service bugs, such as
  an infinite loop at end-of-file in the xref table, published 2026-10-12[^68]. Its docs warn that
  extracting a 300 MB content stream once needed 10 GB of RAM[^69]. No code-execution advisory was seen
  on the first page.
- **pdfminer.six, and so pdfplumber.** A High-severity arbitrary-code-execution advisory: a crafted
  PDF can make the CMap loader unpickle a file at an attacker-chosen path[^70]. It was published
  2025-11-07, and the current release (20260107) is newer. Which version fixed it was not checked.
- **PyMuPDF and pypdfium2.** No advisories are published in their GitHub repositories. Their risk sits
  in the C engines they bundle (MuPDF and PDFium), whose CVE history was not checked. PyMuPDF "does not
  support multithreaded use"[^71].
- **mammoth.** It had a file-read path traversal (CVE-2025-11849): a DOCX image with an external link
  could read any local file[^72]. Since 1.11.0, external file access is off by default[^73]. Its
  maintainer advises processing untrusted documents "in a separate thread with a timeout"[^74].
- **python-docx.** It has disallowed XML entity expansion since 0.8.6[^75].
- **The hand-rolled reader.** Python's zipfile is itself exposed to ZIP bombs[^76]. The reader needs
  its own limits on uncompressed size and entry count. defusedxml covers XML attacks only.

**What to do whichever library is used:** parse each upload in a separate process with a CPU-time and
memory limit, not inside the web worker.

## AGPL and PyMuPDF

- AGPL §13 requires a *modified* program to offer its source to users who reach it over a
  network[^77].
- Artifex's own docs say that if you cannot meet the AGPL's requirements, you need its commercial
  licence[^78].
- Whether importing an unmodified PyMuPDF into a closed SaaS creates obligations is a legal judgement,
  not a technical one. Following the owner's constraint, PyMuPDF counts as blocked unless it runs as a
  separate service whose source can be published.

## Sources

[^1]: https://pypi.org/project/pypdf/ "BSD-3-Clause View SPDX License List"
[^2]: https://pypi.org/project/pypdf/ "6.20.1 This release Oct 12, 2026"
[^3]: https://pypi.org/project/pypdf/ "Python :: 3.13 Python :: 3.14"
[^4]: https://pypdf.readthedocs.io/en/stable/user/reading-pdf-annotations.html "In general, annotations can be read like this"
[^5]: https://pypi.org/project/pdfminer.six/ "MIT View SPDX License List"
[^6]: https://pypi.org/project/pdfminer.six/ "20260107 This release Jan 7, 2026"
[^7]: https://pypi.org/project/pdfminer.six/ "Python :: 3.13 Python :: 3.14"
[^8]: https://pypi.org/project/pdfplumber/ "License MIT License Requires Python >=3.8"
[^9]: https://pypi.org/project/pdfplumber/ "0.11.10 This release Jun 15, 2026"
[^10]: https://github.com/jsvine/pdfplumber "Python 3.10, 3.11, 3.12, 3.13, 3.14"
[^11]: https://github.com/jsvine/pdfplumber "each representing a single PDF annotation of the subtype Link and having an URI action attribute"
[^12]: https://pypi.org/project/pypdfium2/ "BSD-3-Clause, Apache-2.0, dependency licenses"
[^13]: https://pypi.org/project/pypdfium2/ "5.14.0 This release Oct 4, 2026"
[^14]: https://github.com/pypdfium2-team/pypdfium2 "pypdfium2 is an ABI-level Python 3 binding to PDFium"
[^15]: https://github.com/pypdfium2-team/pypdfium2 "Since PDFium is a large library, many components are not covered by helpers yet."
[^16]: https://pypi.org/project/PyMuPDF/ "Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License"
[^17]: https://pypi.org/project/PyMuPDF/ "1.28.2 This release Aug 6, 2026"
[^18]: https://github.com/pymupdf/pymupdf "Linux on Python 3.10–3.14"
[^19]: https://github.com/pymupdf/pymupdf "Extract hyperlinks, internal cross-references, and URI targets"
[^20]: https://github.com/docling-project/docling "The Docling codebase is under MIT license."
[^21]: https://pypi.org/project/docling/ "2.138.0 This release Oct 12, 2026"
[^22]: https://pypi.org/project/docling/ "Python :: 3.13 Python :: 3.14"
[^23]: https://docling-project.github.io/docling/getting_started/installation/ "The Docling models depend on the PyTorch library."
[^24]: https://github.com/datalab-to/marker "Our code is licensed under Apache 2.0"
[^25]: https://pypi.org/project/marker-pdf/ "2.0.0 This release Jul 20, 2026"
[^26]: https://github.com/datalab-to/marker "You'll need python 3.10+ and PyTorch"
[^27]: https://pypi.org/project/unstructured/ "License expression Apache-2.0 View SPDX License List"
[^28]: https://pypi.org/project/unstructured/ "0.27.25 This release Oct 10, 2026"
[^29]: https://pypi.org/project/unstructured/ "Requires Python <3.14, >=3.11"
[^30]: https://pypi.org/project/python-docx/ "License MIT License (MIT)"
[^31]: https://pypi.org/project/python-docx/ "1.2.0 This release Jun 16, 2025"
[^32]: https://raw.githubusercontent.com/python-openxml/python-docx/master/HISTORY.rst "Drop support for Python 3.8, add testing for Python 3.13"
[^33]: https://raw.githubusercontent.com/python-openxml/python-docx/master/HISTORY.rst "Add Hyperlink.fragment and .url"
[^34]: https://pypi.org/project/docx2python/ "License expression MIT View SPDX License List"
[^35]: https://pypi.org/project/docx2python/ "3.7.1 This release Aug 6, 2026"
[^36]: https://pypi.org/project/docx2python/ "Python :: 3.13 Python :: 3.14"
[^37]: https://pypi.org/project/docx2python/ "hyperlinks will always be exported as html"
[^38]: https://pypi.org/project/mammoth/ "License BSD License (BSD-2-Clause)"
[^39]: https://pypi.org/project/mammoth/ "1.13.0 This release Sep 26, 2026"
[^40]: https://pypi.org/project/mammoth/ "Python :: 3.11 Python :: 3.12"
[^41]: https://raw.githubusercontent.com/py-pdf/benchmarks/main/pdf_benchmark/score.py "return ratio(gt_data, extracted_data)"
[^42]: https://github.com/py-pdf/benchmarks "pypdfium2 95% 94% 97% 94% 99%"
[^43]: https://github.com/py-pdf/benchmarks "pypdf 95% 94% 95% 93% 98%"
[^44]: https://github.com/py-pdf/benchmarks "PyMuPDF 94% 93% 96% 92% 97%"
[^45]: https://github.com/py-pdf/benchmarks "pdfminer.six 88% 90% 79% 86% 92%"
[^46]: https://github.com/py-pdf/benchmarks "pdfplumber 74% 89% 84% 68% 97%"
[^47]: https://github.com/py-pdf/benchmarks "pypdfium2 0.1s 0.5s 0.2s 0.2s 0.2s"
[^48]: https://github.com/py-pdf/benchmarks "pypdf 3.3s 23.3s 6.3s 6.5s 3.3s"
[^49]: https://github.com/opendataloader-project/opendataloader-bench "Input PDF corpus (200 sample documents)"
[^50]: https://github.com/opendataloader-project/opendataloader-bench "docling 0.882 0.898 0.887 0.824 0.762 MIT"
[^51]: https://github.com/opendataloader-project/opendataloader-bench "marker 0.861 0.890 0.808 0.796 53.932 GPL-3.0"
[^52]: https://github.com/opendataloader-project/opendataloader-bench "pymupdf4llm 0.732 0.885 0.401 0.412 0.091 AGPL-3.0"
[^53]: https://github.com/opendataloader-project/opendataloader-bench "unstructured 0.686 0.882 0.000 0.388 0.077 Apache-2.0"
[^54]: https://github.com/datalab-to/marker "Marker — fast, no OCR (CPU) 43.6 55.8 23.7 pg/s"
[^55]: https://github.com/datalab-to/marker "Multi column 76.6 76.0 67.0"
[^56]: https://github.com/datalab-to/marker "docling (GPU) 50.3 64.0 2.1 pg/s"
[^57]: https://github.com/opendatalab/OmniDocBench "Marker Pipeline Tools - 78.44 0.157"
[^58]: https://pypdf.readthedocs.io/en/stable/user/extract-text.html "extract text in a fixed width format that closely adheres to the rendered"
[^59]: https://github.com/jsvine/pdfplumber "Attempts to mimic the structural layout of the text on the page(s)"
[^60]: https://pypdf.readthedocs.io/en/stable/user/extract-text.html "Should that be parsed as the Unicode symbol"
[^61]: https://pymupdf.readthedocs.io/en/latest/vars.html "If set, ligatures are passed through to the application in their original form."
[^62]: https://github.com/jsvine/pdfplumber "is one of the four Unicode normalization forms"
[^63]: https://pymupdf.readthedocs.io/en/latest/vars.html "Ignore hyphens at line ends and join with next line."
[^64]: https://pypi.org/project/docx2python/ "converts bullets and numbered lists to ascii with indentation"
[^65]: https://raw.githubusercontent.com/mwilliamson/python-mammoth/master/NEWS "Handle hyperlinks created with complex fields."
[^66]: https://pypi.org/project/docx2python/ "merge consecutive links with identical hrefs"
[^67]: https://github.com/py-pdf/pypdf/security/advisories "Previous 1 2 3 4 5 6 Next"
[^68]: https://github.com/py-pdf/pypdf/security/advisories "Possible infinite loop when hitting EOF in standard xref table"
[^69]: https://pypdf.readthedocs.io/en/stable/user/extract-text.html "we have seen 10 GB RAM being required for an uncompressed content stream of about 300 MB"
[^70]: https://github.com/pdfminer/pdfminer.six/security/advisories/GHSA-wf5f-4jwr-ppcp "pdfminer.six will execute arbitrary code from a malicious pickle file if provided with a malicious PDF file."
[^71]: https://github.com/pymupdf/pymupdf "PyMuPDF does not support multithreaded use, even with Python's newer free-threading mode."
[^72]: https://github.com/advisories/GHSA-rmjr-87wv-gf87 "An attacker can read arbitrary files on the system where the conversion is performed"
[^73]: https://raw.githubusercontent.com/mwilliamson/python-mammoth/master/NEWS "Disable external file accesses by default."
[^74]: https://raw.githubusercontent.com/mwilliamson/python-mammoth/master/NEWS "it is still strongly recommended to process untrusted documents in a separate thread with a timeout"
[^75]: https://raw.githubusercontent.com/python-openxml/python-docx/master/HISTORY.rst "Add #303: disallow XML entity expansion"
[^76]: https://docs.python.org/3/library/zipfile.html "apply to zipfile library that can cause disk volume exhaustion."
[^77]: https://www.gnu.org/licenses/agpl-3.0.html "if you modify the Program, your modified version must prominently offer all users interacting with it remotely through a computer network"
[^78]: https://pymupdf.readthedocs.io/en/latest/about.html "If you determine you cannot meet the requirements of the AGPL, please contact Artifex for more information regarding a commercial license."

Tools used: Exa and Brave for discovery; scrapling `get` and `bulk_get` for every cited page. Context7
and Tavily were available but not used, because the primary pages were fetched directly.

## Open questions

- **How good is each library on real CVs?** No published evidence exists. A 20–30 CV gold set covering
  two-column layouts, right-aligned dates, LaTeX accents, ligatures and link annotations, run through
  pypdf (plain and layout modes) and pypdfium2, would settle it.
- **Which pdfminer.six version fixed the pickle advisory?** Not checked.
- **Which mode does the pypdf benchmark run use?** The `library_code.py` function was not read, so it
  is unknown whether pypdf's 95% is plain or layout mode.
- **How many pypdf advisories are there, and of what kind?** Six pages exist, but only the first was
  read.
- **What is the CVE history of MuPDF and PDFium?** Not checked. It matters only if pypdfium2 or
  PyMuPDF is adopted.
- **Does docling extract link URLs, and can it run without models?** Not checked. It is blocked by
  PyTorch either way.
- **Does python-docx 1.2.0 work on Python 3.14?** It is pure Python plus lxml, so probably yes, but
  this is unverified.

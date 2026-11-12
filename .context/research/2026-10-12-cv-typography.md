# CV typography: embeddable faces, legibility evidence, and three house styles

Date: 2026-10-12. Scope: three sub-questions from the brief, nothing wider.

1. Which typefaces are (a) legally embeddable in PDFs we distribute, (b) available as a Debian package or a pinned upstream release, (c) complete for Azerbaijani (Ə ə U+018F/U+0259, Ğ ğ, İ ı, Ş ş, Ç ç, Ö ö, Ü ü), Turkish, German, French and Russian, with bold and italic?
2. What does published evidence say about serif vs sans, x-height/print size, line length and line spacing for body text at 10–11pt, read on screen?
3. Does any official university guidance name a typeface, size or spacing for CVs that the catalog (S-002..S-006, S-043, S-047, S-048) does not already record?

Already settled and not redone: S-002 (10–12pt, 11 target), S-003 (19–25mm margins), S-004 (standard faces, amended for DejaVu), S-005 (name 14–18pt bold), S-006 (bold caps/small-caps headers, thin rule), S-015, S-016; S-047 already records TUM (Times New Roman or Arial, 12pt, 1.5 spacing, 2cm margins) and Stanford GSE (12pt); S-048 records Harvard GSAS (10–12pt, Times New Roman suggested).

## Answer first

- **Best-evidenced faces for the full language set:** Charis SIL (serif) and Carlito (sans, Calibri-metric) are the strongest picks: both are SIL OFL, both are in Debian trixie `main`, both ship regular/italic/bold/bold-italic, and both cover Azerbaijani Latin and Russian. Charis's coverage is proven on its owner's own character-set page; Carlito's Azerbaijani coverage rests on a third-party coverage list (Fontsource), its Latin+Cyrillic on the upstream README.
- **Ruled out:** Caladea (Cambria-metric) and Gelasio (Georgia-metric). Gelasio's own README says it lacks Cyrillic; Caladea's upstream says its set is only 418 glyphs, and Google Fonts lists it with Latin subsets only. Neither should carry a Russian or Azerbaijani CV.
- **Legibility:** controlled studies find no reliable serif-vs-sans difference in reading speed when x-height and spacing are equalised, and a large 2022 study finds the best font differs per reader. So the choice between serif and sans is a house-style decision, not a legibility one. What does matter: print size above the critical size (x-height about 0.2° of visual angle), line length (55 characters per line read best in one screen study; WCAG AAA and GOV.UK cap at 80 and 75), and leading of at least 1.5 for web accessibility (but that is a web rule, and too loose for a two-page CV).
- **New university guidance (Q3):** only two items not already in the catalog, both from UK employment careers services, not admissions: Edinburgh prefers Arial 12pt, and Nottingham Trent asks for a sans serif no smaller than 10pt. No source found gives a CV line spacing other than TUM's 1.5 (already S-047).

## 1. Candidate typefaces

### How the list was built

The candidate list came from the brief. Searches run to test it and to find more: Exa (`web_search_exa`, "official font project character set documentation listing supported languages including Azerbaijani, Turkish and Cyrillic") surfaced SIL's Charis character-set page, the Noto docs specimens, Fontsource coverage pages and SIL Gentium; no new candidate beyond Gentium (another SIL Latin/Cyrillic face, not evaluated here). Debian availability was checked through `qa.debian.org/madison.php`, because `packages.debian.org` returned a bot-challenge page to every automated request.

**Source tiers used for coverage.** Primary: the font owner's own page (SIL charset page, Noto docs, upstream READMEs). Secondary: Fontsource "about" pages, which list language coverage computed from the font files; these are third-party, so claims resting only on them are marked "(Fontsource only)". Google Fonts' `METADATA.pb` files were read directly (they are the Google Fonts project's own records) but cannot be quoted in a footnote because their syntax is built from double quotes; they are linked inline instead.

### Licence: why embedding is legal

Every candidate below is under the SIL Open Font License 1.1. The OFL states that the fonts "can be bundled, embedded, redistributed and/or sold with any software"[^1], and that the licence's own terms do not extend to documents made with the fonts[^2]. Embedding a subset in every PDF we hand out is therefore permitted, which is exactly what the Microsoft fonts' EULA forbids (see the Dockerfile comment). Liberation additionally sets its embedding flag to permissive in the font itself[^3].

### Comparison table

| Face | Role | Licence | Debian trixie | Bold + italic | Latin incl. Azerbaijani Ə ə | Cyrillic (Russian) | Verdict |
|---|---|---|---|---|---|---|---|
| **Charis SIL** | serif | OFL[^4] | `fonts-sil-charis` 6.200-1, main[^5] | yes, 4 styles[^6] | **yes, primary**: Latin Extended-B and IPA Extensions both fully supported[^7] | yes, primary[^8] | **Recommended** |
| **Carlito** | sans, Calibri metrics | OFL[^1] | `fonts-crosextra-carlito` 20230309-2, main[^9] | yes, 4 styles[^10] | yes (Fontsource only)[^11] | yes, primary[^12] | **Recommended** |
| Noto Serif / Noto Sans | serif / sans | OFL (Unverified: no Noto licence page fetched) | `fonts-noto-core` 20201225-2[^13] | italic + weights, primary[^14] | Latin Extended-B and IPA Extensions blocks listed, primary[^15]; per-character Ə ə not stated by the owner | yes, primary[^16] | Good; see caveats |
| IBM Plex Serif / Plex Sans | serif / sans | OFL[^17] | `fonts-ibm-plex` 6.1.1-1, **contrib**[^18] | yes (14 Serif styles on Fontsource)[^19] | Serif: yes (Fontsource only)[^20]; Sans: Unverified | Sans: yes, primary[^17]; Serif: yes (Fontsource only)[^21] | Good, but contrib |
| Source Serif 4 + Source Sans 3 | serif + sans pair | OFL (Fontsource licence text)[^22] | Sans 3: `fonts-adobe-sourcesans3` 3.052, main[^23]; **Serif 4: not packaged** (madison returned nothing for `fonts-adobe-sourceserif4` or `fonts-adobe-sourceserifpro`) | Serif 4: italic axis[^24] | Serif 4: yes (Fontsource only)[^25]; Sans 3: Unverified | Serif: Greek and Cyrillic since 2.0, primary[^26] | Good; Serif 4 needs a pinned upstream release |
| Liberation Serif / Sans | Times / Arial metrics | OFL[^27] | `fonts-liberation` 2.1.5-3, already installed[^28] | yes (Unverified: no style list fetched) | **Unverified** | Unverified from an owner page (ChangeLog records Cyrillic fixes[^29]) | Keep for programme-stated "Times/Arial" rules; verify Ə ə before house use |
| EB Garamond | serif | OFL (upstream README) | `fonts-ebgaramond` 0.016+git20210310, main[^30] | Unverified for the Debian build | Unverified | Google Fonts lists Cyrillic subsets ([METADATA.pb](https://raw.githubusercontent.com/google/fonts/main/ofl/ebgaramond/METADATA.pb)) | Not recommended: Debian build provenance unclear, small x-height |
| Lato 2.015 | sans | OFL | `fonts-lato` 2.015-1, main[^31] | yes (Unverified) | Unverified (owner claims "100+ Latin-based languages"[^32]) | yes per owner[^32] | Possible; Ə ə unverified |
| Caladea | serif, Cambria metrics | OFL | `fonts-crosextra-caladea` 20200211-2, main[^33] | yes, 4 styles[^34] | **No evidence**; glyph set is 418 glyphs[^34] | **No**: Google Fonts lists only latin, latin-ext, menu ([METADATA.pb](https://raw.githubusercontent.com/google/fonts/main/ofl/caladea/METADATA.pb)) | **Excluded** |
| Gelasio | serif, Georgia metrics | OFL | not in Debian (madison returned nothing) | yes | lists "North Azerbaijani" via Hyperglot (README) | **No**: lacks Greek and Cyrillic per its own README[^35] | **Excluded** |

### Caveats that change the choice

- **Ə ə is the deciding glyph.** Ğ ğ İ ı Ş ş sit in Latin Extended-A and are in almost every Latin-extended font; Ə (U+018F, Latin Extended-B) and ə (U+0259, IPA Extensions) are not. Only Charis has primary, character-level proof (both blocks "fully supported as of Unicode 15.0"[^7]). For every other face, confirm inside the built image before an owner review, e.g. `fc-list ':charset=18f 259 11e 11f 130 131 15e 15f' family style` (suggested command, not run here: this agent has no shell). A face that lacks Ə falls back to another font for that one letter, silently, in the middle of the student's name.
- **IBM Plex is in `contrib`.** The Debian `python:3.14-slim` image's apt sources list only `main` by default (Unverified: the image's sources file was not read), so Plex needs an extra apt component or a pinned upstream download.
- **Source Serif 4 is not packaged** in any Debian suite madison knows. It would be a pinned upstream release (OFL, Adobe GitHub), with a checksum in the Dockerfile. Prefer the static TTF/OTF files over the variable font: whether WeasyPrint embeds a variable font's instances cleanly was not checked (Unverified).
- **`fonts-noto-core` is the 2020-12-25 snapshot** in trixie[^13], and installs every Noto core script, not just Latin/Cyrillic (package size Unverified). Pinning two upstream Noto families would be smaller.
- **Carlito and Caladea map onto Calibri and Cambria** the way Liberation maps onto Times and Arial (Unverified that Debian's fontconfig ships those aliases; it ships them for Liberation per the Dockerfile comment). Carlito is worth installing for that reason alone: a programme rule saying "Calibri 11pt" would then render with the right metrics, which matters for the BINDING `max_pages` constraint the Dockerfile already describes.

## 2. Legibility evidence

### Serif vs sans: no reliable difference once size is equalised

- Arditi & Cho (2005, Vision Research) built fonts that differ only in serifs and found "our data exhibited no difference in legibility between typefaces that differ only in the presence or absence of serifs"[^36]; reading speed showed no effect either[^37].
- A 2022 study (Ophthalmic and Physiological Optics) equalised x-height, line width and spacing and concluded "The legibility of Helvetica and Times New Roman is similar when investigated under equivalent conditions."[^38]
- Wallace et al. (2022, ACM TOCHI), a crowdsourced on-screen study, found reading speed rose by 35% between a reader's fastest and slowest font[^39], and that "High WPM variability across fonts suggests that one font does not fit all."[^40]
- Lead not verified: Millhagen et al. (2025, Behaviour & Information Technology) report no main effect of Verdana vs Times New Roman on comprehension, load or reading time, at 11pt and 1.5 spacing, on screen and paper (Unverified: read from a search excerpt only; tandfonline not fetched).

**Consequence:** serif vs sans should be chosen on house look and on the glyph coverage above. No study found supports "sans for screen" strongly enough to override that.

### Print size and x-height: the variable that actually limits reading

Legge & Bigelow (2011, Journal of Vision) review the vision-science data: maximum reading speed holds over "a factor of 10 in angular print size (x-height) from approximately 0.2° to 2°"[^41], which at a 40 cm reading distance means x-heights of 1.4 mm to 14 mm[^42]. Below about 0.2° reading speed drops sharply.

My arithmetic, not a sourced figure: an 11pt face with an x-height of about half the body gives roughly 1.9 mm at 100% zoom. Read at 50–60 cm from a laptop, that is about 0.19–0.22°, right at the critical size; at "fit page" zoom (often below 100%) it falls under it. Two consequences for the house styles: do not go below 10.5pt body, and between two faces at the same point size prefer the one with the larger x-height (point size alone says nothing about letter size, which is why the 2022 study had to equalise x-heights by measurement[^38]).

### Line length

- Dyson & Haselgrove (2001, Int. J. Human-Computer Studies), reading from screen: "A medium line length (55 characters per line) appears to support effective reading at normal and fast speeds."[^43]
- WCAG 2.2 SC 1.4.8 (Level AAA) asks that "Width is no more than 80 characters or glyphs (40 if CJK)."[^44]
- GOV.UK's layout guidance: "This would usually mean no more than 75 characters per line."[^45]

My arithmetic: A4 with 20 mm margins leaves 170 mm; at 11pt, an average character is about 2 mm wide, so a full-width CV line holds about 85 characters. That is over the 75/80 guidance. Most CV lines are short bullets, so this bites only on summary or thesis prose. A wider margin (still inside S-003's 25 mm) or 11pt instead of 10pt both pull the measure towards 75.

### Line spacing (leading)

- WCAG 2.2 SC 1.4.8 (AAA): "Line spacing (leading) is at least space-and-a-half within paragraphs, and paragraph spacing is at least 1.5 times larger than the line spacing."[^46]
- WCAG 2.2 SC 1.4.12 (AA) is about user overrides, not authoring: content must survive "Line height (line spacing) to at least 1.5 times the font size"[^47], and the criterion itself notes "Content is not required to use these text spacing values."[^48]
- No peer-reviewed study fetched here measures leading for on-screen CV-length documents. "No evidence" is the honest answer for a value between 1.2 and 1.5. The current base template uses 1.3 (per S-047's note); TUM requires 1.5 for its own applicants (S-047).

**Consequence:** 1.5 is a web-accessibility norm and TUM's rule, not a reading-speed finding. For a two-page CV, 1.25–1.4 is the defensible range, and each value must be checked against the page count.

## 3. University guidance not already in the catalog

Searches: Exa ("university careers service CV guide specifying line spacing … and font size") and Brave (`CV guide "line spacing" font size careers site:ac.uk`).

| Source | What it says | Audience | New? |
|---|---|---|---|
| University of Edinburgh Careers | "For the UK a two-page CV is standard (ideally using Arial 12pt font)."[^49] | UK employment | New: a named face and 12pt preference |
| Nottingham Trent University | "Professional font (no smaller than size 10, sans serif font)"[^50] | UK employment | New: a sans serif preference |
| University of St Andrews Careers | 10–12pt, "such as Arial, Calibri or Times New Roman" | UK employment | **Unverified**: the text sits in a script-loaded accordion that the fetch did not return; seen only in an Exa excerpt |
| Cambridge Careers booklet | "Don't go below 10pt"; choose one readable font | UK employment | **Unverified** here (PDF not re-fetched); the booklet is already S-043's source |
| York St John checklist | "equiv. to Arial 10-12; avoiding Times New …" | UK employment | **Unverified** (Brave snippet only, PDF) |

None of these is an admissions office, so by S-039's audience rule they rank below S-047's admissions pages. None gives a line spacing. The only official CV line-spacing value found anywhere remains TUM's 1.5 (S-047).

## Three house styles to render side by side

All three stay inside S-002 (10–12pt), S-003 (19–25 mm), S-005 (name 14–18pt bold), S-006 (bold caps or small caps headings, optional thin rule), S-015, S-016. Each one changes text metrics, so each must be rendered and its page count compared against the current DejaVu Sans output before anything else (S-004's warning).

| | A. Charis classic | B. Calibri-metric sans | C. Source pair |
|---|---|---|---|
| Body | Charis SIL 11pt | Carlito 11pt | Source Serif 4 (text optical size) 10.5pt |
| Leading | 1.3 | 1.25 | 1.35 |
| Name | Charis Bold 16pt | Carlito Bold 18pt | Source Sans 3 Semibold 16pt |
| Section headings | Charis Bold small caps 11pt, +0.05em tracking, 0.5pt rule below | Carlito Bold caps 10.5pt, +0.08em tracking, 0.5pt rule | Source Sans 3 Semibold caps 10pt, +0.08em tracking, no rule |
| Entry header (role) | Charis Bold 11pt | Carlito Bold 11pt | Source Sans 3 Semibold 10.5pt |
| Space above a section / after an entry | 10pt / 4pt | 9pt / 3pt | 11pt / 4pt |
| Margins | 20 mm | 20 mm | 22 mm (shortens the measure towards 75 characters) |
| Install | `fonts-sil-charis` (main) | `fonts-crosextra-carlito` (main) | `fonts-adobe-sourcesans3` (main) + pinned Source Serif 4 static release |
| Coverage proof | primary, character-level | README (Latin+Cyrillic) + Fontsource (Azerbaijani) | Fontsource (Serif 4); Sans 3 Ə ə Unverified |
| Catalog fit | not on S-004's list; meets its amended intent (standard, non-decorative) | Calibri is on S-004's list; Carlito keeps its metrics | not on S-004's list; meets its amended intent |

Fallback for C if a pinned upstream download is unwanted: Noto Serif body + Noto Sans headings from `fonts-noto-core` (main). Render the current DejaVu Sans CV beside the three as the control.

## Open questions

- **Ə ə in Carlito, Noto, Source Sans 3, Liberation and Lato** is not confirmed by an owner page. Run the `fc-list ':charset=…'` check (or render a test line) inside the built image before the owner review.
- **WeasyPrint and variable fonts:** whether static or variable Source Serif 4 embeds cleanly and keeps optical sizes was not checked.
- **Debian slim apt components:** whether `python:3.14-slim` enables only `main` (which would block `fonts-ibm-plex` from `contrib`) was not read from the image.
- **Fontconfig aliases** for Calibri→Carlito and Cambria→Caladea in Debian were not confirmed.
- **Leading 1.2–1.5 for on-screen CV-length text:** no primary study found; treat the house values as a design choice to be tested on page count, not as evidence-backed.
- **x-height ratios** of the three faces were not measured from the font files; the per-face legibility ranking rests on that number and should be read off the fonts (`OS/2.sxHeight / unitsPerEm`) before the owner chooses.

## Sources

Tools available: Exa, Brave, scrapling (`get`, `fetch`). Not used: Context7 (not a library question), Tavily (not needed). `packages.debian.org` and `pmc.ncbi.nlm.nih.gov` refused automated reads; `qa.debian.org/madison.php` and the Europe PMC REST API were used instead. `jov.arvojournals.org` returned 403.

[^1]: https://fontsource.org/fonts/carlito/about "The fonts, including any derivative works, can be bundled, embedded, redistributed and/or sold with any software"
[^2]: https://fontsource.org/fonts/carlito/about "requirement for fonts to remain under this license does not apply to any document created using the fonts or their derivatives"
[^3]: https://raw.githubusercontent.com/liberationfonts/liberation-fonts/main/ChangeLog "set fsType bit to 0, Installable Embedding is allowed."
[^4]: https://software.sil.org/charis/charset/ "This font software is free to use, modify and redistribute according to the terms of the SIL Open Font License"
[^5]: https://qa.debian.org/madison.php?package=fonts-sil-charis&text=on "fonts-sil-charis | 6.200-1 | trixie | source, all"
[^6]: https://fontsource.org/fonts/charis-sil/about "CharisSIL-BoldItalic.ttf Static · Italic · Bold 700"
[^7]: https://software.sil.org/charis/charset/ "*This block is fully supported as of Unicode 15.0."
[^8]: https://software.sil.org/charis/charset/ "Cyrillic U+0400..U+045F, U+0462..U+0463, U+0472..U+0475, U+048A..U+04FF"
[^9]: https://qa.debian.org/madison.php?package=fonts-crosextra-carlito&text=on&s=trixie "fonts-crosextra-carlito | 20230309-2 | trixie | source, all"
[^10]: https://fontsource.org/fonts/carlito/about "Carlito-BoldItalic.ttf Static · Italic · Bold 700"
[^11]: https://fontsource.org/fonts/carlito/about "Azerbaijani azərbaycan (latın) · Latin"
[^12]: https://raw.githubusercontent.com/googlefonts/carlito/main/README.md "It comes with Latin and Cyrillic character sets."
[^13]: https://qa.debian.org/madison.php?package=fonts-noto-core&text=on "fonts-noto-core | 20201225-2 | trixie | all"
[^14]: https://notofonts.github.io/noto-docs/specimen/NotoSerif/ "Noto Serif has italic styles, multiple weights and widths"
[^15]: https://notofonts.github.io/noto-docs/specimen/NotoSerif/ "Combining Diacritical Marks, IPA Extensions, Cyrillic Extended-B"
[^16]: https://notofonts.github.io/noto-docs/specimen/NotoSerif/ "Latin, Cyrillic and Greek scripts"
[^17]: https://raw.githubusercontent.com/IBM/plex/master/README.md "IBM Plex Sans supports extended Latin, Arabic, Chinese (Traditional), Cyrillic"
[^18]: https://qa.debian.org/madison.php?package=fonts-ibm-plex&text=on&s=trixie "fonts-ibm-plex | 6.1.1-1 | trixie/contrib | source, all"
[^19]: https://fontsource.org/fonts/ibm-plex-serif/about "IBMPlexSerif-BoldItalic.ttf Static · Italic · Bold 700"
[^20]: https://fontsource.org/fonts/ibm-plex-serif/about "Azerbaijani azərbaycan (latın) · Latin"
[^21]: https://fontsource.org/fonts/ibm-plex-serif/about "Russian Русский · Cyrillic"
[^22]: https://fontsource.org/fonts/source-serif-4/about "This Font Software is licensed under the SIL Open Font License, Version 1.1."
[^23]: https://qa.debian.org/madison.php?package=fonts-adobe-sourcesans3&text=on "fonts-adobe-sourcesans3 | 3.052+dfsg-2 | trixie | source, all"
[^24]: https://fontsource.org/fonts/source-serif-4/about "Adjust the style from roman to italic."
[^25]: https://fontsource.org/fonts/source-serif-4/about "Azerbaijani azərbaycan (latın) · Latin"
[^26]: https://raw.githubusercontent.com/adobe-fonts/source-serif/release/README.md "Source Serif 2.0: Language support extended, addition of Greek & Cyrillic alphabets"
[^27]: https://github.com/liberationfonts/liberation-fonts "This Font Software is licensed under the SIL Open Font License"
[^28]: https://qa.debian.org/madison.php?package=fonts-liberation&text=on&s=trixie "fonts-liberation | 1:2.1.5-3 | trixie | source, all"
[^29]: https://raw.githubusercontent.com/liberationfonts/liberation-fonts/main/ChangeLog "Improving lowercase Cyrillic glyps localized for Macedonian and Serbian"
[^30]: https://qa.debian.org/madison.php?package=fonts-ebgaramond&text=on&s=trixie "fonts-ebgaramond | 0.016+git20210310.42d4f9f2-1 | trixie | source, all"
[^31]: https://qa.debian.org/madison.php?package=fonts-lato&text=on&s=trixie "fonts-lato | 2.015-1 | trixie | source, all"
[^32]: https://www.latofonts.com/lato-free-fonts/ "The family supports 100+ Latin-based languages, 50+ Cyrillic-based languages, and Greek."
[^33]: https://qa.debian.org/madison.php?package=fonts-crosextra-caladea&text=on&s=trixie "fonts-crosextra-caladea | 20200211-2 | trixie | source, all"
[^34]: https://raw.githubusercontent.com/huertatipografica/Caladea/master/README.md "Character set expanded to WGL (418 glyphs)"
[^35]: https://raw.githubusercontent.com/SorkinType/Gelasio/main/README.md "glyphs not present in Gelasio such as support for Greek and Cyrillic"
[^36]: https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=PMCID:PMC4612630&resultType=core&format=json "our data exhibited no difference in legibility between typefaces that differ only in the presence or absence of serifs"
[^37]: https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=PMCID:PMC4612630&resultType=core&format=json "RSVP and continuous reading speeds showed no effect of serifs."
[^38]: https://link.springer.com/article/10.1111/opo.13039 "The legibility of Helvetica and Times New Roman is similar when investigated under equivalent conditions."
[^39]: https://dl.acm.org/doi/fullHtml/10.1145/3502222 "increased by 35% when comparing fastest and slowest fonts without affecting reading comprehension"
[^40]: https://dl.acm.org/doi/fullHtml/10.1145/3502222 "High WPM variability across fonts suggests that one font does not fit all."
[^41]: https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=PMCID:PMC3428264&resultType=core&format=json "The fluent range extends over a factor of 10 in angular print size (x-height) from approximately 0.2° to 2°."
[^42]: https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=PMCID:PMC3428264&resultType=core&format=json "the corresponding physical x-heights are 1.4 mm (4 points) and 14 mm (40 points)"
[^43]: https://www.sciencedirect.com/science/article/abs/pii/S1071581901904586 "A medium line length (55 characters per line) appears to support effective reading at normal and fast speeds."
[^44]: https://www.w3.org/WAI/WCAG22/Understanding/visual-presentation.html "Width is no more than 80 characters or glyphs (40 if CJK)."
[^45]: https://design-system.service.gov.uk/styles/layout/ "This would usually mean no more than 75 characters per line."
[^46]: https://www.w3.org/WAI/WCAG22/Understanding/visual-presentation.html "Line spacing (leading) is at least space-and-a-half within paragraphs, and paragraph spacing is at least 1.5 times larger than the line spacing."
[^47]: https://www.w3.org/WAI/WCAG22/Understanding/text-spacing.html "Line height (line spacing) to at least 1.5 times the font size"
[^48]: https://www.w3.org/WAI/WCAG22/Understanding/text-spacing.html "Content is not required to use these text spacing values."
[^49]: https://careers.ed.ac.uk/cvs-and-applications/building-your-cv "For the UK a two-page CV is standard (ideally using Arial 12pt font)."
[^50]: https://www.ntu.ac.uk/studenthub/student-help-advice-and-services/employability/job-application-support/cv-guidelines-for-full-time-roles "Professional font (no smaller than size 10, sans serif font)"

# Confirming named staff across scripts, and the cost of module handbooks

Date: 2026-10-14. For: spec `2026-10-14-letter-story-and-research-fit-amendment-design.md` §6.1
(letter-shape worktree). Builds on `docs/research/2026-10-14-letter-story/2026-10-14-professor-and-paper-discovery.md`
and does not repeat it.

## Scope

- **Q1a** What OpenAlex's author object holds for non-Latin names (`display_name_alternatives`).
- **Q1b** Whether ORCID exposes other or native names, how often they are filled, and whether we may use the API.
- **Q1c** Python transliteration libraries for Russian, Japanese, Korean and Chinese, with their licences.
- **Q1d** Whether real staff pages (MSU, HSE, Tokyo, SNU) have an English version with romanised names.
- **Q2a** Page counts of real master's module handbooks.
- **Q2b** Firecrawl PDF billing and page caps.
- **Q2c** Whether per-module HTML pages exist that name the responsible person.

Tools used: Exa, Brave, scrapling `get`/`bulk_get`, and WebFetch (only to download PDFs, whose pages were
then read locally). Every quote below was copied from a scrapling fetch. The library candidates in Q1c came
from two Exa searches ("Python library that transliterates Russian Cyrillic…", "Python library to romanize
Japanese kanji names… Korean… Chinese…") and one Brave search (`site:pypi.org` romanization Korean/pinyin/Hepburn).
Tavily and Context7 were available but not used.

## The answer, in short

**Q1: confirm the name on the department's English staff page first. Where only a native-script page exists,
match it against OpenAlex's own native-script name variants. Use transliteration only to propose candidates,
never as the confirmation. Leave ORCID out.**

**Q2: read per-module HTML pages where the university publishes them (TUMonline, KIT WiWi): one credit each,
and they give the responsible person with an email address. Where only a PDF handbook exists, fetch it once
unparsed (`parsers: []`, 1 credit flat) and parse it locally with the repo's existing pypdf. Never pay Firecrawl's
per-page parse: one KIT handbook is 1,172 pages.**

## Q1 — Cross-script name matching

### Q1a OpenAlex `display_name_alternatives`

- The field holds the name strings printed on the works linked to the profile: "The alternate names are the
  name variants printed on the linked works."[^1] It is a list of "Other name strings seen for this author,
  deduplicated"[^2]. So a native-script form appears only when the author has published under it.
- **Measured 2026-10-14**: a random sample of 10 authors per country (`works_count > 20`, `sample=10&seed=7`).
  The column shows how many had at least one native-script string in `display_name_alternatives`:

  | Country | native-script form present | what was there |
  |---|---|---|
  | Russia | 7 / 10 | full Cyrillic names, e.g. "Карпачева Ирина Анатольевна" |
  | Kazakhstan | 7 / 10 | Cyrillic (Russian and Kazakh letters) |
  | Greece | 3 / 10 | Greek |
  | Japan | 3 / 10 | 2 kanji, 1 katakana only |
  | China | 1 / 10 | one hanzi name |
  | South Korea | 0 / 10 | no Hangul at all |

- **Native-script works can sit on a separate profile.** Searching OpenAlex for 山中伸弥 returned three small
  kanji-only profiles (1, 3 and 5 works). The main "Shinya Yamanaka" profile (412 works) has no kanji. A second
  "Shinya Yamanaka" profile (95 works) carries only katakana ("ヤマナカ, シンヤ"). Matching on native script can
  therefore land on a split-off fragment rather than the researcher's main profile.
- **Mixed-script lookalike letters occur.** Kazakhstan samples include "Аinur Zhumadillayeva" with a Cyrillic "А"
  in `display_name`, and "Ruslan МЕKHTIYEV". An exact string match fails on these unless confusable letters are
  folded first.
- **Over-merged profiles exist.** The Korean "In Sung Song" profile lists "Joo Sung Kim" among its variants.
- ORCID on profiles: "Null is the common case: only about one profile in ten has one."[^3]

### Q1b ORCID other-names

- **Terms rule it out for Elmify.** The ORCID Public API licence is non-commercial: "you may not make use of the
  public APIs in connection with any revenue-generating product or service"[^4]. Commercial use needs ORCID
  membership. Whether ORCID's annual public data file has different terms was not checked (**Unverified**).
- **It is rarely filled.** Measured 2026-10-14 through the anonymous search endpoint (`q=other-names:*`):
  874,539 of 30,079,990 records (2.9%) have any other name. By affiliation: University of Tokyo 1,343 / 20,994
  (6.4%); Lomonosov Moscow State University 1,252 / 10,869 (11.5%); Seoul National University 1,264 / 27,128 (4.7%).
- **Even when filled, it is mostly not native script.** In the first 10 records with other names: Tokyo, 4 were
  kanji (e.g. "坂井 晃介"); MSU, 1 was Cyrillic; SNU, 1 was Hangul. The rest were romanised variants such as
  "Kwang-Hoon Lee".
- ORCID's documentation describes `/other-names` as "Other names by which the researcher is know[n]". This was
  seen in an Exa result only and not re-fetched (**Unverified** as a quote).

### Q1c Transliteration libraries (licences from PyPI classifiers)

| Library | Scripts / schemes | Licence |
|---|---|---|
| iuliia | Russian, 20 schemes incl. GOST 7.79-2000 (ISO 9), GOST R 7.0.34-2014, BGN/PCGN, ICAO DOC 9303 (README via Exa; schemes **Unverified**) | MIT[^5] |
| pypinyin | Chinese → pinyin | MIT[^6] |
| cutlet | Japanese → Hepburn, uses the UniDic dictionary for kanji readings | MIT[^7] |
| pykakasi | Japanese → Hepburn/Kunrei/Passport | GPLv3+[^8] |
| korean-romanizer | Korean Revised Romanization | GPLv3+[^9] |
| koroman | Korean Revised Romanization with pronunciation rules | MIT[^10] |
| anyascii | every script, character by character | ISC[^11] |
| Unidecode | every script, character by character | GPLv2+[^12] |

- The licences of cutlet's dependencies (fugashi, the UniDic package) were not checked (**Unverified**).
- Transliteration cannot confirm a person, for two reasons:
  - **Korean given names are spelled personally, not by Revised Romanization.** SNU's English page lists
    "Kwangkeun Yi"[^13] and "Chung-Kil Hur"[^14]; strict RR would give "I" and "Heo". The `romanizer` package's
    README (Exa only; **Unverified**) reports 26% agreement between RR output and Wikidata spellings.
  - **A kanji name has several possible readings.** A dictionary returns the most common one, which may not be
    the person's.
- Russian goes better, because people use a few standard schemes. HSE's English page mixes them, though:
  "Sergey Vyacheslavovich Veselov", "Tatiana Vetrova"[^15].

### Q1d Real staff pages

| University | English page with romanised names? |
|---|---|
| University of Tokyo, Dept. of Computer Science | Yes: "Professor Naoki Kobayashi Programming languages, program verification"[^16] |
| Seoul National University, CSE | Yes, with each person's own spelling and email[^13] |
| HSE (Graduate School of Business, Marketing) | Yes[^15] |
| MSU, Faculty CMC | **No.** The `/en/` URL still lists names in Cyrillic: "Головизнин Василий Михайлович Профессор кафедры"[^17] |

Both Tokyo and SNU pages carry email addresses (SNU) or are paired with PDFs that print both scripts and an
email. An email's local part (e.g. `jaejin@snu.ac.kr`) is a second, cheap signal for matching.

### Q1 recommendation

1. Find the department's English staff page and match against OpenAlex `display_name` and
   `display_name_alternatives`. Normalise both sides first: NFKC, fold confusable letters, case, hyphens, name
   order and initials.
2. If only a native-script page exists (as at MSU CMC), match the native string directly against
   `display_name_alternatives`. This works for most Russian/Kazakh authors (7/10) and few Japanese/Chinese/Korean
   ones.
3. Otherwise, use MIT/ISC libraries to propose candidates: iuliia (try every scheme), pypinyin, cutlet, koroman.
   Confirm only with a second signal: an email local part, an ORCID or OpenAlex link on the page, or a topic
   overlap.
4. Do not use ORCID: the public API is non-commercial, and fewer than 12% of records have other names.
5. Avoid the GPL libraries (pykakasi, korean-romanizer, Unidecode) if this code could ever ship to clients, for
   example in the browser extension.

## Q2 — Module handbooks

### Q2a Page counts (measured 2026-10-14: PDF downloaded, pages read locally)

| Handbook | Pages | Responsible-person field |
|---|---|---|
| KIT, Informatik Master (SPO 2023), as of 15.04.2026 (`informatik.kit.edu/downloads/stud/88-079-H-2023_v1_2026-04-15_de.pdf`) | **1,172**; the table of contents alone runs to page 19 | "Verantwortung: Prof. Dr. Nadja Klein" (p. 60) |
| TUM, M.Sc. Information Engineering (Heilbronn), SoSe 2026 (`cit.tum.de/.../MIE_SoSe2026_safe.pdf`) | **556** (page footer "12 von 556"; the downloaded copy held only 148 pages, so it was truncated); AES-encrypted | "Modulverantwortliche(r): Matthes, Florian", plus a separate "Dozent(in)" list with "[L]" marking the lead |
| RWTH, Grundlagen der Informatik (MTIK), Master 2 Fächer, 2023 (`mtik.rwth-aachen.de/.../MHB_Master_2_Faecher_...pdf`) | **123** ("Seite 5 von 123") | "Modulverantwortung: Universitätsprofessor Dr. rer. nat. Torsten Wolfgang Kuhlen" |

- RWTH's main CS master's handbook is served through RWTHonline[^18] and was not downloaded (**Unverified**).
- No UK or Dutch handbook was measured (**Unverified**). The UK equivalent is UCL's per-module HTML catalogue,
  already covered in the earlier note.

### Q2b Firecrawl PDF billing

- Parse page: "PDF parsing is billed at 1 credit per page"[^19].
- Billing page: PDF parsing adds "+1 credit / PDF page"[^20], on top of "the base cost per page"[^21].
- **The two pages disagree** on whether the base credit is added; Firecrawl owns both. The repo's `firecrawl.py`
  counts `credits = page_count` (CLAUDE.md). Check it against the first real invoice.
- **Cap:** `maxPages` will "Cap the number of pages to parse."[^22]. It counts from the first page. No page-range
  option is documented on the parse page (absence, not a quoted fact).
- **Cheapest route:** passing `parsers: []` "skips parsing entirely and returns the PDF as base64"[^23] for
  1 credit flat.
- **Price:** "The credits in an increment depend on your plan."[^24] The same page's table gives 1,000 credits
  per 5 USD (Hobby), 2,000 (Standard) and 5,000 (Scale). On Standard, a parsed read of the KIT handbook costs
  about 1,172 credits ≈ $2.93; a base64 read costs about $0.0025.

### Q2c Per-module HTML pages

- **TUM (TUMonline): yes, plain HTML, and it gives an email address.**
  - Module page: "Responsible for the module: Rinderle-Ma, Stefanie; Prof. Dr. rer. nat.:"[^25].
  - Another module: "Groh, Georg; Prof. Dr. rer. nat. habil.: groh@in.tum.de"[^26]. That page also records a
    change of responsible person, "Übertrag der Modulverantwortlichkeit von Prof. Klinker auf Prof. Groh ab
    WiSe25/26"[^26]: a handbook printed before 2025/26 would name the wrong person.
  - The programme's curriculum tree is plain HTML and lists module IDs, e.g. "[IN2081] Patterns in Software
    Engineering"[^27]. So programme → module IDs → module page works without the PDF.
- **KIT: partly.**
  - The WiWi faculty's module pages are plain HTML: "Software-Systeme [M-INFO-101201]" with "Verantwortung
    Prof. Dr. Ralf Reussner"[^28].
  - `campus.kit.edu` module views redirected to `cascampus.studium.kit.edu` and returned HTTP 503 to this run
    (**Unverified**).
- **RWTH:** module handbooks are "Alle Modulhandbücher der RWTH über RWTHonline"[^18]. Whether RWTHonline has
  per-module HTML that a plain fetch can read was not tested (**Unverified**).

### Q2 recommendation

1. For TUM (and probably other CAMPUSonline universities), walk the curriculum tree to the module IDs, then read
   each module page at 1 credit and take "Responsible for the module" and the email.
2. For PDF-only handbooks (KIT Informatik, RWTH), fetch once with `parsers: []`, parse locally with
   `apps/research/pdf.py`, find the module through the table of contents, and cache by the handbook's date.
3. Never use the per-page parse on a handbook.

## Measurement URLs (2026-10-14)

- OpenAlex: `https://api.openalex.org/authors?filter=last_known_institutions.country_code:{RU|JP|KR|CN|GR|KZ},works_count:>20&sample=10&seed=7&select=display_name,display_name_alternatives&per_page=10`;
  `https://api.openalex.org/authors?search=山中伸弥&select=...`; `filter=display_name.search:Yamanaka Shinya`.
- ORCID (anonymous, JSON): `https://pub.orcid.org/v3.0/search/?q=*:*&rows=1`, `q=other-names:*`,
  `q=affiliation-org-name:"University of Tokyo"[ AND other-names:*]` (same for Lomonosov Moscow State University and
  Seoul National University); `expanded-search` with the same queries, `rows=10`.

## Sources

[^1]: https://help.openalex.org/data/authors.md "The alternate names are the name variants printed on the linked works."
[^2]: https://help.openalex.org/data/authors.md "Other name strings seen for this author, deduplicated"
[^3]: https://help.openalex.org/data/authors.md "Null is the common case: only about one profile in ten has one."
[^4]: https://info.orcid.org/public-client-terms-of-service/ "you may not make use of the public APIs in connection with any revenue-generating product or service"
[^5]: https://pypi.org/project/iuliia/ "OSI Approved :: MIT License"
[^6]: https://pypi.org/project/pypinyin/ "OSI Approved :: MIT License"
[^7]: https://pypi.org/project/cutlet/ "OSI Approved :: MIT License"
[^8]: https://pypi.org/project/pykakasi/ "GNU General Public License v3 or later (GPLv3+)"
[^9]: https://pypi.org/project/korean-romanizer/ "GNU General Public License v3 or later (GPLv3+)"
[^10]: https://pypi.org/project/koroman/ "OSI Approved :: MIT License"
[^11]: https://pypi.org/project/anyascii/ "OSI Approved :: ISC License (ISCL)"
[^12]: https://pypi.org/project/Unidecode/ "GNU General Public License v2 or later (GPLv2+)"
[^13]: https://cse.snu.ac.kr/en/people/faculty "Kwangkeun Yi Professor Programming Research Lab"
[^14]: https://cse.snu.ac.kr/en/people/faculty "Chung-Kil Hur Professor Software Foundations Lab"
[^15]: https://gsb.hse.ru/en/marketing/persons-category "Sergey Vyacheslavovich Veselov Tatiana Vetrova"
[^16]: https://www.is.s.u-tokyo.ac.jp/en/lab-members/ "Professor Naoki Kobayashi Programming languages, program verification"
[^17]: https://cs.msu.ru/en/persons/all/%D0%B3 "Головизнин Василий Михайлович Профессор кафедры"
[^18]: https://sc.informatik.rwth-aachen.de/de/pos-und-modulhandbuecher/ "Alle Modulhandbücher der RWTH über RWTHonline"
[^19]: https://docs.firecrawl.dev/features/parse "PDF parsing is billed at 1 credit per page"
[^20]: https://docs.firecrawl.dev/billing.md "+1 credit / PDF page"
[^21]: https://docs.firecrawl.dev/billing.md "Certain scrape options add credits on top of the base cost per page"
[^22]: https://docs.firecrawl.dev/features/parse.md "Cap the number of pages to parse."
[^23]: https://docs.firecrawl.dev/features/parse.md "skips parsing entirely and returns the PDF as base64"
[^24]: https://docs.firecrawl.dev/billing.md "The credits in an increment depend on your plan."
[^25]: https://campus.tum.de/tumonline/wbModHBReport.wbGenHTMLForBeschr?pKnotenNr=457036&pLangCode=DE&pSemesterNr=206 "Responsible for the module: Rinderle-Ma, Stefanie; Prof. Dr. rer. nat.:"
[^26]: https://campus.tum.de/tumonline/WBMODHB.wbShowMHBReadOnly?pKnotenNr=654521 "Übertrag der Modulverantwortlichkeit von Prof. Klinker auf Prof. Groh ab WiSe25/26"
[^27]: https://campus.tum.de/tumonline/wbstpcs.showSpoTree?pStpKnotenNr=3634524&pStpStpNr=5217 "[IN2081] Patterns in Software Engineering"
[^28]: https://www.wiwi.kit.edu/mhbDetails.php?id=DDD1BE0E-015A-1D4F-B917-8F311D9C671B&lang=de&productid=C0083ED1-BEE9-3D46-83C3-30B66B28CE1D&type=module "Verantwortung Prof. Dr. Ralf Reussner"

## Open questions

- **Firecrawl PDF billing:** is it 1 credit per page, or 1 + 1 per page? The two docs pages disagree; settle it
  from a real invoice.
- **Firecrawl page ranges:** is there any option beyond `maxPages`? None was found.
- **ORCID public data file:** its licence was not read.
- **Licences of cutlet's dependencies** (fugashi, UniDic): not checked.
- **RWTH:** the main M.Sc. Informatik handbook's page count (RWTHonline download) and whether RWTHonline has
  readable per-module HTML were not tested.
- **KIT `campus.kit.edu`:** returned 503, so whether KIT Informatik modules have readable per-module HTML is open.
- **UK and Dutch handbooks:** no page counts measured; TU Delft's study guide was found but not fetched.
- **OpenAlex samples:** 10 authors per country is indicative only. A larger sample is needed before quoting rates.
- **Korean RR vs personal spelling:** the 26% agreement figure comes from a third-party README and was not
  verified.

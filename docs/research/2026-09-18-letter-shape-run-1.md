# Letter-shape research — run 1 (direct read), 2026-09-18

Brief: `2026-09-18-letter-shape-research-prompt.md`. Output: `letter-shape-rules.csv` (90 `M-` rows)
and `letter-shape-country-map.csv` (≈50 rows). This is the **primary pass**; the independent
second engine (Gemini/Claude Deep Research on the whole brief) has **not been run**, so nothing here
is reconciled yet. Treat every row as one read, not two.

## How it was run, and what failed

- **GPT Researcher (gptr-mcp) was unusable.** Seven `deep_research` runs: two returned in under two
  minutes with every source scraped to zero bytes and off-target hits (US college homepages,
  coaching blogs — the brief's excluded class); five hung past the 30-minute silence limit and were
  killed. `quick_search` for DAAD's own advice sheet returned zero results. Server log showed
  SerpApi errors on every call; Tavily's monthly credits were already exhausted that morning (HTTP 432
  in another session). The owner supplied fresh Tavily/Exa/SerpApi keys mid-run; installing them into
  the server's key file was left to the owner (the assistant is blocked from credential files).
  Scrapling is **not** available as a gptr scraper in the pinned build (scrapers: bs, browser,
  firecrawl, pymupdf, tavily_extract).
- **What worked:** Claude Code's built-in web search + page reader (≈40 searches, ≈70 page reads),
  `curl` + `pdftotext` for the ~20 PDFs the reader could not decode, and the Scrapling MCP
  (`stealthy_fetch`) for pages that returned 403 to the plain reader (UCL, Otago, Rackham).
- **Blocked or dead pages worth retrying:** Göttingen `en/648936.html` (connection refused and
  browser timeout), Ghent `studiekiezer` brochure (timeout), Heidelberg Sinology model letter (site
  down), Tartu philosophy task page (404), UA History SOP advice (403), Princeton ASOP (403), UBA
  Derecho (DNS), INZ genuine-intent page (404 — moved), Manaaki how-to-apply (no essay content).

## What the read says, in five lines

1. **Order is published almost nowhere; content lists are published almost everywhere.** DAAD says so
   outright ("free to choose the order" / "not all questions have to be addressed"); UK and North
   American pages give frames (Imperial's five parts, Berkeley's four parts, Cornell's three moves)
   but call them suggestions. The only *scored* structural criterion found is TUM's "structured
   presentation of the link between personal suitability and programme content" (M-008).
2. **Letter formalities exist in exactly four places:** French guidance (objet, coordonnées, date,
   "Madame, Monsieur," formule de politesse), Mexico's UNAM template (place/date, Asunto, Presente,
   Atentamente, signature), Ireland's visa letter (signed, in English, prescribed contents), and
   Leiden's form that pre-prints "Dear members of the Admissions Committee," / "Sincerely,". Everywhere
   else the document is an essay or a portal field. The engine's current template (header + paragraphs)
   is therefore right for systems B, C, E and most of A, and wrong for France and Latin America.
3. **The form is eating the letter.** Vienna (per-question character caps), Utrecht/Leiden (header
   fields + questions), SNU (3,000-byte field), Tsinghua (in-system field), Open Doors (portal field),
   Australia Awards and UCT GSB (400-word answers per question), Brunei (200-word box). A renderer
   that emits one continuous letter cannot satisfy these; the `SHORT_ANSWER_SET` path is the right
   target for more of system A than the 2026-08 pass assumed.
4. **Personalisation splits by family, not by border.** Research programmes *require* names (ETH
   Mathematics: courses, specialisation, supervisors; UTokyo Science: supervising professors; NUS
   Psychology: rank-order three faculty; Northwestern research programmes; UBC). Professional
   programmes *discourage* them (Alberta Education: "extensive descriptions of courses, faculty
   members, or information taken from the website" is what they do not want; Imperial: "hear about
   you, not us"). One funder forbids them outright: Fulbright — "References to proposed universities
   or faculty should not be made" (M-075).
5. **Opening moves are contradictory across systems and the contradiction is real evidence.** UK
   guidance bans the origin story ("From a young age…"); UC San Diego's first prompt *is* the origin
   story ("How did you become interested in this field? Establish that you have had a long-term
   interest"). SNU bans family details outright. So "opening" is a per-system rule, never a global one.

## Coverage against the brief

| Cell | Read | Thin | Nothing |
|---|---|---|---|
| A continental | DE, AT, CH, FR, NL, BE, IT, SE, FI, CZ, RU, MX, CL | EE, AR, CO, ES/PT, PL, Nordics beyond SE/FI | Baltics beyond EE, Türkiye universities |
| B UK statement | UK, IE, HK, NZ, ZA | AU, SG coursework | MY |
| C N-American | US (5 grad schools, 3 depts, 3 arts schools, HLS), CA (3), SA, AE, KZ, JP univs | QA | BH |
| D scholarship | DAAD, Fulbright, Australia Awards, Eiffel, Brunei, Open Doors | Manaaki (no essay text found), Türkiye, Hungary | all named African and Latin American schemes, Gulf national schemes |
| E research-plan form | SNU, Tsinghua, ZJU, UTokyo | Kyoto, KAIST/Yonsei, Taiwan | Brunei UBD |
| F immigration | IE, NZ, Campus France EEF | — | Gulf, Türkiye, Russia, Japan CoE, Korea D-2 |

Discipline families: research (TUM, ETH, Vienna, KAUST, Khalifa, UTokyo, NUS Psychology, MIT),
humanities-social (Sciences Po, Leiden, FSV UK, WSU History, AUS), professional (UNAM Nursing, Warwick
WMG, UCT GSB, Alberta Education, HLS LL.M., GraSPP, Ghent Global Health), arts-design (RISD, CalArts,
UCLA DMA). Humanities and professional guidance *does* contradict research guidance on naming faculty
(M-060 vs M-062) — the families earn their keep.

## Questions this pass could not answer from primary sources

- **Salutation and sign-off conventions in German, Dutch, Italian and Spanish university letters.**
  No university page states one; the German pages that do (Heidelberg, LMU career services) are about
  *job* cover letters and were excluded. What would settle it: a university's own model
  Motivationsschreiben for study admission (Heidelberg Sinology's `muster_motivation.pdf` when the site
  is back) or a programme FAQ saying "no salutation needed".
- **Whether DAAD's one-page limit or EPOS's two pages governs when both apply** — two DAAD documents,
  two limits; the programme call decides. Settle per programme call.
- **Göttingen's letter guidance** (the "do not retell our web page" source cited in
  `2026-09-14-letter-storytelling-evidence.md`) could not be re-read; the citation stands on the earlier
  read.
- **Manaaki, Türkiye Bursları and Stipendium Hungaricum essay shapes** — only third-party guides
  surfaced; the official portals hold the prompts behind login.
- **Qatar, Bahrain, Malaysia, Taiwan, the Caucasus, Central Asia, Brazil/Peru and all named African
  destinations** — no primary page returned. Settle by fetching each institution's international
  graduate admissions page directly (the search index, not the institutions, is the gap).
- **Australia Awards form year** — the instructions PDF's year did not survive text extraction; the
  four-question, ~400-word shape is stable across the DFAT forms seen but the cycle should be pinned.

## Run 2 (same day): the tool repaired, the empty cells filled

**What was actually wrong with GPT Researcher.** Its Exa retriever passed an argument the pinned Exa
client library (2.19) had removed; every Exa call raised inside the research loop and was swallowed, so
runs continued on DuckDuckGo alone — the source of the college-homepage junk. Tavily's quota was the
second, independent failure. Fixed in `~/.local/share/gptr-mcp/src/patches.py` (Exa call rewritten for
the 2.x signature) with the owner's fresh Tavily/Exa/SerpApi keys; retrievers now `tavily,exa,serpapi`.
The same patch module adds a **Scrapling scraper** (`SCRAPER=scrapling`: StealthyFetcher, Cloudflare
solver on, WebRTC blocked, three browsers at a time; PDFs keep the PyMuPDF path) because the pinned
gpt-researcher — and upstream master — has none. Verified before use: Tavily and Exa both return the
DAAD advice sheet first; the Scrapling scraper read 3/3 pages including UCL's, which 403s the plain reader.

**Runs.** Three `deep_research` calls after the repair: Gulf/Malaysia/Taiwan/Caucasus/Central Asia
(returned with real primary sources), Africa (returned), Caucasus + Latin America (killed at the
30-minute silence limit — the server still emits no progress, so one slow site reads as a hang; those
countries were then filled by direct fetch). Rows added: M-091–M-105; country map updated for Qatar,
Bahrain, Malaysia, Taiwan, Georgia, Armenia, Azerbaijan, Brazil, Peru, Egypt, Ethiopia, Morocco,
Kenya/Nigeria/Ghana, Rwanda.

**Two findings run 2 adds to the five above.** (6) **A word floor exists**: HBKU rejects a statement
*under* 300 words (M-091) — every other cap in the catalog is a ceiling, and an engine that only
truncates would fail it. (7) **"No document" is a real outcome**: University of Bahrain's regulations and
Malaysia's MIS/UPM list no statement for coursework master's (M-093–095); the country map now records
absence with the page that shows it, not as a gap.

**Still empty after two passes:** Armenia; Kenya, Nigeria, Ghana; Morocco (UM6P call is image-only);
Rwanda's Mastercard portal (prompts behind login); Qatar University and Qatar Foundation; Universiti
Malaya; NTU Taiwan; ADA/Khazar; Ilia State and Free University. Georgia's only hit is a PhD internship
call (formatting spec: Times New Roman 12, spacing 1.0, 2 cm margins, ≤3 pages) — recorded in the map as
out of scope, not as a master's rule.

## Run 3 (same day): the second engine, and the last gaps

**Second engine.** The repaired GPT Researcher was run once per system on the brief's questions
(A, B, C, D, E+F) as the independent read — a different index (Tavily+Exa+SerpApi) and a different
model from the direct pass. Reconciliation against runs 1–2:

- **No contradiction found.** Every primary source the engine surfaced that overlaps the catalog says
  the same thing (Berkeley's four parts, Rackham's header, Cornell's name-on-every-page, Imperial's
  five parts, Uppsala's one page, NUS Psychology's ranked faculty, ETH's one A4 page).
- **It added primary sources the direct pass missed**, now rows M-106–M-119: Oxford's over-length
  removal rule and single-slot-with-subheadings rule; Edinburgh's 3,500-character portal cap and
  fraud warning; Hamburg IAS's 40% weight, 1.5-page cap and "Generic or AI generated letters will be
  rejected!"; Huddersfield, Brunel, Western Sydney (supervisor named and consulted); Qatar University's
  on-the-spot interview essay; UNU-MERIT's letter-plus-referenced-essay pair; CEU; Harvard GSE's
  1,000-word three-prompt statement; RMIT's dual-purpose Genuine Student statement with a signed
  declaration; UTokyo Engineering's named study-plan form and cancellation clause.
- **What it got wrong, and was excluded:** it returned coaching and portal sites (studypath, impeloverseas,
  gradpilot, EDHEC's marketing article, prospects.ac.uk) as if they were institutional guidance — the
  brief's excluded class; its CUHK "4,000-character personal statement" hit is the *undergraduate*
  international FAQ, not a master's rule; its E/F run returned only MEXT/GKS eligibility pages, nothing
  on shape. A second engine is a source-finder here, not a judge.
- **Run D (scholarship) is still running in the background at the time of writing** and is not folded in.

**Gaps closed by direct fetch:** Ghana (KNUST requires a statement, no spec; UG scholarship page limits),
Malaysia (UM: research proposal 3,000–5,000 words, supervisor acknowledgement first), Taiwan (NTU forms),
Morocco (UM6P letter + platform fields + interview), Qatar University. **Still unresolved:** Armenia
(AUA is Cloudflare-blocked to every fetcher we have), Kenya and Nigeria (their graduate-school pages
500/404), Rwanda's Mastercard portal (FAQ 404), Universiti Malaya coursework, NTU Taiwan master's
lengths.

## Next steps

1. Owner (or a second session with the keys in the environment) runs the whole brief once in an
   independent deep-research engine; reconcile disagreements row by row into this CSV.
2. Fill the "nothing" cells above by direct institutional fetch, not by search.
3. Only then plan the engine follow-ups: per-system archetype orders in `silent_funder.py`, a letter
   variant with French/Latin-American formalities, and the `SHORT_ANSWER_SET` widening for form-shaped
   continental programmes.

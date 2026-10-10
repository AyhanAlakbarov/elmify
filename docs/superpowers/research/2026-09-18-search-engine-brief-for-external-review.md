# How the funding-discovery engine works — a brief for an external reviewer

*Written 2026-09-18 for an independent judgement (Gemini Pro). Everything marked **(planned)** is
designed and measured but not yet built; everything else exists in code. Numbers are from our own
measurements, dated; nothing is a vendor's claim.*

## 1. Purpose

Find **every** funding opportunity a master's applicant could plausibly obtain — scholarships, fee
waivers, stipends and assistantships, funded joint degrees, housing/travel support, loans,
employer, diaspora, religious, political-foundation and government money — for **any country, any
script, any funding family**, and show each as a card whose every fact is a sentence quoted from the
organisation's own page. Constraints: legally clean (every provider's terms read), cheap (tens of
dollars per sweep, not thousands), and honest about what it does not know (an unread page is never
shown as "no funding").

## 2. What the engine records about an award

Three axes plus cross-cutting labels, all decided by reading the **holder's own page**, never a
search snippet or a vendor summary:

- **holder** — who owns the money: national government · sub-national government · political
  foundation · religious · private foundation · employer · intergovernmental · regional fund ·
  embassy/bilateral · diaspora/affinity · professional body · bank/lender · alumni · institution ·
  unstated **(planned — the plan is written, this is the next build)**
- **family** — eleven values (government scholarship, multilateral, industrial sponsorship,
  university-wide, department/programme, tuition waiver, stipend/assistantship, relocation,
  research pathway, affinity/diaspora, private foundation)
- **kind** — `I0` holder's own award **(planned)**, `I1`–`I7` institution-side kinds (university-wide,
  programme-attached, stipend/assistantship, research pathway, funded dual degree,
  relocation/housing/travel, paid placement)
- **labels** — eligibility keys (citizenship, residence, descent, region, affinity, open, need,
  gender, refugee/displaced, disability, talent, field, age, prior institution, employment),
  money form (grant, fee waiver, subsidy, loan, forgivable loan, mixed), route (automatic on
  admission, considered with admission, student applies separately, institution nominates, home
  government nominates, joint selection), tuition/living coverage, extras, obligations (return
  home, work in host, serve funder, repay on breach). Out by decision: essay prizes, hackathons,
  exchange/mobility money inside a degree.

## 3. The pipeline

1. **Organisation register.** One shared table of organisations keyed by *registrable domain*
   (Public Suffix List, so `metu.edu.tr` and `ox.ac.uk` key correctly). Status: `REGISTERED` (a
   register vouched for it), `CANDIDATE` (search found it; fetched and classified), `REJECTED`. Every
   route writes here; "is this host new?" is answered here before anything is fetched. **(planned)**

2. **Registries first — the spine and the denominator.** Free, open-licensed enumerators:
   Wikidata (class × country × official website — universities, ministries, agencies, foundations,
   diaspora bodies), DEQAR (externally reviewed HEIs, PDDL), ROR (research/education orgs, CC0),
   the EACEA project API (415 Erasmus Mundus joint masters), Türkiye's VGM register of
   scholarship-giving foundations, and Diffbot's knowledge graph as a small supplement. National
   registers (YÖK, etc.) are read by hand into a versioned file and are the only thing that
   promotes a domain to `REGISTERED`. Measured 2026-09-17: Türkiye — YÖK 208 authorised
   universities, DEQAR 234, ROR 239, Wikidata 229; Azerbaijan — DEQAR 13 against ~50 real, so
   registers are thin there and search/hub pages carry more.

3. **Search, only for the set-difference, routed by family.** Where no register exists (home-country
   outbound government schemes, private foundations, employers, diaspora bodies):
   - **Exa** primary: `type: auto`, `numResults: 100`, a "describe the entity" query written in the
     local language, an aggregator denylist, no other filters.
   - **Brave** as the independent second index: `offset` 0–9 until the first empty page, a
     "Goggle" (Brave's re-ranking rule set, passed inline) that discards commercial scholarship
     aggregators and boosts `.edu`/`.ac`/`.gov`/`stiftung`/`vakf` hosts, no `country`/`search_lang`.
   - **Tavily** as a decaying local-language leg (dropped early by the tally below); its real jobs
     are name→site resolution and page extraction.
   - **Baidu** (China) and **Naver** (Korea) as regional engines, added only where a measured rule
     holds — the national web is large *and* partly outside the global indexes' reach. **(planned)**
   - **Firecrawl** as a PDF channel (funder calls and decrees are PDFs) and for site maps.
   Three phrasings per (country, family), English as a second pass, a fourth phrasing set keyed to
   eligibility ("scholarship for women in engineering …"). Every query is built from country and
   family vocabulary, never from a student.
   **The engines are not a pool.** Per sweep the engine counts *which engine found each new
   organisation first* and drops the ones that stop producing (measured on 99 queries in one cell:
   Exa's per-batch novelty stayed 124, 63, 45, 43, 45, 38, 34, 42, 42 while Brave fell 81 → 11 and
   Tavily 62 → 5).

4. **Host inventory.** For every registered university: certificate-transparency logs (crt.sh)
   plus a site map to enumerate sub-hosts (departments, institutes); and — measured better as a
   first pass — one Exa call restricted to that university's domain with the descriptive query,
   which surfaced departmental scholarships and fully funded MSc positions at TUM and METU for
   $0.022 each. **(planned)**

5. **Hub harvesting and name→site resolution.** Ministry and agency pages list the bodies we want;
   a closed-schema extraction pulls `{name, kind, url?}` one hop out; URL-less names are resolved
   by Wikidata first, then a quoted-name search whose top ten candidates are scored lexically and
   title-checked, with Diffbot's entity lookup on what is still unresolved (7 of 10 on the Turkish
   syllabic acronyms and Georgian-script names no lexical rule reaches). Hand-tuned, the resolver
   reached German 20 right / 0 wrong / 5 unresolved and Turkish 12/1/12; its generalised form
   **failed a blind Kazakh hold-out** (1/11/13) — the causes were missing general *data* (Wikidata
   kinds, place names, English name variants), not missing rules, and that is how it is being
   fixed. Acceptance is always a fresh country in a different script, drawn before any rule edit.
   **(partly built)**

6. **Classification of a new host.** Homepage text, labelled as data, one capped model call with a
   closed schema (kind, country, funds_students, confidence), cached per domain, rate-limited;
   `INFRASTRUCTURE` and `funds_students=false` hosts are remembered so they are never fetched
   twice. **(planned; gated on a hand-checked sample)**

7. **Fetching, in four tiers.** Our own egress (validates every redirect hop against private
   networks, caps size and content type) → Tavily Extract (0.2 credit/page) → Firecrawl
   `proxy: "auto"` (1 credit) → Scrapling stealth browser in a task that holds no secrets, behind
   an egress proxy that validates every CONNECT. Network-class failures (TLS, timeouts, 5xx) enter a
   retry queue (three tries over seven days) and then a human queue only if the host is a plausible
   funder. Cloudflare solving is on for public research pages and never used against an applicant's
   portal. **(tiers 2–4 planned)**

8. **The reader — where an award is decided.** The page is split into lines with their headings;
   each chunk of 80 lines (at most three chunks) is judged **three times** — two OpenAI phrasings
   and one Claude — against one closed question with a schema-constrained answer (`extra="forbid"`,
   capped output, nothing stored by the vendor). Untrusted page text is labelled DATA in every
   prompt. Agreement per line: *agreed* (all three say YES with identical decided fields), *disputed*
   (fields named), *negation* (page says no funding), *noise* (one reading alone), *abstained*
   (fewer than three readings answered). Every quoted sentence is verified against the page; a
   quote not on the page is dropped. An award is **served** only when agreed, offered, and carrying
   a stated money form or benefit. A fourth reading breaks ties on `offered` only **(planned)**;
   every other disagreement goes to a human. Lines naming a third party's money ("pointers") become
   leads into the register instead of being discarded **(planned)**. Model calls are budgeted per
   run; a page is re-read only when its content hash changes.

9. **Human resolution queue.** One dashboard list for counsellors: *site unknown* (name + top-3
   candidates), *award disputed* (quotes + only the disputed fields as buttons), *host unreachable*,
   *kind/country unsure*. Closed questions, one click, written back permanently to the shared
   catalog so no tenant is asked twice; a daily cap per person; target under one host in ten per
   corridor reaching a human. **(planned)**

10. **Demand cells and on-demand search.** A student's profile is reduced to a *cell* — destination
    set, discipline bucket, level, languages, eligibility keys held, funding need — with no personal
    fact in it. Tapping "search" runs discovery for that student in two stages: candidates within
    ~3 minutes (Exa neural descriptive query + Brave, ≤ 40 provider calls, ≤ 30 pages, Exa's
    one-sentence highlights as transient triage of which pages deserve the expensive reader), then
    the reader in the background (≤ 60 pages, ≤ $15 per tap), each served award bumping the pack.
    Everything found is stored in the shared catalog, so the first student in a cell pays the wait
    and later ones are served from the catalog. Per-provider query allow-list: Tavily queries stay
    profile-free (its terms take a perpetual licence over query text); Exa/Brave queries may carry
    non-identifying academic attributes (field, level, destination, nationality as a cell attribute)
    and never a name, an employer with a field, or special-category data. **(planned)**

## 4. The rules the design rests on

- **Only a URL is read from any search provider.** No snippet, title or score is persisted; the
  origin is fetched and validated; what lands in the catalog is what the institution's own server
  returned. A snippet is a vendor's rendering of someone else's page.
- **Constraints go in parameters, never in prose; and almost no filters.** Provider `country`,
  `language`, category and text filters were each measured neutral-to-harmful; the only two
  capabilities that reliably win are **depth** and **writing the query in the local language**.
- **Terms decide the roster, and definitions decide terms.** Exa and Brave: written permission with
  one condition (their output trains no competing search index). Tavily: clean by structure
  ("Services" excludes "Output"). Diffbot: explicit commercial grant. SerpApi for Baidu/Naver: free
  tier, no legal shield, accepted knowingly by the owner. Google: excluded — its search API is
  closed to new customers (ends 1 Jan 2027), Gemini's grounding terms forbid "using Links to identify
  destination pages for crawling or scraping", and the scraped route added +1–2 hosts per country.
  Perplexity, Yandex, Seznam, Coc Coc, Mojeek, aggregators-as-sources: rejected with reasons.
- **Security baseline for every model call:** untrusted content labelled as data, schema-constrained
  output, capped tokens, per-tenant/per-user rate limit in the same change that wires a call.
- **Student data never forms a query**; the catalog is shared by every agency, so no tenant may
  steer what every tenant reads.

## 5. Measured facts (dates in the repo notes)

- **Four-provider probe, 20 queries:** origin-host share Exa 79%; Brave 49% → 76% with the Goggle;
  Tavily 50% → 69% with proper wiring; Firecrawl 42% → 60%. Union of four: 507 hosts vs 254 for the
  best single provider; Exa alone contributed 132 hosts no other index returned, Brave 84.
- **Flag ablation, four countries:** Brave 3 → 10 pages: +47% / +68% / +27% / +104% local funders
  (DE/TR/AZ/ID); Exa 25 → 100 results: ×3.4 / ×2.0 / ×1.7 / ×2.2. Local-language queries beat
  English on local funders in all four; Brave `country`: 0 / −1 / 0 / **−8**; Exa `category:
  "company"`: −2.7 points; no single configuration exceeded 18% recall on a 377-funder German key.
- **Saturation, one dense cell (Germany × private foundations), 99 queries, ~$2:** 1,067 domains,
  353 German funders; novelty decayed for Brave/Tavily and not for Exa.
- **Diffbot:** 137 entities → 24 new German funders (+7% on 353) at 28% precision, including a
  federal programme four engines missed; name-resolution 7/10.
- **Regional engines:** Baidu +7 Chinese institutions from 3 searches at 76% precision; Naver +5
  Korean funders; Yandex 0 in Azerbaijan; Google via SerpApi +2 / +1 / +1.
- **Page-level yield (the decisive number):** the reader over 58 funder hosts discovery produced —
  88 pages, 399 model calls, 102 minutes — **served 2 awards, neither from a funder**; every
  foundation page produced "pointers" or disagreement because the reader had no word for a funder's
  own award. That is a schema gap, not a tuning one, and the holder axis is the fix. 8 of 58 hosts
  were refused by our own egress (bot-blocks, one broken TLS chain, one timeout).
- **Reader stability:** three unioned reads of the same page returned 47 / 42 / 48 statements; no two
  reads ever produced the same set; verification removed fabrication (1–2 unverifiable quotes per
  nine calls) but not selection variance — so stability is judged on *derived rules*, not sentence
  sets.
- **Cost:** search ≈ $20 per cycle at launch scale (Exa $0.097 per 100-result call, Brave $5 per
  1,000 requests) against $15 of free monthly credit; the reader ≈ 7 calls and $0.35 per host, up to
  36 calls and 15 minutes on a text-heavy page; batching and prompt caching (planned) halve the
  model cost.

## 6. Known gaps, stated so they are judged too

The holder axis, register, adapters, classifier, fetch tiers 2–4, human queue and on-demand search
are designed and unbuilt; the catalog is empty. The reader does not yet write amount, deadline or
eligibility keys (the card needs them). No admission-outcome data exists anywhere. The precision of
served cards has never been hand-checked (a 30-card check is required before the first pack).
Baidu/Naver rest on a reseller's free tier. Two cheap knobs are unmeasured (Exa wildcard subdomains;
Brave `OR` phrasing). The sweep's first-discoverer tally is per engine, not yet per family.
Thin-web countries (Azerbaijan, Georgia) depend on registers, hub pages and hand curation, because
more querying cannot find pages that do not exist. Firecrawl's retention terms are unread.

## 7. What we would like judged

1. For "all funding, any student, anywhere": is anything **structurally** missing — a source class,
   a route, an axis?
2. Is *registries first, search only for the difference* the right spine, or is there a cheaper or
   more complete one?
3. Is three-reading agreement plus quote verification a sound way to make model-read facts
   trustworthy, given the measured selection variance? What would you add or drop?
4. Is the terms posture defensible as stated? Where is it weakest?
5. Where would this fail first at scale — cost, freshness, thin national webs, the human queue, or
   something we have not named?
6. Is there anything in the rejected list you would reopen, and on what evidence?
# The origin side — synthesis across two runs

**Date:** 2026-08-29. **Inputs:** two independent runs of
`PROMPT-origin-side-announcements.md`, filed as `2026-08-29-origin-side-review-1.md` (run A) and
`-review-2.md` (run B).

**What it answers:** what nine governments publish to their own citizens about funding a master's
abroad, and — the question the run existed for — whether the origin state's role changes the
application route a student actually faces.

---

## 1. The answer, and it is the one that invalidates portfolio floors

**Yes. For most foreign-state schemes reaching our nine countries, the origin state nominates or
pre-selects, and the scheme is therefore `NOMINATED` for that nationality whatever the funder's page
says.** Both runs establish this independently, each with quoted local-language sentences, across
Azerbaijan, Türkiye, Georgia, Kazakhstan, Kyrgyzstan and Turkmenistan.

The sharpest single proof is Türkiye's (run A only):

> "Millî Eğitim Bakanlığı tarafından mülâkat yoluyla aday seçimi yapılmakta ve ilgili ülkeye kazanan
> adayların isimleri asil ve yedek olarak bildirilmektedir. Adayların kabullerine ait son karar ilgili
> ülkeye aittir."
> — "Candidate selection is done by interview by the Ministry of National Education, and the names of
> winning candidates are reported to the relevant country as principal and reserve. The final decision
> on acceptance belongs to the relevant country."

And Azerbaijan's, on a scheme whose funder markets it as open:

> "…proqramda yalnız Səlahiyyətli Göndərən Tərəf qismində Azərbaycan Respublikasının Təhsil Nazirliyi
> tərəfindən ərizələri təsdiq olunmuş tələbələr və ya ərizəçilər iştirak edə bilərlər."
> — "Only students or applicants whose applications have been approved by the Ministry of Education of
> the Republic of Azerbaijan as the Authorised Sending Party may participate."

**Consequence for the catalog:** a route's `DIRECT`/`NOMINATED` value is not a property of the scheme.
It is a property of the (scheme, nationality) pair, and for these nine nationalities the origin-side
sentence governs. Encoding Stipendium Hungaricum once, as its funder describes it, is wrong for every
student we serve.

**§9.4 proves this in both directions, which is stronger than the claim first written here.** The same
scheme, the same funder, the same cycle: `NOMINATED` for Azerbaijan, Georgia, Kyrgyzstan and
Turkmenistan — and **`DIRECT` for Uzbekistan, because Uzbekistan's ministry says so in writing** and
expressly waives the domestic submission its neighbours require. The origin state is the authority on
the route; it does not always tighten it.

## 2. The named objective is met — the Azerbaijani ISP is no longer a news report

The prompt existed partly because Azerbaijan's Intergovernmental Scholarship Programme was known only
through a news article quoting application counts. Both runs found its own surfaces:
`htp.edu.az` (per-cycle PDFs), `app.htp.edu.az` (the application portal), `portal.edu.az` (the
single intake funnel), and the Ministry's own realised-intake report at
`edu.gov.az/az/qisa-xulase/22236-1`.

The report is the strongest artifact either run produced — a per-destination realised intake for
2024-2025 that no destination country publishes:

> "Macarıstanda 129, Çində 28, Latviyada 8, Qazaxıstanda 9, Türkiyədə 6 …, Rusiyada (MGIMO) 5,
> Rumıniyada 2, Slovakiyada 1, Tacikistanda isə 2, ümumilikdə isə 192 Azərbaycan vətəndaşı"

Run B adds **Morocco** to the HTP destination set, with its own PDF and an August 2026 deadline.

**Three Azerbaijani Stipendium Hungaricum numbers are now in the corpus and they are not the same
number.** They reconcile, and the reconciliation is the encodable lesson:

| Figure | What it is | Source |
|---|---|---|
| up to 200/year | the **MoU ceiling**, 2024–2026 | EATDA's own text (run A) |
| 104 awards, 80 master's | **awarded**, 2026/27 | State Agency via Caspian Post (prior round) |
| 129 in Hungary | **realised intake**, 2024-25 | Ministry annual report (run A) |

Encoding the ceiling as the quota overstates the pool by roughly half. Record which of the three a
number is, or do not record it.

## 3. Where the runs contradict each other

### 3.1 Tajikistan — run B is wrong, and wrong in the shape this programme has been burned by before

Run B reports "confirmed silence; exhaustive queries yielded zero direct state-published outbound
funding pages." Run A found the Center for International Programs (Durakhshandagon): a 314-place
quota for 2026, 170 offered and 96 selected in 2025, a 120-somoni application fee, a five-year
return-service obligation, a street address and a telephone number.

Run A also found **why run B saw nothing**: `edu-cip.tj` is robots-blocked and the Center's
announcements have migrated to `facebook.com/durakhshandagon`.

**A retrieval failure was reported as a finding.** This is the ADB-JSP error exactly — an absence
asserted from a document that could not be reached — and it is the reason the prompt requires every
fetch failure to be recorded with its URL. Run B recorded none.

**Take run A. Tajikistan is not silent.** One caveat run A raises itself and should be honoured: in
2025 the quota was awarded at bachelor's level only, master's "not provided" that year.

### 3.2 Turkmenistan — run A is wrong, and run B over-claimed

Run A reports near-silence. Run B has three `education.gov.tm/announcement-details/…` URLs with
quoted Turkmen text, exact submission windows (1–15 December 2025) and a physical-delivery mechanism
in Ashgabat, including workplace and military references. **An evidenced presence beats an evidenced
absence: Turkmenistan is not silent.**

But run B's own URLs read `…ýokary hünär bilimi **bakalawr** maksatnamasy boýunça…` — *bachelor's*
programme — and it filed both rows in a master's analysis anyway.

**Corrected position, held by neither run:** Turkmenistan publishes a real, high-friction, in-person
selection channel for foreign study, and on the evidence retrieved it is bachelor's-level. **Open
item — verify before encoding anything for Turkmenistan.**

## 4. What each run found alone

Run B found the foreign-funded half of two countries run A covered only on their own programmes:

- **Kazakhstan** — intergovernmental grants at `oq.gov.kz` / `bolashak.gov.kz`, administered by the
  same Center that runs Bolashak, with per-country tables (Azerbaijan 12, of which 5 master's;
  Kyrgyzstan 10; Slovakia 1; Poland 11 recommended), a **GPA 3.0 floor and IELTS 5.5 / TOEFL iBT 50**
  imposed by Kazakhstan, tie-break priority for orphans, disabled applicants, large families and
  rural residents, and **a one-year return-and-work obligation** on the grants.
- **Georgia** — Stipendium Hungaricum **up to 80 Georgians a year**, a sending-partner quota Hungary
  does not publish, plus France (French-Georgian master's, B2 French), China, Italy and Czechia; and
  **up to 5 bonus points** in selection for IDPs, disability, social vulnerability, or residence in
  high-mountain or occupied-territory-adjacent settlements.
- **Armenia** — seven schemes with quotes, including **Jordan at up to 30 places, `NOMINATED`**, which
  run A missed entirely while correctly characterising Armenia as mostly a bulletin board.

Run A found what run B has no equivalent of:

- **Türkiye's MEB `Yabancı Hükûmet Bursları`** and its operative sentence (§1), plus Hungary's
  historical Türkiye sub-quota — 150 for 2021, split 40 BA / 65 MA / 40 PhD / 5 short-term.
- **Part A in full** — thirteen announcement surfaces with cadence, archive depth,
  machine-readability and access constraint. Run B produced no surface table at all.
- **The fetch-failure log**, which is what separates a null result from an absence.

## 5. The modelling consequence neither run drew

**The nominating state imposes its own eligibility and scoring rules, and they are not the funder's.**
Georgia's five bonus points; Kazakhstan's GPA 3.0, IELTS 5.5 and rural tie-break; Kyrgyzstan's HIV
clearance and police certificate; Turkmenistan's 18-to-25 age band and military reference.

`ApplicantCondition` hangs off `FundingBenefit` — the **funder's** route. A condition attached to the
**nomination** is a different object, and for these nationalities it can be the binding one: a student
who fails Kazakhstan's GPA floor never reaches the funder. This is the second
instance this week of the same shape — the GKS Overseas Korean track was the first — and the general
statement is now hard to avoid: **a scheme is not one set of rules, and the set that binds depends on
who the applicant is.**

Second consequence: **Kazakhstan's one-year obligation is a third source of bonding**, after the
funder (ADB-JSP, Bolashak, YLSY) and the visa class (J-1 / INA §212(e)). Here the *origin* state binds
a graduate on someone else's money. `RETURN_SERVICE` currently models a funder obligation; this one
attaches to the nomination, like the conditions above.

## 6. Operational findings for our own fetching design

- **Adopt as monitored surfaces** (dated, archived, stable): `eatda.edu.az/elanlar`,
  `edu.gov.az/az/announcements`, `htp.edu.az`, `escs.am/am/category/interprograms`, `iec.gov.ge`,
  `student.edu.gov.kg` (flat HTML, the cleanest of the nine), `bolashak.gov.kz`, `el-yurt.uz`.
- **Two hostile surfaces need a design decision, not a retry:** `abdigm.meb.gov.tr` is robots-blocked,
  and Tajikistan's live channel is a Facebook page. A web crawler answers neither. The Tajik case is
  the concrete instance of the prompt's "announcements on a messaging platform" flag.
- **`iec.gov.ge` serves percent-encoded Georgian URLs** long enough to defeat direct fetching in run A.
  A real constraint for whatever retrieves these.
- This corroborates `PROMPT-new-opportunity-surfaces` Part A for Azerbaijan: both runs converge on the
  state channels as distinct from the independent aggregators (`edumap.az`, `xaricdetehsil.net`,
  `upass.az`). Agreement across prompts marks these as worth watching.

## 7. Quality caveats — read before encoding

- **Run B cites all seven Armenian schemes to one URL** (`escs.am/am/category/interprograms`), with no
  per-scheme permalink. Unverifiable row by row.
- **Run B asserts Part D without doing it** — "perfect adherence", "perfect factual alignment" — while
  naming no funder page it opened. Run A's Kuwait and Hungary asymmetries are the only real Part D
  content across both runs.
- **Run B's Kazakhstan return-service claim cites the rule and quotes the wrong sentence** (coverage,
  not the obligation). Get the clause before encoding a bond.
- **Run A's Tajik bilateral table (Russia 782, China 277, …) is 2015 and flagged by run A itself as
  directional.** Correct practice; keep the flag.
- Run A is the better-executed run against this prompt; run B has the better per-scheme extraction
  where it exists. Neither is discardable.

## 8. Still open

1. ~~Turkmenistan's degree level~~ — **closed, §9.1.**
2. ~~Kazakhstan's return-service clause~~ — **closed, §9.2.**
3. ~~Armenia's seven schemes~~ — **parked by decision, not by failure, §9.5.**
4. ~~Whether Uzbekistan publishes a bilateral channel~~ — **closed, §9.4.**
5. **Tajikistan's current bilateral quota table**, from the Center rather than a 2015 secondary source.
6. **Whether any origin state publishes a machine-readable feed.** Both runs answer "none found" for
   every body — a confirmed absence worth recording as such, since it decides whether these surfaces
   are polled or scraped.

---

## 9. The three single-page checks, run 2026-08-29

Two closed from primary sources. The third is blocked, and is recorded as blocked rather than
resolved.

### 9.1 Turkmenistan — bachelor's, decisively. Neither run had it right

Retrieved `education.gov.tm/announcement-details/…-I9MZTT` (the Hungary announcement, dated
26 November 2025). The title carries `(bakalawr)`, but the eligibility sentence settles it beyond the
title:

> "Wengriýanyň ýokary okuw mekdeplerine **umumy orta bilimli**, 2026-njy ýylyň 31-nji awgustyna çenli
> 18 ýaşy dolýan, **2025-2026-njy okuw ýylynda umumy orta mekdebi tamamlaýan** Türkmenistanyň
> raýatlarynyň resminamalary 2025-nji ýylyň 1 — 15-nji dekabry aralygynda Halkara ynsanperwer
> ylymlary we ösüş uniwersitetinde kabul edilýär."
> — "Documents of citizens of Turkmenistan **with general secondary education**, turning 18 by
> 31 August 2026, **who complete general secondary school in the 2025-2026 academic year**, are
> accepted between 1 and 15 December 2025 at the International University for Humanities and
> Development."

**These are school-leavers.** The same page's sidebar shows the China/Xinjiang announcement is also
`(bakalawr)`. The mechanism run B described is confirmed — twelve 3x4 photographs, a health
certificate, a character reference from the last place of study or **military unit**, personal
liability for false documents — but that mechanism carries bachelor's places.

**Settled position, held by neither run:** Turkmenistan publishes a live, high-friction, in-person
outbound selection channel, and it is bachelor's-level. Run A's "silence" is wrong; run B's master's
classification is wrong. **For a master's product Turkmenistan yields nothing — now for a sourced
reason rather than an unexamined one.** The only master's mention on the site is a *domestic*
programme opening at the State Energy Institute.

**An operational trap worth more than the finding.** Under plain fetch `education.gov.tm` returns a
2,143-byte JavaScript shell, and **two different announcement URLs return byte-identical HTML**
(verified with `cmp`). A naive fetcher does not fail here — it succeeds, and records identical
content for every announcement on the site. Only a browser render returns the announcement. A
content digest would make this look like a stable page rather than catch it.

### 9.2 Kazakhstan — the clause, and a precedence rule nobody expected

Verbatim from `bolashak.gov.kz/usloviya-i-dokumenty/priem-dokumentov`, repeated in every per-country
block on the page:

> "Согласно подпункту 4) пункта 21 предусматривается обязательное возвращение победителя конкурса в
> Республику Казахстан после завершения академического обучения за рубежом и осуществление
> непрерывной трудовой деятельности со сроком 1 (один) год."
> — "Under sub-paragraph 4) of paragraph 21, the competition winner is required to return to the
> Republic of Kazakhstan after completing academic study abroad and to carry out continuous labour
> activity for a period of 1 (one) year."

**Run B's substance is confirmed.** A third source of bonding stands: the funder, the visa class, and
now the origin state binding a graduate on another state's money.

The master's grade floor, verbatim from `oq.gov.kz/ru/b-grants`:

> "для обучения по программам магистратуры, резидентуры и докторантура – соответствие среднего балла
> диплома бакалавра/специалиста/магистра или транскрипта о текущей успеваемости баллу не менее
> **3.0 из 4.0/4.33**"

And the sentence immediately after it, which is what changes §5:

> "В случае если принимающей стороной будет установлен более низкий средний балл об образовании,
> данное условие не учитывается."
> — "In the event that the receiving party sets a lower average grade, this condition is not taken
> into account."

**Kazakhstan's GPA floor explicitly yields to a lower host requirement. Its return-service obligation
does not.** The origin state's conditions are not a uniformly binding overlay: the precedence between
the two sets is itself published, and it is set per condition. A model carrying nomination-level
conditions has to carry that precedence too.

Tie-break priority confirmed on the same page (para 17): orphans and children without parental care,
then those disabled since childhood, then large families, then rural residents.

### 9.3 Armenia — blocked, and recorded as blocked

`escs.am` sits behind a Radware WAF (`server: rdwr`) and returns **HTTP 403 with a transaction ID on
every path** — `/`, `/am`, `/am/category/interprograms`, `/en/category/interprograms` — to both a
plain fetch with browser headers and a real headless browser. The host also failed to resolve on this
machine's default resolver and needed an explicit `--resolve` to 144.249.139.19 before the WAF would
answer at all.

**Not defeated, deliberately.** Getting past a WAF challenge is defeating an access control, which
this project keeps out of the public-page tier.

**Run B's seven Armenian schemes therefore remain single-sourced to one category URL and unverified.**
The Jordan row — up to 30 places, `NOMINATED` — is the one worth chasing, because a nominated
bilateral quota is the exact shape this run exists to find. It needs an Armenian vantage point or a
person with a browser, not another fetch from here.

**This is also a Part A correction.** Run A recorded `escs.am` as "fetchable" and put it on the
monitored-supplier list. On this evidence it is not fetchable from our infrastructure, and it belongs
with `abdigm.meb.gov.tr` and the Tajik Facebook page as a surface needing a different design.

### 9.4 Uzbekistan — the counter-instance, and it flips the headline for one country

Found by cross-checking with a second research tool (GPT Researcher) after both deep-research runs
failed on this question: run A saw only El-Yurt Umidi relaying foreign schemes, run B marked
Uzbekistan `UNCLASSIFIED` on retrieval grounds. The answer was one page on the government portal,
verified at source: `gov.uz/en/edu/news/view/109534`, Ministry of Higher Education, Science and
Innovation, dated 10 December 2025.

**The bilateral channel exists**, and it publishes a sending-partner quota Hungary does not:

> "…the Government of Hungary provides educational grants in the amount of **up to 200 places for
> citizens of the Republic of Uzbekistan**."

Master's is named explicitly among the eligible levels, and the split between levels is deliberately
unpublished — "established based on the needs of the republic's economy for personnel, as well as
taking into account the number and quality of applications."

**And then the sentence that breaks the pattern.** Uzbekistan is the Sending Partner, and it uses that
position to *remove* a step rather than add one — correcting paragraph 3.4.2 of Hungary's own Call for
Applications:

> "Coordinator ('Sending Partner') from the Uzbek side is the Ministry of Higher Education, Science and
> Innovation of the Republic of Uzbekistan. … we provide an explanation that **it is not required to
> submit documents to the Ministry** of Higher Education, Science and Innovation of the Republic of
> Uzbekistan (MinHE) — either online or in paper form. **It is enough to send all documents in online
> format directly to the online platform specified by** … Tempus Public Foundation …
> `https://apply.stipendiumhungaricum.hu/`"

**For an Uzbek citizen, Stipendium Hungaricum is `DIRECT`.** For an Azerbaijani, Georgian, Kyrgyz or
Turkmen citizen the same scheme in the same cycle is `NOMINATED`, and Georgia and Kyrgyzstan require
dual registration explicitly. This is the same scheme resolving to different routes by nationality, on
the origin state's own instruction — and it is the strongest single piece of evidence in either run
that the route belongs to the pair, not to the scheme.

It also means **`PUBLICISES ONLY` and `NOMINATES` are not the only options for a Sending Partner.**
Uzbekistan formally holds the Sending Partner role and still routes the student straight to the funder.
Whatever encodes this needs to record the role and the route separately; they are not derivable from
each other.

**Funder-side half, checked:** `stipendiumhungaricum.hu/partners` fetches cleanly and lists the sending
partners for all nine of our countries. Hungary publishes **who** the partner is; only the partner
publishes **how many** and **whether you must go through them**. That is the asymmetry stated exactly.

### 9.5 Armenia — parked by decision

Dropped from the open list at the user's direction on 2026-08-29: retrieval of Armenian government
sites is not practical from Azerbaijan. **This is a scope decision, not a research failure, and it
should not be re-derived as a gap.**

Two facts worth keeping for whoever picks it up. The `escs.am` WAF block is **not specific to our
machine**: a commercial research retriever hits it too, and its block pages are indexed — "Due to
previously detected malicious behavior which originated from the network you're using, please request
unblock to site," with a Radware Incident ID. So no automated supplier design reaches this host from a
datacenter network; it needs an allow-listing request or a person. The permalink pattern is
`escs.am/en/news/<id>` (e.g. `36099`), which is what a later pass should collect.

---

## 10. Method note — the second tool earned its place

The Uzbekistan finding in §9.4 is the argument for cross-checking a deep-research run with a different
retrieval stack. Two independent deep-research runs both failed on the same question, in different
ways — one didn't look, one looked and reported a retrieval constraint — and a single query against a
different index returned the government page that answers it, and that inverts the headline finding
for that country.

The corollary is the discipline, not the tool: **the second tool's output was still a lead.** The
finding only counts because `gov.uz/en/edu/news/view/109534` was then fetched and quoted directly. The
same run also returned a plausible-looking secondary (`instrux.uz`) asserting the Sending Partner
identity correctly, and several inbound ICESCO-Uzbekistan results that answer a different question
entirely — the inbound/outbound conflation these prompts are built to keep apart.

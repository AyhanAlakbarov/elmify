# Reconnaissance — UAE, China, South Korea, Japan (and where Australia already stood)

**Date:** 2026-08-31. **Status: NOT a research run.** Third in the series with
`2026-08-31-safety-screen-register-recon.md` and `-destination-registers-recon.md`. Prompted by a
direct question — had these countries been checked? — to which the honest answer was **Australia yes,
China half, UAE / South Korea / Japan not at all.**

**Why they need their own registers.** Measured against the DEQAR CSVs, the QA leg is blind in every
one of them:

| country | listed in DEQAR | screenable |
|---|---|---|
| United Arab Emirates | 12 | 11 |
| **Australia** | 2 | 2 |
| China | 24 | 14 |
| Japan | 8 | 7 |
| **South Korea** | 1 | **0** |
| Hong Kong | 1 | 1 |
| Macao | 0 | 0 |

Eleven UAE institutions out of a real sector of 103 active ones; zero in Korea. Same conclusion as
§4 of `2026-08-31-screen-coverage-measurement.md`: outside the EHEA, the national register is the
only gate.

---

## 1. United Arab Emirates — the best-shaped register found so far, and it publishes its graveyard

**Commission for Academic Accreditation (CAA)**, under the Ministry of Higher Education and
Scientific Research. `caa.ae/Pages/Institutes/All.aspx`, HTTP 200, 285,051 bytes — **the entire
register on one page**, no authentication, no pagination.

**159 institutions**, one HTML table, columns: name (English), name (Arabic), Emirate, website,
**status**.

| status | count | meaning |
|---|---|---|
| **A** | **103** | Active |
| **X** | **55** | Inactive |
| **T** | **1** | on probation / student admissions suspended |

The page's own filter offers *All / Active / Inactive / Currently on Probation*, which confirms the
letter codes.

**The feature no other register in this series has: the closures stay published, by name.**
**24 institutions carry "(LICENSURE REVOKED)" in the title** — AL FALAH UNIVERSITY, AL GHURAIR
UNIVERSITY, AL HOSN UNIVERSITY, AMERICAN COLLEGE OF DUBAI, SKYLINE UNIVERSITY COLLEGE, MENA COLLEGE
OF MANAGEMENT, ROYAL COLLEGE OF SURGEONS IN IRELAND–DUBAI, and others. One entry reads
"INSTITUTE OF MANAGEMENT TECHNOLOGY-DUBAI (STUDENT ADMISSIONS SUSPENDED)".

The brief's §A4 asked whether a licence *history* is retrievable anywhere, and Part C asked for
concrete published examples of institutions that fail a screen. **The UAE answers both in one table.**
It is also the register that makes the risk legible: a third of the institutions ever licensed in the
UAE are no longer active, and several are well-known Western branch campuses.

**Two traps.**

- **The footer reads "Page last updated on: 11/26/2020."** That is the SharePoint page-chrome date,
  not the data date — the table contains institutions licensed well after 2020. Do not read it as a
  staleness signal, and do not build a freshness check on it. The register carries **no visible data
  date at all**, which is its real weakness.
- **CAA licenses the mainland sector. Free-zone providers are a separate question.** Dubai's KHDA
  (`web.khda.gov.ae`, reached via redirect from `khda.gov.ae`) regulates providers in Dubai's free
  zones, and a branch campus can operate there outside CAA licensure. Absence from the CAA table is
  therefore **not** proof a provider is unlicensed. This was not probed further and is the open item
  for the UAE.

**Terms: unverified.** The footer asserts "© 2022 Commission For Academic Accreditation (CAA). All
rights reserved" with a Copyright page and separate Terms & Conditions page, neither read. Treat as
restricted until checked.

## 2. South Korea — a full certified list, published, and non-certification is itself a visa signal

`studyinkorea.go.kr/ko/plan/certifiedUniversity.do`, run by NIIED under the Ministry of Education.
**Page states "Last modified: 2026-03-03."** The whole list is on the page, named, no pagination.

**IEQAS — International Education Quality Assurance System**, evaluated annually and jointly by the
Ministry of Education and the **Ministry of Justice** (which is what ties it to visas).

| category | count |
|---|---|
| Certified for **degree programmes** | **184** — 135 universities, 33 junior colleges, 16 graduate institutions |
| Certified for **Korean language programmes** | 126 — 104 universities, 20 junior colleges, 2 graduate |
| **"Excellent Certified"** (top tier) | **43** — 35 universities, 3 junior colleges, 5 graduate |

**The consequence for a student, in the portal's own words:** certified universities get *"relaxed
visa screening criteria for international students and additional allowances for part-time work
hours"*, and — the part that matters for a safety screen —

> "Non-Accredited universities undergo inspections, and if they fail to meet certain standards, they
> are designated as institutions requiring stricter visa screening for language proficiency,
> financial capability, and other factors."

So in Korea, **absence from the list is a real signal**, not a data gap — unlike Ukraine (see the
coverage measurement §3). Korea is one of the few countries where a negative can be shown honestly.

Format: server-rendered HTML, institution names in comma-separated blocks per category. Parseable,
though names are upper-case and unnormalised — this is a name-matching problem, not a fetching one,
and it is exactly what `identifiers_all`/ROR solves elsewhere. No ROR, no identifiers here.

## 3. Australia — already done, recorded here for completeness

Covered in `2026-08-31-destination-registers-recon.md` §1: CRICOS via `data.gov.au`, **CC-BY 2.5**,
four CSVs plus monthly XLSX snapshots back to July 2021, 1,554 providers of which **1,486 (96%) are
private**. The only register in the whole series with a real historical archive.

## 4. China — half-checked, and the half that was checked is the wrong half for a destination screen

`jsj.moe.gov.cn` responds (HTTPS 200; the `http://www.` form does not resolve). But this is the
**CSCSE recognition portal — foreign degrees being recognised *into* China**, which is the
list-publisher role already credited in synthesis §2 (~10,000 institutions across 44 countries).
That answers "will China accept this foreign degree", which matters only for a student returning to
China. **We have no students returning to China.**

**What was never checked is China as a destination**: which Chinese universities are authorised to
enrol international students, published by the Ministry of Education. That register was not located
in this pass. DEQAR sees 14 Chinese institutions, which is not a sector.

**Recorded as unchecked, not as absent.**

## 5. Japan — the reachable list is self-reported and says so

- **Study in Japan** (`studyinjapan.go.jp/en/search-for-schools/school_search.php`) responds 200 and
  offers a searchable directory of universities, graduate schools and junior colleges accepting
  international students. Its own caveat is disqualifying for a screen: **the information is supplied
  by the individual schools and does not include all such schools.** A self-reported, admittedly
  incomplete directory fails sourcing rule 1 the same way an agent site does.
- **The Immigration Services Agency** (`moj.go.jp/isa`) returned **HTTP 403** to this probe. The
  relevant Japanese gate is the immigration classification of institutions by the quality of their
  student acceptance record (the 適正校 / "appropriate school" distinction), which governs how heavily
  a student's visa application is scrutinised. **Not reached. Retry with a browser transport before
  concluding anything** — a 403 to `curl` is not a finding, per the same rule that governed
  Perplexity in the live-search recon.

Japan is therefore the one country of the five where **no usable register was established**.

## 6. Where this leaves the screen

| country | register | usable now |
|---|---|---|
| **UAE** | CAA institutes table | **yes** — 103 active, 55 inactive, 24 named revocations; terms unverified |
| **South Korea** | IEQAS certified list | **yes** — 184 certified, 43 excellent, dated 2026-03-03 |
| **Australia** | CRICOS via data.gov.au | **yes** — CC-BY 2.5, monthly, five years of history |
| **China** | MoE destination register | **not located** — the English portals no longer resolve; see §7c |
| **Japan** | **MEXT 改善指導対象校 list** | **yes** — named, with a published 5% criterion; see §7a |

**Two things generalise beyond these five.**

1. **Korea and the UAE both publish what Europe does not: an explicit negative.** Korea designates
   non-certified universities for stricter visa screening; the UAE keeps revoked institutions listed
   by name. Both are Part C material — published, official, dateable examples of providers that fail
   a screen — and neither research run found either.
2. **Every register in this series that covers a non-EHEA country is national, single-page, and
   unversioned.** None has an API, none carries a data date except Korea's, and none offers history
   except Australia's. Freshness has to be something we record on ingestion, because the sources will
   not tell us.

## 7. Follow-up pass, same day — the three open items

Chased immediately after the above. **Two of the three failures were transport, not policy**, which
is the reusable lesson: a 403 or a connection error against a government host is a fact about the
fetcher, not a finding about the register.

### 7a. Japan — solved, and the publisher is MEXT, not the Immigration Services Agency

**The 403 was a user-agent block.** `moj.go.jp/isa` returns 200 to a browser transport and serves its
full navigation. So the earlier "not reached" was our client, as suspected.

But the register is not the ISA's. **MEXT publishes it**, at
`mext.go.jp/a_menu/koutou/ryugaku/1412692_00005.htm`, as a web page with a PDF companion, and it is
a **named-and-shamed list with a published numeric criterion**:

- **改善指導対象校 — "Improvement Guidance Target Schools".** Criterion: international-student
  withdrawals exceeding **5% of the institution's international student population in one year**.
- The current designation names **two institutions**, with their numbers: **Tokyo Fukushi University**
  (2,470 international students, 152 withdrawals, **6.2%**) and **Nagoya Management Junior College**
  (94 students, 7 withdrawals, **7.4%**). Assessed on April 2023–March 2024 data.
- **Escalation is defined and severe.** Three consecutive years in that status means designation as
  **在籍管理非適正校**, which **may no longer accept international students at all**; MEXT announces it
  publicly and reports it to the Immigration Services Agency. That tier begins FY2027.

This is the cleanest Part C artefact in the entire series: an official list, a stated threshold, the
underlying counts, and a defined consequence. It is also **very short** — two institutions — which is
itself the finding. Japan's problem set is small and named.

Caveat carried forward: the designation date is given in a Japanese era year and was not converted
against a primary source. Read the date off the page before encoding it.

### 7b. UAE free zones — KHDA is reachable, but its TLS chain is broken

Not a block, and not absence. `web.khda.gov.ae` **serves an incomplete certificate chain**: the leaf
is valid (`CN = *.khda.gov.ae`, issued by `GlobalSign RSA OV SSL CA 2018`) but the server omits the
intermediate, so every standard client fails with *"unable to get local issuer certificate"*. Plain
`curl`, WebFetch and the browser transport all failed for this one reason. With verification
disabled the host returns **HTTP 200**, confirming the content is there.

**The fix is to supply the GlobalSign intermediate, not to disable verification.** Browsers succeed
here only because they fetch or cache intermediates themselves; a server-side fetcher will not. This
is worth writing down because the tempting shortcut — `verify=False` — would silently strip
certificate checking from a path this project deliberately hardens elsewhere.

**KHDA's directory contents remain unread.** The UAE free-zone question from §1 is therefore still
open, but it is now open for a reason we understand and can fix in a line of client configuration.

### 7c. China — the destination register was not found, and the cause is infrastructural

- **`studyinchina.moe.gov.cn` and `campuschina.org` do not resolve at all.** No DNS record, from any
  transport. The portal that historically listed Chinese universities admitting international
  students is simply gone at those names.
- **`jsj.moe.gov.cn` resolves IPv6-only** — `2001:da8:20d:22::253`, with no A record. That is why the
  first probe returned `000` on one form of the URL and 200 on another: it depends entirely on
  whether the client has IPv6. **A worker on IPv4-only networking cannot reach this host at all**,
  which is a deployment constraint, not a research one, and would otherwise be discovered in
  production.
- Its title identifies what it is: **中华人民共和国教育部教育涉外监管信息网**, the Ministry of
  Education's supervision network for foreign-related education. That is the **inbound** side —
  recognition of foreign qualifications into China, plus study-abroad warnings — confirming §4's
  reading. It is not a register of Chinese universities open to international students.

**China's destination register stays unlocated**, and the next attempt should start from MOE's
Chinese-language site rather than the English portals, over a connection with IPv6.

> **Closed 2026-08-31 in `2026-08-31-register-open-questions-closed.md` §5.** MOE publishes all 3,167
> Chinese higher education institutions but **no register of those authorised to enrol international
> students** — that is per-institution under the 2017 Measures, so China is case-by-case on the
> destination side. Also correcting the line above: **`moe.gov.cn` answers over IPv4 normally**; only
> `jsj.moe.gov.cn` is IPv6-only.

## 8. Not established here

- **CAA's terms**, and the contents of Dubai's **KHDA** free-zone directory — reachable but blocked by
  a broken TLS chain until the intermediate is supplied (§7b). Until it is read, absence from the CAA
  table means nothing for a Dubai free-zone provider.
- **A data date for the CAA register.** None is published; the visible footer date is CMS chrome.
- **China's destination register** — and note the host that survives is IPv6-only (§7c).
- **The Japanese era-year conversion** on the MEXT designation date (§7a).
- **Whether Korea's IEQAS list is archived year to year.** It is described as annual; only the
  current year was seen, so a student's certification status at enrolment time may not be recoverable.

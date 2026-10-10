# Reconnaissance — the three remaining destination registers: CRICOS, ILEP, NZQA

**Date:** 2026-08-31. **Status: NOT a research run.** The companion to
`2026-08-31-safety-screen-register-recon.md`, covering the three registers that document left in Part
D. Same method: fetch the thing, parse it, count it, quote the licence.

**Why these stopped being optional.** `2026-08-31-screen-coverage-measurement.md` §4 measured what
DEQAR can see in the English-speaking destinations: **United States 4 of 286 institutions, Canada 3,
Australia 2, New Zealand 0.** For those countries the QA leg returns nothing, so these registers are
not a second opinion — they are the only gate there is.

**Result in one line.** Australia is the best-published register of the seven examined; New Zealand
publishes a quality ladder nobody in either research run mentioned; **Ireland's ILEP is being
retired and must not be built against.**

---

## 1. Australia — CRICOS, and it is open data

`cricos.education.gov.au` itself did not respond (curl exit 28, no status). **The reliable route is
the open-data mirror**, which is the same register published by the Department:

`data.gov.au`, dataset `e5ae7059-bfa8-4fa4-a5c0-c13cf3520193`, "Commonwealth Register of Institutions
and Courses for Overseas Students (CRICOS)".

- **Licence: Creative Commons Attribution 2.5 Australia (`cc-by-2.5`)** — stated in the dataset
  metadata, not inferred.
- **Four CSVs**, no authentication: `cricos-institutions.csv`, `cricos-courses.csv`,
  `cricos-locations.csv`, `cricos-course-locations.csv`, plus a combined ZIP and a PDF provider
  export.
- **Cadence: monthly.** The dataset also retains a **monthly XLSX snapshot back to July 2021** — about
  50 dated files. That is a history no other register here offers: a provider's disappearance between
  two months is retrievable, which is exactly the "was this provider licensed when the student
  enrolled" question the brief's §A4 asked and expected to be unanswerable. CSVs last modified
  2026-08-04.

**`cricos-institutions.csv`** — 216,393 bytes, **1,554 providers**, 13 columns:
`CRICOS Provider Code, Trading Name, Institution Name, Institution Type, Institution Capacity,
Website, Postal Address …`.

**The measured fact that matters:**

| Institution Type | providers |
|---|---|
| **Private** | **1,486 (96%)** |
| Government | 66 |
| blank | 2 |

CRICOS is overwhelmingly a register of **private** providers. Being on it means "permitted to enrol
overseas students", nothing about quality — so in Australia, unlike Germany, a register hit is a
weak signal and the provider category is the strong one. Any screen that treats CRICOS membership as
a safety clear will clear 1,486 private colleges.

State spread: NSW 512, VIC 497, QLD 283, WA 104, SA 101, ACT 25, TAS 19, NT 11.

## 2. Ireland — two lists are live at once, and one of them is frozen

**Ireland cannot be checked against a single list today, and that is the finding.** The ILEP is
closed to new providers and frozen, but it has *not* stopped operating; TrustEd Ireland is being
built alongside it. A provider may recruit non-EEA students if it appears on **either**. Checking one
returns a wrong answer for the other's providers.

`irishimmigration.ie`, ILEP page, fetched 2026-08-31, quoted:

> "The ILEP is closed. Providers without programmes currently listed in the ILEP must have gained
> TrustEd Ireland authorisation before recruiting non-EEA nationals."

> "The final ILEP update was published on **20 June 2025**."

> "Where a provider has programmes listed in the ILEP and remains in compliance with ILEP criteria,
> **it may continue to recruit non-EEA nationals until the ILEP ceases operation.**"

So as of today the two lists partition Irish providers: those grandfathered on the frozen ILEP, and
those authorised under TrustEd since. Neither is a superset of the other until the ILEP ceases.

**The frozen list is a trap of the exact kind sourcing rule 3 names — a stale clear is worse than no
answer.** The same page states removals continue: *"Instances of non-compliance may result in removal
from the ILEP of all of a provider's programme listings."* The list can therefore **shrink after the
date it was last published**. A provider read out of the 20 June 2025 file may have been removed in
the fourteen months since, and the published file would not show it. Treat any ILEP hit as
**"listed as of 2025-06-20"**, never as "currently eligible".

The ILEP criteria themselves were updated 21 March 2025 and are published as three PDFs
(`HE-Prog-Criteria`, `EL-Prog-Criteria`, `Foundation-Criteria`) — rules for staying listed, not a
register.

**Do not build a gate on the ILEP.** It is being replaced by **TrustEd Ireland**, a statutory quality
mark issued by QQI.

QQI, quoted from its higher-education TrustEd page, fetched 2026-08-31:

> "Authorisation to use TrustEd Ireland will be required by providers in order to be eligible to
> recruit non-EU/EEA/Swiss learners. There will be a two-year transition period from the ILEP to
> TrustEd Ireland."

> "This list will cease to operate following the completion of the second TrustEd Ireland window in
> 2026."

The second application window opened 1 September 2025 and is described as the final opportunity to
apply before the interim list closes. **28 higher education institutions** were authorised in January
2026; English-language providers followed in August 2026. `irishimmigration.ie` carries a
policy statement dated February 2026, "TrustEd Ireland Scheme and Immigration Requirements".

**No machine-readable list of authorised providers was found.** QQI's own TrustEd pages do not
publish one; the authorisations are announced as news items. The ILEP page links only programme
*criteria* PDFs (`HE-Prog-Criteria-21-March-2025.pdf`, `EL-Prog-Criteria-21-March-2025.pdf`,
`Foundation-Criteria-21-March-2025.pdf`) — rules, not a register.

**This is the weakest register of the seven** — the only one where a correct answer today requires
reading two sources, one of which is fourteen months stale and can silently shrink. Ireland stays a
consultant check. Revisit once the second TrustEd window closes at the end of 2026 and QQI publishes
a consolidated list — and check then whether it is published as data or only as prose.

## 3. New Zealand — NZQA publishes a quality ladder, and nobody mentioned it

`nzqa.govt.nz/providers/index.do` — **3,363 education organisations**, with a query endpoint that
answers the two questions the screen needs.

```
GET /providers/results.do?regionCode=&typeCode=&category=&copApprovalStatus=&nameQuery=
```

Server-rendered HTML, **no pagination**: `copApprovalStatus=Y` returns all **1,995** signatories in
one 409,307-byte response. **Licence: Creative Commons Attribution 4.0**, per NZQA's copyright page
— *"NZQA materials on this website are licensed under the Creative Commons by Attribution 4.0
International Licence."*

**Two gates in one register:**

- **`copApprovalStatus`** — signatory to the Tertiary and International Learners Code of Practice.
  A provider must be one *before* it may enrol international students. This is New Zealand's
  equivalent of the UK sponsor licence.
- **`category`** — NZQA's own published judgement of the provider, 1 (best) to 4 (worst), covering
  non-university providers. NZQA's definitions: Category 1 is two Highly Confident judgements;
  Category 3 is *"any Not Yet Confident judgement"*; Category 4 is *"any Not Confident judgement"*.

**Measured, filtering on both at once:**

| category | providers that may enrol international students |
|---|---|
| 1 | 103 |
| 2 | 61 |
| **3 — any Not Yet Confident judgement** | **7** |
| **4 — any Not Confident judgement** | **2** |

**Categories 3 and 4 are a published, official list of nine providers the regulator itself rates
poorly and which may still recruit international students.** Part C of the brief asked for
exclusion criteria with concrete published examples; this is the only register examined that hands
one over directly, dated and by name.

**Cost.** The results table carries only Name and Location — category and COP status are not columns.
But the *filters* recover them, so **eight queries** (four categories × signatory yes/no) reconstruct
the mapping, instead of 3,363 per-provider detail fetches. That is the whole difference between
usable and not, and it is the same lesson as anabin: query the server, do not walk the corpus.

## 4. What this changes

1. **Australia is solved and cheap.** Open data, CC-BY 2.5, monthly, with five years of history.
   Treat *Institution Type* as the signal, not membership.
2. **Ireland is deferred, not solved**, and the deferral is now dated: end of 2026. A screen built on
   the ILEP would break on a published schedule — and in the meantime would be wrong twice over,
   because the frozen list omits every TrustEd-authorised provider and still contains any provider
   removed since 20 June 2025.
3. **New Zealand gives us both gates and an exclusion list**, under CC-BY 4.0, in eight requests.
4. **The seven registers now split three ways**, and the product must not present them as one:
   - *quality judged*: DEQAR (report exists), NZQA (category 1–4)
   - *permission to enrol internationals*: UK sponsor register, Canada DLI, CRICOS, NZQA COP
   - *recognition of the qualification at home*: anabin, China MoE — and nothing else, per §2 of the
     synthesis.
   A provider can hold the second and fail the first. CRICOS at 96% private and NZQA's nine
   Category 3/4 signatories are the same fact stated twice.

## 5. Not established here

- **A machine-readable TrustEd Ireland list.** None exists yet as far as this probe reached.
- **CRICOS provider *status history* semantics.** The monthly snapshots exist; whether a provider
  vanishing between two files means suspension, cancellation or a name change was not tested.
- **NZQA `typeCode` values.** The label `University` is not the parameter value; the code list was
  not extracted.
- **Whether NZQA rate-limits.** Eight requests were made without incident; nothing larger was tried.
- **Australia's TEQSA National Register**, which is the degree-awarding-authority list and therefore
  the answer to leg A2 for Australia. Not probed — CRICOS answers enrolment permission, not who
  awards the degree.

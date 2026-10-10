# What the safety screen actually returns — measured over DEQAR, 2026-08-31

**Status: a measurement, not a research run.** It answers the last open item in
`2026-08-31-open-admission-synthesis.md` §8 — that no pre-run recon existed, so nobody checked
whether both runs converging on Germany was a finding or an artefact of the brief's own framing.

**Method.** The screen rule as §7 states it, applied to the DEQAR daily CSVs pulled in
`2026-08-31-safety-screen-register-recon.md` §2: *an institution is screenable if at least one
quality-assurance report on it comes from an agency currently registered with EQAR.* Registration
status is `deqar-agencies.csv::is_registered` — 60 of 78 agencies read `Registered`, 18 read
`Previously registered`. All counts below are from those files, not from any page.

---

## 1. The screen is not Germany-biased. The brief was.

**5,027 of 9,018 institutions pass, spread across 131 countries.** Germany is 9% of them, in fourth
place.

| country | screenable | share |
|---|---|---|
| Spain | 1,018 | 21% |
| **Germany** | **437** | **9%** |
| Poland | 415 | 9% |
| France | 383 | 8% |
| Türkiye | 161 | 3% |
| Kazakhstan | 149 | 3% |

Germany did not come out of the mechanism. It came out of the brief's affordability framing plus a
research run that ran out of budget — run A said so in as many words. **Poland and Kazakhstan, the
two the run named as unreached, are already screenable at 415 and 149 institutions.** Part B being
three rows long was a budget limit, not a limit of the method.

Requiring the agency to be *currently* registered costs almost nothing at corpus scale: 5,119 →
5,027, just **92 institutions**.

## 2. Those 92 are two countries, and one of them nobody mentioned

| country | institutions losing screenability |
|---|---|
| **Georgia** | **52** (60 with reports → **8 screenable**) |
| **Russia** | **33** |
| China | 5 · Switzerland 1 · Spain 1 |

Georgia is the case §4 of the synthesis found. **Russia is the same case and appears in neither run
nor the synthesis** — its agency AKKORK also reads `Previously registered`. Any rule written for
Georgia silently applies to Russia too, so it had to be decided rather than discovered later.

**Decision, taken by the project owner 2026-08-31: Russia is excluded as a study destination and
retained as a funder.** Russian institutions do not enter the safety screen or any
easy-admission surface. Russian *scholarship* schemes stay in scope and stay listed in
`PROMPT-government-inbound-sweep.md`. The two are different questions — where a student studies, and
who pays — and the exclusion answers only the first. The ground is visa and political risk on top of
the QA gap, which is a business judgement, not something the data decides.

**Decision, same date: no single launch country.** The screen is to cover every country it can reach,
worked through one at a time rather than narrowed to one market up front.

## 3. The finding nobody was looking for: coverage varies from 98% to 6%

Screenable as a share of institutions **listed** in DEQAR, by country:

| high | | low | |
|---|---|---|---|
| Hungary | 98% | France | 63% |
| Cyprus | 98% | Bulgaria | 51% |
| Croatia | 96% | Slovenia | 48% |
| Indonesia | 96% | Italy | 47% |
| Latvia | 96% | UK (England) | 37% |
| Norway | 94% | **Ukraine** | **6%** (707 listed, 41 screenable) |

**This is the rule the product needs and did not have: absence from the screen means different things
in different countries.** In Hungary or Croatia, an institution with no current QA report is a real
signal — nearly all its peers have one. In Ukraine, Italy or England it is close to meaningless,
because most listed institutions have no qualifying report either. A screen that renders "not
verified" identically in both cases will libel Ukrainian universities and flatter English ones.

Carry the country's coverage rate alongside every negative result, or do not show negatives at all.

## 4. DEQAR is useless for the English-speaking destinations — which makes the other registers mandatory

| destination | listed | screenable |
|---|---|---|
| United States | 286 | **4** |
| Canada | 3 | **3** |
| Australia | 2 | **2** |
| New Zealand | 0 | **0** |
| Ireland | 40 | 34 |
| UK (England / Scotland / Wales) | 270 / 24 / 15 | 100 / 18 / 15 |

The screen effectively **cannot see** the US, Canada, Australia or New Zealand. That reframes
§9d's destination registers: Canada's DLI list and the UK sponsor register are not a convenient
second leg, they are **the only mechanism** for those countries — and **CRICOS (Australia), ILEP
(Ireland) and NZQA (New Zealand) stop being Part D nice-to-haves.** Without them those destinations
have no gate at all.

## 5. Two corrections to the synthesis

- **Indonesia is covered.** §8 lists Indonesia's *penyetaraan ijazah* under "neither run reached
  primary depth, Part D by default". DEQAR holds **81 Indonesian institutions, 78 screenable (96%)**
  — one of the best coverage rates of any country. The *recognition* question there is still open;
  the *quality-assurance* question is not.
- **DEQAR is not EHEA-only.** Both runs treated it as a European database. It spans **137 countries
  with listed institutions, 131 with screenable ones**, including Kazakhstan (149), Türkiye (161),
  Indonesia (78) and Armenia (34). The real coverage bias is toward Europe, not toward Germany, and
  it is a bias of *depth*, not of presence.

## 6. Blind spots are small, and one is a parsing artefact

Only **6 countries, 16 institutions**, are listed with zero screenable: Holy See (11), Martinique,
New Caledonia, Paraguay, and a `Korea` / `South` pair that is **a CSV artefact** — the country name
"Korea, South" splits on its own comma. Anything parsing `deqar-institutions.csv::country` must treat
that field as a quoted list, not split naively, or it will invent countries.

## 7. What this does not answer

No register measured here holds **price, entry requirements, or teaching language** — the other half
of what the brief asked for. Those live on the institutions' own programme pages, which is what the
extraction pipeline on `claude/claims-merge-money-design` reads. **The screen says an institution is
real; the pipeline says what it costs and who it admits. Neither is usable alone, and that dependency
is stated nowhere else in these documents.**

**Amended 2026-08-31 — this is true everywhere except the United States.**
`2026-08-31-us-registers-recon.md` found that the US Department of Education publishes admission
rate, tuition, accreditor and graduate earnings for 6,273 institutions in one free 23 MB file with no
key: 882 institutions admitting 80% or more, 127 admitting essentially everyone. So the data model
must let a country supply selectivity and cost **directly**, rather than assuming both always come
from reading programme pages.

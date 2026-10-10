# The three gaps that survived four register recons — 2026-08-31

**Status: NOT a research run.** Prompted by the question "nothing else to research?", asked after this
series had twice been declared finished. It was not finished twice. These are the three gaps that
were named in earlier documents and then not acted on.

**One of them breaks an assumption the screen is built on.**

---

## 1. Degree-awarding versus teaching rights — Australia answers it outright

The brief's leg A2 asked where a body may legally *teach* but not *award its own degrees*. Every
register in this series answers "may this provider operate" or "may it enrol foreign students".
**None answered whose degree the student receives.** Australia does.

**TEQSA's National Register** (`teqsa.gov.au/national-register` — plain `curl` gets no response at
all; a browser transport returns it, the fourth government host in this series to behave that way)
publishes the distinction as a summary table:

| provider category | self-accrediting | **not** self-accrediting | total |
|---|---|---|---|
| Australian University | 44 | 0 | 44 |
| University College | 8 | 0 | 8 |
| Institute of Higher Education | 23 | **144** | 167 |
| **total** | 75 | **144** | **219** |

**144 of 219 Australian higher education providers hold no self-accrediting authority** — their
courses are accredited by TEQSA rather than by themselves. That is leg A2, published, counted, and
free. The provider *category* is the answer, which is the same lesson CRICOS taught: in Australia the
category carries the signal, not the membership.

**TEQSA also publishes two things Part C asked for**, on the same register:

- **Unsuccessful applications** for registration.
- **A list of unregistered entities** — bodies advertising higher education without registration.
  Currently **three**, published 21 December 2021, page last updated 16 January 2024. TEQSA states the
  consequence plainly: *"awards from unregistered entities are not recognised in Australia"*, and
  *"You will not be awarded a higher education qualification on completion of your study."*
  It also disclaims: *"We make no comment that any particular entity published in this list is in
  breach of the TEQSA Act."*

**The UK is only half done.** The OfS Register gives each provider a page covering *"whether the
provider has the power to award degrees and at what level"*, and a CSV of providers with current
degree awarding powers is referenced — but the route points at
`regulation@officeforstudents.org.uk` rather than a download URL. **Published per provider,
bulk availability unconfirmed.** Leg A2 is therefore answered for Australia, partially for England,
and nowhere else.

## 2. Türkiye's blacklist — and it breaks the screen's unit of analysis

**This is the finding that matters, and it is not the list itself.**

YÖK maintains a list of **41 higher education institutions whose graduates are refused equivalence**,
on grounds of FETÖ/PDY affiliation. They span the USA, Canada, Australia, Albania, Azerbaijan,
Afghanistan, Belgium, Bosnia-Herzegovina, Georgia, Indonesia, Iraq, Cambodia, Kazakhstan, Kyrgyzstan,
Colombia, Kosovo, Nigeria, Poland, Romania and Turkmenistan.

**It does not operate at institution level.** The list names **institutes, centres and chairs inside
otherwise reputable universities** — reported examples include a named institute within the
University of Houston and a research chair at Deakin University. **Students of those units are
refused equivalence even though the parent university is not listed.**

**Every register in this series is keyed to an institution or a campus.** A screen built that way
would clear the University of Houston, clear Deakin, and never be able to express that a specific
unit inside them is excluded for a Turkish student — in one of our two launch markets. Neither
research run surfaced this, and it is not a data-collection problem: **it is a data-model problem, and
it has to be settled before the schema is written, not after.**

**Sourcing warning, and it is the important part.** Everything above is from Turkish news and
consultancy sites. **The primary YÖK source was not reached** — `yok.gov.tr/ogrenci` and the guessed
list path both return 404; `denklik.yok.gov.tr` responds (HTTP 200) and was not explored further.
**None of the 41, and none of the named sub-units, may be encoded from these sources.** This is
precisely run B's failure mode from §3b of the synthesis: a real finding arriving through a
forbidden source. The finding to keep now is the *structural* one — sub-institutional exclusion
exists and the model must allow it. The list itself needs primary sourcing.

## 3. Norway — closed, negatively, and it settles the portfolio floor

Open since §8 of the synthesis and never revisited. **Norway is not a second tuition-free
destination.**

`studyinnorway.no/cost-and-requirements`, the official portal, fetched 2026-08-31:

> "Degree seeking students from outside of EU/EEA and Switzerland **must normally pay tuition fees**
> when studying in Norway. The tuition fees varies between institutions and study programmes."

The same page states the study-permit requirement: **NOK 15,488 per month, NOK 170,368 per year
(2026-2027)**. Secondary sources put actual fees at roughly NOK 150,000–190,000 per year
(≈€13,000–17,000) with institutions setting their own rates — that range is **not** primary-sourced
and should be re-checked per institution before use, but the direction is not in doubt because the
official page states fees are normally payable.

**Consequence for §7.5 of the synthesis: Germany remains the only tuition-free public floor either
run identified, and it now stands alone on purpose rather than by absence of checking.** Norway's
living-cost requirement alone (NOK 170,368) exceeds Germany's blocked-account minimum (€11,904)
before any tuition is added.

## 4. What these three change

1. **Leg A2 is answerable in Australia and half-answerable in England, and nowhere else.** Record
   self-accrediting status where a regulator publishes it; treat its absence elsewhere as unknown
   rather than as "awards its own degrees".
2. **The exclusion model must be finer than the institution.** Türkiye excludes named units inside
   listed-clean universities. Every register we hold is institution- or campus-keyed. **Design for a
   sub-institutional exclusion record now**, even though only one market is known to need it.
3. **Germany is the only free floor.** Norway is closed, negatively, on the official source.

## 5. Not established here

- **The YÖK list itself, from a primary source.** Structural finding usable; contents not.
- **The OfS degree-awarding-powers CSV**, if a public download exists.
- **Whether other markets besides Türkiye exclude sub-institutional units.** Only one was checked, and
  it was the one that turned out to matter.
- **Malaysia (MQA)**, still unexamined, and a plausible market for our students.

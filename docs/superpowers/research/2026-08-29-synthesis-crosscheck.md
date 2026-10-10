# Adversarial cross-check over the finished syntheses

**Date:** 2026-08-29. **Method:** cheap searches probing what each synthesis's *taxonomy*
structurally excludes, rather than searching inside its categories. Run after the Fulbright miss
showed that four deep-research runs can share a blind spot inherited from the prompt's own framing.

**Cost:** four searches. **Result:** three real gaps, one confirmed non-gap.

The test used throughout: grep every synthesis for a concept; **zero mentions across all of them is
a taxonomy signal, not a coincidence.**

---

## 1. Work during study — the most consequential gap

**Zero mentions across every synthesis and every spec.** The corridor research covered **post-study**
work rights thoroughly — they feed `MOBILITY_FIT` and the utility function — and nobody asked
whether a student can work *while enrolled*.

| Destination | Term-time limit | Note |
|---|---|---|
| Germany | 20 h/week; **140 full days or 280 half-days per year** | Minimum wage €13.90/h → **≈ €1,112/month**. On-campus HiWi posts are exempt from the annual cap |
| South Korea | 20 h/week during semester, **unlimited during official vacations** | Strictly enforced; exceeding it is a visa violation |
| UK | 20 h/week (10 for some courses) | **A student sponsored for a part-time postgraduate course may not work at all** |
| USA | 20 h/week in session, full-time in breaks | On-campus / CPT / OPT rules apply |

**Why this is a defect and not an enrichment.** `risk-aware-portfolio-design.md` §2 says a candidate
"whose unfunded cost exceeds what the student can cover has no `u_unfunded` — that outcome is not
available to them." Work income appears nowhere in that test.

So the optimizer currently discards outcomes that are genuinely available. **Germany is the worst
case**: public universities charge only a semester fee, and €1,112/month of permitted work income is
of the same order as the €992/month DAAD stipend. A German programme can be *unaffordable unfunded
on paper and affordable in practice* — and the engine would never surface it, silently, with no
disclosure that a widening exists.

**The UK detail is the dangerous kind**: work rights interact with **study mode**. Recommend a
part-time postgraduate course to a student relying on work income and the recommendation is not
merely suboptimal, it is wrong in a way nothing in the current model would catch.

**What it is not.** Work income is not a funding route and must not be modelled as one. It is a
**property of the destination and the study mode that changes the affordability test**, and it
carries its own risk — the income is not guaranteed, it depends on finding a job in a language the
student may not speak. It belongs in the affordability dimension with an explicit caveat, never as a
component of `covers_commitment_payment` or of any funded outcome.

## 2. Sub-national government schemes — a whole tier

**Zero mentions across every synthesis.** The instrument landscape enumerated *national* instruments
for eight corridors. Federal and devolved states run their own, and they were never in frame.

- **Bavarian Scholarship Programme** — Bavarian State Ministry of Science and the Arts
  (`study-in-bavaria.de`), for international students at Bavarian state universities, applications
  through university international offices, needs-and-merit based.
- **BAYHOST** — the Bavarian Academic Centre for Central, Eastern and Southeastern Europe, funding
  graduate students from Bulgaria, Croatia, Poland, Romania, Russia, Serbia, Slovakia, Czechia,
  Ukraine and Hungary. **This is sub-national *and* nationality-keyed — a double miss**, sitting in
  the intersection of two prompts and caught by neither.

Spain's autonomous communities, Canada's provinces and Switzerland's cantons are the obvious places
to look next. The generalisable rule: **in a federal or devolved state, "the government" is not one
funder.**

## 3. Political-foundation scholarships — neither state nor corporate

**Zero mentions.** Germany's party-affiliated *Stiftungen* fund international master's students
directly and substantially:

| Foundation | Master's rate |
|---|---|
| Konrad-Adenauer-Stiftung | €992/month, 2 years |
| Heinrich-Böll-Stiftung | €934/month |
| Friedrich-Ebert-Stiftung | International access restricted — EU citizenship or permanent residence |
| Ernst Ludwig Ehrlich Studienwerk | Restricted availability for internationals |

These fall between our categories: not a state instrument, not a corporate sponsor, not a diaspora
or affinity body. `FundingFamily` has no obvious slot — the nearest is `INDUSTRIAL_SPONSORSHIP`,
which is plainly wrong for a party foundation.

Several carry **non-financial eligibility conditions** that are unusual and decisive: Adenauer
expects endorsement of Christian Democratic values, and several require C1 German even for
English-taught programmes. Those are exactly the conditions a nationality-only eligibility model
cannot express — the same defect §7 of the nationality-keyed synthesis raised about ADB-JSP's work
and income tests.

## 4. Confirmed non-gap — OpenAlex and Wikidata

Checked and **rejected on merit**, recorded so it is not re-proposed.

OpenAlex is CC0, covers ~109,000 institutions, links ROR/Crossref/ORCID/Wikidata, and is adding
funder metadata under a Wellcome grant. It is nonetheless **the wrong shape twice over**:

1. It is a **bibliographic** catalogue — research outputs, authors, citations. It does not know
   which institutions offer which master's programmes, which is what tier 2 needs.
2. Its funder and grant side is **research funding**, which is precisely why CORDIS and KAKEN were
   dropped: they fund doctoral and postdoctoral research, not master's training.

Its institution frame duplicates ROR, which we already use. **No action.** This is the same
reasoning that dropped CORDIS, applied before building rather than after.

## 5. Visa lead time — the schedule has no term for it

**Corridor mechanics synthesis.** It established what money must be *shown* and *committed*, and
when. It never asked **how long the visa itself takes**, and the answer is long enough to change
decisions.

German student-visa processing runs **4–12 weeks** and varies by post: Türkiye min. 4 weeks, Russia
6–8, Ukraine 12–15, India 12. **Appointment queues are a separate and larger delay** — Mumbai VFS
10–12 weeks merely for a slot, and one post reported an 8-month waiting list. The German mission in
Mumbai maintains a formal student-visa waiting list.

**Why this is a schedule defect.** §8.3 puts the wait/commit pivot at the deposit deadline. But a
student can be admitted, funded, pay the deposit, and **still not reach the country in time**. Where
an appointment queue runs months, the constraint binds at *application* time, a year ahead — long
before any deadline the model currently reasons about.

**And there is an interaction worth having.** Several German posts process faster for students
holding a scholarship from a German public institution such as DAAD. So a funded and an unfunded
outcome differ **not only in money but in feasibility** — the funded route can be the only one that
arrives before the start date. `u_funded` and `u_unfunded` currently differ "mainly on the
affordability dimension"; this is a second axis.

`DestinationPolicy` should carry visa processing time and appointment-queue length **per origin
post**, not per destination — the figures above vary by consulate, not by country.

## 6. Undermatching — the portfolio theory synthesis has no behavioural evidence

The portfolio theory synthesis is thorough on what the *optimal* portfolio is — Chade & Smith,
Ali & Shorrer, Kapur & Hong. It contains nothing on whether students actually build one, which is
**the empirical warrant for this product existing.**

The literature is strong and directly on point. Hoxby & Avery: *"the vast majority of very
high-achieving students who are low-income do not apply to any selective college or university."*
Hoxby & Turner's Expanding College Opportunities project — a **randomised controlled trial** —
found that semi-customised information on the application process and net prices *"substantially
raises students' probability of applying to, being admitted at, enrolling at, and progressing at
selective colleges,"* with treated students admitted to **12% more colleges** and **31% more likely
to be admitted to a peer institution.**

Two consequences:

1. **It is evidence the intervention works**, from an RCT, for a population defined by information
   scarcity rather than ability — which is our population.
2. **It predicts a specific failure mode we should expect and measure**: students systematically
   under-apply to reaches. §7's optimizer produces a reach-and-safety portfolio; the behavioural
   literature says the student's prior is skewed against the reach, so a pack that merely *offers*
   one may not be enough. The undermatching rate is a candidate calibration metric for §10.

This is a **literature gap, not a source gap** — it needs a reading pass, not a research run. Verify
the citations before anything load-bearing rests on them, per §14 item 6's existing rule.

## 7. What the method is worth

Four searches found three gaps that six deep-research runs did not. The runs were not poor — they
were good, and each answered its prompt well. **The gaps were inherited from the prompts' own
categories**, and no amount of depth inside a category finds what the category excludes.

Sub-national government, work-during-study rights, and party foundations are each *invisible* to a
question framed as "which national government or bloc funds master's study" — the framing that
produced every prompt in this programme.

**Run this pass after every synthesis.** It is cheap, it is adversarial to our own framing rather
than to the sources, and its yield so far is four findings from seven searches across two sessions.

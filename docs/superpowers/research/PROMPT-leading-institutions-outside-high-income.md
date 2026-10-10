# Deep research prompt — funded master's places at leading institutions outside the high-income core

**Status:** ready to run. Written 2026-08-29. Run twice, independently, so the results can be
adjudicated.

**Why this exists.** The catalogue is skewed toward expensive destinations. A strong applicant who
cannot pay Western fees may be best served by a leading institution in a middle-income country that
funds international master's students directly — IIT-class in India, ADA in Azerbaijan, and their
equivalents. These are **floor-makers**: full-cost places a student can apply for without a
nomination.

The engineering side is already solved. Entity expansion reaches any institution's own pages, and
ROR supplies the institution list free (2,106 education organisations in India, 52 in Azerbaijan,
96 in Kazakhstan, 239 in Türkiye). **What is missing is knowing which institutions are worth
pointing at** — this run answers that.

---

## Prompt

Identify **institutions outside the high-income core that fund international master's students**,
and say what they fund.

### Geographic scope, in priority order

1. **Azerbaijan and Türkiye** — the launch markets, and both sides of the question at once. These
   are where our students come *from*, and also places where a strong regional institution on a
   funded place is a genuine option rather than a consolation. Cover both countries properly before
   moving on.
2. **Georgia, Armenia, Kazakhstan, Uzbekistan** and the wider Turkic world.
3. **India, Pakistan, Vietnam, Indonesia** — the phase-2 markets, and the same duality applies:
   IIT-class institutions are both a destination for others and a home option for their own
   citizens.
**Tiers 1–3 are this run's scope. Do not attempt the rest.** Listed only so a later run knows where
to resume: Malaysia, Thailand, Egypt, Jordan, Morocco, South Africa, Rwanda, Ghana, Kenya, Brazil,
Mexico, Chile; and Russia and China, whose large state-funded international intakes come with
political and mobility constraints that need their own treatment.

**Capacity rule.** Part B is the highest-value section and needs only a **sample of 15–20
institutions**, not exhaustive coverage — finish it properly even if Part A is shorter than you
would like. Part A's value is breadth of *institutions*, so twenty institutions each with a
confirmed funded route beats three documented exhaustively.

### Part A0 — a floor shape found on 2026-08-29, and not anticipated by this prompt

Before Part A, cover **state-supported international dual-degree programmes at home institutions.**
The outbound research turned this up as a live instrument, and it is a different object from anything
the table below describes: **a degree begun at a home institution with a foreign partner, delivered
partly abroad, funded domestically at the level of the programme rather than the student.**

Azerbaijan publishes six on `dp.edu.az` (`/az/content/29`, retrieved 2026-08-29):

| Home institution | Foreign partner |
|---|---|
| ADA University | George Washington University (US) |
| Azerbaijan State Pedagogical University (ADPU) | George Washington University (US) |
| Baku Engineering University (BMU) | INHA University (Korea) |
| Azerbaijan State Agricultural University (ADAU) | Ege University (Türkiye) |
| Baku State University (BDU) | Hebrew University of Jerusalem (Israel) |
| Azerbaijan State Oil and Industry University (ADNSU) | University of Warwick (UK) |

They are live: ADAU students began their next stage at Ege in August 2026, and the agriculture
programme was publicised the same month.

**Why this belongs in a prompt about floor-makers.** Both Azerbaijani and Turkish state outbound
instruments were established on 2026-08-29 to be unusable as portfolio floors — Azerbaijan's funds
only an admission the student already holds, and Türkiye's YLSY binds the graduate for twice the
funded period with guarantors. A dual-degree place at a home institution is the state's own answer to
the same problem, and it may be the closest thing to a floor these markets have.

**Establish, for each and for equivalents elsewhere in scope:**

1. **Whether it exists at master's level**, or only at bachelor's. **Not yet established, and it
   decides whether any of this is in scope.** Do not assume.
2. **Who pays what.** The financing rule (Cabinet decision No. 450 of 20 November 2019) divides costs
   into design costs, steering-committee costs, local faculty costs and similar — **this is funding of
   the programme, not of the student.** So establish separately what the *student* pays: home tuition,
   partner-institution tuition, living costs abroad, and whether any of it is waived.
3. **How much time is spent abroad**, and on whose visa and cost.
4. **The application route** — direct to the home institution, or a separate competition.
5. **What the award is**, if any: is this a funded place, or a cheaper route to a foreign-partnered
   qualification that the student still pays for? Those are very different products, and the
   distinction decides whether it is a floor at all.

**The administrative fact that explains where to look.** These sit under a *different* State
Programme from the outbound one — the **State Programme on increasing the international
competitiveness of the higher education system** (Cabinet decisions 450 and 451, both 20 November
2019) — administered by the same management group, DPİQ. That shared administrator is why prior
research kept merging adjacent Azerbaijani instruments. Keep them apart here.

**Then generalise.** Türkiye, Georgia, Kazakhstan, Uzbekistan, India and Pakistan all have national
internationalisation programmes; establish whether any funds equivalent home-institution dual degrees,
and treat a partner-degree route you find outside Azerbaijan as a more valuable finding than the six
above, which are already known.

### Part A — institutions with funded international master's places

| Column | Notes |
|---|---|
| Institution | Name, country, and **ROR ID** if you can find it |
| Scheme name | The specific award, not just "scholarships available" |
| **Application route** | **`DIRECT` / `NOMINATED` / `AUTOMATIC_ON_ADMISSION`.** Quote the sentence. `AUTOMATIC_ON_ADMISSION` is the most valuable category we can find — it is a funded place with no separate competition |
| Eligible nationalities | Any restriction; note explicitly if our priority nationalities qualify |
| Fields | |
| What it covers | Tuition waiver / stipend / accommodation / travel. State whether living costs are covered — a tuition-only waiver in a city the student cannot afford is not a floor |
| Teaching language | **Decisive.** An English-taught master's is usable; a Russian-, Turkish-, Chinese- or Hindi-taught one is usable only by some students. State the language of instruction explicitly |
| Tuition if unfunded | The fallback cost, since some of these are affordable even unfunded |
| Official URL | The institution's own page |
| Where the funding page lives | The **URL path** — this tells us whether our path triage would find it |

### Part B — the structural question

For each institution, note **whether its funding information sits on a funding-shaped URL**
(`/scholarships/`, `/funding/`, `/financial-aid/`) **or inside a programme page** with no funding
term in the path.

This is not incidental. Our discovery triages candidate pages by path substring, so an award
described in the body of `/admissions/masters-programmes/data-science` is structurally invisible to
it. **Report the ratio you observe**, with examples of each. If funding at these institutions
typically lives inside programme pages rather than on dedicated ones, that changes how discovery
must work far more than any individual scheme found here.

### Part C — is there any list?

Does any body publish a list of institutions offering funded international master's places in these
regions?

**Derive the set of bodies to check rather than working from a list.** Ask who would have a reason
to publish such a list: a government marketing its own institutions abroad; a regional bloc
promoting mobility between members; a development agency funding education in these countries; a
university network or consortium; an accreditation or quality-assurance body. Then name who fits
each category for the regions in scope, and check them.

Known candidates worth checking regardless — a floor, not the scope: national ministries and
study-in-X portals, the Organization of Turkic States, ASEAN, the African Union, Erasmus+
partner-country lists, the World Bank and regional development banks, GIZ, JICA, KOICA and TIKA.
**If your derivation surfaces bodies beyond these, they are the more valuable finding.**

If nothing systematic exists, **say so plainly** — that is the expected answer and it is worth
confirming rather than assuming.

### Part D — which are actually worth attending

A funded place at an institution whose degree carries no weight is not a good outcome, and we should
not sell one. For the institutions in Part A, give what is **verifiably published** about standing:
national accreditation status, membership of recognised quality registers, subject-level
international standing where a credible published source exists.

**Do not rank by commercial league table.** If a claim about standing cannot be supported from an
official or accreditation source, state that no verifiable basis was found rather than substituting
a ranking site. Employability and recognition of the qualification abroad matter more here than
prestige, so prefer evidence about those where it exists.

### Sourcing rules

1. **The institution's own page for every claim about its funding.** Ranking sites and
   scholarship-aggregator listings may be used to find candidates, never to establish a fact.
2. **Confirm the scheme is currently open**, with the most recent cycle you can evidence and its date.
3. **Quote the operative sentence** for the application route and for eligibility.
4. **State the teaching language explicitly for every row.** An unstated language is a missing
   answer, not an implied "English".
5. **Where something is unpublished, say so.** Do not estimate coverage amounts or infer eligibility
   from marketing copy.
6. Prefer breadth of *institutions* over depth on any single scheme. Naming twenty institutions with
   a confirmed funded route is more useful than exhaustively documenting three.

### What would change our plans

Flag explicitly: any institution offering `AUTOMATIC_ON_ADMISSION` full funding to our nationalities;
any list or register that enumerates such institutions; any country whose public universities are
free or near-free to international students at master's level regardless of scheme; and the Part B
ratio, if funding overwhelmingly lives inside programme pages rather than on funding-shaped URLs.

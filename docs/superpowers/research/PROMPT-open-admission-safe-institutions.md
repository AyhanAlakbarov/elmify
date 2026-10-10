# Deep research prompt — open-admission institutions that are actually safe

**Status:** ready to run. Written 2026-08-29. Run twice, independently, so the results can be
adjudicated.

**Why this exists.** The portfolio model needs a **safety**, not only a reach. For a self-funded
student, a low-selectivity institution they can afford *is* that safety — and we currently have no
way to identify one, which means every portfolio built for a self-funded student is missing its
floor.

`2026-08-27-risk-aware-portfolio-design.md` §6 already states the hazard exactly: *"The destinations
where admission is easiest and tuition-driven are also where degree mills live. Recommending one to
a weak student is the worst failure this product can produce, and without this gate the design would
rank it as an excellent floor: bar met, admission rule-based, self-funding sufficient."*

**So the question is not which universities admit anyone who pays.** Answered that way, this run
produces a list that eventually hands a student a worthless degree, a refused visa, or an
institution that loses its licence mid-course. The question is which institutions are **genuinely
low-selectivity, affordable, and safe — and what screen separates them from the ones that merely
look like it.** The screen is the real deliverable.

---

## Prompt

### Part A — the screen, first

Before listing any institution, establish **how an institution's safety can be verified from public
sources**. This part is more important than Part B; a good screen lets us evaluate institutions this
run never reaches.

For each mechanism below: what it covers, whether it is machine-readable, its terms, and — critically
— **what it does not tell you.**

1. **Accreditation and quality assurance.** DEQAR/EQAR for the EHEA; national accreditation bodies
   elsewhere. Establish for each: does listing mean the *institution* is recognised, or only some
   programmes? Can an institution be accredited while a specific master's is not?
2. **Degree-awarding powers versus teaching rights.** In several systems a body may legally teach
   but not award its own degrees, validating through a partner instead. Establish where this
   distinction exists and how it is published — it is a common source of student confusion and a
   genuine difference in what the qualification is.
3. **Home-country recognition**, which is often the binding constraint. **Derive the set of
   recognition bodies rather than working from a list.** Every Lisbon Recognition Convention
   signatory operates an ENIC-NARIC centre; start from the ENIC-NARIC directory, establish which
   centres publish an **actual list** of recognised foreign institutions as opposed to assessing
   case by case, and report that set. Four are already known to publish lists — Germany's
   **anabin**, China's **`jsj.moe.gov.cn`**, Ireland's **QQI**, Poland's **NAWA** — but those are a
   floor, not the scope: **if the directory yields others, they matter more than these four**, since
   a list-publishing body turns recognition from a disclosure into a computable gate. Establish
   coverage, access route and terms for each you find. **Then establish what Azerbaijan and Türkiye publish, in depth — these are the
   launch markets and their recognition rules are the binding constraint on everything we
   recommend** — followed by Georgia, Armenia, Kazakhstan, India, Pakistan, Vietnam and Indonesia.
   For each: whether it recognises foreign qualifications by list or case by case, who decides, and
   where it is published. Türkiye's YÖK operates a recognition and equivalence regime with published
   conditions; establish exactly what it lists and what it assesses individually.
4. **Visa-sponsor standing.** The UK Home Office publishes its register of licensed student sponsors,
   and a revocation strands enrolled students mid-degree. Establish which other destinations publish
   an equivalent register, how often status changes, and whether history is retrievable. **This is a
   distinct risk from degree-mill risk** — a properly accredited institution can still be a bad bet
   if its sponsor status is unstable.
5. **Regulatory action and warning lists.** Which authorities publish enforcement actions, warnings,
   or lists of unrecognised providers, and where.

**Capacity rule.** Part A is the deliverable. If the run cannot complete everything, **finish Parts
A, C and D fully and give whatever Part B you can** — a working screen lets us evaluate institutions
this run never reaches, whereas a longer institution list without the screen is unusable and
possibly dangerous. Do not trade screen depth for table length.

### Part B — institutions that pass it

Only institutions that clear Part A's screen. **Report the screen result per institution**, not just
the name.

| Column | Notes |
|---|---|
| Institution, country | And **ROR ID** where findable |
| **Published admission bar** | The actual stated requirement — GPA, degree class, language level. Quote it. An institution that publishes a low bar is *bandable*; one that publishes nothing is not |
| Admission regime | Open/rolling, rule-based with a published threshold, or capacity-limited |
| Acceptance rate | **Only if published.** Do not estimate one |
| **All-in annual cost** | Tuition **plus** the living cost the visa authority requires the student to show. A cheap degree in an expensive city is not affordable, and the visa minimum is the real floor |
| Teaching language | Explicitly. An unstated language is a missing answer, not an implied "English" |
| Accreditation status | With the source and date |
| **Recognised in Azerbaijan and Türkiye?** | By list, case-by-case, or not recognised — the launch markets, so this column is mandatory, not best-effort. Add Georgia, Armenia, India and Pakistan where findable. This is often decisive and is frequently the fact nobody checks |
| Sponsor-register status | Where the destination publishes one |
| Post-study work eligibility | Whether graduates of *this* institution qualify — some routes exclude certain provider categories |
| Official URL | |

**Geographic priority:** destinations where a self-funded student can plausibly afford the all-in
cost. Include public systems with low or no tuition for internationals (Germany, Norway's public
sector, parts of Central and Eastern Europe), affordable private sectors, and regional options in
Türkiye, Kazakhstan and the Caucasus. Include expensive destinations only where a genuinely
low-cost, low-selectivity, screened option exists.

### Part C — what we must never surface

Give the **exclusion criteria**, with concrete published examples of institutions or provider types
that meet them. Cover: unaccredited providers presenting as universities; accreditation-mill
"accreditors" that exist to certify anyone; institutions under active regulatory action; those whose
qualifications are unrecognised in our students' home countries; and any provider category
systematically excluded from post-study work routes.

**Name the tells.** What can be observed from an institution's own public materials that reliably
predicts failing the screen? Recruitment-agent commission structures, guaranteed-admission language,
an accreditor with no governmental standing, a campus address that is a serviced office. This is the
part most reusable as a heuristic.

### Part D — where the screen cannot reach

Countries and regions where none of Part A's mechanisms produce an answer, so no institution there
can be automatically cleared. **Say so plainly.** That is a finding: it defines where a consultant
check is mandatory rather than optional, and it must not be papered over with a weaker proxy.

### Sourcing rules

1. **Regulator and accreditor sources for every safety claim.** Never an institution's own assertion
   about its accreditation, and never a ranking or agent site. Institutions misrepresent this
   routinely, and it is the specific thing being tested.
2. **Quote the published admission bar** rather than characterising it. "Low entry requirements" is
   not usable; "a bachelor's degree with a minimum GPA of 2.0/4.0" is.
3. **Date every status.** Accreditation and sponsor licences change, and a stale clear is worse than
   no answer because it will be trusted.
4. **State costs with their year and currency**, and separate tuition from the visa-required living
   minimum.
5. **Where a fact is unpublished, say so.** Never estimate an acceptance rate, and never infer
   recognition from accreditation — they are different questions with different answers.
6. **Do not soften a negative finding.** If an institution is widely marketed to students from our
   region and fails the screen, saying so is the most valuable output in this run.

### What would change our plans

Flag explicitly: any machine-readable register combining accreditation *and* recognition; whether
Azerbaijan, Georgia or Armenia publishes a list of recognised foreign institutions, since that would
become a hard gate rather than a disclosure for our primary population; any destination with a
public, low-cost, genuinely low-selectivity sector that clears the screen — that is the best floor
this product could offer a self-funded student; and any provider category that passes accreditation
but is excluded from post-study work, which would look like a safe floor and is not.

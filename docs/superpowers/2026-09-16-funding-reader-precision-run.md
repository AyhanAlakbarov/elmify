# The funding reader, measured live — 497 EACEA leads

Run finished 2026-09-16 after 15h12m. Throwaway database `tehsil_funding_precision_v2`,
evidence on local disk, both model families answering live. Driver: `funding_run.py`
(scratchpad, not committed — it is the pipeline's own entry points wired to a disk store).

**Read the framing before the numbers: this is not a precision measurement.** There is no
known-answer set, so nothing here says whether a served award is *correct*. §6 of the design
already names that as owed work. What this run measures is that the pipeline completes with
both families live, and *where* it loses candidates between a fetched page and a served award.
Two served awards cannot establish precision, and this report does not claim they do.

## The report line

```
DiscoveryReport(leads=497, written=69, unchanged=4, blocked=424,
  degraded=("118 programmes' pages never stated a required gate fact",
            '45 dates unreadable, citations kept',
            '18 joint programmes await provider resolution'),
  funding=FundingCounts(served=2, unagreed=53, abstained=8, pointers=88,
                        unreadable=9, negations=27, noise=68))
```

## Four attempts, one that counts

| # | database | outcome |
|---|---|---|
| 1 | `..._precision` | crashed — an INSTITUTION-scope award on a joint programme has no single institution |
| 2 | `..._precision` | completed during an **Anthropic** credit outage: `served=0 abstained=56` |
| 3 | `..._precision_v2` | died early; 6 awards |
| 4 | `..._precision_v2` | **this run** — killed at 61m on an **OpenAI** credit outage, restarted, completed |

Attempt 2's `served=0` measured a billing gap, not the reader. Attempt 4's first hour hit the
same failure on the other provider: 160 leads blocked by `429 — "You have no credits
remaining."` Those 160 were retried from cached snapshots on restart
(`pipeline.py:494` reuses a snapshot whose prior extraction failed) and none re-blocked.

**The abstentions were the outage.** `abstained` fell from 56 to 8 once both families answered.
Exactly one reading was lost in 15 hours — `funding judge lost claude reading(s) on
25d9f275-…`, a transient; Anthropic answered on probe immediately after.

## Where 497 leads go

69 award rows survive. By agreement:

| agreement | rows |
|---|---|
| UNAGREED | 32 |
| pointers (blank) | 24 |
| ABSTAINED | 8 |
| AGREED | 5 |
| **served** | **2** |

The run's counters (`unagreed=53`, `pointers=88`) exceed the stored rows because they count
decisions, and many decisions collapse onto one `canonical_key`.

## The binding constraint is disagreement, not abstention

Of the 53 unagreed decisions, the fields the two families split on:

| disputed field | count |
|---|---|
| money_form | 26 |
| route | 25 |
| nationality_shape | 22 |
| kind | 19 |
| internationals_included | 18 |
| **offered** | **17** |
| readings | 8 |
| scope | 3 |

`offered` is the one to look at first: on 17 decisions the families disagreed about whether the
page offers funding **at all**. That is not a taxonomy quarrel over an award both saw.

## The serve gate, and the one thing that closes it

All five AGREED rows:

| | kind | name | money_form | benefits |
|---|---|---|---|---|
| **served** | I2 | Reduced Tuition Fee Scholarship | FEE_WAIVER | TUITION |
| **served** | I6 | Erasmus mobility grant | GRANT | STIPEND |
| unserved | I2 | Partner financial support | UNSTATED | — |
| unserved | I5 | Erasmus Mundus funding | UNSTATED | — |
| unserved | I5 | Erasmus Mundus Joint Master Degree scholarship | UNSTATED | — |

**Three of three unserved-but-agreed rows fail on the same gate** — `money_form == UNSTATED`
with no `FundingBenefit`. Both families agreed the award exists; the page never said what form
the money takes. That gate, not `can_support_claim` and not `offered`, is what stands between
an agreed award and a student.

Worth a product decision, not a code change: both served awards carry
`internationals_included=UNSTATED` and `nationality_shape=UNSTATED`. Serving does not require
either, so a student is shown an award without being told whether they are eligible for it.

## What this run does not answer

- **Correctness.** No known-answer set exists. 2 served awards is a throughput figure.
- **Recall.** 424 of 497 leads blocked; 118 pages never stated a required gate fact. Whether
  those pages hold awards the reader missed is unmeasured.
- **Whether disagreement means the page is ambiguous or a reading is wrong.** 32 unagreed rows
  sit in the review queue (`manage.py funding_review`) and reading a sample of them by hand is
  the cheapest next measurement — it is also the only way to turn `offered`-disagreement into
  either a prompt fix or a "the page really is ambiguous" finding.

## Sample verification: the 32 unagreed rows, read by hand (2026-09-22)

Read all 32 stored quotes directly from `tehsil_funding_precision_v2` (`FundingOpportunity`
rows filtered `agreement="UNAGREED"`) against their pages' content, and specifically 15 of the
17 decisions carrying `offered` in `disputed` — the question the previous section left open.

**About two-thirds look like a reading error on a page that is actually clear, not genuine
ambiguity.** Ten of the fifteen state funding in terms no reasonable reading should call `NO`
or skip — explicit amounts, named recipients, and application mechanics (e.g. IMSOGLO: "IMSOGLO
offers Erasmus Mundus Scholarships for student intake September 2026"; STRAINS: a monthly
allowance table; SDSI: "the SDSI scholarship will be monthly paid to..."; MITRA: "€1,400 per
month for 24 months"). A page stating an award this plainly getting `offered` disputed points at
the judge, not the page.

**The other third are genuinely ambiguous, and cluster around one gap the schema doesn't
name: temporal/administrative language that isn't a yes/no statement about eligibility.**
- `6df9807d`ᐧ`edumah`: *"Erasmus Mundus Scholarship applications are now closed."* — a real
  scholarship exists, but the schema's `offered: YES/NO` has no state for "exists, not
  currently open." A reading calling this `NO` isn't wrong about the schema; the schema is
  wrong about the world.
- `66377b5c`ᐧ`neurasmus`: *"...consider your funding options. Learn more about Neurasmus
  scholarship"* — a link caption, states nothing about the award itself.
- `f606d894`ᐧ`mespom`: *"Potential sources of funding Erasmus Mundus scholarships"* — a
  navigation heading, same problem.
- `b91ffde5`ᐧ`imsoglo`/admission: application-deadline mechanics for an award whose existence
  is stated on a *different* page, not this one.
- `48d0cd93`ᐧ`mastergeotech`: *"Those students granted by the Erasmus Mundus program who do not
  possess a laptop must buy one..."* — presupposes a recipient rather than stating the award.

**A second pattern, orthogonal to the first: bigger awards disagree more, independent of
clarity.** The clearest-worded pages in the whole sample (`85c807fe`, 15 quoted lines;
`a670ba30`, 7 lines) still land in the "reading error" bucket with `offered` disputed, and both
are large multi-line award descriptions merged under one `(kind, scope)` key. `awards()` adds
`offered` to a group's `disputed` set the moment *any one line* in the group falls short of 3/3
`YES` (spec 2.4's per-line rule, correctly implemented) — so an award described across many
lines needs every one of them read unanimously, and the more lines an award spans the more
chances one line has to lose a vote even though the award as a whole is stated unambiguously
nowhere in doubt. This is a real, structural finding, not a page-reading mistake: **verbosity
lowers a genuinely-offered award's odds of reaching AGREED**, independent of how clearly it's
worded. Worth a design note before the next iteration; not fixed here.

**Net read:** disagreement is not proof of a bad reader — a third of the sample is the schema
missing a real-world state (closed applications, navigational mentions) and a third is a
structural verbosity penalty, not label noise. But the remaining ~two-thirds where a plainly-
stated award still failed to reach 3/3 is a real judging-quality gap worth a prompt iteration,
separate from the schema and grouping issues above.

## What tiered agreement does to these numbers — a bound, not a measurement (2026-09-23)

Tiered agreement shipped on 2026-09-23 (spec §8.6, owner decision 2026-09-22): a split on
`offered`, `holder` or `scope` is still `UNAGREED`, and a split on any **other** decided field
leaves the award `AGREED` with that field blanked to `UNSTATED` and named in a new
`FundingDecision.unconfirmed`. The question this file exists to answer is what that buys, and
**the honest answer here is a bound, because the 58-host fixtures are not in the repository** —
re-deriving the real ratio means re-running the live sweep, which is real API spend. The exact
`awards shown ÷ awards found` is **owed to the §8.8 gate** and is deliberately not invented.

What the recorded table above does support, arithmetically:

- The existence set is `offered` ∪ `holder` ∪ `scope`. In this run that is **17 + 0 + 3**;
  `holder` never appears in the breakdown at all.
- So **at most 20** of the 53 unagreed decisions can still be `UNAGREED` — fewer if any decision
  was split on both `offered` and `scope`, which the per-field counts cannot distinguish.
- Therefore **at least 33 of 53** unagreed decisions (≈62%) become `AGREED` with a caveat.

Two cautions before anyone quotes that:

- `AGREED` is necessary for serving, not sufficient. `_served` also needs a vouched lead,
  `offered == "YES"` and a benefit or a stated money form, so the number of rows that actually
  reach a student is lower than 33 and cannot be read off this table.
- Decisions collapse onto `canonical_key`s, as the note above this one says — and the collapse
  ratio itself changed on the same day, because `heading` joined award identity (§8.7). Counts of
  *decisions* from this run are not comparable to counts of *rows* after that change.

The verbosity penalty recorded at the end of this file is **narrowed but not closed** by the same
two changes. Splitting on `heading` means a long award no longer merges with its neighbours, so
fewer lines are pooled into one `offered` vote; and a non-existence split no longer sinks the
award. A single award still described across many lines under one heading still needs every one of
them to reach 3/3 on `offered`, which is the structural part.

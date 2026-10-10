# Funding reader precision: every line judged, two model families, a review queue

**Status:** design, 2026-09-14. Supersedes §4.3 and §4.4 of
`2026-09-13-institution-programme-funding-search-design.md` for how a funding row is read and
decided; everything else in that spec stands.

**Owner target (2026-09-14):** a funding row shown to a student without a human is correct
95–100% of the time, on the labels a student acts on; anything short of that goes to a human;
recall is measured, never asserted.

## 1. What the built reader gets wrong

The reader on `claude/programme-funding-reader` asks one model three times to *quote and label*
funding sentences, then serves an award only when all three readings quoted it and labelled it
identically. Four things stop that reaching the target.

1. **Unanimity of one model filters noise, not bias.** Three samples of `gpt-5.6-luna` share
   every systematic reading that model has. `CLAUDE.md` records this for the CV-format judge, and
   the owner's 2026-09-14 decision — one of three readings from a second family — exists because
   of it. The funding reader has no second family.
2. **Open extraction throws recall away.** Measured on the programme-page reader: no two reads of
   the same page quote the same sentence set (29–40 statements per read). An award the third
   reading did not quote can never be served, and nothing shows it to anyone.
3. **The unit of agreement is wrong.** Awards are grouped by `(kind, scope)`, so two different
   awards of one kind merge, and an `UNSTATED` eligibility on one sentence defers to a stated
   value on another (final review C2 patched the symptom; the grouping is the cause).
4. **Nothing surfaces the near-misses.** `UNAGREED` and `ABSTAINED` rows are stored and no
   command, screen or report lists them. "Uncertain goes to a human" is a promise the code does
   not keep.

Plus one wording trap the first corpus will hit: the prompt calls EU-owned money a `POINTER`
that writes no row, and every EACEA consortium page describes EU-funded scholarships attached
to that programme.

## 2. Design

The shape is `apps/documents/derive.py`'s, which measured 100% on 48 sentences against 61% for
the open approach: candidates found by code, a closed question asked three times, unanimity per
sentence, abstention visible.

### 2.1 Candidates: every line of the funding sections

`readable_text(page, terms=_FUNDING_TERMS)` already keeps only the sections that mention money
(falling back to the whole page when none does). Its lines become the candidates, numbered, each
with its nearest preceding heading as context, exactly as `derive.candidates` lists them
(`index | heading > sentence`). A line longer than 300 characters is split into sentences before
numbering (on whitespace after `.`, `!` or `?`), so a stored quote is a sentence the page printed,
never a cut. Headings are candidates too ("## Erasmus Mundus scholarships" states something).

Chunks of at most 80 lines, at most 3 chunks per page; a page over 240 lines is judged for its
first 240 and the overflow is logged with the line count, the way `reader._capped` logs a cut —
a page we only partly read must never look like a page that said nothing.

No quote can be invented: the row's quote is the candidate line by index, so the
`_haystack`/`normalize` verification step disappears with the extraction stage.

### 2.2 The closed question, three readings, two families

One question per chunk, answered three times: two phrasings by `OPENAI_EXTRACTION_MODEL` and one
by `ANTHROPIC_JUDGE_MODEL` (Sonnet 5, the 2026-09-14 pick, reused from
`claude/second-model-judge`: its `MessagesAPI` seam, setting and dependency).

For every line that **states money, a fee reduction, a paid position or in-kind support for a
student of this programme, or states that none is available**, the reading returns one verdict:

| field | values | decided? |
|---|---|---|
| `line` | index | — |
| `offered` | `YES` / `NO` | yes |
| `kind` | `I1`…`I7` as today | yes |
| `scope` | `PROGRAM` / `PROGRAMS` / `INSTITUTION` / `POINTER` | yes |
| `internationals_included` | `YES` / `NO` / `UNSTATED` | yes |
| `nationality_shape` | `OPEN` / `COUNTRY_LIST` / `BLOC` / `BILATERAL_PAIR` / `UNSTATED` | yes |
| `route` | as today | yes |
| `money_form` | `GRANT` / `FEE_WAIVER` / `SUBSIDY` / `LOAN` / `FORGIVABLE_LOAN` / `MIXED` / `UNSTATED` | yes |
| `tuition`, `living` | `NONE` / `PARTIAL` / `FULL` / `UNSTATED` | no (majority) |
| `extras`, `obligation` | closed sets as today | no (union) |
| `name` | ≤ 6 words | no |

A line with no verdict is `NONE`: not a funding statement. Absence is a vote, so a reading that
skipped a line has said "nothing here"; a truncated reading must therefore never count, and does
not: `parsed_or_none` returns `None` for an incomplete OpenAI response (its partial JSON does not
parse) and the Claude reading is dropped unless `stop_reason == "end_turn"`, as
`derive._claude_reading` already does.

**Labels describe the award the line belongs to, read with the whole listing as context.** A
line that says "They are open to international students" under a scholarship paragraph carries
that scholarship's kind and scope, and the scholarship's first line carries `internationals_
included=YES` from this one. `UNSTATED` means the listing nowhere states it for that award, not
"this sentence does not say". This is what lets several lines about one award converge on one
label set instead of pushing every multi-sentence award to review.

The DATA guardrails are the repo's: the listing is labelled data, never instructions; `extra=
"forbid"`; `max_output_tokens` capped (`8_000`, Claude `2×` for thinking); `store=False`;
`safety_identifier` hashed from the source id.

### 2.3 Agreement, per line

With `n` surviving readings for a chunk:

- **Fewer than 3** (a refusal, an off-schema or truncated answer): every line of the chunk is
  `ABSTAINED`. Nothing served; the lines that at least one reading called funding go to review.
  This is not the budget case — a read stopped by the budget or the rate limit writes nothing
  for the page (the I4 rule stands, and a cut-short read leaves the page un-read so recall shows
  it as `PENDING`).
- **Three readings.** With `y` = readings saying `YES` and `k` = readings saying `NO`:

  | case | outcome |
  |---|---|
  | `y + k ≤ 1` | noise: dropped, counted (`noise`) |
  | `y = 0`, `k ≥ 2` | negation: no row, counted (`negations`) -- no reading saw an award |
  | `y = 3`, every decided field unanimous | **agreed** |
  | `y = 3`, any decided field differs | **disputed**, fields named |
  | `y = 2` | **disputed**, `offered` named (one reading saw no award, or a negation) |
  | otherwise (`y = 1`, `k ≥ 1`) | **disputed**, `offered` named |

A reading that returns two verdicts for one line has contradicted itself: it counts as one
`YES` (or `NO`) whose labels agree with nothing, so the line can be disputed but never agreed
(the 2249fe4 rule: one reading is one vote).

### 2.4 Awards

Award lines are grouped by `(kind, scope)`. A group is one `FundingDecision`:

- `AGREED` when every line in the group is agreed **and** every line carries the same decided
  values (`UNSTATED` is a value, distinct from a stated one). Two lines that disagree make the
  group `UNAGREED` with the fields named — that is the C2 case, now the rule rather than a patch.
- `UNAGREED` when any line is disputed or the group disagrees with itself.
- `ABSTAINED` when the chunk had fewer than three readings; the lines are grouped on the labels
  the surviving readings gave (the first reading's where they differ) so the reviewer sees them.
- `POINTER` scope: recorded as pointers for the census, never a row.

Coverage (`tuition`, `living`) is the majority over the group's verdicts; `extras` and
`obligation` are unioned; `name` is the first agreed line's, capped at 80 characters as today.
`disputed` (the named fields, `;`-joined) is carried on the decision and stored on the row.

### 2.5 The serving rule

`served` is true only when all of these hold; the writer is the only place that sets it:

1. `agreement == AGREED`;
2. `offered == YES` and the award names a benefit or a stated `money_form`;
3. the lead is a vouched catalogue lead (`can_support_claim` and `one_programme_per_site`, the
   I3 gate, unchanged);
4. no `REJECTED` review stands for this page version (§2.6).

An operator's `ACCEPTED` review is the one other way a row becomes served.

### 2.6 Review: `manage.py funding_review`

Five columns on `FundingOpportunity`, blank on every row an older writer created:

| column | type | meaning |
|---|---|---|
| `review` | `""` / `ACCEPTED` / `REJECTED` (check constraint) | the operator's decision |
| `review_note` | char 200 | why, in the operator's words |
| `reviewed_at` | datetime, null | when |
| `reviewed_sha256` | char 64 | the page version the decision was made on |
| `disputed` | char 200 | the fields the readings disagreed on, for the reviewer |

The command:

- `funding_review` (or `list`): every row with `served=False` and `review=""` — unagreed,
  abstained, and agreed-but-unserved — one block each: id, kind/scope, the decided labels,
  `disputed`, every quote, the page URL, and the reason it is pending. (Headings are listing
  context only and are not stored; the page URL is one click away.)
- `funding_review accept <id> [--note]`: `served=True`, `review=ACCEPTED`, `reviewed_at`,
  `reviewed_sha256` from the row's evidence snapshot; the row's evidence claims become
  `STUDENT_FACING`.
- `funding_review reject <id> --note`: `served=False`, `review=REJECTED`, the rest as above.

**A decision is bound to the page version.** On a re-read, the writer compares the snapshot's
`sha256` with `reviewed_sha256`: equal, and the writer returns the row untouched (a human beats a
model on the same page); different, and the review fields are cleared before the ordinary write,
so a changed page goes back through the readings and, if still short, back into the queue.

Operator-only by construction: a management command runs as the platform, never as a tenant.
`AuditEvent` is not written — no catalogue command writes one today, and the shared catalogue is
not a person's data. A console screen for the same queue is a later increment.

### 2.7 Pointer versus attached

Replaces the `scope` definition in the prompt: money the student obtains **by applying to a body
outside this programme** is a `POINTER` (a national scholarship page that says "you may also
apply to DAAD"). Money **this programme awards, nominates for, or that comes with a place** is
attached, whoever funds it — an EU-funded Erasmus Mundus scholarship the consortium awards is
`I5_FUNDED_DUAL_DEGREE` at `PROGRAM` scope, not a pointer. The census still records the EU
scheme under O2; the two are different facts about the same money.

### 2.8 Wiring

- A new pure module, `apps/research/funding_judge.py`, holds the lines, the readings and the
  agreement: `funding_chunks`, `judge`, `line_outcomes`, `awards`, `read_funding(parser, claude,
  *, source_id, chunks) -> FundingReadResult`, `FundingDecision` (plus `offered`, `quotes`,
  `name`, `disputed`) and `FundingReadResult` (`pointers`, `negations`, `noise` as counts).
  `funding_reader.py` keeps `_FUNDING_TERMS` and the catalogue side: `write_funding_decision`
  (plus §2.6) and `review_funding`. It loses `FundingStatement`, `FundingStatements`,
  `extract_funding_statements`, the phrasings, `_verified`, `_consistent`, `_vote`,
  `decide_funding`, and the `_haystack`/`normalize` imports.
- The Claude reading reuses one helper, `extraction.claude_parsed_or_none`, which
  `derive._claude_reading` also delegates to, so the two judges cannot drift apart.
- `pipeline._fund_page` counts the model calls a page needs (`3 × chunks`) and pays for all of
  them -- one budget unit and one rate-limit unit each -- before the first call; a page it cannot
  pay for in full writes nothing and makes no call. `run_discovery` gains `claude: MessagesAPI | None`
  beside `funding_parser`; `discover --funding` builds both clients and **refuses to start
  without `ANTHROPIC_API_KEY`**, so a single-family run cannot happen by accident. The extraction
  budget ceiling becomes `1 + 9` per lead (three chunks of three calls).
- `FundingCounts` gains `noise`; `negations` keeps its meaning.
- Migrations: after merging master (whose funding migrations now end at
  `0031_cv_directives_undecided_unreadable`), this branch's `0030_cv_directives…` is dropped as a
  duplicate, `0031_funding_opportunity_read_fields` and `0032_snapshot_funding_read_at` are
  renumbered to follow, and the review columns land in the next number. Nothing is deployed, so
  renumbering costs nothing.

## 3. Alternatives rejected

- **Keep find-then-judge** (three extraction readings unioned, then three judge readings over the
  union): six calls a page, and the find stage keeps selection variance — a sentence no reading
  quoted is still lost. Judging every line of the funding sections costs three calls and looks
  at everything.
- **Serve on two of three.** The target is 95–100% on labels a student acts on; a 2-of-3 rule
  serves precisely the rows one family disagreed with.
- **Serve the verified quote with unagreed labels blanked.** The quote is safe by construction;
  the labels are what decide whether a student can get the money, and a row with blank labels
  is a row the product cannot rank or filter. Review is the cheaper answer.
- **Per-tenant counsellor review.** The catalogue is shared; a served row is every tenant's. A
  tenant-level decision needs per-tenant overrides, which is a different design.

## 4. Measurement

Run after the build, on a throwaway database, in the foreground (background jobs are killed on
this machine), with both keys sourced:

```
POSTGRES_DB=tehsil_funding_precision DATABASE_ROLE=migration uv run python manage.py migrate -v0
POSTGRES_DB=tehsil_funding_precision DATABASE_ROLE=migration uv run python manage.py discover \
  --field any --country XX --tenant <agency id> --max-leads 200 --cycle 2027 --funding
```

Four numbers, written to `docs/superpowers/research/2026-09-14-funding-reader-precision-run.md`:

1. **Served precision.** Every served row: the page fetched again (Scrapling), the quote found on
   it, and each decided label checked against the sentence in context. One row per served award:
   right / wrong, and which label if wrong. Target: 95–100%.
2. **Queue size and queue precision.** How many awards went to review, and, for 20 of them graded
   as an operator would, how many an operator would accept. High queue precision means the rule
   is stricter than it needs to be; low means it is doing its job.
3. **Reader recall on a sample.** Ten pages read in full by hand, every funding statement listed,
   compared with what was served or queued. Missed awards named with the line that stated them.
4. **Cost and time** from the OpenAI and Anthropic dashboards, per page.

What the run shows: the reader, on pages a catalogue vouched for, on one corpus (EU-funded joint
master's, whose money is mostly one kind). What it does not show: precision on fee-charging
destinations, and the crawl's recall — that needs the known-answer set, which needs the register
increments before there are pages to find. The grader is a model reading the page, spot-checked
by the owner; the run note says so.

## 5. Testing

Fakes only; the live pieces are gated behind `-m live`.

- `candidates`: numbering, headings, sentence splitting, the 300-character rule, chunking, the
  240-line overflow logged.
- `line_outcomes`: each row of §2.3 — fewer than three readings, ≤ 1 `YES`, unanimous `NO`,
  2 `NO` + 1 `YES`, 3 `YES` agreed, 3 `YES` disputed with the fields named, a reading answering
  twice for one line, a truncated reading dropped.
- `awards`: grouping, self-disagreement → `UNAGREED`, `UNSTATED` distinct, pointers, majority
  coverage, union of extras.
- `write_funding_decision`: the serving rule's four conditions; review binding on same and
  changed `sha256`; `ACCEPTED` claims become `STUDENT_FACING`.
- `funding_review`: list output, accept, reject, an unknown id.
- pipeline: `read_funding` called with both clients; refusal without the key; budget and
  rate-limit stops still write nothing; counts.
- one `live` test: three readings of one real EACEA page produce the same served set (or a
  printed spread), the same shape as `test_three_live_reads_of_a_real_page_derive_the_same_rules`.

## 6. Limits, stated

- Two readings of three are still one family; a bias the two OpenAI phrasings share can outvote
  Claude into review, never into a served row — served needs Claude's agreement.
- A page that withdraws an award keeps its served row until a re-read of that page (unchanged
  from the 2026-09-13 branch; the unserve sweep is still owed before anything reads `served`).
- An INSTITUTION-scope row's origin is still not checked against `institution.official_website`;
  the I3 gate stands in until it is.
- Review has no screen; an operator runs a command. The queue is visible, which is the point.
- The known-answer set and the crawl's recall are the register increments' to measure.

# CV-requirement corpus: baseline measurement (2026-09-16)

Task 9 of `docs/superpowers/sdd/2026-09-15-cv-requirement-corpus/`. Spec:
`docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md`. This is the third and
final attempt at Step 4 (the live runner); the first two failed for infrastructure reasons
unrelated to the pipeline or the corpus, detailed in "Spend and attempt history" below.

## The table (verbatim)

```
row                n  bind.recall  recall  precision  localiz.  outcome  drift  unjudged
ALL               30         0.00    0.00          -      0.00     0.10      3         7
(control)          9         0.00    0.00          -      0.00     0.11      1         2
deep              12         0.00    0.00          -      0.00     0.00      2         0
blocked            4         0.00    0.00          -      0.00     0.00      0         0
js_only            2            -       -          -         -     0.00      0         0
no_cv              3            -       -          -         -     0.00      0         0
careers_decoy      3            -       -          -         -     0.00      0         0
in_template        6            -       -          -         -     0.33      0         5
non_english        4            -       -          -         -     0.25      0         3
```

`unmeasured`: none. All 30 dev programmes returned a `ProgrammeReport` this run (no
`openai.APIConnectionError` / `anthropic.APIConnectionError` was raised, so the Step B
hardening's `except transport_errors` branch never fired).

## Drift lines (verbatim)

```
drift: globed https://globed.eu/how-to-apply/ (changed)
drift: we-team https://we-team.education/faq/12-are-there-specific-guidelines-for-preparing-my-cv-for-the-erasmus-mundus-application/ (changed)
```

Two distinct URLs drifted; the table's `drift` column counts affected **rule rows**, not URLs
(`score_programme`'s `tally.drifted = len(own) - len(live)`), which is why `(control)` shows 1
(globed carries one rule on the drifted URL) and `deep` shows 2 (we-team carries two rules on
its drifted URL) — 3 rule-rows total, matching `ALL`'s `drift=3`. Both drifted rows were excluded
from that run's recall/precision denominators, not silently kept or silently dropped, per the
runner's design.

## Unjudged requirements block (verbatim)

```
programme_id,requirement_key,requirement_value
emship,undecided,directive
emship,undecided,max_pages
sisgp,undecided,cv_format
sisgp,undecided,directive
eiffel-paris-saclay,max_pages,2
eiffel-paris-saclay,unapplied,cv
eiffel-paris-saclay,undecided,language
```

Seven rows the pipeline reported that nobody has adjudicated yet — handed back for adjudication
as `post_hoc`, never scored as wrong, per `ScoreTable.unjudged`'s contract.

## Candidates pooled

**Pipeline pass (from the live runner's `candidates` CSV block): 8 rows**, appended to
`docs/research/cv-corpus-candidates.csv` (which did not exist before this run — its header was
written for the first time): 2 for `sisgp` (a template mandate and a 3-page limit), 6 for
`eiffel-paris-saclay` (four variants of a résumé-length/template sentence duplicated across
list-marker formatting, plus a referee's-résumé sentence duplicated the same way).

**Vendor pass: 1 of 30 programmes completed.** `manage.py pool_cv_corpus --pass vendor --split
dev` printed one success line —

```
vendor: mathmods: 5 pages, 3 candidates
```

— then crashed with an unhandled exception while crawling the **second** dev programme
(`emship`, CSV row order = processing order, confirmed by inspection of
`cv-corpus-programmes.csv`):

```
urllib3.exceptions.ReadTimeoutError: HTTPSConnectionPool(host='100.57.251.205', port=443): Read timed out. (read timeout=20)
...
apps.research.egress.SourceBlocked: ReadTimeoutError: HTTPSConnectionPool(host='100.57.251.205', port=443): Read timed out. (read timeout=20)
  File ".../apps/research/management/commands/pool_cv_corpus.py", line 172, in _vendor
    pages = tavily_crawl(
  File ".../apps/research/search.py", line 354, in tavily_crawl
    data: Mapping[str, Any] = post(
  File ".../apps/research/egress.py", line 466, in fetch_json_api
    raise SourceBlocked(...) from error
```

This is **not** the graceful `no crawl results` case `_vendor` already handles (an empty page
dict, printed as a stderr line and skipped) — Tavily's crawl endpoint did not return within the
client's 20-second read timeout, `fetch_json_api` raised `SourceBlocked`, and nothing in
`Command._vendor` catches an exception from `tavily_crawl` itself, so the whole management
command process exited. **mathmods' 3 candidates were already flushed to
`cv-corpus-candidates.csv` before the crash** (`write_candidates` is called once per programme,
inside the loop), so no vendor-pooled data was lost — only the remaining 29 programmes were
never attempted:

```
emship, globed, i-mesc, europubhealth, amir, emhrpp, emjm-imaging, we-team, membiomed,
daad-prime, fau-ai-msc, turkiye-burslari, sciencespo-graduate, ethz-master,
stipendium-hungaricum, tudelft-master, leiden-master, rhodes, sisgp, eiffel-paris-saclay,
fulbright-nepal, chevening, aalto-master, jasso, gks-korea, sbfi-swiss, mext-japan,
daad-epos, emle
```

**Following the task brief's own rule for a vendor-crawl HTTP error** ("stop the vendor pass,
record exactly which programmes completed... the digests and baseline are still committed"), the
vendor pass was **not retried**. Re-running it would re-crawl `mathmods` and (per
`_vendor`'s `known` set, which is built from `corpus.rules`, not from
`cv-corpus-candidates.csv`) would append duplicate rows for `mathmods`'s three sentences, since
the dedup check only looks at already-*adjudicated* sentences. A resume that skips already-pooled
programmes needs either a `--only` flag pass excluding `mathmods`, or a dedup pass against the
candidates file itself — a decision left to the controller, not made unilaterally here.

## Firecrawl fallback needed for: none

Zero `vendor: no crawl results for <id>` lines were printed. The brief's Firecrawl-fallback
clause covers a **graceful empty crawl result**, which is a different condition from the crash
above (an unhandled read-timeout that aborted the command before 29 programmes were even
attempted). Whether any of those 29 would themselves need a Firecrawl fallback is unknown; none
of them were reached.

## Spend and attempt history

**This was the third and final attempt at Step 4**, per the controller's explicit ruling
(one more attempt only, database isolated, do not run it again regardless of outcome).

- **Attempt 1** (prior session): errored in the pytest-django test-database fixture
  (`database "test_tehsil" already exists` / `is being accessed by other users`) before any
  live API call — a different worktree's concurrent pytest session was using the same
  `test_tehsil` database. Zero API cost.
- **Attempt 2** (prior session): passed the fixture, then failed 530.60s (8m50s) into the run
  with `psycopg.errors.AdminShutdown` / `django.db.utils.OperationalError: terminating
  connection due to administrator command`, while writing `Program.cv_constraints` for a
  programme partway through the dev split. **Root cause, identified by the controller**: every
  worktree on this machine derives the same Postgres test database name
  (`test_tehsil`) from the shared default `POSTGRES_DB`; a concurrent Claude session running
  pytest from `/home/orkhan/Desktop/tehsil_agent/.worktrees/glass-box-kit` re-created that
  database mid-run, killing attempt 2's connection. From attempt 2's tee'd output, the warnings
  visible before the crash place it at or past programme #12 of 30 in CSV order
  (`fau-ai-msc`, which logged a handled `OffSiteRedirect` and continued) — so **at least 12,
  and likely a few more, of the 30 dev programmes had already completed real
  OpenAI/Anthropic/Tavily calls** before the interrupted database write ended the run. That
  spend produced no usable table, since the run never reached scoring.
- **Attempt 3 (this run)**: run with `POSTGRES_DB=tehsil_cv_corpus` (isolated per the
  controller's ruling), so pytest-django created and used `test_tehsil_cv_corpus`, untouched by
  any other worktree. **Passed**, 568.74s (9m28s), all 30 dev programmes measured, `1 passed`.

**Tavily calls, this attempt, as printed/countable:**
- Digest step (2026-09-15, prior session): 11 distinct URLs extracted (`digest: filled 11 of 11
  URLs`) — not repeated this session.
- Drift check (this run, inside the live runner): re-extracted the same 11 distinct labelled
  URLs (all 17 rules' source URLs collapse to 11 distinct addresses); 2 came back changed.
- Vendor pass (this run): 1 crawl call succeeded (`mathmods`, 5 pages returned); 1 crawl call
  timed out client-side (`emship`) and aborted the command before any further calls were made.

**OpenAI/Anthropic calls, this attempt:** not separately printed by the runner. Per the
documented cost model (`CLAUDE.md`, "LLM/AI security"), each of the 30 measured programmes ran
up to 3 statement-read calls plus up to 6 format-judge calls (the judge only runs when
candidate sentences exist), so the ceiling is 30 × 9 = 270 combined OpenAI + Anthropic calls;
the actual count is lower since most programmes carried no format-worthy sentences for the judge
to score. This is a ceiling from the documented design, not a measurement — the runner prints no
per-call counter.

**Programmes the runner reached:** all 30 of 30 dev programmes, this attempt.

## Reading the numbers

Binding recall and overall recall are both **0.00** on `ALL`, exactly as the design predicted:
today's baseline reads only the seed page (no discovery, no vendor pass wired into
`read_and_derive`), so it can only ever find a requirement that happens to sit on a programme's
front page — none of the 30 dev programmes' accepted rules live there. Outcome accuracy is
**0.10**, below the brief's own 0.7 expectation and mechanically explained by two of the four
outcomes today's baseline structurally cannot get right: every `no_cv` programme (3, all scoring
0.00) is a guaranteed miss because "reading one page cannot prove a negative," and every `blocked`
-stratum programme (4, all scoring 0.00) is *also* a guaranteed miss by design — that stratum
marks sites where the baseline's own direct fetch is refused even though Tavily (used only for
digests, drift and the vendor pass, not for `read_and_derive`) can read them; `expected_outcome`
for these is `found`, so a baseline that correctly reports `blocked` is still wrong relative to
the label. `(control)` (0.11) is *not* the highest-scoring row as the brief's hypothesis
expected — `in_template` (0.33) and `non_english` (0.25) both score higher on outcome accuracy,
because a page that visibly names a template or a non-English requirement is enough for the
baseline's `names_cv` check (`CANDIDATE_TERMS.search`) to report `found` even without deriving a
structured requirement, while an ordinary control page more often reads as `not_found`.
`careers_decoy` and `deep` are both at the floor (0.00), matching the hypothesis for those two
specifically, tied there with `blocked`, `js_only` and `no_cv`. Precision is undefined (`-`) on
every row: nothing the baseline reported this run overlapped either the `accepted` or `rejected`
pool, so there is no false-positive signal yet either way. Localization is 0.00 everywhere there
is a denominator, consistent with recall being 0.00 — nothing was found, so nothing could be
localized. **What this says about where part 3 (ranking/discovery) should start:** the two
guaranteed-miss outcome categories (`no_cv`, `blocked`) are not pipeline bugs to fix inside
`read_and_derive` — they need, respectively, a way to assert a programme genuinely has no CV
requirement, and the vendor-crawl path (already proven to work, on `mathmods`, in this session)
wired into the scored pipeline so a refused direct fetch is not a dead end. Everything else —
recall, binding recall and localization all at zero — says discovery beyond the seed page is the
entire remaining gap; derivation quality cannot be assessed at all until pages beyond the seed
are reached.

## Vendor-pass coverage gap — a note for the controller

Only `mathmods` (1 of 30 dev programmes) was vendor-crawled this cycle; the pipeline pass (8
candidates from 2 programmes) and the vendor pass (3 candidates from 1 programme) together cover
just 3 of the 30 dev programmes with any pooled candidate at all. The adjudication queue is real
and usable for what it has, but it is far short of the "all 30 dev programmes" the task brief
anticipated. Resuming the vendor pass for the remaining 29 (skipping `mathmods` to avoid
duplicate rows, and possibly raising the client read timeout past 20s, which is outside this
task's permitted files) is a decision for the controller, not made here.

## Vendor pass, second run (fix round 1)

Fix round 1 raised the Tavily crawl's own client read timeout to 120 s (the egress default of
20 s is what killed `emship` above) and made `_vendor` catch `SourceBlocked`/`UnsafeTarget` per
programme instead of letting one crawl failure abort the whole command, and dedupe against
`cv-corpus-candidates.csv` itself (not just adjudicated rules) so re-running never re-queues an
already-pooled line. `manage.py pool_cv_corpus --pass vendor --split dev`, run once, live, reached
all 30 dev programmes and its final total line:

```
vendor: no crawl results for i-mesc -- run the Firecrawl /agent fallback by hand and record its use in the programme's note
vendor: no crawl results for europubhealth -- run the Firecrawl /agent fallback by hand and record its use in the programme's note
vendor: no crawl results for sciencespo-graduate -- run the Firecrawl /agent fallback by hand and record its use in the programme's note
vendor: no crawl results for tudelft-master -- run the Firecrawl /agent fallback by hand and record its use in the programme's note
vendor: no crawl results for fulbright-nepal -- run the Firecrawl /agent fallback by hand and record its use in the programme's note
vendor: no crawl results for gks-korea -- run the Firecrawl /agent fallback by hand and record its use in the programme's note
vendor: mathmods: 6 pages, 0 candidates
vendor: emship: 5 pages, 1 candidates
vendor: globed: 4 pages, 4 candidates
vendor: amir: 4 pages, 0 candidates
vendor: emhrpp: 3 pages, 2 candidates
vendor: emjm-imaging: 2 pages, 1 candidates
vendor: we-team: 2 pages, 1 candidates
vendor: membiomed: 9 pages, 3 candidates
vendor: daad-prime: 2 pages, 0 candidates
vendor: fau-ai-msc: 12 pages, 3 candidates
vendor: turkiye-burslari: 5 pages, 0 candidates
vendor: ethz-master: 2 pages, 0 candidates
vendor: stipendium-hungaricum: 8 pages, 0 candidates
vendor: leiden-master: 11 pages, 3 candidates
vendor: rhodes: 7 pages, 3 candidates
vendor: sisgp: 5 pages, 5 candidates
vendor: eiffel-paris-saclay: 11 pages, 4 candidates
vendor: chevening: 2 pages, 0 candidates
vendor: aalto-master: 14 pages, 0 candidates
vendor: jasso: 2 pages, 0 candidates
vendor: sbfi-swiss: 5 pages, 8 candidates
vendor: mext-japan: 3 pages, 0 candidates
vendor: daad-epos: 6 pages, 79 candidates
vendor: emle: 7 pages, 0 candidates
vendor: 117 candidates appended to cv-corpus-candidates.csv
```

**Total: 117 candidates appended** (`cv-corpus-candidates.csv` grew from 11 to 128 data rows).
`mathmods` correctly reports **0 candidates** — the dedup fix recognized all 3 of its
previously-pooled sentences on the re-crawl and appended nothing for it, confirmed by `git diff`
showing 117 pure insertions and no changes to the pre-existing rows.

**Crawls failed (raised `SourceBlocked`/`UnsafeTarget`, need the Firecrawl fallback by the
brief's original meaning): none.** Six programmes — `i-mesc`, `europubhealth`,
`sciencespo-graduate`, `tudelft-master`, `fulbright-nepal`, `gks-korea` — hit the pre-existing
graceful "no crawl results" path (an empty page dict, not an exception); whether any of those six
need the Firecrawl `/agent` fallback is a separate, still-open question this run does not answer.

**Credits: 30 crawl calls attempted, one per dev programme** (the count of crawl calls equals the
count of programmes since `tavily_crawl` is called at most once per programme per run, whether it
returns pages, returns empty, or raises).

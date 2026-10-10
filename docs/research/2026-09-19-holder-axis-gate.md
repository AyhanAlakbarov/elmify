# Gate 3.4, positive control: the holder axis decides awards on funder pages, and nothing serves

Run 2026-09-19 with `manage.py funding_yield`, the command that now carries the harness
(`apps/research/management/commands/funding_yield.py`). Hosts:
`docs/research/2026-09-18-positive-control-hosts.txt` — five sites known to hand out
master's money, chosen so that serving nothing means the reader is incomplete, not the page.

Cross-reference owed: this table belongs beside §4.13c of
`2026-09-17-role-routed-discovery-design.md` and §3.4 of the funder-reader design, both of
which live on `claude/program-page-reader`. Move it there when the branches merge.

## The five hosts

| host | pages read | served | unagreed | abstained | noise | unreadable |
|---|---|---|---|---|---|---|
| daad.de | 1 | 0 | 1 | 0 | 0 | 1 |
| tev.org.tr | 0 | 0 | 0 | 0 | 0 | 2 |
| cusanuswerk.de | 2 | 0 | 2 | 1 | 0 | 1 |
| visegradfund.org | 4 | 0 | 5 | 0 | 25 | 0 |
| bw-stipendium.de | 3 | 0 | 2 | 0 | 2 | 1 |
| **total** | **10** | **0** | **10** | **1** | **27** | **5** |

**Read the second column, not the third.** Before this change these pages produced
*pointers*: under the old menu an award on its holder's own page could only be "money a
student gets by applying elsewhere", and `awards()` discarded it. Ten awards are now
decided on funder hosts, which is what the holder axis was for. None is served.

## Why nothing serves — measured, not inferred

The tally now prints which fields the readings split on. Re-reading one host
(`cusanuswerk.de`, 2 pages, both fixes in place):

```
pages=2 served=0 unagreed=3 abstained=0 noise=1 unreadable=1
split-on={'route': 3, 'money_form': 2}
```

**Not `holder`.** The new axis agrees; `route` (how the student gets the money) and
`money_form` (grant, waiver, loan) are what the two model families disagree about, and both
are pre-existing `_DECIDED` fields. Spec §3.3 is explicit that only `offered` gets a
tie-break reading and **every other disagreement goes to the resolution queue** — component
C, which is not in this plan. So A cannot pass a gate measured in *served* awards on its
own: the agreement rule blocks exactly the fields C exists to resolve.

Two directions follow, and they are the owner's call, not a code change to make quietly:

1. Build C (the counsellor queue) and count a queued-then-answered award as served.
2. Decide whether `route` and `money_form` belong in `_DECIDED` at all. An award whose
   money form is disputed between "grant" and "mixed" is still money; refusing to show it
   costs a student the award, while showing it with the disputed field named costs a
   sentence of hedging. **Do not simply drop them** — that is the serve rule weakening, and
   the spec's global constraint forbids it without a decision recorded here.

## Two defects the run found

- **`prompt_cache_key` caps at 64 characters.** Task 6 passed `source_id` raw; a caller
  whose `source_id` is a URL (this command) got `400 Invalid 'prompt_cache_key': string too
  long ... got 67` on **every** OpenAI reading, which `_openai_reading`'s own
  `except Exception` swallowed as a lost reading — visible only as
  `abstained=1 split-on={'readings': 3}`. Measured against the live API on both a 67-character
  URL (refused) and a short key (accepted). Fixed by hashing it with
  `privacy_safe_identifier`, exactly as `safety_identifier` already is and for the same
  documented reason; pinned by test.
- **Five of fifteen pages are JavaScript shells** (`unreadable`), including both of
  `tev.org.tr`. The reader records them rather than reading them as "states no funding",
  which is correct and is also why this control cannot be passed by the reader alone: those
  pages need the vendor fetch path (funder spec §4), which has no client on this branch.

## What was not run

The 58-host before/after (`docs/research/2026-09-18-yield-hosts.txt`) — the comparable
number against the 2 served of 2026-09-18. It is one command; the control above is what
decides whether it is worth its model calls, and on this evidence the answer is to settle
the `route`/`money_form` question first.

# The sweep harness's two owed measurements

Measurement 1 was run on 2026-09-27 with the owner's approval (below). Measurement 2 has not
been run: it is blocked on the prerequisites listed in its section. This note prepares it; it
invents no numbers.

## Measurement 1: Exa `category: company` with client-side exclusion (Task 1)

**Run 2026-09-27 with owner approval ($0.144): not adopted.** Result and labels:
`2026-09-27-exa-category-company-remeasure.md`. The rest of this section is the preparation, kept.

**Decision this settles.** Whether a later change adds `category: company` to Exa's
organisation-search angles. `ExaProvider` does not send it today, and this measurement does
not change that on its own — only a separate change adopts the result.

**Owner approval and cost, stated before any numbers.** The script in the plan's Task 1 Step 2
(`docs/superpowers/plans/2026-09-25-sweep-harness.md`) makes 12 Exa calls at
`numResults: 15` (6 angles x 2 arms), ≈ $0.012/call, ≈ $0.15 total, billed and read back from
each response's `costDollars.total`. Do not run it without that approval.

**The script resolves as written.** Checked by importing every name it uses under
`DJANGO_SETTINGS_MODULE=config.settings.test` with `django.setup()`, no network call made:

```
uv run python -c "
import django; django.setup()
from apps.research.domains import AGGREGATOR_DOMAINS, is_catalogue
from apps.research.egress import fetch_json_api
from apps.research.hosts import registrable_domain
from apps.research.models import OrganisationDomain, RegisterEntry
from apps.research.providers.exa import EXA_SEARCH_URL
from django.conf import settings
"
```

All six imports resolve; `EXA_SEARCH_URL = "https://api.exa.ai/search"`; `fetch_json_api(url,
*, payload=None, params=None, headers, ...)` accepts the script's `payload=`/`headers=`
keywords as called; `settings.EXA_API_KEY` is defined. Nothing in the plan's script needs
correcting against this tree.

**Decision rule, stated before reading the numbers** (unchanged from the plan's Task 1): `category:
company` is adopted only if it returns at least as many VGM-recaptured domains **and** at
least as many hand-labelled novel foundations as `auto`, with no higher noise share.

**Steps, when a key and approval exist:**
1. Run the script above (with a real `EXA_API_KEY`) against the database holding item 6a's
   `vgm_tr` rows — the recapture set the script diffs against.
2. Hand-label every novel domain from both arms (`auto`, `company`) as foundation,
   government, university, or noise (news, blog, directory) — the same labelling the
   2026-09-24 sweep used.
3. Record in a new note (`docs/superpowers/research/2026-09-2x-exa-category-company-remeasure.md`,
   dated the day it runs): both arms' counts, the hand labels, the billed cost, the decision
   rule above, and which way the result went.
4. Commit that note on its own. Adoption of `category: company` (if the rule says yes) is a
   separate change, not part of this note.

## Measurement 2: the saturation gate (Task 11)

**Prerequisites, refused until all hold** (per the plan's Task 11):
- A per-language kind-word vocabulary adapter is wired into
  `generate_sweep_angles._vocabulary()`. As built, `_vocabulary()` returns `None` and the
  command's own docstring says why: item 8's `apps/research/vocabulary.py` maps a folded word
  to Wikidata kind QIDs with no language key and no holder-kind map, so it cannot answer
  `KindVocabulary.words(kind, language)` yet. `--from-steering` (one hand-written angle,
  `PRIVATE_FOUNDATION` only) is the interim and does not satisfy this prerequisite — one
  angle is not an angle set.
- Gate B only: item 7's Azerbaijan register survey states AZ's rung for
  `PRIVATE_FOUNDATION`, and any register it names has been read (has `RegisterEntry` rows).
- The Jev classifier gate (or its frontier fallback) has run, and its measured accuracy is
  recorded beside every figure below — "verified" in this gate means the classifier's
  `funds_students`.

**The commands, as built.** `sweep_organisations` takes no `--rung` and no `--register` flag
— the rung and register are derived from `ClosedList` by `apps.research.harness.ladder_rung`,
never passed. Confirmed by reading `sweep_organisations.py`'s `add_arguments` and
`harness.ladder_rung`, not by running a pass:

```
uv run python manage.py generate_sweep_angles --country TR --family PRIVATE_FOUNDATION
uv run python manage.py sweep_organisations --country TR --family PRIVATE_FOUNDATION --budget-usd 5
uv run python manage.py sweep_tally --country TR --family PRIVATE_FOUNDATION

uv run python manage.py generate_sweep_angles --country AZ --family PRIVATE_FOUNDATION
uv run python manage.py sweep_organisations --country AZ --family PRIVATE_FOUNDATION --budget-usd 10
```

**Which list each pass is actually diffed against**, read from `docs/research/closed-lists.csv`
and `angles.PASS_SHAPES` (ruling R12). The ladder is the lists of the kinds the pass searches
for — `PASS_SHAPES["PRIVATE_FOUNDATION"].kinds` is `PRIVATE_FOUNDATION`, `POLITICAL_FOUNDATION`,
`RELIGIOUS` — not every kind `FAMILY_BY_HOLDER` files under the family: banks and professional
bodies map to the foundation family but are reached by register and domain call, never by
open-web search (spec 6.3), so their lists are not this pass's denominator. "Verified" credit
stays family-wide (spec 6.7): a bank host a foundation pass finds still counts.

- **TR / PRIVATE_FOUNDATION -> `vgm_tr`, rung 1.** The only TR list of a searched-for kind;
  it is the recapture denominator. `tr_banks` and `tr_professional_bodies` are not on this
  pass's ladder.
- **AZ / PRIVATE_FOUNDATION -> rung 4, search only.** No AZ list holds a searched-for kind
  (`az_banks` is `BANK_OR_LENDER`), so there is no register to diff against and `recaptured`
  is 0 by construction — unless item 7's AZ survey adds a foundation list, which then must be
  read (have `RegisterEntry` rows) before the pass runs: `ladder_rung` refuses a winning rung
  <= 3 whose register is empty.

**Languages.** A pass runs in the country's Wikidata P37 languages, then English. A diaspora
pass (`AFFINITY_OR_DIASPORA`) is keyed (host country, home language) and takes exactly one
`--home-language`: it runs in that language, then English. Every angle and run row carries
the home language in its key, so the English set of the `az` pass in DE is never the `tr`
pass's.

**Fields to report** (Gate A, from the plan's Task 11, unchanged): stop reason and batch
count; the per-batch curve of novel and verified hosts; `recaptured` against `vgm_tr`; new
verified hosts outside the register; precision (verified / novel); hand-labelled noise share;
novel hosts by (classified family, provider) -- every provider that returned one -- and
first-discoveries per angle and per language; search and
fetch spend.

**Fail criteria** (unchanged from the plan's Task 11):
1. Pass ends `BUDGET` or `CLASSIFIER_LIMIT` — neither stop rule reached.
2. Pass ends `EXHAUSTED` — the angle set was too small; raise `PASS_SHAPES[...].samples` and
   re-run rather than report a plateau.
3. The report cannot separate `recaptured` from "verified outside the register" against
   `vgm_tr`.
4. Hand-labelled noise share among novel `.tr` hosts is >= 28% (20 of 72, the 2026-09-24
   topic-query baseline).

Gate B adds: fails if the pass ends `BUDGET` at $10 before either stop rule fires (on a thin
cell that means the stop rules cannot be read where they matter most, and the finding is that
the route should switch before scaling); reports in-country precision against the measured
10-17% for Azerbaijan; the curve itself is the deliverable pass or fail.

Nothing above was run. No pass, no classifier call, no search call was made to produce this
note.

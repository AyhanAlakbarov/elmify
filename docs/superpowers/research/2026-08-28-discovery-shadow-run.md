# Discovery increment 1 — first shadow run against the live network

Run 2026-08-28 from the dev environment (local Postgres, real S3 bucket
`tehsil-evidence-367842306577` in eu-central-1, real OpenAI key, no search key).
Command: `manage.py discover --field robotics --country DE --tenant <agency> --max-leads 5`,
then a second run at `--max-leads 2`.

## Result

| Run | leads | written | unchanged | blocked | degraded |
|---|---|---|---|---|---|
| dry run | 5 | 0 | 0 | 0 | none |
| live, 5 leads | 5 | 0 | 0 | 5 | none |
| live, 2 leads | 2 | 0 | 0 | 2 | none |

Zero catalog rows. Zero snapshots. Five `ConsultantResearchTask` rows, all
recording `source returned HTTP 403`.

## What works

- **The EACEA seed adapter works against the live catalogue.** It fetched the
  real listing and harvested **60 genuine Erasmus Mundus detail URLs**
  (`erasmus-plus.ec.europa.eu/projects/search/details/<id>`), paging correctly
  and de-duplicating.
- **The egress layer works.** A direct `fetch_official_source` on one of those
  detail URLs returns HTTP 200 and 172,132 bytes.
- **The object store works.** A put/get round trip through `S3ObjectStore`
  succeeded and recorded a real S3 version id (`DN33f4f_...`), not `"null"` —
  bucket versioning is doing what the evidence chain needs.
- **Invariant 4 held against a real server.** Every refusal became a consultant
  task. Nothing crashed, nothing was silently dropped.

## Why nothing was written — the decisive finding

**`erasmus-plus.ec.europa.eu` detail pages are client-side rendered.** The
172 KB response yields **2,772 characters of visible text**, all of it site
chrome ("Search - Erasmus+", menu, disclaimer, terms-of-use notice). The
project's own content — title, consortium, partner institutions, programme
website — is not in the static HTML. Markers: 553 `ecl-`, 62 `drupal-`,
86 `ng-`, and zero server-rendered project fields.

Consequences, both verified directly:

1. `official_url_from_catalogue_page()` returns **None** for these pages. There
   is no institution link to hop to. Of 36 anchors, the only off-`europa.eu`
   links are Facebook, Instagram, X, LinkedIn, Bluesky and YouTube.
2. Even if the hop were skipped, `page_text()` would hand the extraction model
   2.7 KB of navigation furniture, so no claim could be extracted either.

So the EACEA catalogue is **BROWSER_REQUIRED at the detail level** — design
§2.1 tier 3, the same tier as Campus France — even though its *listing* is
static HTML and the adapter reads it correctly. The access-terms review had
this host as SHIP, which remains true: this is a technique limit, not a
permission one.

## The standing position

Every route to a catalog row is currently closed:

| Route | Status |
|---|---|
| DAAD International Programmes (JSON API, tier 1) | Access-terms HOLD; adapter deliberately not built |
| EACEA Erasmus Mundus (shipped seed) | Listing static and working; **detail pages need a browser** |
| Live search → institution pages directly | No provider key, and the wired provider's ToS forbids persisting results |

The engine is correct — 201 tests green, every invariant verified across
commits — and it discovers nothing, because all three inputs are blocked for
three different reasons.

## The 403s were transient, and the message was misattributed

The recorded reason is `source returned HTTP 403` on the EACEA detail URLs.
Isolated fetches of the same URLs immediately afterwards returned 200, both
standalone and in listing-then-detail sequence, so the site throttles bursts
rather than blocking us. Not the reason nothing was written — the hop returns
None regardless.

**Separate defect worth fixing:** in `run_discovery`, when the *hop* fetch
fails, the exception handler records `lead.canonical_url` — the catalogue URL —
because the lead is only rebuilt after that fetch succeeds. A consultant
working the queue is pointed at the catalogue page rather than the page that
actually failed.

## Cheapest routes out, ranked

1. **A search provider with acceptable terms.** Produces `PROGRAM` leads
   pointing straight at institution pages, skipping the catalogue hop entirely
   — no browser, no catalogue permission. Perplexity Search was the design's
   named fallback; its storage terms need the same check Exa got.
2. **DAAD permission.** One request. Unlocks a public faceted JSON API whose
   records already carry the institution's own `link`, so no rendering needed.
3. **Browser rendering for catalogue detail pages.** Heaviest, but this repo
   already has a renderer sandbox from the Phase 3 portal work that could serve
   it.

---

## Addendum, same day: EACEA was never a rendering problem

After shipping the rendered fetch mode, the first real render of
`erasmus-plus.ec.europa.eu/projects/search/details/101241136` returned, from the
server itself:

> **403 - Disallowed by robots.txt** — Status ID 331182fc

Their `robots.txt` carries `Disallow: /search/`, and their edge is treating
`/projects/search/details/` as covered by it. Under a strict reading of the
robots standard a `Disallow: /search/` prefix does not match
`/projects/search/details/`, so their matching is broader than the rule as
written — but that is not our call to make. The site is stating plainly that it
does not want automated retrieval of these pages.

**So the diagnosis in the section above was wrong, and rendering is what
corrected it.** The blocker is policy, not technique. Client-side rendering was
real but incidental; even a perfect renderer does not get this data.

**The mechanism of the correction is worth keeping.** Plain retrieval, sending
no `User-Agent`, received HTTP 200 and 172 KB of meaningless shell — an
ambiguous non-answer that read as a technical limitation. The renderer, sending
`tehsil-discovery/1.0 (+https://tehsil.app/bot; funding research)`, received a
clear refusal naming its reason. Identifying honestly is what produced a usable
answer; anonymity produced noise that pointed at the wrong conclusion.

This also settles a live design argument in favour of the existing constraint.
The rule to respect published access terms (§7.4) was called excessive caution
earlier in the session. The first source we tried at production intent says no,
in writing, at the server. The rule is load-bearing.

### What follows

- **EACEA detail pages are out**, unless someone asks EACEA for permission —
  the same conversation DAAD needs. The listing remains fetchable and the seed
  adapter still harvests 60 real URLs from it; what cannot be taken is the
  detail behind each one.
- **Two of three catalogue routes are now permission-blocked rather than
  technically blocked** (DAAD by terms, EACEA by robots), which moves the
  decision further toward search → institution pages directly. Institutions'
  own programme pages are the target anyway, and they carry no comparable
  policy.
- **The rendered fetch mode remains worth having.** It is not wasted: it is the
  answer for genuinely JavaScript-only sources that permit retrieval, and it is
  what surfaced this refusal instead of hiding it behind a shell.

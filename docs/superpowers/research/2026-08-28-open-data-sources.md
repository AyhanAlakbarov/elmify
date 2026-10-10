# Licensed open data for discovery — first pass

Probed 2026-08-28. The question: can licensed, machine-readable datasets replace
HTML scraping, given that every scraping route so far has failed on permission,
rendering, or storage terms?

## Confirmed working, no key, permissive licence

| Source | Probe | What it gives |
|---|---|---|
| **ROR** (Research Organization Registry) | `api.ror.org/v2/organizations?query=Nuremberg` → HTTP 200, 9 results, no key | Canonical institution identity: persistent IDs, name variants, country, relationships. **CC0.** |
| **OpenAIRE** | `api.openaire.eu/search/projects` → HTTP 200 | Research project metadata; relevant to the research-ecosystem pathway, not to taught master's |

ROR is an immediate win and solves a problem the catalog has today:
`catalog_key(country, institution_name)` currently dedupes on a normalised
string, which is why "Nürnberg" vs "Nuremberg" needed a deliberate workaround in
`location_key`. ROR IDs replace string matching with a real identifier.

## The lead that did not pan out

**The Erasmus+ project catalogue does not appear to be published as open data.**
`data.europa.eu` returns 158 datasets matching "erasmus" with the dataset filter
applied, but they are individual universities' incoming/outgoing mobility
records (Italian, Greek, and other national portals) — not the central Erasmus+
Project Results Platform. A filtered query for "Erasmus+" specifically returns
**zero** datasets.

So the hoped-for outcome — that the very records whose HTML we could not parse
were sitting in a CC BY dataset — is not supported. The Commission's CC BY 4.0
grant covers its website content, but the project database itself is not
published as a reusable dataset that this probe could find.

Endpoint-guessing against the platform's backing API was attempted and
abandoned: `webgate.ec.europa.eu/.../api/search/project` and two other patterns
returned 403/404. Guessing undocumented endpoints is not a supported integration
and is not the kind of access this project builds on.

## Reachable, unassessed — this is where the real work is

| Corridor | Source | Probe |
|---|---|---|
| DE | Hochschulkompass (HRK) | HTTP 200 |
| TR | YÖK Atlas | HTTP 200 |
| KR | 대학알리미 (academyinfo.go.kr) | HTTP 200 |
| KR | data.go.kr national portal | HTTP 200 |
| HU | felvi.hu | connection failed (000) |

Reachability is not a licence and not a machine-readable interface. Each needs
the same treatment DAAD and EACEA got: published terms, quoted clause, and a
check for whether a listing exists in static HTML or behind an API.

## The conclusion that matters, and it corrects my earlier framing

**Open data solves a different problem than the one blocking discovery.**

What these sources give is *institution identity* and *accreditation status* —
which is exactly what the portfolio spec's §6 legitimacy gate needs, and ROR
alone is worth adopting for that. What none of them give is **programme-level
data**: which master's programmes exist, in what language, over how many months,
with what fees and deadlines. That is the catalog's core, and it is published as
human-readable prose on institutions' own websites, not as datasets.

So open data **complements** discovery; it does not replace it. My earlier
suggestion that it might sidestep the search question was wrong, and this probe
is what showed it.

## Recommendation

1. **Adopt ROR now**, independently of everything else. Free, CC0, no key, and it
   replaces string-matched institution dedupe with real identifiers.
2. **The search question still decides discovery.** Ask Brave and Perplexity the
   transient-storage question — that remains the unblock.
3. **A real corridor-by-corridor open-data survey is warranted, and is genuinely
   deep research**: seven corridors × (programme catalogue, institution register,
   accreditation register), most in non-English portals with their own licences.
   That is too large to do inline and should be scoped as its own pass, aimed at
   the §6 legitimacy gate rather than at discovery.

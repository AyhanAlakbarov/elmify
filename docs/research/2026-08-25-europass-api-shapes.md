# Europass e-Portfolio API: captured request shapes

Captured 2026-08-25 by driving the live Europass CV editor and intercepting its own
requests, then replaying them through plain `urllib`. This is the authority for
`apps/documents/europass.py`'s mapper — the field names were NOT guessable, and six
guesses produced six bare HTTP 500s before this was captured.

Kept in the repo because it is not reproducible cheaply: it cost a full browser-driving
session, europa.eu publishes no schema for this service (its `/v3/api-docs` documents
only the API gateway's own three endpoints), and the API answers a wrong shape with a
bare 500 carrying no validation detail.

---

# Task 4b report: Europass ENTRY shapes, captured from the real editor

Status: **DONE**

## How this was done

Explored interactively via the Playwright MCP browser tools against the live guest CV
editor at `https://europa.eu/europass/eportfolio/screen/cv-editor` (one browser session,
one guest CV). The "standard" builder (`.../cv-editor/legacy-cv-editor`) only edits
`personalInformation` -- it has no UI for education, work experience, languages, skills,
etc. at all. The "beta" builder (`.../cv-editor/compact-cv-editor`, reached via "Try the
new CV builder (beta)") is the one that exposes an "Add new section" flow for every
profile section, so that is the one that was driven.

Filled one entry per section with synthetic data (`Canary Probe`, `canary@example.invalid`,
`Example University`, `Example GmbH`, `Example City`) and read back the request/response
bodies via the MCP `browser_network_request`/`browser_network_requests` tools and via
`fetch()` GETs run in the page's own session (`page.evaluate`). The session learned is
codified into `capture_entry_shapes.py` (sync Playwright API) for reproducibility; it was
not itself executed live (re-running it would open a second guest session, which the
brief's "no hammering" rule argues against once the data is already in hand).

All 8 sections targeted by the brief were successfully added, filled, and saved:
Personal Information, Language Skills, Education & Training, Work experience, Skills,
Projects, Publications, Honours and Awards. Every autosave `PUT /eprofile/cv/{id}`
returned **200** (never a 500) -- the "Discrepancies found" dialog seen occasionally in
the UI is a client-side validation summary, unrelated to the HTTP status.

Raw captured request/response bodies: `captured-requests.json` (8 entries: 7 `PUT`s
building the document up section by section, plus the final `GET` readback showing the
server-canonical, normalized shape).

## THE answer: per-section entry shape table

| Section | Profile key | One entry's shape (server-canonical, from GET) |
|---|---|---|
| Language | `languageSkills.nativeLanguages[]` | `{"languageCategory": "NORMAL", "language": "aze", "mediaAttachments": []}` |
| Language | `languageSkills.otherLanguages[]` | `{"languageCategory": "NORMAL", "language": "eng", "listening": "B2", "reading": "B2", "spokenInteraction": "B2", "spokenProduction": "B2", "writing": "B2", "mediaAttachments": []}` |
| Education | `educationTrainings[]` | `{"id": "<uuid>", "order": 0, "qualification": "Bachelor of Canary Studies", "organisationName": "Example University", "streetAddress": null, "postalCode": null, "city": "Example City", "country": "de", "website": null, "creationDate": "<iso>", "startDate": {"date": "2020-09-01", "dateType": "DAY", "empty": false}, "endDate": {"date": "2023-06-30", "dateType": "DAY", "empty": false}, "ongoing": false, "description": null, "studyFields": [], "finalGrade": null, "thesis": null, "eqf": "6", "nationalClassification": null, "typeOfCredits": null, "numberOfCredits": null, "validUntil": null, "mediaAttachments": null, "links": []}` |
| Work experience | `workExperiences.solidWorkExperiences[]` | `{"id": "<uuid>", "order": 1, "employerDetails": {"employer": "Example GmbH", "organisationDepartment": null, "organisationBusinessSector": null, "organisationWebsite": null, "organisationContactEmail": null, "organisationAddress": {"addressPart1": "", "addressPart2": "", "postalCode": "", "city": "Example City", "country": "de"}}, "workExperience": {"id": "<same uuid>", "occupation": {"label": "Canary Handler", "uri": null}, "creationDate": "<iso>", "startDate": {"date": "2023-07-01", "dateType": "DAY", "empty": false}, "endDate": {"date": "2024-12-31", "dateType": "DAY", "empty": false}, "ongoing": false, "mainActivities": null, "mediaAttachments": null, "links": null, "groupReference": null}}` |
| Skills | `profileSkills.other[]` | `{"type": "digitalSkill", "label": "Microsoft Office"}` (free-text/other skills added via `groups[]` instead, not exercised) |
| Projects | `projects[]` | `{"id": "<uuid>", "order": 0, "title": "Canary Nest Tracker", "description": null, "creationDate": null, "startDate": {"date": "2024-01-01", "dateType": "DAY", "empty": false}, "endDate": {"date": "2024-06-01", "dateType": "DAY", "empty": false}, "ongoing": false, "mediaAttachments": null, "links": null}` |
| Publications | `publications[]` | `{"id": "<uuid>", "order": 0, "title": "Canary Migration Patterns", "creationDate": null, "year": null, "reference": "C. Probe (2024)", "doi": null, "description": null, "mediaAttachments": null, "links": null, "authors": null, "journalConference": null, "publisher": null, "volumeIssuePages": null}` |
| Awards | `honoursAwards[]` | `{"id": "<uuid>", "order": 0, "title": "Best Canary Handler Award", "description": null, "institution": "Example GmbH", "creationDate": null, "date": {"date": "2024-12-15", "dateType": "DAY", "empty": false}, "mediaAttachments": null, "links": null}` |

## The specific questions the brief asked

**The five CEFR sub-skill key names, as they really appear:**
`listening`, `reading`, `spokenInteraction`, `spokenProduction`, `writing` -- **exactly
the brief's original guess.** Values are plain CEFR level strings (`"A1"`..`"C2"`), not
nested objects. These five keys are the correct ones; the earlier 500s were not caused by
a wrong key-name guess (see "what actually broke Task 4," below).

**How a language is identified:** ISO 639-3 three-letter lowercase code as a plain string
under the `language` key -- `"aze"` (Azerbaijani), `"eng"` (English). **Not** ISO 639-1
(`"az"`/`"en"`), **not** a display name, **not** a nested object in the persisted shape.
Each entry also needs `"languageCategory": "NORMAL"` and `"mediaAttachments": []`
alongside `language` -- these are required siblings, not optional decoration (see below).

**`educationTrainings` entry field names:** `qualification`, `organisationName`,
`streetAddress`, `postalCode`, `city`, `country` (ISO 3166-1 alpha-2, lowercase --
`"de"`), `website`, `startDate`/`endDate` (nested `{date, dateType, empty}` objects, not
flat ISO strings), `ongoing`, `description`, `studyFields`, `finalGrade`, `thesis`, `eqf`
(EQF level as a **string**, `"6"` not `6`), `nationalClassification`, `typeOfCredits`,
`numberOfCredits`, `validUntil`, `mediaAttachments`, `links`.

**Do entries carry a server-assigned `id`/`uuid`?** It's mixed and section-dependent:
- `educationTrainings`, `workExperiences.solidWorkExperiences`, `projects`,
  `publications`, `honoursAwards` -- **yes**, each entry gets a server-assigned UUID
  (visible on GET readback even though the client's own PUT already sent one it
  generated client-side and the server kept it unchanged in this session's observations).
- `languageSkills.nativeLanguages[]` / `otherLanguages[]` -- **no** `id` field on
  individual entries. Only the parent `languageSkills` object has an `id` (which stayed
  `null` throughout this session).
- `workExperiences.solidWorkExperiences[]` entries are unusual: the **same UUID** is
  reused for both the outer wrapper's `id` and the nested `workExperience.id`.

## What actually broke Task 4's language attempts

Task 4's six 500s all sent a bare `{"language": "..."}` (in various code systems) with no
sibling fields. The real editor never sends that shape -- every language entry, native or
other, always carries `languageCategory: "NORMAL"` and `mediaAttachments: []` alongside
`language`. It's plausible the 500 was a validation failure on a missing required field
(`languageCategory` and/or `mediaAttachments`), not on the code system itself -- Task 4's
attempt #1 (`{"language": "aze"}`, ISO 639-3, no other fields) used the *correct* code
system and still 500'd, which is consistent with this reading.

## Verification: replay through the API directly, independent of the browser

Per the brief's mandatory verification step, `verify_replay.py` uses plain `urllib` (no
Playwright) to independently reproduce the transport contract already proven in
`apps/documents/europass.py`/`europass_canary.py` (GET `frontend-config` for the
XSRF-TOKEN cookie -> POST `eprofile/cv` to create -> PUT the captured language shape ->
GET to read it back), starting a fresh guest session with no relation to the browser
capture above.

```
$ uv run python .superpowers/sdd/2026-08-25-europass-api-render/verify_replay.py
GET frontend-config -> 200
POST eprofile/cv (create) -> 201
cv id: 8820b7cf-3515-4ba2-9125-8fc95db66ace
PUT eprofile/cv/{id} (replayed language shape) -> 200
PUT response body: b'{"id":"8820b7cf-3515-4ba2-9125-8fc95db66ace"}'
GET eprofile/cv/{id} (readback) -> 200
languageSkills after readback:
{
  "id": null,
  "nativeLanguages": [
    {
      "languageCategory": "NORMAL",
      "language": "aze",
      "mediaAttachments": []
    }
  ],
  "otherLanguages": [
    {
      "languageCategory": "NORMAL",
      "language": "eng",
      "listening": "B2",
      "reading": "B2",
      "spokenInteraction": "B2",
      "spokenProduction": "B2",
      "writing": "B2",
      "mediaAttachments": []
    }
  ],
  "showGuidanceLevelSentence": null
}

VERIFIED: replayed language shape round-trips as 200, not 500.
```

**200, not 500** -- exactly the outcome the brief asked to prove. The language section
came back populated on GET with the exact sub-skill values sent. This turns "we observed
a body in the browser" into "the mapper will work": the shape is real, minimal (no
`natives`/`others` client-noise needed), and portable outside the browser session that
captured it.

## Surprises for Task 5's mapper

1. **The "standard" CV builder is a dead end for anything but personal info.** Anyone
   reaching for the first/default editor entry point will conclude (as Task 4 did) that
   education/work/language sections aren't supported on create -- they're supported, just
   not through that UI. The beta/compact builder is the one that matters.
2. **`natives`/`others` in the PUT body are client view-state, not schema.** The live
   editor's autosave PUT includes redundant `languageSkills.natives.languages[]` /
   `others.languages[]` blocks (full language *objects* with `label`/`value`/`title`)
   alongside the real `nativeLanguages[]`/`otherLanguages[]` arrays. These do **not**
   survive to the GET readback -- the server evidently ignores or strips them. The mapper
   should send only `nativeLanguages[]`/`otherLanguages[]`; the `natives`/`others` blocks
   are safe to omit.
3. **Dates are sent as full ISO datetimes but read back as date-only.** The PUT body uses
   `{"date": "2020-09-01T00:00:00.000Z", "dateType": "DAY"}`; the GET readback normalizes
   to `{"date": "2020-09-01", "dateType": "DAY", "empty": false}` (adds `empty`, drops the
   time-of-day). Sending the date-only form was not tested directly, but the `empty` field
   appearing only on readback suggests the server, not the client, owns that field --
   worth a cheap try-date-only-first check before assuming the full-ISO form is required.
4. **`country` in education/work-experience is ISO 3166-1 alpha-2, lowercase** (`"de"`)
   -- a different code system from the language's ISO 639-3, easy to conflate if a mapper
   reuses one "country/language code" helper for both.
5. **EQF level is a string, not a number** (`"6"`), even though the UI presents it as a
   numbered dropdown 1-8.
6. **The response body of a `PUT` is minimal** (`{"id": "..."}`), unlike `POST` create
   which returns the full document. A caller that PUTs and expects the updated document
   back in the response, rather than doing a follow-up GET, will get much less than it
   expects. `apps/documents/europass.py`'s existing GET-after-write pattern already
   anticipates this correctly.
7. **The per-section "Add new section" UI button is ambiguous by DOM position** when
   automating: there are two such buttons (before the first section, after the last), and
   once a section already exists empty, adding its first entry goes through that
   section's own "Actions -> Add X" menu instead of the global dialog. Not an API finding,
   but worth flagging in case Task 5's own verification tooling drives the UI again.

## Live-network call count

One capture session: guest CV created once, 7 section-adding autosave `PUT`s (all 200), 1
create `POST` (201), a handful of read-only `GET`s (readback + codification lookups the
UI itself triggers, e.g. `codifications?types=profileLanguages`, `?types=countries`,
`?types=cefrLevels`, `?types=eqfs`). Plus the separate verification run: 1
`GET`/`POST`/`PUT`/`GET` sequence (4 calls) against a fresh guest session via `urllib`.
No loops, no retries of an identical request, no more than the one browser session the
brief asked for.

## Files

- `.superpowers/sdd/2026-08-25-europass-api-render/captured-requests.json` -- 8 captured
  `{"method", "url", "body"}` entries (7 `PUT`s + 1 final `GET` readback), pretty-printed.
- `.superpowers/sdd/2026-08-25-europass-api-render/capture_entry_shapes.py` -- reproducible
  sync-Playwright script codifying the interactive MCP session (selectors, click order,
  synthetic values) that produced the capture.
- `.superpowers/sdd/2026-08-25-europass-api-render/verify_replay.py` -- the independent
  `urllib` verification script and its evidence (above).
- This report.

`git status` was checked before and after; no files outside `.superpowers/` (git-ignored)
were touched. `apps/`, `tests/`, `pyproject.toml`, and the plan documents were not opened
for editing.

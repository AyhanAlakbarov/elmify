# WHED recon — the IAU World Higher Education Database as a register

**Measured 2026-09-11**, in the format the parent design's §9 asks for: access route, HTTP status,
byte count, row count, authentication, cadence, terms, and what an absence means. Every figure is a
dated snapshot of a live site.

## Terms — established in writing

WHED's published terms (`whed.net/Terms_of_use.html`, read 2026-09-11) say the IAU holds the
intellectual property rights and *"the copying of all or substantial parts of the Portal is not
allowed without prior consent of IAU."* The project rule is that no adapter is written for a host
whose terms cannot be established, so consent was asked for.

**Consent, received by the project owner on 2026-09-11 from an IAU staff member, verbatim:**

> Dear Orkhan, I hope you are well! You can scrape and access without any problem but we can't help
> you exactly how. So, feel free to do it yourself at your most convinient way! Best regards

**What this establishes:** scraping and access, with no condition on method. **What it does not
name:** storage of the data in our own database, and use inside a commercial product. Both are what
the adapter does. A follow-up asking IAU to confirm those two words is a work item, not a blocker;
the reply's "without any problem ... at your most convenient way" is read as covering them until IAU
says otherwise. This is the same shape as the anabin decision in the parent design's §7: an owner
decision, recorded, not re-argued.

## What WHED is

The International Association of Universities' database, run with UNESCO, of *"all accredited or
recognized higher education institutions that meet WHED criteria (currently ca. 21,000 HEIs)"* in
196 countries. Each has a *Global WHED ID* of the form `IAU-011713`. From `whed.net/About.html`,
the conditions for listing:

> Be recognized and referenced by the national competent body. Be a degree-conferring institution
> offering at least a four-year degree. Have had at least three cohorts at undergraduate level or
> its equivalent at a postgraduate institution. [...] Institutions that may have been recognized by
> their national competent body in the past, but are no longer recognized, are not listed in the
> WHED.

DEQAR's own submission rules (`docs.deqar.eu/stable/institution_data`) say an institution that
provides a WHED identifier *"is thus accepted automatically"* as nationally recognised. That is a
regulator using WHED presence as an automated verdict, which is exactly what this project needs.

## Access route

| what | route | status | notes |
|---|---|---|---|
| home and search form | `GET https://whed.net/home.php` | 200, 43,533 bytes | plain HTML, `PHPSESSID` cookie set, no JavaScript needed |
| per-country listing | `POST https://whed.net/results_institutions.php` with `Chp1=<country>`, `nbr_ref_pge=100`, `debut=<offset>`, `afftri=yes`, `stat=Country`, `Ope0=and`, empty `Chp0`/`Chp2`/`Chp4`/`Chp5` | 200, ~108-125 KB a page | 100 rows a page; `debut` is the row offset. Each row carries the IAU ID, English name, native name and an IAU-member flag. Detail links on the page are opaque, session-bound tokens |
| all-countries listing | same POST with empty `Chp1` | 200 | **returns the search form, no results.** A full walk is one POST per country, 266 options |
| stable institution page | `GET https://whed.net/institutions/IAU-011713` | 200, 11,180 bytes | **no session, no referer needed.** Shows name, native name, country, address, website, funding, founding history, accrediting agency, degrees, officers |
| unknown ID | `GET https://whed.net/detail_institution.php?id=IAU-019897` | **200, 21 bytes: `Institution not found`** | a miss is a 200, not a 404. The read must check the body |
| `www.whed.net`, any path | | **403**, Cloudflare "Just a moment" challenge | never use the `www` host. The bare host serves everything |
| `robots.txt` | | | disallows only `/pdf/` and `/workspace/` |

**Timing.** Country POSTs answered in 0.7-1.7 s. Six stable-page GETs in a row: 0.29-1.47 s each,
all 200, no throttling seen. Longer horizons not tested.

**Cadence.** The page footer reads "Database update September 2026". Monthly.

## Counts, against DEQAR's file the same day

| country | WHED listed | DEQAR open | DEQAR CLEAR under the 2026-09-11 rule |
|---|---|---|---|
| United States of America | 2,552 | 286 | 4 |
| Germany | 360 | 494 | 401 |
| Ukraine | 297 | 707 | 35 |
| Türkiye | 178 | 211 | 130 |
| Kazakhstan | 111 | 170 | 117 |
| Azerbaijan | 45 | 13 | 10 |

WHED lists fewer institutions than DEQAR in Europe because it admits only degree-granting,
nationally recognised institutions and drops delisted ones; it lists the anglophone destinations
DEQAR cannot see at all.

**DEQAR carries WHED IDs for 2,755 of its 8,062 open institutions** (`identifiers_all`, the form
`WHED:IAU-019897`), 0 for Ukraine and the United States, 86 of 1,340 for Spain. A crosswalk, not a
substitute for the site.

## What an absence means

Not listed in WHED means one of: not recognised by the national competent body; recognised but
not degree-granting at four-year level; fewer than three cohorts; delisted; or not yet entered. WHED
does not say which. The parent design's rule holds: absence is unknown, never a negative.

## Search by ID — measured 2026-09-12

WHED's search form also accepts a plain GET, which gives every bound institution a re-runnable
query that answers whether its ID is in the list now:

```
GET https://whed.net/results_institutions.php?Chp2=IAU-011713&Chp0=&Chp1=&Ope0=and&Chp4=&Chp5=&nbr_ref_pge=100&debut=0&afftri=yes&stat=Country
```

| ID | HTTP | bytes | result line, `<p class="infos">`, verbatim |
|---|---|---|---|
| `IAU-011713` | 200 | 28,075 | `1 results found for (Global WHED ID=IAU-011713)` |
| `IAU-000000` | 200 | 24,370 | `No matching records for (Global WHED ID=IAU-000000)` |

No session and no referer were needed. The hit page carries one result row, the ID in
`<span class="gui">`, the English name in the row's `<h3><a>`, the native name in `<p class="i_name">`
and the country in the row's first right-aligned block.

**The miss page prints the searched ID twice**, in its result line and in the search box's `value`.
A read that tested for the ID's presence would clear every missing institution. Key on the whole
result line.

This is the route the adapter uses (design §2.2): it answers WHED's own listing rule directly, where
the stable page only shows that a page exists.

## Not established here

- Whether IAU's consent extends, in their words, to storage and commercial use (above).
- Rate limits over a full walk, or over months of daily stable-page fetches.
- Whether a delisted institution's stable page is removed or kept with a note. The adapter reads the
  search instead, so this no longer affects a verdict; one observed delisting would still settle it.
- The Global WHED ID's shape beyond the six-digit form seen on every page read.
- How "United States of America (all)" and the per-state entries in the country list relate.

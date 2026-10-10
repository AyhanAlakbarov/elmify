# 1a membership enumeration — per-claim sourcing: method, two bodies closed, the rest scoped

**Date:** 2026-08-29. **Addresses** open item 4 of `2026-08-29-nationality-keyed-synthesis.md` §9:
"the 1a membership enumeration's per-claim sourcing".

**Status: NOT closed.** Two bodies are sourced to their own pages. The remainder is scoped below with
a working recipe and a demonstrated failure mode. This file exists so the next run starts from a
method rather than from scratch.

---

## 1. The axis to invert

The naive shape is 9 countries × dozens of bodies — hundreds of individual claims. But **membership is
published by the organisation, not by the member**: each body publishes one list, and one fetch
resolves all nine countries against it at once. That turns hundreds of claims into roughly twenty
fetches.

Source by **body**, never by country. A country's foreign ministry page is a secondary source for its
own membership; the organisation's list is primary.

## 2. The failure mode, demonstrated

A whole-page regex for country names is **not sourcing**, and it produces confidently wrong claims.
Run against the Organization of Turkic States' page, a substring match reported **Turkmenistan as a
member**. The page itself says otherwise:

> "MEMBER STATES **AZERBAIJAN KAZAKHSTAN KYRGYZSTAN TÜRKİYE UZBEKISTAN** — OBSERVERS **HUNGARY
> TURKMENISTAN** TURKISH REPUBLIC OF NORTHERN CYPRUS"

Turkmenistan is an **observer**. Observer status is not membership, and for a scholarship keyed to
member states the difference decides eligibility. The same regex would also match a country named in a
news item, a language switcher, or a navigation menu.

**Rule for the next run: extract the member-list section and quote it. Never assert membership from a
page-level match.** Capture observer, associate and dialogue-partner status as distinct values — the
1b axis in the original prompt asks for exactly this distinction and a boolean loses it.

## 3. Closed, with quotations

### Organization of Turkic States — `turkicstates.org/en/organization-of-turkic-states`

| | our nine |
|---|---|
| **Members** | Azerbaijan, Kazakhstan, Kyrgyzstan, Türkiye, Uzbekistan |
| **Observers** | Turkmenistan |
| **Neither** | Armenia, Georgia, Tajikistan |

Tajikistan's absence is correct rather than an oversight — it is Persian-speaking and not a Turkic
state. Also observers: Hungary and the Turkish Republic of Northern Cyprus.

### Economic Cooperation Organization — `eco.int/member-states/`

Quoted verbatim: *"Currently ten countries from West and South Asia, Caucuses and Central Asia are
Members of the Organization"* — Afghanistan, Azerbaijan, Iran, Kazakhstan, Kyrgyz Republic, Pakistan,
Tajikistan, Türkiye, Turkmenistan, Uzbekistan.

| | our nine |
|---|---|
| **Members** (7) | Azerbaijan, Kazakhstan, Kyrgyzstan, Tajikistan, Türkiye, Turkmenistan, Uzbekistan |
| **Not members** | Armenia, Georgia |

The page requires a browser-class fetch; a plain GET returns navigation only.

**Note the shape.** OTS and ECO between them cover seven of the nine, and **Armenia and Georgia are in
neither**. Any enumeration built only from Turkic and Central Asian bodies structurally under-serves
the two Caucasus countries that are not Turkic — which is a coverage bias worth naming before the
enumeration is used to argue coverage.

## 4. Not closed, with the access problem for each

| Body | Access problem |
|---|---|
| **OIC** | `oic-oci.org/en/members` returns navigation only; `/states/?lan=en` redirects to `/en` and yields nothing. Needs the browser path or the member list from an OIC summit document. High value — OIC membership is the gate for several IsDB-adjacent instruments. |
| **BSEC** | `bsec-organization.org/member-states` returns navigation only. Matters for Armenia and Georgia, the two countries OTS and ECO miss. |
| **TÜRKSOY** | Returned 330 bytes; JS-loaded. |
| **AIIB** | Members page is JS-loaded; a fact-sheet PDF is linked from the same site and is probably the cheaper route. |
| **CIS, GUAM, Council of Europe, OSCE, UNESCO, World Bank/IBRD, ADB, EBRD, NAM** | Not attempted. |

## 5. Recipe for the next run

1. Work from a fixed body list, agreed before starting, so coverage is auditable.
2. For each body: fetch its own member page, **extract the member-list region**, quote it, and record
   the URL and retrieval date.
3. Record status as an enum — member / observer / associate / dialogue partner / not listed — never a
   boolean.
4. Where a page is JS-loaded, use the browser path; where that fails, prefer a summit communiqué or
   fact sheet **published by the body**, not a country's own claim and not an encyclopaedia.
5. Emit one matrix, nine columns, one row per body, every cell traceable to a quoted list.

**Budget honestly.** Roughly twenty bodies, of which several need a browser and a few need documents
rather than pages. This is a run of its own, not a lookup — the original §9 entry was right to say so,
and the two bodies closed here took as long as the whole Fulbright pass over nine countries.

## 6. What this does not change

Nothing here alters a funding conclusion. Membership was never sufficient for eligibility — the
ADB-JSP case established that, and the IsDB LDMC case repeated it. This item is about making the
**enumeration's coverage claim** auditable, not about finding new schemes. A body list with unsourced
membership cannot support "we looked everywhere"; it can still support "we checked these".

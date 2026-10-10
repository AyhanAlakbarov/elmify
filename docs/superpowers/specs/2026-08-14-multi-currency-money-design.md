# Multi-Currency Money Handling — Design

Status: draft, pending review
Date: 2026-08-14

## Problem

`apps/funding/affordability.py` sums money across currencies without converting and
labels the result with whichever line item happened to come first.

```python
currency = currency or component.currency  # affordability.py:66
currency = currency or benefit.currency  # affordability.py:90
gap = max(baseline_cost - covered, Decimal("0.00"))  # affordability.py:99
```

Worked example: tuition 800,000 INR plus a 5,000 EUR scholarship yields a reported gap of
795,000 INR. The real gap is roughly 350,000 INR. The result is wrong by more than 2x and
its currency label is correct only by luck.

No test catches this — every fixture is single-currency.

Blast radius: the `AFFORDABILITY` dimension score, hard gate 8 (mandatory funding route),
`FUNDING_FIRST` ranking order (which sorts directly on `gap`), and the paid/excluded split
against `application_budget`.

A second, unrelated problem shares the word "normalization" in this file:
`_normalize_to_program_total` converts *time periods* (MONTHLY/ANNUAL to program total).
That function is correct and is not in scope here. Currency normalization is a distinct
concern and must not be folded into it.

## Three layers of money

Every monetary value has three representations. Conflating them is what produced the defect.

1. **Source (immutable).** The amount and currency exactly as the source page stated them.
   This is evidence. It is never overwritten, never converted in place, and is what gets
   cited in the report.
2. **Comparison.** The amount converted to the platform currency at ingestion, stored
   alongside the FX rate, the rate source, and the retrieval date as an evidence row.
   **Only this layer feeds ranking arithmetic.** All summation, gap calculation, and
   ordering happen here, in a single currency, by construction.
3. **Presentation.** Converted once at pack-build time to the student's home currency,
   using a rate frozen onto the `RecommendationRun` so the pack is reproducible.

The defect is fixed by making layer 2 the only input to arithmetic. Mixed-currency
summation then becomes structurally impossible rather than merely tested against.

## Display rule

Home currency for **decision numbers**: is this affordable, is it cheaper, how large is the
gap. These exist to be compared and understood, and the student reasons in the currency
they earn and save in.

Destination currency for **obligation numbers**, with the home-currency figure as an
approximate parenthetical: application fees, tuition invoices, visa financial-proof
thresholds, German blocked-account minimums. These are amounts the student must actually
produce on a given date. A converted figure acted on before an FX move can cause a visa
refusal, so the authoritative number stays in the currency the obligation is denominated in.

The student's display currency **cannot** be inferred from `application_budget.currency`.
In Azerbaijan and across Central Asia, students commonly state savings in USD or EUR
precisely because the local currency is unstable. Budget currency records what a student
saves in, not where they live or what they price things in.

Nor should it be inferred from IP geolocation: that introduces a new category of personal
data and a third-party lookup, is defeated by VPNs and carrier routing, and produces a
guess the consultant then has to confirm anyway.

Store it. `StudentProfileSnapshot` gains, at `schema_version` 2:

- `nationality` (ISO 3166-1 alpha-2) — required for eligibility, see below.
- `country_of_residence` (ISO 3166-1 alpha-2) — drives which central bank supplies the
  display rate. Defaults to `nationality` in the consultation UI, overridable.
- Display currency is derived from `country_of_residence`, with a student-facing override.
  It is not a third question.

### Nationality is an eligibility field, not a display field

`benefit_applies` (`apps/funding/evaluation.py:138`) scopes a `COUNTRY` benefit against the
**program's** country:

```python
if benefit.scope_type == "COUNTRY":
    return benefit.country_code == candidate.program_country_code
```

There is no student nationality anywhere in the profile, so a benefit restricted to citizens
of a given country is currently applied to every student at that program. This inflates
`covered`, shrinks `gap`, and can flip hard gate 8 (mandatory funding route) — reporting a
program as funded when the student cannot claim the funding.

`BenefitFact` also cannot express a nationality restriction; `scope_type` covers
GLOBAL / COUNTRY / CITY / program, all of which describe program location. Both sides need
the concept before the gate is correct.

## Rate sources

ECB covers destinations. It does not cover origins. Verified 2026-08-14 against
`eurofxref-daily.xml` (HTTP 200, 1,547 bytes, no key, 29 currencies, EUR base):

- Present: USD GBP CHF SEK NOK DKK PLN CZK HUF TRY CAD AUD JPY KRW SGD CNY INR — every
  plausible study destination.
- Absent: AZN NGN PKR BDT VND EGP KZT UZS GEL UAH RUB LKR NPR KES SAR AED MAD — nearly
  every plausible origin.

So: **ECB for the comparison layer, the student's own central bank for the display layer.**

Verified endpoints, 2026-08-14, all HTTP 200 and none requiring a key:

| Market | Endpoint | Format | Currencies | Date served |
| --- | --- | --- | --- | --- |
| Azerbaijan | `cbar.az/currencies/DD.MM.YYYY.xml` | XML | 42 | 14.08.2026 |
| Kazakhstan | `nationalbank.kz/rss/rates_all.xml` | RSS | 48 | 15.08.2026 |
| Uzbekistan | `cbu.uz/uz/arkhiv-kursov-valyut/json/` | JSON | 74 | 14.08.2026 |
| Kyrgyzstan | `nbkr.kg/XML/daily.xml` | XML, windows-1251 | 5 | 15.08.2026 |
| Georgia | `nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json` | JSON | 42 | 15.08.2026 |
| Tajikistan | `nbt.tj/en/kurs/export_xml.php` | — | HTTP 200 with **empty body** | — |

Consequences for the adapter contract:

- **One pair, not a basket.** The display layer needs only home-vs-platform. Kyrgyzstan's
  five currencies include EUR, so KGS is fully supported. Do not require broad coverage.
- **Validate parsed content, not HTTP status.** Tajikistan returns 200 with zero bytes; a
  status-only health check would report that source healthy while producing no rates.
- **Per-source parsing is genuinely different.** RSS, JSON, windows-1251 XML with comma
  decimal separators (`87,4500`), and differing `Nominal` divisors (NBG quotes AMD per
  1000, several banks quote per 10 or 100). Comma decimals and nominal divisors are exactly
  where `Decimal` money silently goes wrong. Each source needs its own parser test with a
  recorded fixture.
- **Staleness bounds are per-source.** Three national banks served 15.08 while ECB still
  served 13.08. A single global freshness threshold would either falsely flag the fast
  sources or fail to catch a genuinely stale one.

ECB's own terms state the rates are "published for information purposes only" and that
"using the rates for transaction purposes is strongly discouraged". Converted figures
therefore never carry the same authority as sourced ones.

## Rules

- Freeze the rate set on the `RecommendationRun`. A re-run of an approved pack must
  reproduce identical figures.
- Print the rate, its source, and its retrieval date next to every converted figure.
- Convert one way only. Never round-trip a value through a second conversion.
- Enforce a per-source staleness bound.

## Failure path

An amount that cannot be converted — currency absent from every configured source, or all
sources stale — sets `evidence_confidence = LOW`. That trips the existing hard gate 5, which
excludes the candidate with a reason attached for consultant review.

No new gate, no new failure mode, no silent fallback to an unconverted number.

## Scope note

Fixing `affordability.py` requires the comparison layer to exist, so the ingestion-side FX
work lands first. Until then the mixed-currency defect stands; it must not be papered over
with a currency-equality assertion that would exclude legitimate mixed-currency candidates.

## Open

- Platform currency: EUR is the natural choice given ECB is the comparison source, but this
  should be stated explicitly rather than assumed.
- Whether historical rates are retained per run or only the frozen set is kept.

### Residual items from the money-correctness implementation (commits 457620b..c4de9c2)

- **Rounding-mode disagreement — RESOLVED.** `ROUND_HALF_UP` governs the whole money
  pipeline. `_normalize_to_program_total` (`apps/funding/affordability.py:12`) and
  `convert()` (`apps/funding/fx.py:23`) are unified through one shared quantize-to-2dp
  helper with `ROUND_HALF_UP` explicit, rather than left as two functions that happen to
  agree — proration and currency conversion both end in the same "round money" step, so
  there is no reason for two code paths to state the rule twice.
- **Multi-currency-fee path is implemented but unverified.** `calculate_affordability`
  (`apps/funding/affordability.py:86-91`) pins `application_fee_currency` to the first
  `APPLICATION_FEE` component's currency and routes any further fee components through
  `convert()` into that currency, so it cannot silently sum mismatched currencies — but no
  fixture constructs a candidate with more than one `APPLICATION_FEE` component, so this
  path has no test coverage.
- **Home-currency presentation has no production caller.** `PresentedMoney`,
  `present()`, and `home_currency_for()` (`apps/funding/fx.py:38,46,50`) are implemented
  and unit-tested but nothing in `apps/funding/pack.py` or elsewhere calls them yet — Layer
  3 of the three-layer model (source → EUR comparison → home-currency presentation) exists
  only as primitives, not as a wired display path.
- **Precious-metal codes land in the currency rate table.** `parse_cbar_daily`
  (`apps/funding/rate_sources.py:49`) filters only by `code not in ISO_4217_CODES`, and
  CBAR's bullion codes (XAU, XPT, XAG, XPD) are valid ISO 4217 codes, so they end up in
  `RateTable.rates` indistinguishable from spendable currencies. Inherited from
  `ISO_4217_CODES` itself, which is used unvalidated for currency fields throughout the
  codebase; fixing it means curating a currency-only code set, a repo-wide reference-data
  change.

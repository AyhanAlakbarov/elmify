# Dates, month-year finding and "exact or up to" — what the data says and the fixes (2026-10-03)

Re-scored for $0 from session f7's v5 run (`~/agent-workspace/elmify-jev-harness/results.json`: 48
pages, 9 languages, key = DeepSeek V4.1 Flash + GPT-5.6 Luna agreeing, Sol on disputes; Jev 1.13
native). Read-only use of that file; scripts in this session's scratchpad.

## 1. Date role: "Jev is sure on only 15% of dates" is mostly not Jev

- 55 date candidates: **36 are Korean month cells from one university table** whose column header is
  신청시기 ("application period") or 선발시기 ("selection period"). The key labelled most of them
  `other`, because the option list had no "application period" (a window, not one opening or closing
  day); Jev mostly said `application_opening`, which is closer to the page than the key.
- The other 19 (az, tr, ru, en, fr): **Jev picked the key's role on 18 of 19**, but only 10 were above
  0.8 confidence. The low ones are the second date of a range ("с 1 февраля по 31 июля": 0.23–0.51)
  and month-only English payment dates ("August 2026": 0.40). That is a confidence gap, not a reading
  gap.

**Fixes:** (a) the two-reader joint score (engine spec §3.3) — the pair, not Jev alone, decides dates;
(b) code detects **date ranges** ("X–Y", "с X по Y", "from X to Y", "X-Y tarihleri arasında",
"X-dən Y-dək", "~") and asks the role once for the range, start and end inheriting it; (c) code reads a
**table column header** through a per-language cue table (application/başvuru/müraciət/приём
заявок/신청 → application window; deadline/son/до/마감 → deadline; selection/선발/отбор → selection;
payment/지급/выплата/ödeme → funding period; results/sonuç/nəticə/результаты/발표 → results) and
passes it with the cell; (d) the option list gains **`application_period`** (a window). (c)'s cue
table is code and is shown to Jev as context — it does not decide the role on its own.

## 2. "The code finds 4 of 10 English month-year dates"

The 10 "dates" the key readers listed on English lines were mostly **years and academic years**
("2023-2025", "2026") — intakes, which the design already sends to the intake finder, not to dates —
and vague month phrases ("September or October", "late March or early April").

`dateparser` 1.2.2 (BSD, PyPI) was tested as a ready-made finder and **rejected**: lower recall than
our pattern (Turkish 20/52 vs 40/52, Russian 27/41 vs 32/41, Korean 4/59), and it flagged dates on 90
Azerbaijani lines the key says carry none.

The improved code finder (month-year and year-month, CJK 年/월/日, month pairs joined by
or/and/et/и/və/ve, "early/late/end of <month>", no `\b` before Russian "г."), with year-only and
academic-year spans routed to intakes: **208 of 211 key dates found** — az 47/47, en 6/6, ko 53/53,
zh 7/7, hu 3/3, tr 42/43, ru 33/34, fr 17/18. Remaining: "весной 2021 года" (a season), "octobre et
janvier" (now covered by the month-pair pattern), "50 adet burs" (a key error, not a date). On lines
the key lists no date, the finder's hits are almost all real dates the key did not need; the one true
false alarm is Russian specialty codes ("37.03.01"), removed by requiring day ≤ 31 and month ≤ 12.

## 3. "Exact or up to": the confusion is ranges

152 amounts; key: exact 131, not_stated 9, up_to 8, at_least 4. Jev right on 139. Jev said up_to 13
times (7 right) and at_least 6 times (3 right). **7 of the 9 wrong ones are ranges or approximations**:
"50만원~150만원", "100만원~500만원", "250만원 내외" (≈), "entre 1 200 et 2 100 €", "¥143,000～145,000"
— Jev called the low end at_least and the high end up_to, which is a reasonable reading of a range
the option list has no word for.

A keyword rule alone ("up to/до/kadar/최대…") scored 126/152, worse than Jev (it fires on grade
minimums — "minimum 71 bal, ayda 145 manat" — and misses "не более" across a line).

**Fixes:** (a) code detects **amount ranges and approximations** (two amounts joined by ~, –, -, to,
et, до, ile, ilə, arası, "between … and", "entre … et"; or one amount with 내외/약/about/approx./около/
yaklaşık/təxminən) and records `range` (min, max) or `approximately` itself, verbatim; (b) Jev's
`bound` is asked only for single amounts, with the `{what, not_for, examples}` criteria the
verified-catalog session added for up_to and at_least.

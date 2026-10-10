# Deep research prompt — programme-attached funding, one destination

**Status:** template for spec section 7.1 of
`docs/superpowers/specs/2026-09-13-institution-programme-funding-search-design.md`. Fill
`{{DESTINATION}}` with one country. Run twice, independently (Claude Research and Gemini Deep
Research). Add nothing else — the runs are blind, and their overlap with the crawler is a measurement.

---

## Prompt

Find **master's programmes in {{DESTINATION}} where money is attached to the programme itself** and an
international student can get it: a tuition waiver or discount stated on the programme's page, a
scholarship for that programme or a named set of programmes, a stipend or assistantship, a funded
research position, a funded place in a dual or joint degree, housing or travel support, or a paid
placement built into the programme. Aim for **at least 10 programmes across at least 5 institutions**,
favouring smaller programmes and institutions over famous ones: the point is money nobody lists.

**Exclude:** national or government scholarships (they are catalogued elsewhere), money paid from a
university's central fund with no programme attached unless the programme page itself states it,
doctoral-only funding, exchanges and non-degree study.

**For each programme, one row:** `institution`, `programme` (exact name), `programme_url` (the
programme's own page on the institution's site), `award_quote` (the sentence on that page or a page
linked from it that states the money, verbatim), `quote_url` (where the sentence is), `kind`
(I1_UNIVERSITY_WIDE / I2_PROGRAMME_ATTACHED / I3_STIPEND_OR_ASSISTANTSHIP / I4_RESEARCH_PATHWAY /
I5_FUNDED_DUAL_DEGREE / I6_RELOCATION_HOUSING_TRAVEL / I7_PAID_PLACEMENT), `internationals_included`
(YES / NO / UNSTATED, with the sentence), `route` (how a student gets it, quoted), `money_form`
(GRANT / FEE_WAIVER / SUBSIDY / LOAN / FORGIVABLE_LOAN / MIXED), `cycle` (the academic year the page
states), `how_found` (the search or path that led you there).

**Rules.** Institution pages only for every fact; aggregators may point you there and may not be
cited. Quote, never paraphrase. If a page is dated to an old cycle, say so. Give a completion line:
how many institutions you looked at, and which you dropped and why.

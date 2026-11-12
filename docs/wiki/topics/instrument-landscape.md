# Instrument landscape

Twelve national and state schemes tested against the funding-route attribute model; the model survives with four changes. [src: 2026-08-27-instrument-landscape-synthesis.md] Pages: [Heydar Aliyev grant](../schemes/heydar-aliyev-grant.md), [GKS](../schemes/gks.md), [MEXT](../schemes/mext.md), [CSC](../schemes/csc.md), [Türkiye Bursları](../schemes/turkiye-burslari.md), [Chevening](../schemes/chevening.md), [Stipendium Hungaricum](../schemes/stipendium-hungaricum.md), [DAAD EPOS](../schemes/daad-epos.md), [Georgia](../countries/ge.md), [India](../countries/in.md).

## Who may initiate
- Azerbaijan's Heydar Aliyev grant needs nomination by the applicant's own government on top of a SIACAS application; India is eligible in principle through the Non-Aligned Movement but cannot simply apply. [src: 2026-08-27-instrument-landscape-synthesis.md §1]
- Georgia has no open national inbound scheme, only bilateral allocations such as 10 places a year with Armenia. [src: 2026-08-27-instrument-landscape-synthesis.md §1]
- Five of the twelve cannot be applied to directly, so `initiation` is the highest-value field. [src: 2026-08-27-instrument-landscape-synthesis.md §1]
- A nominated route cannot satisfy the floor: Eiffel, Azerbaijan, Russia and Commonwealth are upside, not safety. [src: 2026-08-27-instrument-landscape-synthesis.md §5]

## The four model changes
- Tracks: GKS and MEXT run embassy and university tracks with different quotas, deadlines and selectors. [src: 2026-08-27-instrument-landscape-synthesis.md §2]
- `origin` gains `BILATERAL`, and nationality eligibility is a rule (bloc, list, bilateral deal, per-nationality quota, or Erasmus Mundus's 10% cap), not a list. [src: 2026-08-27-instrument-landscape-synthesis.md §2]
- DAAD, CSC, MEXT, Russia and Erasmus Mundus have no single global deadline, so dates need a `DECENTRALISED` marker. [src: 2026-08-27-instrument-landscape-synthesis.md §3]
- Chevening's offer-by-date pattern is real: 9 July 2026 for 2026/27, 8 July 2027 for 2027/28. [src: 2026-08-27-instrument-landscape-synthesis.md §3]

## Selectivity
- Türkiye Bursları published 121,830 applications from 170 countries in 2024 against about 5,000 awards a year; Chevening had 1,545 awards for 2023; GKS publishes per-country quotas. [src: 2026-08-27-instrument-landscape-synthesis.md §4]
- CSC's "about 30,000 a year" is agency-sourced and must not be treated as official. [src: 2026-08-27-instrument-landscape-synthesis.md §4]

## Crawler seeds and test cases
- Discovery should seed from official index portals that enumerate schemes, one per country or body. [src: 2026-08-27-instrument-landscape-synthesis.md §6]
- Georgia, Russia (overseas Rossotrudnichestvo offices only), Eiffel (no applicant portal), CSC (four-digit agency codes) and Erasmus Mundus are the structural test cases. [src: 2026-08-27-instrument-landscape-synthesis.md §7]
- Run 1 and run 2 on Georgia are both right: no open competition, yet bilateral allocations exist. [src: 2026-08-27-instrument-landscape-synthesis.md §8]
- The two Erasmus Mundus living-cost figures are not reconcilable; re-fetch before use. [src: 2026-08-27-instrument-landscape-synthesis.md §8]

Superseded: the seed list names the DAAD scholarship database as a seed adapter, but no DAAD programme-database adapter is written because its terms of automated retrieval could not be established — see [How the search engine works](../../superpowers/2026-10-24-search-engine-how-it-works.md).

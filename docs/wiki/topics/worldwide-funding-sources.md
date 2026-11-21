# Worldwide funding sources

Which data sources supply tier-0 (grant and funder) records outside the EU, and what their access terms are. Related: [Korea](../countries/kr.md), [Japan](../countries/jp.md).

## Supranational sources
- CORDIS offers bulk XML/CSV/JSON on data.europa.eu under CC BY 4.0 with no auth, covering over 56,000 unique organisations that each carry an EU PIC identifier; the research counts it as one adapter for roughly forty countries. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §1]
- The OpenAIRE Graph is published as CC BY 4.0 Zenodo dumps aggregating 368 funders and about 4 million grants. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §1]
- CORDIS terms were checked on its legal page: Commission Decision 2011/833/EU and a CC BY 4.0 clause; beneficiary-supplied materials follow the grant's own terms, which the synthesis reads as covering attachments, not project and organisation metadata. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §2]
- Probe on 2026-08-28: the CORDIS search API returned live JSON with `{"total": 59002}`, and the OpenAIRE Graph API was live JSON. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §7]

## Joining a grant to an institution
- ROR deliberately excludes PIC codes from `external_ids`, and run 1 found no published PIC-to-ROR mapping, so nothing official joins CORDIS to national registries. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §1]
- Position taken: use the OpenAIRE Graph as the join layer; community CORDIS-to-ROR tables on GitHub are a fallback only, being unversioned third-party data. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §1]
- A ROR query filtered to China returned 5,708 organisations in the 2026-08-28 probe. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §7]

## Access terms by source
- ANR (France) is published on data.gouv.fr under Licence Ouverte v2.0 in XLSX, CSV and JSON. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §2]
- Opintopolku (Finland) is not resolved: no service-specific licence exists, run 1's reading (CC BY via JHS 189, unconfirmed) is preferred over run 2's EUPL argument, and the fix proposed is an email to Opetushallitus. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §2]
- UKRI Gateway to Research: the 2026-08-28 probe found `gtr.ukri.org/api/projects` returns XML (so JSON needs an Accept header) while run 1's `/gtr/api/` path returns HTTP 400, so run 2's path is right. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §7]
- Italy: `dati-ustat.mur.gov.it` timed out twice and `offf.miur.it` responds, so Italy is treated as search-form-only. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §7]
- Netherlands: the register is RIO via DUO's `onderwijsdata.duo.nl` bulk files, not `studyinnl.org`. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §6]
- Probes returned HTTP 403 for data.go.kr with a placeholder key, for KAKEN without a CiNii id, and for NWO; China NSFC (`kd.nsfc.gov.cn`) was refused at DNS and cannot be tested from the project's egress. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §7]

## Design consequences the research draws
- Enumeration ceilings differ per source: NSF caps a search at 3,000 results (25 per page), NIH RePORTER caps the offset at 9,999, and Korea's grid download caps at 50,000 rows, so each needs slicing. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §6]
- No index of home-origin government schemes exists anywhere, so origin-side scheme knowledge must come from the tenant at onboarding. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §6]
- 360Giving publishes grant history, not a catalogue of schemes. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §6]
- Mastercard Foundation Scholars and Rotary Global Grants are nomination-gated, so neither can be a portfolio floor. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §6]
- The synthesis's first consequence is to build the CORDIS bulk adapter first (one adapter, about 40 countries, 56,000+ PIC-identified organisations). [src: 2026-08-28-worldwide-funding-sources-synthesis.md §6]
- Search providers' own terms on keeping result URLs are covered in [live search provider](live-search.md). [src: 2026-08-30-live-search-synthesis.md §1]

Superseded: CORDIS was dropped as a funding source because Horizon has no master's-level instrument, and KAKEN because it funds researchers, not master's training; the OpenAIRE Graph stays as the crosswalk hub — see [Funding-Led Discovery design](../../superpowers/specs/2026-08-28-funding-led-discovery-design.md).

# South Korea

Korea as a data source [src: 2026-08-28-worldwide-funding-sources-synthesis.md §3] and as the host of GKS. [src: 2026-08-29-gks-quota-primary-verification.md] See [worldwide funding sources](../topics/worldwide-funding-sources.md) and the [GKS scheme](../schemes/gks.md).

- The prompt's "no supplier" claim for Korea was refuted: data.go.kr dataset #15139338 is an XLSX of 55,228 rows (school, college, department/major, degree program) under KOGL, with a companion Open API #15107736 carrying bilingual institution names. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §3]
- Grid downloads from that portal are capped at 50,000 rows, so the API is the full-extract route. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §3]
- The 2026-08-28 probe found data.go.kr returned HTTP 403 with a placeholder key, i.e. live and enforcing auth, so a free key registration is a prerequisite. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §7]
- On the grant side, run 1 found no machine-readable feed from NRF, while run 2's NTIS route needs a registered data.go.kr key; the synthesis says to register the key and rejects run 2's proposed MCP wrapper to avoid registration. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §4]
- The GKS-G 2026 guideline copy that was read is a mirror hosted by the Korean Education Centre in the UK, because `studyinkorea.go.kr` was found browser-required and partly 404 by an earlier probe. [src: 2026-08-29-gks-quota-primary-verification.md]
- Korea appears as a build target in the design consequences: KOGL-licensed, degree-level, enumerable via the Open API. [src: 2026-08-28-worldwide-funding-sources-synthesis.md §6]

Superseded: both Korean datasets were later opened without an account, so registration is no longer a blocker; #15139338 is a catalogue card for a file that 대학알리미 serves anonymously, and #15107736 is institution-level with 17 fields including website, not just bilingual names — see [Funding-Led Discovery design](../../superpowers/specs/2026-08-28-funding-led-discovery-design.md).

## As a destination
- Korea's D-10 job-seeker visa is 2 or 3 years (the runs conflict) and the D-2 proof is ₩20m in Seoul metro and ₩16m elsewhere, disputed against a USD figure. [src: 2026-08-27-corridor-mechanics-synthesis.md §4]
- The full-tuition-before-Certificate-of-Admission sequence is a Ministry of Education rule; the amount is per university and a refund on visa denial is published per university. [src: 2026-08-28-corridor-mechanics-round2-synthesis.md §1]
- No Korean university publishes a matched international applicant and admitted count. [src: 2026-08-28-corridor-mechanics-round2-synthesis.md §2]
- Work is 20 h/week in semester and unlimited in official vacations. [src: 2026-08-29-synthesis-crosscheck.md §1]
- See [corridor mechanics](../topics/corridor-mechanics.md) and [round 2](../topics/corridor-mechanics-round2.md).

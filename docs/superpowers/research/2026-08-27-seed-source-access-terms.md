# Seed-source access terms (design §7.4, open item #1)

Checked 2026-08-27. `robots.txt` findings are carried over from the design's §2.1
survey and re-verified here; the terms-of-use column is new.

| Host | robots.txt | Terms URL | Quoted clause on automated access / reuse | Verdict |
|---|---|---|---|---|
| www2.daad.de | (verified: `https://www2.daad.de/robots.txt` returns HTTP 404 — no robots.txt served) | `https://www.daad.de/en/imprint/` (reached via `www2.daad.de/en/` → redirects to `www.daad.de/en/` → footer link "Imprint"; fetched 2026-08-27, HTTP 200; German original `https://www.daad.de/de/impressum/` confirmed word-for-word equivalent) | "All contents of this website (in particular texts, images and graphics) are protected by copyright. The respective authors of the images are named." | HOLD |
| www.eacea.ec.europa.eu | (verified: `https://www.eacea.ec.europa.eu/robots.txt` returns HTTP 200, standard Drupal file — `Disallow` only covers `/core/`, `/profiles/`, `/admin/`, `/search/` and other utility paths; funding/programme content paths are open) | `https://commission.europa.eu/legal-notice_en` (fetched 2026-08-27 via `https://ec.europa.eu/info/legal-notice_en`, which redirects here with HTTP 200 — this is the Commission-wide legal notice, not a host-specific page; it governs eacea.ec.europa.eu as a europa.eu-domain site) | "The Commission's reuse policy is implemented by the Commission Decision of 12 December 2011 on the reuse of Commission documents. Unless otherwise indicated (e.g. in individual copyright notices), content owned by the EU on this website is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence. This means that reuse is allowed, provided appropriate credit is given and changes are indicated." | SHIP |
| erasmus-plus.ec.europa.eu | (verified: `https://erasmus-plus.ec.europa.eu/robots.txt` returns HTTP 200, standard Drupal file — same shape as eacea's, content paths open) | `https://commission.europa.eu/legal-notice_en` (same Commission-wide legal notice as the eacea row above — checked once, applies to both EU hosts; fetched 2026-08-27, HTTP 200) | "The Commission's reuse policy is implemented by the Commission Decision of 12 December 2011 on the reuse of Commission documents. Unless otherwise indicated (e.g. in individual copyright notices), content owned by the EU on this website is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence. This means that reuse is allowed, provided appropriate credit is given and changes are indicated." | SHIP |
| www.studyinkorea.go.kr | Allow: / except /Sims/ (re-verified 2026-08-27, HTTP 200, unchanged) | `https://www.studyinkorea.go.kr/ko/main.do` footer (site root redirects here; fetched 2026-08-27, HTTP 200). A separate "저작권정책" (Copyright Policy) page exists at `https://www.niied.go.kr/web/main/contents/copyright` (fetched 2026-08-27, HTTP 200) but its body renders no policy text in the static HTML response — no clause found at that URL, fetched 2026-08-27. | "© National Institute for International Education (NIIED). All rights reserved" | HOLD |
| api.exa.ai | n/a (contracted API; `https://api.exa.ai/robots.txt` returns HTTP 404 `{"error":"Not found"}`, consistent with an API host serving no static robots file) | `https://exa.ai/assets/Exa_Labs_Terms_of_Service.pdf` (linked from the exa.ai homepage footer; fetched 2026-08-27, HTTP 200, extracted with `pdftotext`) | "You may not... download, modify, copy, distribute, transmit, display, perform, reproduce, duplicate, publish, license, create derivative works from, or offer for sale any information contained on, or obtained from or through, the Services, except for temporary files that are automatically cached by your web browser for display purposes, or as otherwise expressly permitted in these Terms or by us in writing." (§4.2(a), "Restrictions On Your Use of the Services") | HOLD |

## Notes

- Any host whose terms forbid automated retrieval or forbid storing retrieved
  content is HOLD: no adapter is written for it, and it becomes a
  `ConsultantResearchTask` instead (design §2.6).
- A host that permits retrieval but serves no listing in static HTML is
  BROWSER_REQUIRED, not HOLD: same class as Campus France (§2.1 tier 3),
  deferred to a later increment rather than refused. None of the five hosts
  checked here fell into this category — all five terms/robots pages were
  reachable as static HTML.
- **www2.daad.de is effectively decommissioned.** `https://www2.daad.de/`
  (bare root) returns HTTP 404, and every path checked except `/en/` also
  404s; `/en/` itself 302-redirects to `www.daad.de/en/`. The organization's
  live site — and its imprint/copyright terms — is `www.daad.de`. The
  copyright notice found there is a bare "protected by copyright" reservation
  with no reuse licence and no clause addressing automated retrieval or
  storage, in explicit contrast to the Commission's affirmative CC BY 4.0
  grant below. Given the absence of any affirmative permission to store
  retrieved content, this is recorded as HOLD rather than assumed SHIP from
  the host's silence or its non-profit/academic reputation.
- **www.studyinkorea.go.kr** has the same shape of gap: robots.txt is
  permissive, but the only content-reuse-adjacent text actually reachable is
  a bare "All rights reserved" footer notice. A dedicated Copyright Policy
  page exists on the parent NIIED domain but did not return body text on a
  static fetch (likely client-side rendered), so its actual clause is
  unverified — recorded above as "no clause found," not paraphrased or
  reconstructed. HOLD follows for the same reason as DAAD: no affirmative
  permission to store retrieved content was found in what could be read.
- **api.exa.ai** is the one host with an explicit, unambiguous prohibition:
  its Terms of Service (§4.2(a)) bars copying, reproducing, or duplicating
  "any information... obtained from or through the Services" except for
  incidental browser caching, with no carve-out for API `Output` (search
  results) found elsewhere in the same document. Persisting Exa search
  results in the engine's database is exactly the storage this clause
  forbids, so this is HOLD even though no API key or call was involved in
  reaching this verdict — only the published terms were read.
- The two EU Commission hosts (eacea, erasmus-plus) are the only SHIP
  verdicts: both are europa.eu-domain sites governed by the same
  Commission-wide legal notice, which explicitly grants CC BY 4.0 reuse
  (attribution + indicate changes) for EU-owned content, and both serve
  standard Drupal robots.txt files that leave programme/funding content
  paths open to crawling.

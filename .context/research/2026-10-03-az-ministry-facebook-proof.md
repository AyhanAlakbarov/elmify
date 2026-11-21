# Proving a Facebook page belongs to an Azerbaijani funding body (2026-10-03)

## Answer

- **The site-link proof works for most of these bodies.** Every domestic body checked links to its
  Facebook page from its own website. So do four of the six embassy sites checked. Hungary's
  embassy site links to a page that is not the embassy's, and Japan's English page has no
  Facebook link at all.
- **The site link proves less on non-`.gov.az` domains.** For `.gov.az` sites, the state's own
  domain register at `www.gov.az` ties the domain to the named body.[^1][^2] So the chain
  "register → domain → site's Facebook link → page" is entirely first-party. `htp.edu.az`,
  `youthfoundation.az`, `ada.edu.az` and `heydar-aliyev-foundation.org` are not in that register.
  `htp.edu.az` still gets a first-party anchor through one more hop: `edu.gov.az` links to it.[^3]
  For `youthfoundation.az` I found no state anchor (**Unverified**).
- **The blue badge adds little, and requiring it would drop the most important page.** 9 of 13
  pages checked show it. **The HTP (intergovernmental scholarships, `htp.edu.az`) page does not**,
  and neither do the Heydar Aliyev Foundation's or the Korean embassy's. Meta says the badge can
  come from a paid subscription.[^4] It also says content from verified pages is not verified.[^5]
  At most it is a second signal for the case where the website itself has been compromised.
- **The badge can be read without logging in, but only by scraping.** The documented field is
  Graph API `verification_status`.[^6] Reading it needs the Page Public Metadata Access feature,[^7]
  which requires App Review[^8] and business verification.[^9] Without logging in, a headless
  browser sees the badge in the page DOM. Plain HTTP gets an empty shell. That route is not
  documented anywhere (see Q3).
- **I found no state register of official social-media accounts.** The closest thing is the
  `gov.az` domain register, which covers domains only.

## Sub-questions

1. For each body: which Facebook page does its official site link to, and does the page show
   Meta's verified badge?
2. Where on the site is the link, quoted?
3. Can the badge be read by a machine without logging in? Through the Graph API, and through the
   page HTML?
4. Is there an Azerbaijani state register of official social-media accounts?

## Q1 + Q2: site links and badges

How the links were found: a scrapling `get` of each homepage with selector `a[href*="facebook"]`.
The quotes are raw HTML. The links are icons with no visible text, so the `href` is the evidence.
These are site-wide social icons. Several appear twice (desktop and mobile copies). I did not
determine whether each copy sits in the header or the footer.

How the badges were checked: a headless Playwright browser, logged out, on 2026-10-03, reading
two signals per page. The first is the `<svg><title>Verified account</title>` element inside the
page's `<h1>`. The second is the `"show_verified_badge_on_profile":true|false` value in the page's
JSON. The two agreed on every page. These are **measurements, with no footnote**: Facebook page
URLs return an empty shell to a plain HTTP fetch, so the citation check cannot load them.

| Body | Official site | Facebook link on the site | Badge (measured) |
|---|---|---|---|
| Ministry of Science and Education | `edu.gov.az` (in the gov.az register[^1]) | `facebook.com/tehsil.gov.az/`[^10] | **Verified** |
| HTP: intergovernmental scholarship programmes / education abroad | `htp.edu.az`, linked from `edu.gov.az` as "Hökumətlərarası Təqaüd Proqramları"[^3] | `facebook.com/HTP-…-106344741042781/`[^11], which redirects to `facebook.com/htp.edu.az` | **Not verified** |
| State Programme on education abroad | No separate site found. The HTP page slug reads "HTP çərçivəsində xaricdə təhsil" ("education abroad under HTP"). | Same as HTP (**Unverified** that it is the same programme) | Not verified |
| Agency for State Support to NGOs | `ngoagency.gov.az` (in the register[^12]) | `facebook.com/ngoagency.gov.az`[^13] | **Verified** |
| Youth Foundation | `youthfoundation.az` (no `.gov.az` anchor found) | `facebook.com/youthfundaz/`[^14] | **Verified** |
| Ministry of Youth and Sports | `mys.gov.az` (in the register[^15]) | `facebook.com/mysofficial`, seen only in a browser render (`stealthy_fetch`). Plain `get` returned no link, so no footnote. | **Verified** |
| ASAN | `asan.gov.az` (in the register[^16]) | `facebook.com/asanxidmat`[^17] | **Verified** |
| ADA University | `ada.edu.az` | `facebook.com/ADAUniversity`[^18] | **Verified** |
| Heydar Aliyev Foundation | `heydar-aliyev-foundation.org` | `facebook.com/heydaraliyevfoundationofficial`[^19] | **Not verified** |
| UK Embassy Baku | `gov.uk` | `facebook.com/ukinazerbaijan/`, link text "Our Embassy on Facebook"[^20] | **Verified** |
| US Embassy Baku | `az.usembassy.gov` | `facebook.com/baku.usembassy/`[^21] | **Verified** |
| Korean Embassy | `overseas.mofa.go.kr/az-ko` | `facebook.com/koreanembassyazerbaijan`[^22] | **Not verified** |
| German Embassy | `baku.diplo.de` | `facebook.com/AlmaniyaSefirliyiBaki`, in the footer (`footer__social-media-list-link`)[^23] | **Verified** |
| Hungarian Embassy | `baku.mfa.gov.hu` | Links to a Hungarian institute's page ("Külügyi és Külgazdasági Intézet"), **not the embassy's**[^24] | not checked |
| Japanese Embassy | `az.emb-japan.go.jp` (English top page) | No Facebook link found | n/a |
| Turkish Embassy | `baku.be.mfa.gov.tr` | DNS did not resolve from here | n/a |

Two side observations:

- `edu.gov.az` also links `facebook.com/profile.php?id=61552057321724`. That redirects to
  `facebook.com/mutdaeduaz/`, the State Agency for Preschool and General Education, which is not
  verified. It is not a study-abroad body.
- A Facebook vanity URL can change: the HTP link redirected from a slug URL to `/htp.edu.az`. So
  key a page on its **numeric page ID** (here `106344741042781`), not on its handle.

The "ADA / ASAN / Heydar Aliyev Foundation education programmes" row is answered at the
organisation level. I did not establish which of these runs a scholarship scheme announced only
on Facebook (**Unverified**).

## Q3: reading the badge by machine

- **Graph API.** The Page node has `verification_status`, documented as: "This field can be read
  with the Page Public Metadata Access feature."[^6] The older `is_verified` field is
  "Deprecated, use "verification_status"".[^25] For a published, unrestricted Page, the
  reference's requirements table lists "App Access Token or User Access Token PPCA or PPMA".[^26]
  The Pages search guide says a logged-out caller needs "An App access token with the Page Public
  Metadata Access feature".[^7] It also documents the values: "verification_status string The
  verification status of the Facebook Page that represents a business, blue_verified or
  not_verified".[^27] Page Public Metadata Access "requires successful completion of the App
  Review process before your app can access live data"[^8] and "is only available with business
  verification".[^9]
- **Page HTML, logged out.** Measured, with no documentation behind it. Plain HTTP (scrapling
  `get`) returned an empty `<title>` for `facebook.com/tehsil.gov.az/`. A headless browser
  returned the page with `<svg … title="Verified account">` in the `<h1>`, plus
  `"show_verified_badge_on_profile":true`. The same HTML also contained `"is_verified":false` on
  verified pages (the Ministry of Science and Education, ADA, ASAN), so that key is about some
  other entity and **must not be used**. This is scraping undocumented markup, which Meta can
  change without notice.

## Q4: a state register of official accounts

None found. Searches run: Exa ("Azerbaijan official list of government agencies' social media
accounts register e-gov.az"), and Brave (`"sosial şəbəkə" "rəsmi səhifələri" dövlət qurumları
siyahı site:gov.az`). The Brave search returned one district administration's activity page,
which says it opened social-media pages, and no register. The closest first-party anchor is the
`gov.az` domain register. "GOV.AZ (Government.az) is a special domain zone reserved for the
naming of Internet information resources of state bodies."[^2] Its administration is assigned
by Cabinet of Ministers decision No. 91 of 2006.[^28] Each entry names the body that holds the
domain.[^1] **Unverified**: whether some decree requires state bodies to list their social
accounts on their sites.

## What this means for the proof

Treat a page as official when:

1. the body's `.gov.az` domain is in the `gov.az` register under that body's name, or the domain
   is linked from such a site;
2. the live site links to that page; and
3. the page's numeric ID matches the ID stored when it was confirmed.

That covers the Ministry of Science and Education, HTP (two hops), the NGO Agency, the Ministry
of Youth and Sports and ASAN. The Youth Foundation, ADA and the Heydar Aliyev Foundation rest on
their own site's link alone. Embassies rest on their foreign ministry's site. Hungary's
counter-example shows the link has to be checked per body, not assumed. Store the badge as a
signal, never as a requirement: the HTP page, the one that matters most here, does not have it.

Tools: scrapling, Exa, Brave and Playwright were used. Firecrawl was not available in this
session.

## Sources

[^1]: https://www.gov.az/az/orgs/domain/edu.gov.az "Qurum: Azərbaycan Respublikası Elm və Təhsil Nazirliyi"
[^2]: https://scis.gov.az/en/pages/view/dns-xidmeti "GOV.AZ (Government.az) is a special domain zone reserved for the naming of Internet information resources of state bodies."
[^3]: https://edu.gov.az/ "<a target="_blank" href="http://htp.edu.az/az/index">"
[^4]: https://www.facebook.com/help/196050490547892/ "Some verified accounts are owned by a notable person, brand, or entity, while others are subscribed to Meta Verified."
[^5]: https://www.facebook.com/help/196050490547892/ "Posts, stories and other content from verified Pages and profiles aren’t verified by Facebook."
[^6]: https://developers.facebook.com/docs/graph-api/reference/page/ "This field can be read with the Page Public Metadata Access feature."
[^7]: https://developers.facebook.com/documentation/pages-api/search-pages "An App access token with the Page Public Metadata Access feature if the app user is not logged into Facebook"
[^8]: https://developers.facebook.com/docs/features-reference/page-public-metadata-access "This permission or feature requires successful completion of the App Review process before your app can access live data."
[^9]: https://developers.facebook.com/docs/features-reference/page-public-metadata-access "This permission or feature is only available with business verification."
[^10]: https://edu.gov.az/ "<a href="https://www.facebook.com/tehsil.gov.az/" target="_blank"><i class="i-facebook"></i></a>"
[^11]: https://htp.edu.az/az/index "<a id="HprLnkFace" href="https://www.facebook.com/HTP-%C3%A7%C9%99r%C3%A7iv%C9%99sind%C9%99-xaricd%C9%99-t%C9%99hsil-106344741042781/" target="_blank">"
[^12]: https://www.gov.az/az/orgs/domain/ngoagency.gov.az "Qurum: Azərbaycan Respublikasının Qeyri-Hökümət Təşkilatlarına Dövlət Dəstəyi Agentliyi"
[^13]: https://ngoagency.gov.az/az "href="https://www.facebook.com/ngoagency.gov.az?mibextid=ZbWKwL" target="_blank" rel="noopener noreferrer" aria-label="Social""
[^14]: https://youthfoundation.az/ "<a target="_blank" href="https://www.facebook.com/youthfundaz/" title="Facebook" aria-label="Facebook icon">"
[^15]: https://www.gov.az/az/orgs/domain/mys.gov.az "Qurum: Azərbaycan Respublikası Gənclər və İdman Nazirliyi"
[^16]: https://www.gov.az/az/orgs/domain/asan.gov.az "Qurum: Azərbaycan Respublikasının Prezident yanında Vətəndaşlara Xidmət və Sosial İnnovasiyalar üzrə Dövlət Agentliyi"
[^17]: https://asan.gov.az/ "<a target="_blank" href="https://www.facebook.com/asanxidmat" class="fb">Facebook</a>"
[^18]: https://www.ada.edu.az/en "<a href="https://www.facebook.com/ADAUniversity" target="_blank">"
[^19]: https://heydar-aliyev-foundation.org/az "<a href="https://www.facebook.com/heydaraliyevfoundationofficial" target="_blank" class="facebook"></a>"
[^20]: https://www.gov.uk/world/organisations/british-embassy-baku "Our Embassy on Facebook"
[^21]: https://az.usembassy.gov/ "<a href="https://www.facebook.com/baku.usembassy/%20" title=" Facebook " target="_blank"></a>"
[^22]: https://overseas.mofa.go.kr/az-ko/index.do "<a class="item-link" href="https://www.facebook.com/koreanembassyazerbaijan" target="_blank" title="새 창 열림">"
[^23]: https://baku.diplo.de/az-de "<a href="https://www.facebook.com/AlmaniyaSefirliyiBaki" title="Facebook" target="_blank" class="footer__social-media-list-link is-social-background">"
[^24]: https://baku.mfa.gov.hu/ "<a href="https://www.facebook.com/pages/K%C3%BCl%C3%BCgyi-%C3%A9s-K%C3%BClgazdas%C3%A1gi-Int%C3%A9zet/481757045295140?fref=ts""
[^25]: https://developers.facebook.com/docs/graph-api/reference/page/ "This field indicates whether the Page is verified by this process."
[^26]: https://developers.facebook.com/docs/graph-api/reference/page/ "App Access Token or User Access Token PPCA or PPMA"
[^27]: https://developers.facebook.com/documentation/pages-api/search-pages "The verification status of the Facebook Page that represents a business, blue_verified or not_verified."
[^28]: https://scis.gov.az/en/pages/view/dns-xidmeti "According to the decision No. 91 of the Cabinet of Ministers of the Republic of Azerbaijan dated March 31, 2006"

## Open questions

- Is the "State Programme on education abroad" run through HTP (`htp.edu.az`), or does it have
  its own site and Facebook page? Not settled.
- What anchors `youthfoundation.az` to the state, for example a link from `mys.gov.az` or
  `president.az`? Not found.
- Whether the citation check matches raw HTML (`href` attributes) or only visible text. If only
  visible text, footnotes 3, 10, 11, 13, 14, 17–19 and 21–24 will fail even though the links are
  on the live pages.
- `mys.gov.az` gives its Facebook link only to a browser render, so it has no citable plain-fetch
  quote.
- The Turkish (`baku.be.mfa.gov.tr`, DNS failed), Japanese, Chinese and Hungarian embassies'
  official pages are not settled.
- Whether Meta exposes `verification_status` to an app token with only basic access, without
  PPMA. Not tested; there was no app.

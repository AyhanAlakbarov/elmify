# Closing the six open register questions — 2026-08-31

**Status: NOT a research run.** The last pass over the register series
(`safety-screen-register-recon`, `destination-registers-recon`, `asia-gulf-registers-recon`,
`us-registers-recon`). Six questions were left open across those files. **All six are now answered** —
four positively, one negatively, and one negative that qualifies the strongest claim made in the
series.

---

## 1. DAPIP — closed. One POST returns the whole US accreditation history

The API base is **`ope.ed.gov`**, not `surveys.ope.ed.gov`; the client's `getApiUrl` builds from
`window.location.hostname`, and the `surveys.` host is the *collection* side
(`getColApiUrl`). Getting that wrong is what produced the earlier round of 404s.

```
POST https://ope.ed.gov/dapip/api/downloadFiles/accreditationDataFiles
Content-Type: application/json
{"CSVChecked": true, "ExcelChecked": false}
```

→ **HTTP 200, `application/zip`, 3,639,296 bytes**, no authentication. The archive is **generated on
request** — the files inside carry today's timestamp. Contents:

| file | rows |
|---|---|
| `InstitutionCampus.csv` | **44,954** |
| `AccreditationRecords.csv` | **64,598** |
| `AccreditationActions.csv` | **89,532** |

`AccreditationActions.csv` carries `ActionDescription`, `ActionDate` and `JustificationDescription` —
**accreditation history including terminations**, the thing §A4 of the brief assumed was unavailable
and which only Australia otherwise provides (and there only by diffing monthly snapshots).

**A property worth keeping:** DAPIP's 404s distinguish *"No type was found that matches the controller
named X"* from *"No action was found on the controller X"*. Unlike anabin, **probing is safe here** —
a 404 is a real 404, and the two messages tell you whether the controller exists.

## 2. SEVP — closed. A Drupal view with GET filters, no bulk export

`studyinthestates.dhs.gov/school-search`, reachable **only via a browser transport** (plain `curl`
403s, as `ice.gov` does). It is an ordinary exposed Drupal view:

```
GET /school-search?field_education_level_value=1        # 1 = Higher Education
                  &field_f_1_school_value[1]=1          # F-1 visa
                  &field_m_1_school_value[1]=1          # M-1 visa
                  &field_school_name_value= &field_location_city_value=
                  &field_location_state_value= &field_location_zip_value=
```

Each row returns school name, **campus name**, full address and the F-1/M-1 flags — SEVP certification
is per *campus*, not per institution, which matters for matching. Education-type values run 1–8
(Higher Education, High School, Middle School, Private School, Technical/Vocational, Flight School,
Language Training, Other).

**No bulk export found.** Results paginate behind a "Load More" control, so a full extract means
walking the view. Cheapest full-coverage route is 50-odd state-scoped queries, the same shape as
NZQA's eight.

## 3. UAE free zones — closed. KHDA publishes 34 Dubai providers, with star ratings

**The connection failure had a precise cause and a clean fix.** `web.khda.gov.ae` omits the
intermediate certificate from its chain. Fetching that intermediate from the leaf's own
Authority-Information-Access URI —
`http://secure.globalsign.com/cacert/gsrsaovsslca2018.crt` — appending it to the CA bundle, and
passing that bundle makes verification **pass properly** (`ssl_verify_result=0`, HTTP 200,
238,925 bytes). **The fix is a CA bundle, never `verify=False`.**

`web.khda.gov.ae/en/Education-Directory/Higher-Education` — 395,257 bytes, server-rendered,
**34 higher education institutions**, each with name, location, year established, and a **UQAIB
overall star rating dated 2022**:

| rating | providers |
|---|---|
| ★★★★★ | 9 |
| ★★★★ | 4 |
| ★★★ | 2 |
| ★★ | 1 |
| **unrated** | **18** |

Examples: Murdoch University Dubai and Manipal Academy of Higher Education at 5; Amity University
Dubai and S P Jain at 4; one institution at 2.

**So the UAE now has both halves**: CAA's 103 active mainland institutions (plus 55 inactive and 24
named revocations) and KHDA's 34 free-zone providers with a quality rating. **The caveat is that 18 of
34 carry no rating**, and the ratings that exist are four years old — carry the 2022 date with every
one of them.

## 4. Ireland — closed as far as it can be. 27 named providers, no list file

`qqi.ie/trusted-ireland-reports` names **27 authorised higher education providers**, each linked to
its own assessment-report PDF. **There is no downloadable master list.**

QQI describes the successor register by name: providers and eligible programmes will be published on a
new **"TrustEd Ireland Authorised Providers: List of Eligible Programmes"**, managed by QQI, which
supersedes the ILEP.

**Ireland is therefore two enumerable lists, not an unknown** — the frozen ILEP (last published
2025-06-20) and these 27, growing as windows close. That is workable, but it is 27 names scraped from
a reports index, and it will keep changing until the ILEP ceases at the end of 2026. **Ireland stays a
consultant check**; the difference is that we now know exactly what to watch and where.

## 5. China — closed with a negative, and the earlier IPv6 finding was too broad

**MOE publishes a complete national list of Chinese higher education institutions** — 全国高等学校名单,
**3,167 institutions as of 2025-06-20** (2,919 regular, 248 adult), at `moe.gov.cn`.

**It does not publish a register of institutions authorised to enrol international students.** That
authorisation exists — it is governed by the 2017 *Administrative Measures for Schools Recruiting and
Cultivating International Students* and a 2020 MOE notice on regulating international-student
admission — but it is administered per institution rather than published as an enumerable list. **China
is a case-by-case regime on the destination side**, the same shape as Azerbaijan on the recognition
side.

**Correction to `asia-gulf-registers-recon` §7c:** that file says the surviving Chinese host is
IPv6-only. True of `jsj.moe.gov.cn` specifically, **but `moe.gov.cn` answers over IPv4 normally**
(HTTP 200, 103,515 bytes). The IPv6 constraint applies to the *supervision* portal, not to Chinese
government education sites generally.

## 6. Graduate tuition — closed, negatively, and it qualifies the strongest claim in the series

**College Scorecard does not publish master's tuition anywhere.**

- **Institution file** (3,308 columns): `TUITIONFEE_IN` and `TUITIONFEE_OUT` are **undergraduate**.
  `TUITIONFEE_PROG` is programme-year cost at occupational schools; `TUITFTE` is tuition revenue per
  full-time-equivalent student, an accounting figure and not a price. No graduate tuition column
  exists.
- **Field-of-Study file**: 227,980 rows carrying `CREDLEV`, of which **38,621 are master's degrees**
  (`CREDLEV=5`) — and it holds **debt and earnings only. No price column at all.**

So for a master's applicant, Scorecard answers **how selective, who accredits, what graduates earn,
and how much debt they leave with — but never what it costs.**

**This qualifies `us-registers-recon` §1.** That file called the US "the largest single finding of the
whole programme" because it supplies selectivity *and* price where nothing else does. **The price half
does not hold for our population.** US master's tuition still has to come from programme pages, via
the extraction pipeline, exactly like everywhere else. The selectivity half stands and is still
unique.

`DEBT_ALL_STGP_ANY_MDN` at `CREDLEV=5` — median federal loan debt of master's completers — is the
closest available proxy. **It is not a price**, it reflects only borrowers and only federal loans, and
it must never be displayed as a cost.

## 7. What is actually left

- **Nothing blocking.** Every register in the series is now either usable or understood well enough to
  decide against.
- **Ireland's TrustEd list will keep growing** until the ILEP ceases at the end of 2026. Re-read then.
- **KHDA's star ratings are dated 2022** and 18 of 34 providers are unrated. Check whether UQAIB has
  published a newer round before relying on them.
- **SEVP has no bulk export**; a full extract is a paginated walk, not a download.
- **China's destination authorisation is per-institution**, so it joins Azerbaijan and Türkiye in the
  "cannot be pre-computed" column.

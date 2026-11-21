# Website Proof Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing provenance gate prove that a website belongs to the body it is credited to, and turn it on for students: one cited list of government-only domain zones, a homepage identity check wherever a recognition was granted without reading the site, origin checks for register rows, no scheduled re-check of a proven body, and no unconfirmed body ever reaching a student.

**Architecture:** Everything lands in the provenance gate built by PR #158 (`apps/research/recognition.py`, `provenance.py`, `provenance_job.py`) and its two readers in `apps/funding` (`services.replace_candidate`, `views._pack_context`). The verdict vocabulary, the tables and `decide()` are unchanged: this plan only changes **which recognitions reach `decide()`** (identity and origin checks run in `check_body` before it), **when a verdict comes due again**, and **what a student path accepts and shows**. No migration.

**Tech Stack:** Django 6, Postgres 17 with RLS, lxml, pytest with `django_db`, CloudFormation template tests (`tests/infra/test_template.py`).

**Spec:** `docs/superpowers/specs/2026-09-27-verified-catalog-one-reader-design.md` on branch `claude/verified-catalog-design`, sections §4 (Part B), §4.1 (the lean university rule), §0.10 and §0.18 (verified-only, counsellor path removed), §11.1 "Part B: proof". Research behind Task 1's zones: `.context/research/2026-10-03-government-zone-citations.md` (same branch).

## Global Constraints

- Work on a new branch from `origin/master` (02926ac2 or later): `claude/website-proof-hardening`, in its own worktree. Never push to `master`.
- Tests: `POSTGRES_DB=elmify_website_proof uv run pytest -q` (a per-branch database name; the shared `test_elmify` wedges across parallel sessions).
- Lint only: `uv run ruff check .`. **Never run `ruff format`** (it rewrites hundreds of untouched files).
- Types: `uv run mypy apps config`.
- `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run` must pass; this plan adds **no migration**.
- No network in tests: every fetch goes through `FakeFetch`/`HomeFetch` (`tests/research/provenance_helpers.py`).
- A government zone is added only with a registry or government-authority page stating the restriction (the rule already written above `GOVERNMENT_ZONES`). A zone whose citation page does not load, or does not contain its marker text, when Task 1 runs is **not** added.
- Comments only for non-obvious constraints, matching the surrounding modules' style (they cite the spec section and the measurement behind a rule).
- `bandit` runs on every commit through pre-commit; do not add `# nosec` without a reason.

## Review Focus

1. **A government body whose homepage names it only in the local language** (`edu.gov.az` prints "Elm və Təhsil Nazirliyi", the body row is named in English). Expected: identity passes when any name the platform holds for the body matches, including a register row's local-language name. Pinned in Task 2 (`test_a_local_language_register_name_counts_as_the_bodys_name`).
2. **A regulator's site that names other bodies** (`yok.gov.tr`'s homepage lists universities). Expected: a programme whose evidence sits on `yok.gov.tr` is not recognised for a university, because only the identity regions (title, site name, header, footer, banner, logo alt) count and YÖK's own name is what they carry. Pinned in Task 2 (`test_a_zone_site_that_names_another_body_in_its_body_text_is_not_that_body`).
3. **A parked or for-sale page that prints the domain** ("mfa.gov.az is for sale"). Expected: tokens carrying the domain are blanked before matching, as `names_institution` already does. Pinned in Task 2 (`test_a_parked_page_printing_the_domain_does_not_name_the_body`).
4. **A body known only by its domain** (`check_named_url` records a body named after its domain). Expected: identity cannot pass on a domain-as-name; the zone recognition is dropped and the verdict is UNCONFIRMED, never RECOGNISED by default. Pinned in Task 2 (`test_a_body_named_only_by_its_domain_cannot_pass_identity`).
5. **The homepage cannot be fetched** (vendor DEAD, timeout). Expected: the recognition that needed it is dropped and the verdict is `lookup_failed`, retried in a day, never BLOCKED and never RECOGNISED. Pinned in Task 2 (`test_an_unreadable_homepage_is_a_failed_lookup_not_a_verdict`).

---

## File map

| file | change |
|---|---|
| `apps/research/recognition.py` | `GOVERNMENT_ZONES` gains the cited zones (Task 1); new `identity_text`, `names_on_identity`, `site_identity` (Task 2); new `verify_register_origins`, `list_recognitions(..., require_register_origin=)` (Task 3) |
| `apps/research/domains.py` | `VERIFIED_SECOND_LEVEL` gains the new government suffixes; new `KIND_ONLY_GOVERNMENT_SUFFIXES` (Task 1) |
| `apps/research/provenance_job.py` | `check_body` runs the identity and origin checks (Tasks 2, 3); `next_check` returns `None` for RECOGNISED (Task 4) |
| `apps/research/provenance.py` | new `blocked_note` (Task 5) |
| `apps/research/management/commands/provenance_recheck.py` | docstring only (Task 4) |
| `apps/funding/services.py` | `replace_candidate` refuses any non-RECOGNISED candidate while the gate is enforced (Task 5) |
| `apps/funding/views.py` | `_pack_context` shows a student only the BLOCKED note (Task 5) |
| `infra/template.yaml` | `ProvenanceGateEnforced` defaults to `"1"` (Task 5) |
| `tests/research/provenance_helpers.py` | new `HomeFetch` (Task 2) |
| `tests/research/test_recognition_lists.py` | zone list tests (Task 1) |
| `tests/research/test_provenance_identity.py` | new: identity tests (Task 2) |
| `tests/research/test_provenance_check.py` | origin, identity and next-check updates (Tasks 2–4) |
| `tests/funding/test_named_program_gate.py` | refusal and note tests (Task 5) |
| `tests/infra/test_template.py` | the gate's default (Task 5) |

---

### Task 1: One cited list of government-only zones

**Files:**
- Modify: `apps/research/recognition.py:227-250` (the comment block and `GOVERNMENT_ZONES`)
- Modify: `apps/research/domains.py:439-467` (`VERIFIED_SECOND_LEVEL`) and a new constant after it
- Test: `tests/research/test_recognition_lists.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `recognition.GOVERNMENT_ZONES: tuple[tuple[str, str], ...]` (zone, citation URL), unchanged in shape; `domains.KIND_ONLY_GOVERNMENT_SUFFIXES: frozenset[str]`.

Today there are two lists of government suffixes. `VERIFIED_SECOND_LEVEL` labels a host's holder kind and carries no citations. `GOVERNMENT_ZONES` admits a body, one citation each, and lacks `gov.az`, `gov.ge`, `gov.uk` and more (spec §11.1). This task makes them one list in effect: a test that fails when either list carries a government suffix the other does not explain.

- [ ] **Step 1: Re-check every candidate citation live, and keep only the ones that pass**

Run this from the worktree root. It prints `KEEP` or `DROP` per zone. A zone is kept only if its page loads and contains the marker text.

```bash
python3 - <<'EOF'
import urllib.request, ssl
CANDIDATES = {
    "gov.az": ("https://scis.gov.az/en/pages/view/dns-xidmeti", "special domain zone reserved"),
    "gov.ge": ("https://nic.ge/en/domains/what-is-a-domain-name", "state entities"),
    "gov.uk": ("https://www.gov.uk/guidance/check-if-your-organisation-can-get-a-govuk-domain-name", "Only the following organisations can apply"),
    "gov.au": ("https://www.domainname.gov.au/policies/eligibility-and-allocation-policy", "government department or agency"),
    "gov.sa": ("https://nic.sa/en/help/regulation/", "governmental entities in the Kingdom of Saudi Arabia"),
    "gov.qa": ("https://www.cra.gov.qa/en/Regulatory-Framework/Domain-Management/Registrants", "Qatar governmental organizations"),
    "gov.sg": ("https://www.sgnic.sg/domain-registration/sg-categories-rules", "Only government bodies or members of the Singapore Government"),
    "gov.cn": ("https://www.cac.gov.cn/2012-05/28/c_126540129.htm", "行政机关法人"),
    "gov.vn": ("https://archive.vnnic.vn/tenmien/chinhsach/quy-trinh-dang-ky-ten-mien-duoi-govvn", "Cơ quan nhà nước"),
    "gov.rs": ("https://www.uzzpro.gov.rs/latinica/procedure.html", "registraciju domena za državne organe"),
    "gov.za": ("http://dnsadmin.gov.za/faq.htm", "government department"),
    "gov.it": ("https://www.nic.it/it/domini-gov-it", "Pubbliche Amministrazioni"),
}
ctx = ssl.create_default_context()
for zone, (url, marker) in CANDIDATES.items():
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        body = urllib.request.urlopen(req, timeout=30, context=ctx).read().decode("utf-8", "replace")
        print("KEEP" if marker in body else "DROP (marker missing)", zone, url)
    except Exception as error:  # noqa: BLE001
        print("DROP", zone, url, type(error).__name__)
EOF
```

Expected: most zones print `KEEP`. Note every `DROP` in the commit message. A zone that drops here can be added later through the same task, once its citation loads.

- [ ] **Step 2: Write the failing tests**

Add to `tests/research/test_recognition_lists.py`. Extend its existing import of `GOVERNMENT_ZONES, government_zone` from `apps.research.recognition`, and import `VERIFIED_SECOND_LEVEL, KIND_ONLY_GOVERNMENT_SUFFIXES` from `apps.research.domains`.

```python
_GOVERNMENT_KINDS = {"NATIONAL_GOVERNMENT", "SUBNATIONAL_GOVERNMENT"}


@pytest.mark.parametrize(
    "host", ["edu.gov.az", "www.gov.uk", "moe.gov.sa", "mofa.gov.qa", "moe.gov.sg"]
)
def test_launch_government_hosts_are_in_a_cited_zone(host: str) -> None:
    zone = government_zone(host)
    assert zone is not None and zone.reason == "government_zone"
    assert zone.source_url.startswith(("https://", "http://"))


def test_every_cited_zone_that_labels_a_kind_labels_a_government_kind() -> None:
    for zone, _citation in GOVERNMENT_ZONES:
        if zone in VERIFIED_SECOND_LEVEL:
            assert VERIFIED_SECOND_LEVEL[zone] in _GOVERNMENT_KINDS, zone


def test_every_government_kind_suffix_is_cited_or_named_as_kind_only() -> None:
    """One list: a government suffix that labels a holder kind either proves a
    site (cited in GOVERNMENT_ZONES) or is named as a label that proves nothing."""
    cited = {zone for zone, _ in GOVERNMENT_ZONES}
    for suffix, kind in VERIFIED_SECOND_LEVEL.items():
        if kind in _GOVERNMENT_KINDS:
            assert (suffix in cited) != (suffix in KIND_ONLY_GOVERNMENT_SUFFIXES), suffix


def test_a_zone_never_admits_a_lookalike_suffix() -> None:
    assert government_zone("gov.az.example.com") is None
    assert government_zone("notgov.uk") is None
```

Drop any `host` from the first parametrize whose zone dropped in Step 1.

- [ ] **Step 3: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_website_proof uv run pytest tests/research/test_recognition_lists.py -q -k "zone or kind"`
Expected: FAIL. The import of `KIND_ONLY_GOVERNMENT_SUFFIXES` fails, and `government_zone("edu.gov.az")` is None.

- [ ] **Step 4: Add the zones and the kind-only set**

In `apps/research/recognition.py`, extend the comment block above `GOVERNMENT_ZONES` with one line per added zone, quoting its page the way the existing six lines do. Then add one tuple per zone that Step 1 kept. With all twelve kept, it reads:

```python
#: - gov.az: Special State Protection Service, "GOV.AZ (Government.az) is a
#:   special domain zone reserved for the naming of Internet information
#:   resources of state bodies";
#: - gov.ge: "can only be registered under the name of state entities, or local
#:   self-government units or organizations, legal entities under public law";
#: - gov.uk: "Only the following organisations can apply for a .gov.uk domain name";
#: - gov.au: "The Registrant must be an organisation established by an Act of
#:   Parliament or government regulation as a government department or agency";
#: - gov.sa: "Dedicated only for governmental entities in the Kingdom of Saudi Arabia";
#: - gov.qa: CRA, "For Qatar governmental organizations";
#: - gov.sg: "Only government bodies or members of the Singapore Government are eligible";
#: - gov.cn: CNNIC rules (CAC), "申请者应为行政机关法人";
#: - gov.vn: VNNIC, "Cơ quan nhà nước ở trung ương và địa phương";
#: - gov.rs: "Procedura za registraciju domena za državne organe";
#: - gov.za: SITA, "Any South African government department";
#: - gov.it: Registro .it, "solo da quelle Pubbliche Amministrazioni".
#: Measured 2026-10-03 (.context/research/2026-10-03-government-zone-citations.md
#: on claude/verified-catalog-design). Not added, and why: gov.kw (a description,
#: no rule), gov.bh ("semi-Government"), gov.ru (no published rule), gov.et
#: ("should"), gc.ca (no exclusivity sentence); gob.mx, gov.eg, gov.ng, gov.pl,
#: gov.br and gov.kz admit state companies or rest on repealed text.
GOVERNMENT_ZONES: tuple[tuple[str, str], ...] = (
    ("gov", "https://get.gov/domains/eligibility/"),
    ("gov.tr", "https://www.trabis.gov.tr/content/Belgeli"),
    ("go.jp", "https://jprs.co.jp/en/jpdomain.html"),
    (
        "go.kr",
        "https://xn--3e0bx5euxnjje69i70af08bea817g.xn--3e0b707e/jsp/eng/domain/kr/qualification.jsp",
    ),
    ("europa.eu", "https://commission.europa.eu/legal-notice_en"),
    ("auswaertiges-amt.de", "https://www.auswaertiges-amt.de/de/impressum"),
    ("gov.az", "https://scis.gov.az/en/pages/view/dns-xidmeti"),
    ("gov.ge", "https://nic.ge/en/domains/what-is-a-domain-name"),
    ("gov.uk", "https://www.gov.uk/guidance/check-if-your-organisation-can-get-a-govuk-domain-name"),
    ("gov.au", "https://www.domainname.gov.au/policies/eligibility-and-allocation-policy"),
    ("gov.sa", "https://nic.sa/en/help/regulation/"),
    ("gov.qa", "https://www.cra.gov.qa/en/Regulatory-Framework/Domain-Management/Registrants"),
    ("gov.sg", "https://www.sgnic.sg/domain-registration/sg-categories-rules"),
    ("gov.cn", "https://www.cac.gov.cn/2012-05/28/c_126540129.htm"),
    ("gov.vn", "https://archive.vnnic.vn/tenmien/chinhsach/quy-trinh-dang-ky-ten-mien-duoi-govvn"),
    ("gov.rs", "https://www.uzzpro.gov.rs/latinica/procedure.html"),
    ("gov.za", "http://dnsadmin.gov.za/faq.htm"),
    ("gov.it", "https://www.nic.it/it/domini-gov-it"),
)
```

In `apps/research/domains.py`, add the missing government suffixes to `VERIFIED_SECOND_LEVEL` under a new comment line, then add the kind-only set right after the dict:

```python
    # Gulf, East Asia, Balkans, Africa, Europe -- cited zones (recognition.GOVERNMENT_ZONES).
    "gov.sa": "NATIONAL_GOVERNMENT",
    "gov.qa": "NATIONAL_GOVERNMENT",
    "gov.sg": "NATIONAL_GOVERNMENT",
    "gov.cn": "NATIONAL_GOVERNMENT",
    "gov.rs": "NATIONAL_GOVERNMENT",
    "gov.za": "NATIONAL_GOVERNMENT",
    "gov.it": "NATIONAL_GOVERNMENT",
}

#: Government suffixes that label a holder's kind but prove no site: no registry
#: page restricting them was found on 2026-10-03, so they are not in
#: recognition.GOVERNMENT_ZONES. A test keeps the two lists from drifting apart.
KIND_ONLY_GOVERNMENT_SUFFIXES: frozenset[str] = frozenset(
    {"bel.tr", "gov.kz", "gov.uz", "gov.in", "gov.pk", "go.id"}
)
```

`bel.tr` is SUBNATIONAL_GOVERNMENT and belongs here until a citation is added; `gov.uz`, `gov.in`, `gov.pk` and `go.id` were not researched. Any zone that Step 1 dropped leaves `GOVERNMENT_ZONES`. If that zone is already in `VERIFIED_SECOND_LEVEL` (`gov.az`, `gov.ge`, `gov.uk`, `gov.au`, `gov.vn` are), it moves into `KIND_ONLY_GOVERNMENT_SUFFIXES`; if not, it is not added to `VERIFIED_SECOND_LEVEL` at all.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_website_proof uv run pytest tests/research/test_recognition_lists.py tests/research/test_domains.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/research/recognition.py apps/research/domains.py tests/research/test_recognition_lists.py
git commit -m "feat(provenance): cite twelve more government-only zones; one list with VERIFIED_SECOND_LEVEL

Zones re-checked live on <date>; dropped: <list or 'none'>.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: A homepage identity check where a recognition was granted without reading the site

**Files:**
- Modify: `apps/research/recognition.py` (new functions after `verify_origin`, around line 315)
- Modify: `apps/research/provenance_job.py:153-258` (`check_body`)
- Modify: `tests/research/provenance_helpers.py` (new `HomeFetch`)
- Create: `tests/research/test_provenance_identity.py`
- Modify: `tests/research/test_provenance_check.py:273-275` (the go.kr test)

**Interfaces:**
- Consumes: `recognition.government_zone`, `recognition.name_variants`, `names.tokens`, `hosts.registrable_domain`, `fetch.types.FetchedPage`.
- Produces:
  - `recognition.identity_text(body: bytes) -> str`
  - `recognition.names_on_identity(names: Iterable[str], body: bytes, *, domain: str) -> bool`
  - `recognition.site_identity(organisation: Organisation, domain: str, *, fetch: Fetch) -> str`: returns `"verified"`, `"lookup_failed"` or a reason sentence.
  - `tests.research.provenance_helpers.HomeFetch`

Two recognitions bind a body to a domain without anyone reading the site:
- `GOVERNMENT_ZONE` is a bare suffix match. On master today, any body whose evidence sits on `yok.gov.tr` is recognised.
- A REGISTER row bound through ROR's identifier (`admitted_via="ror"`) takes ROR's domain unchecked.

From this task on, both count only when the domain's homepage names the body in the places a site names *itself*. Those places are `<title>`, `og:site_name` and `application-name`, `<header>`, `<footer>`, the `banner` and `contentinfo` roles, and a logo's `alt`. Spec §4 (P2) and §4.1 step 3 require this. The live test on 2026-10-03 showed a title-only check failing on Qatar University (its title is Arabic for "Home") and on UFAZ (title gives only the acronym), which is why the check reads every identity region and every name the platform holds.

- [ ] **Step 1: Add `HomeFetch` to the test helpers**

Append to `tests/research/provenance_helpers.py`. Extend the module's imports with `from apps.research.hosts import registrable_domain` and `RegisterEntry` from `apps.research.models`; `field` is already imported from `dataclasses`.

```python
@dataclass
class HomeFetch(FakeFetch):
    """`FakeFetch` whose `homes` domains each serve a homepage that names the
    body: the name on the domain's register row, else its Organisation's name.
    Any other URL it does not hold answers DEAD, like FakeFetch."""

    homes: frozenset[str] = field(default_factory=frozenset)

    def __call__(self, url: str, **_kwargs: object) -> FetchedPage:
        self.calls.append(url)
        if url in self.pages:
            return self.pages[url]
        domain = registrable_domain(url)
        if domain not in self.homes:
            return page(url, b"", outcome=Outcome.DEAD)
        name = (
            RegisterEntry.objects.filter(website_domain=domain).values_list("name", flat=True).first()
            or Organisation.objects.filter(domains__registrable_domain=domain)
            .values_list("name", flat=True).first()
        )
        return page(
            url,
            f"<html><head><title>{name}</title></head><body><header>{name}</header>"
            "<main>Welcome</main></body></html>",
        )


@dataclass
class SiteFetch(FakeFetch):
    """Every URL on `site` (by registrable domain) answers `html`, landing on
    `landed` when set; anything else answers DEAD. For tests that must not
    depend on which exact URL form a caller asks for first."""

    site: str = ""
    html: str = ""
    landed: str | None = None

    def __call__(self, url: str, **_kwargs: object) -> FetchedPage:
        self.calls.append(url)
        if registrable_domain(url) != self.site:
            return page(url, b"", outcome=Outcome.DEAD)
        return page(url, self.html, final_url=self.landed)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/research/test_provenance_identity.py`:

```python
"""Site identity: a recognition granted without reading the site (a government
zone, a register row bound through ROR) counts only when the homepage names the
body where a site names itself (spec §4 P2, §4.1 step 3). No network."""

import pytest
from django.utils import timezone

from apps.research.fetch.types import Outcome
from apps.research.models import RegisterEntry
from apps.research.provenance_job import check_body
from apps.research.recognition import identity_text, names_on_identity, site_identity
from apps.research.register import record_organisation
from tests.research.provenance_helpers import FakeFetch, make_list, page
from tests.research.test_provenance_check import _deps

pytestmark = pytest.mark.django_db
NOW = timezone.now()


def _body(domain: str, name: str, kind: str = "NATIONAL_GOVERNMENT"):
    return record_organisation(domain=domain, name=name, kind=kind, country_code="", found_via="TEST")


def _home(domain: str, html: str) -> FakeFetch:
    return FakeFetch({f"https://{domain}/": page(f"https://{domain}/", html)})


def test_identity_text_reads_the_regions_a_site_names_itself_in() -> None:
    html = (
        '<html><head><title>الرئيسية</title><meta property="og:site_name" content="QU"></head>'
        '<body><header><img class="site-logo" alt="Qatar University"></header>'
        "<main>Qatar University students and Doha news</main>"
        "<footer>© 2026 جامعة قطر</footer></body></html>"
    ).encode()
    text = identity_text(html)
    assert "Qatar University" in text and "جامعة قطر" in text and "QU" in text
    assert "Doha news" not in text


def test_an_arabic_title_still_passes_on_the_logo_and_footer() -> None:
    html = (
        "<html><head><title>الرئيسية</title></head><body>"
        '<header><img id="logo" src="/l.png" alt="Qatar University"></header></body></html>'
    ).encode()
    assert names_on_identity(["Qatar University"], html, domain="qu.edu.qa")


def test_a_zone_site_that_names_another_body_in_its_body_text_is_not_that_body() -> None:
    yok_home = (
        "<html><head><title>Yükseköğretim Kurulu</title></head><body>"
        "<header>YÖK</header><main>Orta Doğu Teknik Üniversitesi yeni programlar</main></body></html>"
    )
    metu = _body("yok.gov.tr", "Orta Doğu Teknik Üniversitesi", kind="INSTITUTION")
    assert site_identity(metu, "yok.gov.tr", fetch=_home("yok.gov.tr", yok_home)) == (
        "the homepage does not name the body"
    )


def test_a_parked_page_printing_the_domain_does_not_name_the_body() -> None:
    """"azportal.gov.az" folds to the token "azportal": without blanking the
    domain's own tokens, a for-sale page would name a body called Azportal."""
    portal = _body("azportal.gov.az", "Azportal")
    parked = "<html><head><title>azportal.gov.az is for sale</title></head><body></body></html>"
    assert site_identity(portal, "azportal.gov.az", fetch=_home("azportal.gov.az", parked)) == (
        "the homepage does not name the body"
    )


def test_a_body_named_only_by_its_domain_cannot_pass_identity() -> None:
    named = _body("studyinkorea.go.kr", "studyinkorea.go.kr")
    home = "<html><head><title>studyinkorea.go.kr</title></head></html>"
    assert site_identity(named, "studyinkorea.go.kr", fetch=_home("studyinkorea.go.kr", home)) != (
        "verified"
    )


def test_a_local_language_register_name_counts_as_the_bodys_name() -> None:
    ministry = _body("edu.gov.az", "Ministry of Science and Education")
    make_list("az_gov", country_code="AZ")
    RegisterEntry.objects.create(
        register="az_gov", external_key="mse", name="Elm və Təhsil Nazirliyi",
        organisation=ministry, website_domain="edu.gov.az", resolution="RESOLVED", last_seen=NOW,
    )
    home = "<html><head><title>Elm və Təhsil Nazirliyi</title></head></html>"
    assert site_identity(ministry, "edu.gov.az", fetch=_home("edu.gov.az", home)) == "verified"


def test_an_unreadable_homepage_is_a_failed_lookup_not_a_verdict() -> None:
    ministry = _body("edu.gov.az", "Elm və Təhsil Nazirliyi")
    assert site_identity(ministry, "edu.gov.az", fetch=FakeFetch({})) == "lookup_failed"
    verdict = check_body(ministry, "edu.gov.az", now=NOW, deps=_deps(fetch=FakeFetch({})))
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "lookup_failed")


def test_a_homepage_that_redirects_off_the_domain_does_not_verify() -> None:
    ministry = _body("edu.gov.az", "Elm və Təhsil Nazirliyi")
    moved = FakeFetch({"https://edu.gov.az/": page(
        "https://edu.gov.az/", "<title>Elm və Təhsil Nazirliyi</title>",
        final_url="https://elmtehsil.example.com/",
    )})
    assert site_identity(ministry, "edu.gov.az", fetch=moved).startswith("redirected off")


def test_a_named_ministry_on_its_zone_is_recognised() -> None:
    ministry = _body("edu.gov.az", "Elm və Təhsil Nazirliyi")
    home = "<html><head><title>Elm və Təhsil Nazirliyi</title></head></html>"
    verdict = check_body(ministry, "edu.gov.az", now=NOW, deps=_deps(fetch=_home("edu.gov.az", home)))
    assert (verdict.verdict, verdict.reason_code) == ("RECOGNISED", "government_zone")
    assert verdict.evidence["site_identity"] == "verified"


def test_a_zone_body_whose_homepage_names_someone_else_is_unconfirmed() -> None:
    ministry = _body("edu.gov.az", "Elm və Təhsil Nazirliyi")
    home = "<html><head><title>Another Agency</title></head></html>"
    verdict = check_body(ministry, "edu.gov.az", now=NOW, deps=_deps(fetch=_home("edu.gov.az", home)))
    assert verdict.verdict == "UNCONFIRMED"
    assert verdict.reason_code == "no_domain_binding"
    assert verdict.evidence["site_identity"] == "the homepage does not name the body"


def test_dead_is_not_verified() -> None:
    dead = FakeFetch({"https://edu.gov.az/": page("https://edu.gov.az/", b"", outcome=Outcome.DEAD)})
    ministry = _body("edu.gov.az", "Elm və Təhsil Nazirliyi")
    assert site_identity(ministry, "edu.gov.az", fetch=dead) == "lookup_failed"
```

Then fix the existing go.kr test in `tests/research/test_provenance_check.py:273-275`. A body named after its own domain can no longer pass, so the test gives it a real name and a homepage. Add `HomeFetch` to that file's import from `tests.research.provenance_helpers`.

```python
def test_a_go_kr_funder_is_recognised_by_its_government_zone() -> None:
    record_organisation(domain="studyinkorea.go.kr", name="Study in Korea",
                        kind="NATIONAL_GOVERNMENT", country_code="KR", found_via="TEST")
    deps = _deps(fetch=HomeFetch({}, homes=frozenset({"studyinkorea.go.kr"})))
    verdict = _verdict("studyinkorea.go.kr", deps, kind="NATIONAL_GOVERNMENT")
    assert verdict.reason_code == "government_zone"
```

Also add `from apps.research.register import record_organisation` to that file's imports.

- [ ] **Step 3: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_website_proof uv run pytest tests/research/test_provenance_identity.py -q`
Expected: FAIL with `ImportError: cannot import name 'identity_text'`.

- [ ] **Step 4: Implement the identity functions**

In `apps/research/recognition.py`, after `verify_list_origins` (around line 341), add:

```python
#: Where a site names itself (spec §4.1 step 3). The body text is deliberately
#: not read: a regulator's homepage names the bodies it regulates (yok.gov.tr
#: lists universities), and those names must never make it their site.
_IDENTITY_REGIONS = (
    "//title", "//header", "//footer", "//*[@role='banner']", "//*[@role='contentinfo']",
)
_IDENTITY_META = "//meta[@property='og:site_name' or @name='application-name']/@content"
_LOGO_ALT = (
    "//img[contains(translate(concat(@class, ' ', @id, ' ', @src), 'LOGO', 'logo'), 'logo')]/@alt"
)


def _parse_html(body: bytes) -> Any:
    """UTF-8 first, as reader._document does: lxml assumes Latin-1 for bytes
    with no charset, and vendor bodies are UTF-8 (measured, PR #155)."""
    try:
        return lxml.html.document_fromstring(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return lxml.html.document_fromstring(body)


def identity_text(body: bytes) -> str:
    """The text of the parts of a page where a site names itself, joined."""
    if not body.strip():
        return ""
    try:
        doc = _parse_html(body)
    except (lxml.etree.ParserError, ValueError):
        return ""
    parts: list[str] = [el.text_content() for xpath in _IDENTITY_REGIONS for el in doc.xpath(xpath)]
    parts.extend(str(value) for value in doc.xpath(_IDENTITY_META))
    parts.extend(str(value) for value in doc.xpath(_LOGO_ALT))
    return " ".join(parts)


def names_on_identity(names: Iterable[str], body: bytes, *, domain: str) -> bool:
    """Whether any of `names` appears, as whole folded words, where the page
    names itself. Tokens carrying `domain` are blanked first: a parked page
    prints the domain, never the body (as names_institution does)."""
    text = re.sub(rf"\S*{re.escape(domain)}\S*", " ", identity_text(body), flags=re.I)
    words = f" {' '.join(tokens(text))} "
    for name in names:
        for variant in name_variants(name):
            if domain in variant:
                continue
            folded = " ".join(tokens(variant))
            if folded and f" {folded} " in words:
                return True
    return False


def body_names(organisation: Organisation) -> tuple[str, ...]:
    """Every name the platform holds for a body: its own label and the name on
    each register row bound to it (local-language names arrive this way)."""
    listed = RegisterEntry.objects.filter(organisation=organisation).values_list("name", flat=True)
    return tuple(dict.fromkeys((organisation.name, *listed)))


def site_identity(organisation: Organisation, domain: str, *, fetch: Fetch) -> str:
    """Fetch `domain`'s homepage (its `www.` counterpart only if unreadable) and
    confirm it names the body where a site names itself. "verified",
    "lookup_failed", or why not; it writes nothing."""
    for url in (f"https://{domain}/", f"https://www.{domain}/"):
        fetched = fetch(url, purpose="provenance")
        if readable_page(fetched):
            break
    else:
        return "lookup_failed"
    if registrable_domain(fetched.final_url) != domain:
        return f"redirected off the domain to {fetched.final_url}"
    if not names_on_identity(body_names(organisation), fetched.body, domain=domain):
        return "the homepage does not name the body"
    return "verified"
```

`Iterable` is already imported from `collections.abc` in this module, and `Any` from `typing`; check both before adding anything.

- [ ] **Step 5: Wire it into `check_body`**

In `apps/research/provenance_job.py`:
- import `site_identity` alongside the module's other names from `.recognition`;
- change `from dataclasses import dataclass, field` to also import `replace`.

Then make three edits to `check_body`.

(a) Right after `found, unverified = recognitions()` (line 179), add:

```python
    identity: str | None = None

    def identity_ok() -> bool:
        """The homepage check, run at most once per check_body."""
        nonlocal identity, lookup_failed
        if identity is None:
            identity = site_identity(organisation, domain, fetch=deps.fetch)
            lookup_failed |= identity == "lookup_failed"
        return identity == "verified"

    def unread(recognition: Recognition) -> bool:
        """Granted without reading the site: a bare zone, or a register row bound by ROR."""
        return recognition.reason == Reason.GOVERNMENT_ZONE or (
            recognition.reason == Reason.REGISTER and recognition.admitted_via == "ror"
        )
```

(b) Immediately before `hits: tuple[ContentHit, ...] = ()` (line 233), add:

```python
    if not blocked and any(unread(r) for r in found):
        if identity_ok():
            pass
        elif identity == "lookup_failed":
            # Nothing was read, so nothing is decided about the site: drop the
            # unread recognitions and let decide() report lookup_failed.
            found = tuple(r for r in found if not unread(r))
        else:
            # Read, and it names someone else: keep the recognition but unbind
            # it, so decide() says so (no_domain_binding), never "not checked".
            found = tuple(replace(r, bound_domain="") if unread(r) else r for r in found)
```

This gives three outcomes for a body whose only recognitions were unread:
- **homepage names the body:** RECOGNISED, as before.
- **homepage could not be read:** `found` is empty, `facts.lookup_failed` is True, and `decide()` returns UNCONFIRMED `lookup_failed`, retried in a day.
- **homepage names someone else:** an empty `bound_domain` never equals the domain, so `decide()` step 3 returns UNCONFIRMED `no_domain_binding`.

A body that also has a read recognition (a verified register row, a vouch) keeps it whatever the homepage says.

(c) Between `decision = decide(...)` and `return _record(...)` at the end of `check_body`, record the outcome:

```python
    if identity is not None:
        decision.evidence["site_identity"] = identity
```

`Decision` is frozen, but its `evidence` dict is the one `decide()` built for this call, so adding a key is safe.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_website_proof uv run pytest tests/research/test_provenance_identity.py tests/research/test_provenance_check.py -q`
Expected: the new file passes. In `test_provenance_check.py`, only tests whose RECOGNISED verdict came through a bare zone or ROR may fail; Step 7 fixes them.

- [ ] **Step 7: Give every zone- or ROR-recognised test body a homepage**

For each failing test from Step 6, set `fetch=HomeFetch(<its existing pages dict>, homes=frozenset({<the domain>}))` in its `_deps(...)`. If the body was created with `make_body(domain)`, which names it after its domain, recreate it with a real name: `record_organisation(domain=..., name=<a real name>, kind=..., country_code=..., found_via="TEST")`. Do not loosen any assertion. Re-run until the file is green:

Run: `POSTGRES_DB=elmify_website_proof uv run pytest tests/research -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/research/recognition.py apps/research/provenance_job.py \
        tests/research/provenance_helpers.py tests/research/test_provenance_identity.py \
        tests/research/test_provenance_check.py
git commit -m "feat(provenance): a zone or ROR-bound recognition counts only when the homepage names the body

Closes the yok.gov.tr hole (spec 11.1): a government zone was a bare suffix match.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: A register row's printed website must name the institution before it proves anything

**Files:**
- Modify: `apps/research/recognition.py:151-224` (`list_recognitions`) and a new `verify_register_origins` after `verify_list_origins`
- Modify: `apps/research/provenance_job.py` (`check_body`'s `recognitions()` closure)
- Modify: `tests/research/test_provenance_check.py` (the `_register` helper and the real-register tests)
- Test: `tests/research/test_provenance_check.py`

**Interfaces:**
- Consumes: `recognition.verify_origin` (unchanged), `HomeFetch` (Task 2).
- Produces:
  - `recognition.list_recognitions(organisation, sources=None, *, domain="", require_register_origin=False)`;
  - `recognition.verify_register_origins(organisation: Organisation, domain: str, sources: tuple[ProvenanceSource, ...], *, now: datetime, fetch: Fetch, tried: set[object]) -> None`.

Today a curated-list row must pass `verify_origin` (fetch the printed website, confirm it names the institution), but a **register** row recognises a body with no fetch at all (spec §11.1, "P1 is weaker than §4 says"). From this task on, `check_body` verifies the domain's register rows first and asks `list_recognitions` to require that. An unverified register row then reads as `unmapped_list_row` ("Listed officially, but its website is not confirmed yet"), exactly as an unverified curated row does today. The default `require_register_origin=False` keeps every other caller and the register-loading tests unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/research/test_provenance_check.py`:

```python
def test_a_register_row_whose_site_does_not_name_it_is_unmapped() -> None:
    source = _register("de_register", "DE", "tum.de", origin_verified=False)
    parked = SiteFetch({}, site="tum.de", html="<title>tum.de for sale</title>")
    verdict = _verdict("tum.de", _deps(sources=(source,), fetch=parked))
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "unmapped_list_row")


def test_a_register_row_whose_site_names_it_is_recognised_and_stays_verified() -> None:
    source = _register("de_register", "DE", "tum.de", origin_verified=False)
    RegisterEntry.objects.filter(website_domain="tum.de").update(name="Technische Universität München")
    fetch = HomeFetch({}, homes=frozenset({"tum.de"}))
    verdict = _verdict("tum.de", _deps(sources=(source,), fetch=fetch))
    assert (verdict.verdict, verdict.reason_code) == ("RECOGNISED", "register")
    entry = RegisterEntry.objects.get(website_domain="tum.de")
    assert entry.origin_verified_domain == "tum.de"


def test_a_register_row_redirected_off_its_domain_is_unmapped() -> None:
    source = _register("de_register", "DE", "tum.de", origin_verified=False)
    moved = SiteFetch({}, site="tum.de", html="<title>tum.de</title>",
                      landed="https://casino.example/")
    assert _verdict("tum.de", _deps(sources=(source,), fetch=moved)).reason_code == (
        "unmapped_list_row"
    )


def test_a_failing_origin_is_verified_once_per_check() -> None:
    """recognitions() runs up to three times per check; the memo keeps
    verify_origin to one attempt (its printed URL plus one counterpart)."""
    source = _register("de_register", "DE", "tum.de", origin_verified=False)
    fetch = SiteFetch({}, site="tum.de", html="<title>nothing</title>")
    _verdict("tum.de", _deps(sources=(source,), fetch=fetch))
    assert len([url for url in fetch.calls if "tum.de" in url]) <= 2


def test_list_recognitions_without_the_flag_is_unchanged() -> None:
    _register("de_register", "DE", "tum.de", origin_verified=False)
    tum = Organisation.objects.get(domains__registrable_domain="tum.de")
    source = ProvenanceSource(slug="de_register", role="register", named_by_hand_because="test")
    assert [r.reason for r in list_recognitions(tum, (source,))[0]] == ["register"]
    assert list_recognitions(tum, (source,), require_register_origin=True) == ((), True)
```

Add `list_recognitions` to the file's import from `apps.research.recognition`, and `HomeFetch` and `SiteFetch` to its import from `tests.research.provenance_helpers`.

Change the `_register` helper (lines 107-120) so it can make verified rows, with `origin_verified=True` as the default. The many tests that use it are about other behaviour and represent an already-verified register:

```python
def _register(
    slug: str, country: str, *websites: str, unbound: str = "", origin_verified: bool = True
) -> ProvenanceSource:
    spec = make_list(slug, country_code=country)
    rows = tuple(
        ListRow(external_key=w, name=w, kind="INSTITUTION", website=f"https://{w}", page_url="",
                country_code=country, home_cells=("ANY",), host_cells=(country,),
                rejected_reason="", source_url=spec.source_url, verified_on=date(2026, 9, 26))
        for w in websites
    )
    record_list(spec, rows, now=NOW)
    if origin_verified:
        for w in websites:
            RegisterEntry.objects.filter(register=slug, website_domain=w).update(
                origin_verified_domain=w, origin_verified_at=NOW
            )
    if unbound:
        RegisterEntry.objects.create(register=slug, external_key=unbound, name=unbound,
                                     resolution="UNRESOLVED", last_seen=NOW)
    ClosedList.objects.filter(slug=slug).update(loaded_at=NOW)
    return ProvenanceSource(slug=slug, role="register", named_by_hand_because="test")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_website_proof uv run pytest tests/research/test_provenance_check.py -q -k "register_row or without_the_flag or once_per_check"`
Expected: FAIL. `list_recognitions` rejects `require_register_origin`, and the unverified rows still come back RECOGNISED.

- [ ] **Step 3: Implement**

In `apps/research/recognition.py`, change `list_recognitions`'s signature and its origin check:

```python
def list_recognitions(
    organisation: Organisation,
    sources: tuple[ProvenanceSource, ...] | None = None,
    *,
    domain: str = "",
    require_register_origin: bool = False,
) -> tuple[tuple[Recognition, ...], bool]:
```

and, inside the loop, replace lines 191-194:

```python
        verified = entry.origin_verified_domain == entry.website_domain
        # A register row proves nothing until its printed website names it
        # (spec 11.1, P1): `check_body` asks for that; the register loaders do not.
        needs_origin = source.role == Reason.CURATED_LIST or (
            require_register_origin and source.role == Reason.REGISTER
        )
        if needs_origin and not verified:
            unverified = True
            continue
```

Add after `verify_list_origins`:

```python
def verify_register_origins(
    organisation: Organisation,
    domain: str,
    sources: tuple[ProvenanceSource, ...],
    *,
    now: datetime,
    fetch: Fetch,
    tried: set[object],
) -> None:
    """Run verify_origin on this body's register rows for `domain` that are not
    verified yet, each at most once per check (`tried` is the check's memo)."""
    slugs = [source.slug for source in sources if source.role == Reason.REGISTER]
    entries = RegisterEntry.objects.filter(
        organisation=organisation, register__in=slugs, website_domain=domain,
        resolution=RegisterEntry.Resolution.RESOLVED, resolved_via=ResolvedVia.LISTED,
    ).exclude(origin_verified_domain=domain)
    for entry in entries:
        if entry.pk in tried:
            continue
        tried.add(entry.pk)
        outcome = verify_origin(entry, now=now, fetch=fetch)
        if outcome != "verified":
            logger.warning("register origin of %s %s not verified: %s",
                           entry.register, entry.external_key, outcome)
```

In `apps/research/provenance_job.py`, import `verify_register_origins` and change the `recognitions()` closure in `check_body`:

```python
    tried: set[object] = set()

    def recognitions() -> tuple[tuple[Recognition, ...], bool]:
        verify_register_origins(
            organisation, domain, sources, now=now, fetch=deps.fetch, tried=tried
        )
        found, unverified = list_recognitions(
            organisation, sources, domain=domain, require_register_origin=True
        )
        zone = government_zone(domain)
        by_ror = ror_recognitions(ror, domain, sources)
        return (*found, *by_ror, *((zone,) if zone else ())), unverified
```

- [ ] **Step 4: Run the new tests, then the whole file**

Run: `POSTGRES_DB=elmify_website_proof uv run pytest tests/research/test_provenance_check.py -q`
Expected: the five new tests pass. Tests that load a **real** register and expect RECOGNISED now fail, because their fake fetch serves no homepage. Expect these: `test_tum_is_recognised_after_loading_germanys_register`, `test_edinburgh_is_recognised_via_the_sfc_list`, and the METU, Kentech and ESMT tests near lines 520–580. Also expect the run-wide tests near lines 398–409 and 620–641 that use `_germany_deps`.

- [ ] **Step 5: Serve those tests a homepage that names the institution**

Make `_germany_deps` serve TUM's homepage. Leave the register pages untouched and add the home.

```python
def _germany_deps(**overrides) -> Deps:
    make_list("de_hochschulkompass", country_code="DE", source_url=HRK_DOWNLOADS_URL)
    fields = dict(
        ror_call=_ror(**{"tum.de": _record("tum.de", "DE")}),
        fetch=HomeFetch({ENIC_DE_URL: page(ENIC_DE_URL, ENIC_GERMANY),
                         HRK_DOWNLOADS_URL: page(HRK_DOWNLOADS_URL, HRK_DOWNLOADS)},
                        homes=frozenset({"tum.de"})),
        fetch_file=Files({HRK.data_url: HRK_TSV}), sources=(HRK,), load=load_register,
    )
    fields.update(overrides)
    return _deps(**fields)
```

For every other failing test from Step 4, wrap its existing `FakeFetch({...})` in `HomeFetch({...}, homes=frozenset({<domain under test>}))`. `HomeFetch` prints the register row's own name, so the test needs no name of its own. Assertions stay as they are. One exception: `test_tum_is_recognised_after_loading_germanys_register`'s `next_check_at` line is Task 4's to change, so leave it failing until then.

- [ ] **Step 6: Run the research suite**

Run: `POSTGRES_DB=elmify_website_proof uv run pytest tests/research tests/funding -q`
Expected: PASS, except the `next_check_at` assertions Task 4 changes.

- [ ] **Step 7: Commit**

```bash
git add apps/research/recognition.py apps/research/provenance_job.py tests/research/test_provenance_check.py
git commit -m "feat(provenance): a register row proves a site only after its printed website names it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: A proven body is not re-checked on a schedule

**Files:**
- Modify: `apps/research/provenance_job.py:138-145` (`next_check`) and the `due()` docstring (line 295)
- Modify: `apps/research/management/commands/provenance_recheck.py` (module docstring)
- Test: `tests/research/test_provenance_check.py` (the `next_check` parametrize near line 423, and `test_tum_is_recognised_after_loading_germanys_register`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `next_check(decision, now)` returns `None` for RECOGNISED; `due()` therefore never returns a RECOGNISED pair.

Spec §4.1 (owner, 2026-10-03): a university is proven once and not re-checked on a schedule. Other bodies keep §4's evidence-only triggers, so no proven body is re-checked on a timer. UNCONFIRMED keeps its retries, so "not checked yet" and "register not loaded" still resolve. BLOCKED stays never.

- [ ] **Step 1: Change the tests first**

In the `next_check` parametrize (near line 423), change the RECOGNISED row:

```python
        ("RECOGNISED", "register", None),
```

In `test_tum_is_recognised_after_loading_germanys_register`, change the last assertion:

```python
    assert verdict.next_check_at is None
```

and add a test that a proven pair never comes due:

```python
def test_a_recognised_pair_never_comes_due() -> None:
    source = _register("de_register", "DE", "tum.de")
    evidence_program("https://www.tum.de/msc")
    run_checks(bodies_in_play(), now=NOW, deps=_deps(sources=(source,)))
    assert ProvenanceVerdict.objects.get(domain="tum.de").verdict == "RECOGNISED"
    assert not due(NOW + timedelta(days=3650)).exists()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_website_proof uv run pytest tests/research/test_provenance_check.py -q -k "next_check or never_comes_due or tum_is_recognised"`
Expected: FAIL: `next_check` still returns `now + 30 days`.

- [ ] **Step 3: Implement**

```python
def next_check(decision: Decision, now: datetime) -> datetime | None:
    # A proven body is proven once (spec §4.1, owner 2026-10-03): no timer
    # re-checks it. BLOCKED is never re-checked either. Only UNCONFIRMED retries.
    if decision.verdict in (Verdict.BLOCKED, Verdict.RECOGNISED):
        return None
    # no_register waits on a register being shipped, not on a load: daily
    # retries would only re-learn that none exists.
    if decision.reason_code == Reason.NO_REGISTER:
        return now + timedelta(days=settings.PROVENANCE_CYCLE_DAYS)
    return now + (_SOON if decision.reason_code in _RETRY_SOON else _UNCONFIRMED_RETRY)
```

In `due()`'s docstring, change "BLOCKED (next_check_at NULL) never comes due." to "BLOCKED and RECOGNISED (next_check_at NULL) never come due." In `provenance_recheck.py`'s module docstring, add one sentence after the scheduling line: "A RECOGNISED pair is never due (spec §4.1): this re-checks UNCONFIRMED pairs and anything not yet checked."

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_website_proof uv run pytest tests/research -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/research/provenance_job.py apps/research/management/commands/provenance_recheck.py \
        tests/research/test_provenance_check.py
git commit -m "feat(provenance): a proven body is proven once; no scheduled re-check

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The gate is on, and an unconfirmed body never reaches a student

**Files:**
- Modify: `infra/template.yaml:94-104` (`ProvenanceGateEnforced`)
- Modify: `apps/research/provenance.py:273-278` (new `blocked_note` beside `candidate_note`)
- Modify: `apps/funding/services.py:157-205` (`replace_candidate`)
- Modify: `apps/funding/views.py:113-120` (`_pack_context`) and its import line 17
- Test: `tests/infra/test_template.py:1879-1882`, `tests/funding/test_named_program_gate.py`

**Interfaces:**
- Consumes: `provenance.RECOGNISED_REASONS`, `BLOCKED_REASONS`, `WAITING_REASONS`, `WORDING`.
- Produces: `provenance.blocked_note(reason_code: str) -> str`.

Spec §0.18 (owner, 2026-10-03): a body the gate cannot confirm never reaches a student, whoever placed it. Today `replace_candidate` lets an UNCONFIRMED candidate in with a note, and the student's pack page prints "Recognition not confirmed: …". From this task on:
- while the gate is enforced, only RECOGNISED is placed;
- the student page carries only the BLOCKED explanation ("Cannot be added: …").

The counsellor's approve page keeps `candidate_note` and still sees why. The template default flips to `"1"`. There is no production database yet, so the runbook's ordering (backfill and check before flipping) holds trivially for the first deploy. The parameter's description keeps that ordering for any later restore of an old database.

- [ ] **Step 1: Write the failing tests**

In `tests/infra/test_template.py`, replace `test_provenance_gate_enforced_defaults_off_and_only_takes_0_or_1`:

```python
def test_provenance_gate_enforced_defaults_on_and_only_takes_0_or_1(template: Template) -> None:
    """Verified-only (spec §0.18): the gate ships on."""
    parameter = template.parameter("ProvenanceGateEnforced")
    assert parameter["Default"] == "1"
    assert set(parameter["AllowedValues"]) == {"0", "1"}
```

In `tests/funding/test_named_program_gate.py`, replace `test_an_unconfirmed_programme_is_placed_and_the_student_sees_the_note` (lines 79-92):

```python
def test_an_unconfirmed_programme_is_refused_while_the_gate_is_enforced(
    agency_a, membership_a, settings
) -> None:
    settings.PROVENANCE_GATE_ENFORCED = True
    pack, first, named = _pack(agency_a, membership_a, code="absent_from_register")
    with tenant_scope(agency_a.id), pytest.raises(
        PackCommandError, match="its recognition is not confirmed"
    ):
        replace_candidate(pack, first.id, named.id, membership_a)


def test_the_student_never_reads_recognition_not_confirmed(agency_a, membership_a) -> None:
    _pack_, _first, named = _pack(agency_a, membership_a, code="absent_from_register")
    with tenant_scope(agency_a.id), reads_no_catalogue():
        context = _pack_context(membership_a)
    assert named.id not in context["recognition_notes"]
```

and in `test_under_the_web_role_placement_and_the_note_need_no_catalogue` (lines 276-303), replace the block from `placed = client.post(` to the end of the test:

```python
    refused_unconfirmed = client.post(
        url, {"replacement_candidate_id": str(named_world["unconfirmed"].id)},
        HTTP_HOST=domain_a.host,
    )
    assert refused_unconfirmed.status_code == 400
    assert "its recognition is not confirmed" in refused_unconfirmed.context["error"]
    page = client.get("/student/recommendation/", HTTP_HOST=domain_a.host)
    assert page.status_code == 200
    notes = page.context["recognition_notes"]
    assert named_world["unconfirmed"].id not in notes
    # Never placed, and the student reads why before trying to.
    assert notes[named_world["blocked"].id].startswith("Cannot be added: On a published list")
```

`test_the_student_sees_why_a_blocked_named_programme_cannot_be_added` and the counsellor test `test_the_counsellor_sees_each_named_verdict_under_the_web_role` stay unchanged and must still pass.

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_website_proof uv run pytest tests/infra/test_template.py tests/funding/test_named_program_gate.py -q -k "gate or unconfirmed or recognition or blocked or counsellor"`
Expected: FAIL. The default is still `"0"`, the UNCONFIRMED candidate is placed, and the note is shown to the student.

- [ ] **Step 3: Implement**

`infra/template.yaml`, the `ProvenanceGateEnforced` parameter:

```yaml
  ProvenanceGateEnforced:
    Type: String
    AllowedValues: ["0", "1"]
    Default: "1"
    Description: >
      PROVENANCE_GATE_ENFORCED (config/settings/base.py). On by default: verified-only
      (spec 2026-09-27 verified-catalog §0.18) -- no unconfirmed body reaches a student.
      Restoring an old database? Set "0", run manage.py backfill_evidence_domain and
      manage.py provenance_check --all to completion, then "1" -- turning it on first
      times every pre-existing programme out of its pack in silence. One parameter
      feeds both WebTaskDefinition and WorkerTaskDefinition so the two tiers can never disagree.
```

`apps/research/provenance.py`, after `candidate_note`:

```python
def blocked_note(reason_code: str) -> str:
    """What a STUDENT reads beside a candidate: only why a BLOCKED one cannot
    be added. An unconfirmed one is never shown to a student (spec §0.18)."""
    if reason_code in BLOCKED_REASONS:
        return f"Cannot be added: {WORDING[reason_code][0]}"
    return ""
```

`apps/funding/services.py`, in `replace_candidate`:
- replace the comment block and the two checks (lines 177-186) with the block below;
- add `RECOGNISED_REASONS` to the module's existing import from `apps.research.provenance`.

```python
    # The tenant copy the worker wrote (spec §7.4) -- this web path never reads
    # the catalogue. BLOCKED never enters a pack. While the gate is enforced
    # only RECOGNISED does (verified-catalog §0.18: an unconfirmed body never
    # reaches a student, whoever placed it); a check not yet run waits.
    code = replacement.provenance_reason_code
    if code in BLOCKED_REASONS:
        raise PackCommandError(f"this programme cannot be added: {WORDING[code][0]}")
    if settings.PROVENANCE_GATE_ENFORCED and code not in RECOGNISED_REASONS:
        if not code or code in WAITING_REASONS:
            raise PackCommandError("still being checked; try again shortly")
        raise PackCommandError("its recognition is not confirmed; it cannot be added")
```

`apps/funding/views.py`, in `_pack_context`: change the import on line 17 to also bring in `blocked_note`, and the notes comprehension to:

```python
    # "Cannot be added: ..." beside a BLOCKED one before the student tries --
    # rendered from the tenant copy the worker wrote, never the catalogue. A
    # student never reads "Recognition not confirmed" (verified-catalog §0.18).
    notes = {
        candidate.id: note
        for candidate in (*(member.candidate for member in pool), *considered)
        if (note := blocked_note(candidate.provenance_reason_code))
    }
```

Leave `_named_note` (the counsellor's approve page) on `candidate_note`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_website_proof uv run pytest tests/infra/test_template.py tests/funding -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/template.yaml apps/research/provenance.py apps/funding/services.py \
        apps/funding/views.py tests/infra/test_template.py tests/funding/test_named_program_gate.py
git commit -m "feat(provenance): the gate ships on; an unconfirmed body never reaches a student

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The whole branch, through every gate

**Files:** none new.

- [ ] **Step 1: Run every CI gate locally**

```bash
uv run ruff check .
uv run mypy apps config
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
POSTGRES_DB=elmify_website_proof uv run pytest -q
uv run bandit -c pyproject.toml -r apps config
```

Expected: all pass. `makemigrations --check` reports "No changes detected". CI is blocked by GitHub billing, so these local runs are the evidence. Paste their tail lines into the PR body.

- [ ] **Step 2: Read the exact diff**

Run: `git diff origin/master --stat` and then `git diff origin/master`.
Expected: only the files in the file map change. No unrelated file is touched, and `ruff format` was not run.

- [ ] **Step 3: Push the branch and open a PR**

```bash
git push -u origin claude/website-proof-hardening
gh pr create --title "Website proof hardening: cited zones, identity check, register origins, gate on" \
  --body "Implements verified-catalog §4/§4.1/§0.18/§11.1 plan 1 (docs/superpowers/plans/2026-10-03-website-proof-hardening.md on claude/verified-catalog-design).

<local gate output>

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

## Deliberately not in this plan

- **The per-student rate limit** (spec §4). No student-triggered catalogue path exists yet (`run_tap` is not on any branch). It lands with the plan that builds that trigger (Part F), where it has something to wrap.
- **Shared government hosts by host and path** (`path_prefix`, spec §4 and §11.1): a schema change with a migration and an RLS re-check. It is plan 2.
- **Resetting a proven university when a page fetch from its site lands off-origin** (spec §4.1, the compensation for no re-check). It touches the reader paths the decision-engine session is changing (`reader.py`, the funding reader), so it lands with Part F's freshness work, after that session's reader.
- **P3** (register number, or address and phone, on the site): `RegisterEntry` has no such columns yet.
- **The WHED reader and the parent rule** (spec §4.1): plan 4.
- **Six caveat zones** (gob.mx, gov.eg, gov.ng, gov.pl, gov.br, gov.kz) and the unverified ones (gouv.fr, gov.ae, gov.bn, go.ke, gov.ma and six more). They can be added later through Task 1's recipe once a citation proves the zone is government-only.

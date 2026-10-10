# Student Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every student-facing page as plain, unstyled HTML: login, a home page with "Needs you now" above a five-column board (one card per application), programmes and funding grouped under the funding, a documents-by-application table, messages, settings, the profile wizard, the gap interview and the kit — plus the counsellor's view of one assigned student's board with full rights, the mail-to-board effects (document requests, decision available, outcome recorded from trusted mail) and the `create_student` operator command.

**Architecture:** Django templates in a new root `templates/` extending one `base.html`; no stylesheet, no JS framework, one small static script on the documents page. Board, needs and grouping logic are pure functions over rows (`apps/dashboard/board.py`, `apps/dashboard/needs.py`, `apps/funding/grouping.py`, `apps/documents/table.py`) so they are tested without markup; views only query and render. The web tier still never reads the catalogue: everything the pages show about a programme or a funding opportunity is a tenant copy the research worker writes onto `RecommendationCandidate`, and the kit's catalogue parts are copied onto the `Application` by the document worker.

**Tech Stack:** Django 5.2 templates and class-based auth views, pytest-django, Postgres 17 with RLS, the existing OpenAI structured-output classifier (`apps/mailbox/classify.py`) for labels and quotes, TypeSafe's Jev through OpenRouter (`apps/research/decisions.py::ask`) for the one decision reading, `apps/research/engine_eval/score.py` for learning its bars, SQS document queue (`apps/documents/document_queue.py`).

**Spec:** `docs/superpowers/specs/2026-10-04-student-dashboard-design.md`

---

## Global Constraints

- Presentation is plain unstyled HTML for testing; designers do the visual design later (owner, 2026-10-03). No stylesheet, no CSS classes added for looks.
- No new JS framework and no htmx; the only script is `static/dashboard/documents.js`, calling the existing JSON APIs.
- Templates live in root `templates/` (`base.html`, `403.html`, `400.html`, `registration/login.html`, `student/*`); app templates may extend `base.html`.
- Ownership split with the consent session (f7): this branch owns `templates/base.html`, `templates/registration/login.html`, `templates/student/*`, `/accounts/login/`, `/accounts/logout/`. Never create `apps/privacy/*`; f7 adds `/accounts/logout/` to its `_ACCEPTANCE_EXEMPT_PREFIXES`.
- Every test command uses `POSTGRES_DB=tehsil_student_dashboard`.
- Never run `ruff format`. Lint: `uv run ruff check .`
- Types: `uv run mypy apps config`
- Django: `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run`
- Never hand-edit `uv.lock` or an applied migration; migrations are generated with `makemigrations --name`.
- Every LLM call: untrusted text labelled as data, output schema-constrained with Pydantic `extra="forbid"`, `max_output_tokens` capped, rate-limited through `apps/ratelimit.py::rate_limited`.
- Student mail reaches Jev only through `apps/mailbox/decision_reader.py`: the student's name words, every email address and phone number stripped first, `record=False`, rate-limited; owner decision 2026-10-04, `docs/legal/2026-09-provider-terms.md`. Jev never falls back to another reader: unavailable means abstain.
- RLS: web views run inside `HostTenantContextMiddleware`'s transaction; worker code wraps every tenant read/write in `tenant_scope()` + `tenant_transaction()`/`set_local_tenant()`. Never traverse `candidate.program`, `candidate.opportunity` or `draft.programme` on the web tier — read the `_id` columns and tenant copies only (`tests/conftest.py::reads_no_catalogue`).
- Only `https` links are rendered from third-party data (evidence URLs, portal form URLs, kit `RequirementItem.source_url`, funding contact URLs), through the `https_only` filter.
- id-addressed refusals are 404, never 403; every new student page is behind the deletion lock (middleware) and, once f7 merges, the acceptance lock.
- `apps/portals/*.py` other than `ext_api.py`/`models.py` must not contain the string `SUBMITTED` (`tests/portals/test_boundary.py`); code that names that state lives in `apps/dashboard/`.
- Every new field on a student-reachable model is classified in `apps/audit/redaction.py` in the same commit.
- An upload is copied out of `quarantine/`, ingested or served only after GuardDuty's `NO_THREATS_FOUND` **and** the upload check in the isolated OCR function (Task 14); a PDF is never rewritten. A clean verdict commits `CHECKING`; from Task 14 on, `AVAILABLE` means scanned clean, checked and promoted, and only `_check_and_promote` writes it. Every route that serves an upload sends `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox; default-src 'none'`.
- Commits end with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; never push to `master`.

## Review Focus

These are the input classes the spec implies that no happy-path test would exercise, most likely first. Each has a named test in the owning task.

1. **Another student's id in every new URL is a 404.** Application ids (start, outcome, remove, submit document), candidate ids (add), pairing ids (disconnect), document ids (expiry, submit), and a counsellor opening an unassigned student. Tests: Task 9 `test_another_students_application_is_404_on_every_action`, Task 9 `test_another_students_candidate_cannot_be_added`, Task 15 `test_submitting_another_students_document_is_404`, Task 17 `test_another_students_pairing_is_404`, Task 20 `test_an_unassigned_counselor_gets_404_everywhere`.
2. **A deletion-locked (and, after f7, acceptance-locked) student is redirected away from every new page.** `tests/dashboard/test_locks.py::test_every_student_page_is_behind_the_deletion_lock`, created in Task 12 and extended by each page task (13, 15–19); the acceptance variant skips until `apps.privacy.acceptance` exists.
3. **An untrusted `DECISION` mail never moves a card.** Task 8 `test_an_untrusted_decision_moves_no_card` (no `decision_available_at`, no `outcome`, the reading kept on the signal only).
4. **A person-recorded outcome is never overwritten by a later automatic reading.** Task 8 `test_a_person_recorded_outcome_survives_a_later_trusted_mail`.
5. **A third-party URL with a `javascript:` or `http:` scheme is never rendered as a link.** Task 6 `test_https_only_refuses_everything_but_https` (filter), Task 13 `test_a_javascript_source_url_is_never_a_link`, Task 19 `test_a_kit_action_with_an_http_url_is_text_not_a_link`.
6. **A hostile file never reaches a portal under the student's name.** An HTML or SVG file named `passport.pdf`, and a PDF carrying JavaScript, a launch action, an embedded file, rich media or XFA, end `REJECTED_TYPE` / `REJECTED_ACTIVE_CONTENT` and are never copied; an upload is `CHECKING`, never `AVAILABLE`, while the check runs, and a `CHECKING` upload is offered for no Submit and 404s at `/ext/documents`; a check that never answers promotes nothing; a signed PDF is copied byte for byte; the served copy is an inert attachment. Tests (Task 14): `ocr/test_read_pages.py::test_a_pdf_with_active_content_is_named` and `test_the_type_is_read_from_the_bytes_and_only_three_pass`, `tests/documents/test_upload_promotion.py::TestTheRealCheck`, `test_a_clean_upload_is_copied_under_the_students_prefix_byte_for_byte` (asserts the committed state during the check is `CHECKING`) and `test_a_check_that_does_not_answer_promotes_nothing_and_ends_review_required`, Task 15 `test_an_upload_being_checked_reads_checking_and_offers_no_submit`, `tests/portals/test_ext_document.py::test_every_refusal_is_a_404` (`checking`), `tests/portals/test_ext_document.py::test_a_named_promoted_upload_is_streamed_as_an_inert_attachment`.

## File Structure

| Path | Responsibility |
|---|---|
| `templates/base.html` | skip link, agency name, student/counsellor nav, POST logout, messages with `role` |
| `templates/403.html`, `templates/400.html` | denied pages (copy pinned by `tests/acceptance/test_denied_page.py`) |
| `templates/registration/login.html` | login form, one refusal sentence, rate-limit notice |
| `templates/student/dashboard.html` + `_needs.html` + `_board.html` | home: Needs you now, the board, message form |
| `templates/student/recommendation_pool.html` + `_pack.html` | programmes and funding, grouped under the funding |
| `templates/student/documents.html` + `_documents_table.html` | documents × applications, uploads, drafts, submit |
| `templates/student/messages.html` + `_messages.html` | recognised mail and counsellor messages per application |
| `templates/student/settings.html`, `settings_mailbox.html`, `settings_extension.html`, `settings_account.html` | settings pages |
| `templates/student/consultation.html` + `_consultation_step.html` | profile wizard |
| `templates/audit/deletion_pending.html` | the waiting page with Restore |
| `templates/portals/kit.html` | the Application Kit |
| `templates/counselor/dashboard.html`, `student_board.html`, `review.html` | counsellor entry, one student's board, named-programme review |
| `templates/tenancy/mfa_setup.html` | staff MFA enrolment/verification (counsellor board needs it) |
| `templates/reports/consultation_report.html` | the consultation report body (kept tests) |
| `static/dashboard/documents.js` | upload via presigned POST, confirm facts, generate, approve |
| `apps/dashboard/` (new app, no models) | `board.py` (columns, cards), `needs.py` (NeedItem aggregation), `routes.py` (action URLs per viewer), `views.py`/`urls.py` (counsellor board), `templatetags/dashboard.py` (`https_only`) |
| `apps/funding/grouping.py` | `funds()` predicate and `group_under_funding()` |
| `apps/documents/table.py` | which document each application needs; the table |
| `apps/portals/applications.py` | add, remove, start, record portal, queue upload — each audited |
| `apps/portals/outcome.py` | outcome from trusted mail (a Jev reading that cleared its bars); correction by a person |
| `apps/mailbox/decision_questions.py`, `decision_bars.py`, `decision_reader.py` | the Jev questions (two wordings each), the learned bars and their date, the one reading that abstains |
| `apps/mailbox/management/commands/decision_eval.py` | seed `GoldItem` `decision_mail` rows, read with Jev, learn bars (Learn-then-Test), report |
| `apps/accounts/management/commands/create_student.py` | operator command |
| `apps/ratelimit.py` | `login_rate_limited()` shared by both login doors |
| `apps/accounts/{views,forms,urls}.py` | the rate-limited `LoginView` subclass; Django's own POST-only `LogoutView`; routes |
| `apps/mailbox/{classify,actions,views}.py` | verdict fields, board effects, form posts + settings page |
| `apps/portals/{models,packets,ext_api,tags,escalation,reminders,views,urls}.py` | new fields, nullable portal guards, student action views, extension settings |
| `apps/concierge/{models,views,urls}.py` | `Notification.application/action`, upload kinds, home/messages/settings views |
| `apps/funding/{models,views}.py` | candidate tenant copies; grouped pack context |
| `apps/research/services.py` | worker writes the candidate tenant copies |
| `apps/documents/{api,views,urls,document_queue,document_worker}.py` | upload kinds, documents page, capture action |
| `apps/audit/{redaction,views,urls}.py` | classification + nullable-date empty value; account settings |
| `apps/watch/{watchdog,mailbox_health}.py`, `apps/mailbox/sync.py` | notification `action` + nullable portal guard |
| `tests/mailbox/decision_corpus.json` + `test_decision_eval.py` | five-language synthetic letters for every hard case; the `live` eval run |
| `ocr/read_pages.py` (`inspect`), `ocr/pdf_fixtures.py`, `apps/documents/ocr.py` (`inspect_upload`) | the upload check in the isolated OCR function: type by magic bytes, active content in a PDF (pypdf, added to the OCR image) |
| `apps/documents/storage.py` (`promote_upload`, `read_upload`), `apps/documents/document_worker.py` (`_check_and_promote`), `apps/portals/ext_api.py` (`document`) | a scanned-clean, checked upload copied byte for byte under the student's prefix and streamed to the paired extension as an inert attachment |
| `.github/workflows/ci.yml`, `Dockerfile`, `tests/test_static_references.py` | static files under production settings |
| `docs/runbooks/student-dashboard-live-check.md` | manual end-to-end check |

---

## Task 1: Base page, login, logout, error pages — and the frontend-test triage

Creating `templates/` un-skips every `@pytest.mark.frontend` test (`tests/conftest.py::pytest_collection_modifyitems`). There are **40**, not 42 (counted with `grep -rc "^@pytest.mark.frontend" tests`; `tests/templates/README.md` also says 40). The triage therefore lands first, in its own commit, while they are still skipped: 12 are retired (they pin the deleted visual layer), 28 are kept; the 5 denied-page tests pass in this task, the other 23 get `@pytest.mark.xfail(strict=True)` naming the task that builds their page, and that task deletes the marker.

| Test | Decision | Reason / owning task |
|---|---|---|
| `acceptance/test_denied_page.py` ×5 | keep | exact 403/400 copy, skip link, `role="alert"` — pass in this task |
| `acceptance/test_htmx_config.py::test_htmx_config_swaps_validation_status_codes` | retire | htmx-config meta |
| `acceptance/test_swap_render.py::test_student_pack_renders_under_swap_hexes` | retire | `--brand-primary` |
| `acceptance/test_vertical_slice.py::test_thin_slice_publishes_automatically_after_research` | keep, edited | drop htmx vendor file, htmx-config, `--brand-primary`, logo `<img>` assertions; 5 s polling becomes the 15 s meta refresh — Task 13 |
| `accounts/test_consultation.py` ×2 | keep | wizard renders — Task 18 |
| `accounts/test_wizard_sequencing_errors.py` ×2 | keep | `role="alert"` + wizard re-render — Task 18 |
| `concierge/test_roadmap_display.py` ×2 (frontend ones) | retire | component partial file names (`components/_deadline.html`, `_roadmap_stage.html`) and badge classes |
| `concierge/test_roadmap.py::test_student_nav_does_not_link_to_owner_or_counselor_dashboards` | keep | student nav — Task 12 |
| `concierge/test_roadmap.py::test_student_messages_are_rate_limited_and_length_capped` | keep | `role="alert"`, typed value kept — Task 12 |
| `concierge/test_roadmap.py::test_counselor_sees_only_assigned_students` | keep | counsellor entry lists assigned students — Task 20 |
| `concierge/test_roadmap.py::test_counselor_marks_roadmap_item_done` | keep | inline alert on counsellor page — Task 20 |
| `funding/test_approval_badge.py` ×2 | retire | `components/_approval_badge.html`, `class="approval"` ("Approved v" stays pinned by kept tests) |
| `funding/test_eligibility_badge.py` ×2 (frontend ones) | retire | `components/_eligibility_badge.html`, badge classes, SVG glyphs |
| `funding/test_evidence_and_money.py` ×4 (frontend ones) | retire | `components/_evidence.html`, `_money.html`, `money--gap` ("Official source"/"Last checked" stay pinned) |
| `funding/test_review_publication.py::test_review_page_shows_the_published_pack_without_an_approval_form` | keep | Task 20 |
| `funding/test_student_controls.py` — dashboard evidence (edited: `badge--eligible`→"Eligible", drop `class="approval"`), reject htmx partial, consider named, most recent run, named-program failures (edited: h1 is the page's new name), reject refusal, htmx fragment error | keep | Task 13 |
| `funding/test_student_controls.py` — resolve validation, counsellor resolves, review survives edits | keep | Task 20 |
| `reports/test_consultation_report.py` ×2 | keep (one edited in Task 13) | report content rules; `phased requirements.md` P1-7.1's 2026-08-28 amendment keeps official source URLs out of the student-facing report, so its `source_url in body` assertion is inverted — Task 13 |
| `tenancy/test_mfa.py::test_staff_with_preexisting_confirmed_device_can_reverify_in_a_new_session` | keep | named token field — Task 20 |

The htmx fragment branches in `apps/funding/views.py` stay: the kept tests still post with `HX-Request`, and `_pack.html` is the include the full page uses anyway.

**Files:**
- Delete: `tests/acceptance/test_htmx_config.py`, `tests/acceptance/test_swap_render.py`, `tests/funding/test_approval_badge.py`
- Modify (tests): `tests/concierge/test_roadmap_display.py`, `tests/funding/test_eligibility_badge.py`, `tests/funding/test_evidence_and_money.py`, `tests/acceptance/test_vertical_slice.py`, `tests/funding/test_student_controls.py`, `tests/accounts/test_consultation.py`, `tests/accounts/test_wizard_sequencing_errors.py`, `tests/concierge/test_roadmap.py`, `tests/funding/test_review_publication.py`, `tests/reports/test_consultation_report.py`, `tests/tenancy/test_mfa.py`, `tests/templates/README.md`
- Create: `templates/base.html`, `templates/403.html`, `templates/400.html`, `templates/registration/login.html`, `tests/accounts/test_login.py`
- Modify: `apps/ratelimit.py`, `apps/documents/api.py`, `apps/accounts/forms.py`, `apps/accounts/views.py`, `apps/accounts/urls.py`, `config/urls.py`, `config/settings/base.py`, `apps/tenancy/middleware.py`

**Interfaces:**
- Produces: `apps.ratelimit.login_rate_limited(username: str) -> bool` (bucket `"api-login"`, 10 per 900 s, key = first 8 bytes of SHA-256 of the username)
- Produces: `apps.accounts.forms.PlainAuthenticationForm(AuthenticationForm)`
- Produces: `apps.accounts.views.RateLimitedLoginView(LoginView)`; `/accounts/logout/` is Django's own `LogoutView` (POST only). URL names `accounts-login`, `accounts-logout`
- Logout keeps the extension paired (owner, 2026-10-04): pairing needs a toolbar click today (`docs/superpowers/plans/2026-09-17-glass-box-extension.md`, Task 3 superseded glass-box decision 4's invisible pairing), so revoking at logout would force a re-pair after every login and break one-click Start application. Disconnect lives in Settings (Task 17); erasure revokes (`audit.console.request_deletion` already revokes every pairing).

- [ ] **Step 1: Retire the 12 tests that pin the deleted visual layer**

```bash
cd /home/orkhan/Desktop/student-dashboard && git rm tests/acceptance/test_htmx_config.py tests/acceptance/test_swap_render.py tests/funding/test_approval_badge.py
```

In `tests/concierge/test_roadmap_display.py` delete `test_deadline_partial_pairs_icon_and_label_for_urgent_states` and `test_roadmap_stage_pill_is_labeled_per_state`, and the now-unused `import pytest` and `from django.template.loader import render_to_string`. Keep `test_deadline_urgency_thresholds`.

In `tests/funding/test_eligibility_badge.py` delete `_render`, `test_badge_renders_icon_and_label_for_every_state` and `test_badge_states_are_visually_distinct_without_hue`, and the now-unused imports (`pytest`, `render_to_string`). Keep `test_tri_state_mapping_low_is_the_review_threshold`.

In `tests/funding/test_evidence_and_money.py` delete the four `@pytest.mark.frontend` tests and the now-unused imports (`Decimal`, `pytest`, `render_to_string`). Keep the two `source_domain` tests.

- [ ] **Step 2: Edit the kept tests whose assertions pinned the visual layer**

`tests/acceptance/test_vertical_slice.py`, replace the body of `test_thin_slice_publishes_automatically_after_research` from `pending = ...` to the end with:

```python
    pending = slice_driver.student_opens_dashboard()
    # The deleted htmx poll became a plain meta refresh, present only while
    # research is still running (spec §5).
    assert pending.contains('<meta http-equiv="refresh" content="15">')
    slice_driver.worker_processes(message)
    page = slice_driver.student_opens_dashboard()
    with tenant_scope(run.tenant_id):
        pack = PackVersion.objects.get(run=run, published_at__isnull=False)
    assert pack.published_at is not None
    assert page.contains("Official source")
    assert page.contains("Funding gap")
    assert page.contains("Approved v")
    assert not page.contains('http-equiv="refresh"')
```

and add above its `@pytest.mark.frontend`:

```python
@pytest.mark.xfail(strict=True, reason="pack page built in Task 13")
```

`tests/funding/test_student_controls.py::test_dashboard_renders_complete_evidence_for_every_visible_candidate`: replace `assert "badge--eligible" in body` with `assert "Eligible" in body` and delete `assert 'class="approval"' in body`.

`tests/funding/test_student_controls.py::test_named_program_failures_re_render_the_page_with_inline_errors`: replace `assert "<h1>Recommendation</h1>" in body` with `assert "<h1>Programmes &amp; funding</h1>" in body` (the spec renames the page; the assertion still proves the full page came back, not the fragment).

- [ ] **Step 3: Mark every kept-but-unbuilt test `xfail(strict=True)`**

Add the line above each test's `@pytest.mark.frontend`:

```python
# tests/concierge/test_roadmap.py
#   test_student_nav_does_not_link_to_owner_or_counselor_dashboards
#   test_student_messages_are_rate_limited_and_length_capped
@pytest.mark.xfail(strict=True, reason="home page built in Task 12")

# tests/funding/test_student_controls.py
#   test_dashboard_renders_complete_evidence_for_every_visible_candidate
#   test_reject_command_htmx_returns_updated_partial
#   test_consider_named_program_requires_a_name_and_queues_review
#   test_dashboard_shows_the_most_recent_run_not_the_highest_version_number
#   test_named_program_failures_re_render_the_page_with_inline_errors
#   test_reject_refusal_re_renders_with_the_service_error_inline
#   test_htmx_fragment_error_returns_the_partial_with_the_alert
# tests/reports/test_consultation_report.py (both frontend tests)
@pytest.mark.xfail(strict=True, reason="pack page built in Task 13")

# tests/accounts/test_consultation.py (both frontend tests)
# tests/accounts/test_wizard_sequencing_errors.py (both tests)
@pytest.mark.xfail(strict=True, reason="wizard built in Task 18")

# tests/concierge/test_roadmap.py
#   test_counselor_sees_only_assigned_students
#   test_counselor_marks_roadmap_item_done
# tests/funding/test_review_publication.py::test_review_page_shows_the_published_pack_without_an_approval_form
# tests/funding/test_student_controls.py
#   test_resolve_validation_failure_rerenders_review_with_inline_error
#   test_counselor_can_resolve_a_named_program_and_the_placeholder_url_is_replaced
#   test_counselor_review_survives_repeated_student_edits
# tests/tenancy/test_mfa.py::test_staff_with_preexisting_confirmed_device_can_reverify_in_a_new_session
@pytest.mark.xfail(strict=True, reason="counsellor pages built in Task 20")
```

In `tests/templates/README.md` replace the section "## The deferred tests" with:

```markdown
## The frontend tests

`templates/` exists again (2026-10-04, student dashboard). The 12 tests that pinned the
deleted visual layer (htmx vendor file and config meta, `--brand-primary`, component
partial file names, the 5-second poll) were retired in the commit that names each one.
The 28 kept tests assert behaviour the plain pages still owe. A stub here is used only
for a template root `templates/` does not provide yet; each stub is deleted in the task
that builds the real page.
```

- [ ] **Step 4: Run the suite to see the triage is green while `templates/` is still absent**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/acceptance tests/accounts tests/concierge tests/funding tests/reports tests/tenancy/test_mfa.py`
Expected: PASS (frontend tests still skipped; skip wins over xfail).

- [ ] **Step 5: Commit the triage**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add -A tests && git commit -m "test(frontend): retire the 12 tests that pin the deleted visual layer

Retired (the spec's plain pages carry no visual layer):
- acceptance/test_htmx_config.py: the htmx-config meta
- acceptance/test_swap_render.py: --brand-primary swap hexes
- concierge/test_roadmap_display.py x2: components/_deadline.html, _roadmap_stage.html
- funding/test_approval_badge.py x2: components/_approval_badge.html
- funding/test_eligibility_badge.py x2: components/_eligibility_badge.html, glyphs
- funding/test_evidence_and_money.py x4: components/_evidence.html, _money.html
Edited: vertical slice drops htmx, brand and logo assertions and expects the 15 s
meta refresh; student controls drop badge classes; the pack page's h1 follows the
spec's new name. 23 kept tests are xfail(strict) until the task that builds their page.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Write the failing login tests**

`tests/accounts/test_login.py`:

```python
"""The HTML login and logout: the JSON door's limiter, one refusal sentence."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.audit.models import DeletionRequest
from apps.portals.pairing import issue_pairing_code, redeem_pairing_code
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db

LOGIN = "/accounts/login/"
LOGOUT = "/accounts/logout/"


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def student(agency_a):
    user = get_user_model().objects.create_user(username="amina", password="correct-horse-battery")
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=user, role=Membership.Role.STUDENT)
    return user


def test_the_login_page_labels_both_fields(client, domain_a) -> None:
    response = client.get(LOGIN, HTTP_HOST=domain_a.host)
    body = response.content.decode()
    assert response.status_code == 200
    assert '<label for="id_username">' in body
    assert '<label for="id_password">' in body
    assert "Skip to content" in body


def test_a_right_password_signs_in_and_lands_on_the_board(client, domain_a, student) -> None:
    response = client.post(
        LOGIN, {"username": "amina", "password": "correct-horse-battery"}, HTTP_HOST=domain_a.host
    )
    assert response.status_code == 302
    assert response["Location"] == "/"
    assert client.get("/", HTTP_HOST=domain_a.host)["Location"] == "/student/"


def test_a_wrong_password_says_one_sentence(client, domain_a, student) -> None:
    response = client.post(
        LOGIN, {"username": "amina", "password": "wrong"}, HTTP_HOST=domain_a.host
    )
    body = response.content.decode()
    assert response.status_code == 200
    assert 'role="alert"' in body
    assert "Wrong username or password." in body
    assert "_auth_user_id" not in client.session


def test_an_unknown_username_gets_the_same_sentence(client, domain_a) -> None:
    response = client.post(
        LOGIN, {"username": "nobody", "password": "wrong"}, HTTP_HOST=domain_a.host
    )
    assert "Wrong username or password." in response.content.decode()


def test_the_html_door_shares_the_json_door_s_limit(client, domain_a, student) -> None:
    for _ in range(10):
        client.post(
            "/api/auth/login",
            json.dumps({"username": "amina", "password": "wrong"}),
            content_type="application/json",
            HTTP_HOST=domain_a.host,
        )
    response = client.post(
        LOGIN, {"username": "amina", "password": "correct-horse-battery"}, HTTP_HOST=domain_a.host
    )
    assert response.status_code == 429
    assert "Too many attempts" in response.content.decode()
    assert "_auth_user_id" not in client.session


def test_an_anonymous_visitor_at_the_root_goes_to_login(client, domain_a) -> None:
    assert client.get("/", HTTP_HOST=domain_a.host)["Location"] == "/accounts/login/"


def test_a_protected_page_sends_an_anonymous_visitor_to_login(client, domain_a) -> None:
    response = client.get("/student/", HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert response["Location"] == "/accounts/login/?next=/student/"


def test_logout_refuses_get(client, domain_a, student) -> None:
    client.force_login(student)
    assert client.get(LOGOUT, HTTP_HOST=domain_a.host).status_code == 405


def test_logout_ends_the_session_and_keeps_the_extension_paired(
    client, agency_a, domain_a, student
) -> None:
    with tenant_scope(agency_a.id):
        membership = Membership.objects.get(user=student)
        pairing, _token = redeem_pairing_code(issue_pairing_code(membership), "install-1")
    client.force_login(student)

    response = client.post(LOGOUT, HTTP_HOST=domain_a.host)

    assert response.status_code == 302
    assert response["Location"] == "/accounts/login/"
    assert "_auth_user_id" not in client.session
    pairing.refresh_from_db()
    # Owner, 2026-10-04: logout keeps the extension paired; Settings disconnects.
    assert pairing.revoked_at is None
    assert pairing.token_hash != ""


def test_a_deletion_locked_student_can_still_log_out(client, agency_a, domain_a, student) -> None:
    with tenant_scope(agency_a.id):
        membership = Membership.objects.get(user=student)
        DeletionRequest.objects.create(
            tenant=agency_a, student=membership, state="REQUESTED", reason="OTHER"
        )
    client.force_login(student)
    response = client.post(LOGOUT, HTTP_HOST=domain_a.host)
    assert response["Location"] == "/accounts/login/"
```

- [ ] **Step 7: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/accounts/test_login.py`
Expected: FAIL — `/accounts/login/` is 404 and `/` answers 200 "Tehsil".

- [ ] **Step 8: Share the login limiter**

Append to `apps/ratelimit.py`:

```python
import hashlib

#: Ten sign-in attempts per username in fifteen minutes, shared by the JSON door
#: (apps/documents/api.py::auth_login) and the HTML door (accounts.views), so an
#: attacker cannot spend ten on each.
LOGIN_LIMIT = 10
LOGIN_WINDOW_SECONDS = 900


def login_rate_limited(username: str) -> bool:
    """True once this username has been tried more than LOGIN_LIMIT times.

    Keyed on SHA-256 of the username: never the client address (a university's
    NAT would share one key) and never CRC32 (linear, so a crafted username
    could collide with a victim's and lock them out). auth_login's docstring
    carries the full reasoning.
    """
    return rate_limited(
        "api-login",
        int.from_bytes(hashlib.sha256(username.encode()).digest()[:8], "big"),
        limit=LOGIN_LIMIT,
        window_seconds=LOGIN_WINDOW_SECONDS,
    )
```

Move `import hashlib` to the top import block (ruff `E402`). In `apps/documents/api.py` delete `_LOGIN_RATE_LIMIT`, `_LOGIN_RATE_WINDOW_SECONDS` and `import hashlib`, change `from apps.ratelimit import rate_limited` to `from apps.ratelimit import login_rate_limited, rate_limited`, and replace the `if rate_limited("api-login", ...)` block in `auth_login` with:

```python
    if login_rate_limited(username):
        raise _ApiError(429, "rate_limited")
```

- [ ] **Step 9: The form, the two views, the routes, the settings**

Append to `apps/accounts/forms.py` (add `from django.contrib.auth.forms import AuthenticationForm` to the imports):

```python
class PlainAuthenticationForm(AuthenticationForm):
    """One sentence for every refusal: a separate one for an inactive account
    would tell whoever is guessing that the username exists."""

    error_messages = {
        "invalid_login": "Wrong username or password.",
        "inactive": "Wrong username or password.",
    }
```

Append to `apps/accounts/views.py` (imports: `from typing import Any`, `from django.contrib.auth.views import LoginView`, `from apps.ratelimit import login_rate_limited`; change the forms import to `from .forms import ConsultationQuestionForm, PlainAuthenticationForm`):

```python
class RateLimitedLoginView(LoginView):
    """Django's LoginView behind the JSON login's limiter (spec §1)."""

    form_class = PlainAuthenticationForm

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if login_rate_limited(request.POST.get("username", "")):
            context = self.get_context_data(form=self.form_class(request), rate_limited=True)
            return self.render_to_response(context, status=429)
        return super().post(request, *args, **kwargs)
```

Logout is Django's own `LogoutView`, used as is: it refuses GET since 5.0 and it leaves the extension paired, which is the owner's decision (Interfaces above).

`apps/accounts/urls.py`:

```python
from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import RateLimitedLoginView, profile

urlpatterns = [
    path("accounts/login/", RateLimitedLoginView.as_view(), name="accounts-login"),
    # POST only; the extension stays paired (owner, 2026-10-04).
    path("accounts/logout/", LogoutView.as_view(), name="accounts-logout"),
    path("student/profile/", profile, name="student-profile"),
]
```

`config/settings/base.py`, after `ROOT_URLCONF`:

```python
LOGIN_URL = "accounts-login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "accounts-login"
```

`config/urls.py`, replace `index` (imports: `from django.shortcuts import redirect`, `from apps.tenancy.models import Membership`; drop `HttpResponse`):

```python
def index(request: HttpRequest) -> HttpResponse:
    """A student lands on the board, a counsellor on their list, anyone else on login.

    The Outlook callback ends on the mailbox page now, but any other link to the
    bare host lands somewhere useful instead of on the word "Tehsil".
    """
    role = getattr(getattr(request, "membership", None), "role", None)
    if role == Membership.Role.STUDENT:
        return redirect("concierge-student-dashboard")
    if role == Membership.Role.COUNSELOR:
        return redirect("concierge-counselor-dashboard")
    return redirect("accounts-login")
```

(keep `from django.http import HttpRequest, HttpResponse` — the annotation still needs `HttpResponse`).

`apps/tenancy/middleware.py`:

```python
#: The paths a student with an open deletion request must still reach. Without
#: them the lock is a one-way door and the thirty-day reversal window is
#: decorative -- and without logout a locked student cannot leave a shared
#: machine. Same shape as _MFA_SETUP_PATH above.
_DELETION_EXEMPT_PREFIXES = (
    "/student/account/deletion/",
    "/student/account/restore/",
    "/accounts/logout/",
)
```

- [ ] **Step 10: The four templates**

`templates/base.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}{% if request.tenant %}{{ request.tenant.name }}{% else %}Tehsil{% endif %}{% endblock %}</title>
  {% block head %}{% endblock %}
</head>
<body>
  <a href="#main">Skip to content</a>
  <header>
    {% if request.tenant %}<p>{{ request.tenant.name }}</p>{% endif %}
    {% if viewer_role == "STUDENT" %}
      <nav aria-label="Main">
        <ul>
          <li><a href="/student/">Home</a></li>
          <li><a href="/student/recommendation/">Programmes &amp; funding</a></li>
          <li><a href="/student/documents/">Documents</a></li>
          <li><a href="/student/messages/">Messages</a></li>
          <li><a href="/student/settings/">Settings</a></li>
        </ul>
      </nav>
    {% elif viewer_role == "COUNSELOR" %}
      <nav aria-label="Main"><ul><li><a href="/counselor/">Students</a></li></ul></nav>
    {% endif %}
    {% if user.is_authenticated %}
      <form method="post" action="/accounts/logout/">{% csrf_token %}<button type="submit">Log out</button></form>
    {% endif %}
  </header>
  {% for message in messages %}
    <p role="{% if message.level_tag == 'error' %}alert{% else %}status{% endif %}">{{ message }}</p>
  {% endfor %}
  <main id="main">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

`base.html` holds no text input: `tests/documents/test_gap_interview_view.py` counts `<input type="text"` on a page that will extend it (Task 18). Nav hrefs are literal because the pages they name are built in later tasks.

`templates/403.html`:

```html
{% extends "base.html" %}
{% block title %}Not allowed{% endblock %}
{% block content %}
  <h1>Not allowed</h1>
  <p role="alert">{{ exception }}</p>
{% endblock %}
```

`templates/400.html` (Django's `bad_request` renders it with no request and no context, so it carries static copy):

```html
{% extends "base.html" %}
{% block title %}Address not recognized{% endblock %}
{% block content %}
  <h1>Address not recognized</h1>
  <p role="alert">This address isn't recognized. Check the link, or contact your counselor if you were sent here.</p>
{% endblock %}
```

`templates/registration/login.html`:

```html
{% extends "base.html" %}
{% block title %}Log in{% endblock %}
{% block content %}
  <h1>Log in</h1>
  {% if rate_limited %}<p role="alert">Too many attempts. Try again in a few minutes.</p>{% endif %}
  {% for error in form.non_field_errors %}<p role="alert">{{ error }}</p>{% endfor %}
  <form method="post" action="{% url 'accounts-login' %}">
    {% csrf_token %}
    <p>
      <label for="id_username">Username</label>
      <input type="text" name="username" id="id_username" autocomplete="username" value="{{ form.username.value|default_if_none:'' }}" required>
    </p>
    <p>
      <label for="id_password">Password</label>
      <input type="password" name="password" id="id_password" autocomplete="current-password" required>
    </p>
    <input type="hidden" name="next" value="{{ next }}">
    <button type="submit">Log in</button>
  </form>
{% endblock %}
```

- [ ] **Step 11: Run the login tests and the kept frontend tests**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/accounts/test_login.py tests/acceptance tests/documents/test_api.py`
Expected: PASS (the 5 denied-page tests now run and pass; the vertical slice is xfail).

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q`
Expected: PASS, with 23 xfailed.

- [ ] **Step 12: Lint, types, checks**

Run: `uv run ruff check . && uv run mypy apps config && uv run python manage.py check`
Expected: no errors.

- [ ] **Step 13: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add -A templates apps/accounts apps/ratelimit.py apps/documents/api.py apps/tenancy/middleware.py config tests/accounts/test_login.py && git commit -m "feat(accounts): login, logout and the base page

LoginView at /accounts/login/ behind the JSON login's limiter (shared bucket),
one refusal sentence; Django's POST-only LogoutView, which keeps the extension
paired (owner, 2026-10-04); LOGIN_URL; / sends a student to the board; base.html, 403.html,
400.html. A deletion-locked student can still log out.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: `manage.py create_student`

**Files:**
- Create: `apps/accounts/management/__init__.py`, `apps/accounts/management/commands/__init__.py` (both empty), `apps/accounts/management/commands/create_student.py`, `tests/accounts/test_create_student.py`

**Interfaces:**
- Produces: `manage.py create_student --agency <uuid> --host <verified host> --username <name>`; password prompted twice via `getpass.getpass`.

- [ ] **Step 1: Write the failing test**

`tests/accounts/test_create_student.py`:

```python
import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from apps.accounts.models import StudentProfileVersion
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


@pytest.fixture
def typed(monkeypatch):
    answers: list[str] = []
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": answers.pop(0))
    return answers


def _run(agency, host, username="amina"):
    call_command("create_student", "--agency", str(agency.id), "--host", host, "--username", username)


def test_it_creates_a_user_and_one_student_membership_and_nothing_else(
    agency_a, domain_a, typed
) -> None:
    typed.extend(["correct-horse-battery", "correct-horse-battery"])
    _run(agency_a, domain_a.host)

    user = get_user_model().objects.get(username="amina")
    assert user.check_password("correct-horse-battery")
    with tenant_scope(agency_a.id):
        membership = Membership.objects.get(user=user)
        assert membership.role == Membership.Role.STUDENT
        assert not StudentProfileVersion.objects.filter(student=membership).exists()


def test_an_unverified_host_is_refused(agency_a, unverified_domain, typed) -> None:
    with pytest.raises(CommandError, match="not a verified domain"):
        _run(agency_a, unverified_domain.host)
    assert not get_user_model().objects.filter(username="amina").exists()


def test_another_agency_s_host_is_refused(agency_a, domain_b, typed) -> None:
    with pytest.raises(CommandError, match="not a verified domain"):
        _run(agency_a, domain_b.host)


def test_mismatched_passwords_create_nothing(agency_a, domain_a, typed) -> None:
    typed.extend(["correct-horse-battery", "different-horse-battery"])
    with pytest.raises(CommandError, match="do not match"):
        _run(agency_a, domain_a.host)
    assert not get_user_model().objects.filter(username="amina").exists()


def test_a_weak_password_is_refused(agency_a, domain_a, typed) -> None:
    typed.extend(["123", "123"])
    with pytest.raises(CommandError):
        _run(agency_a, domain_a.host)


def test_a_password_is_never_an_argument(agency_a, domain_a) -> None:
    with pytest.raises(CommandError):
        call_command(
            "create_student", "--agency", str(agency_a.id), "--host", domain_a.host,
            "--username", "amina", "--password", "x",
        )


def test_a_taken_username_is_refused(agency_a, domain_a, typed, user_a) -> None:
    with pytest.raises(CommandError, match="already taken"):
        _run(agency_a, domain_a.host, username=user_a.username)
```

- [ ] **Step 2: Run it to see it fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/accounts/test_create_student.py`
Expected: FAIL — `Unknown command: 'create_student'`.

- [ ] **Step 3: Write the command**

`apps/accounts/management/commands/create_student.py`:

```python
"""Create one student account for testing, until self-signup exists (spec §1).

    uv run python manage.py create_student --agency <uuid> --host a.example.test --username amina

The password is prompted twice and is never an argument: an argument lands in
shell history and the process list. Creates the User and one STUDENT
Membership and nothing else -- no profile, no pack, no mailbox.
"""

from __future__ import annotations

import getpass
from typing import Any
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Agency, Membership, TenantDomain


class Command(BaseCommand):
    help = "Create a test student: one User and one STUDENT Membership."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--agency", required=True, help="The agency's id (UUID).")
        parser.add_argument("--host", required=True, help="A verified domain of that agency.")
        parser.add_argument("--username", required=True)

    def handle(self, *args: object, **options: Any) -> None:
        try:
            agency = Agency.objects.get(id=UUID(str(options["agency"])))
        except (ValueError, Agency.DoesNotExist):
            raise CommandError("No agency with that id.") from None
        host = str(options["host"]).strip().lower()
        if not TenantDomain.objects.filter(
            agency=agency, host=host, verified_at__isnull=False
        ).exists():
            raise CommandError(f"{host} is not a verified domain of {agency.name}.")
        username = str(options["username"]).strip()
        user_model = get_user_model()
        if not username or user_model.objects.filter(username=username).exists():
            raise CommandError("That username is empty or already taken.")
        password = self._password(username)
        with transaction.atomic():
            user = user_model.objects.create_user(username=username, password=password)
            with tenant_scope(agency.id), tenant_transaction(agency.id):
                Membership.objects.create(tenant=agency, user=user, role=Membership.Role.STUDENT)
        self.stdout.write(f"Created {username}. Log in at https://{host}/accounts/login/")

    def _password(self, username: str) -> str:
        first = getpass.getpass("Password: ")
        if first != getpass.getpass("Password (again): "):
            raise CommandError("The passwords do not match.")
        try:
            validate_password(first, user=get_user_model()(username=username))
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from None
        return first
```

- [ ] **Step 4: Run it to see it pass**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/accounts/test_create_student.py && uv run ruff check . && uv run mypy apps config`
Expected: PASS, no lint or type errors.

- [ ] **Step 5: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add apps/accounts/management tests/accounts/test_create_student.py && git commit -m "feat(accounts): create_student operator command

Prompts the password twice, validates it, refuses an unverified or foreign
host, and creates one User plus one STUDENT Membership and nothing else.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: Static files under production settings

`CompressedManifestStaticFilesStorage` (production) serves only what `collectstatic` wrote and raises on any `{% static %}` absent from the manifest; test settings swap in `StaticFilesStorage`, so no test sees it, and nothing in the `Dockerfile` or CI runs `collectstatic` today. Three changes: the image runs it (without that, production serves no static file at all), CI runs it under production settings, and a test checks every `{% static %}` path against the finders — `collectstatic` itself never reads templates, so the test is what actually catches a missing reference. `static/` is created in Task 15 with the first real file; `STATICFILES_DIRS` pointing at a missing directory is a `W004` warning, not an error.

Production settings refuse to import without `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_ROLE` + its two credentials, `POSTGRES_DB`, `POSTGRES_HOST`, the six queue URLs and `CACHE_URL`. `collectstatic` opens no database, cache or queue, so placeholders are enough.

**Files:**
- Modify: `.github/workflows/ci.yml`, `Dockerfile`
- Create: `tests/test_static_references.py`

- [ ] **Step 1: Write the failing test**

`tests/test_static_references.py`:

```python
"""Every {% static %} path names a file collectstatic will collect.

Production's CompressedManifestStaticFilesStorage raises on a path missing from
the manifest; test settings use StaticFilesStorage, which never does. This is
the check that runs in the suite (CLAUDE.md, "Static files").
"""

import re
from pathlib import Path

from django.contrib.staticfiles import finders

_STATIC = re.compile(r"""{%\s*static\s+['"]([^'"]+)['"]\s*%}""")
ROOT = Path(__file__).resolve().parents[1]


def test_every_static_reference_names_a_file_collectstatic_will_find() -> None:
    templates = [*ROOT.glob("templates/**/*.html"), *ROOT.glob("apps/*/templates/**/*.html")]
    missing = sorted(
        {
            path
            for template in templates
            for path in _STATIC.findall(template.read_text(encoding="utf-8"))
            if finders.find(path) is None
        }
    )
    assert missing == []


def test_the_pattern_finds_a_reference() -> None:
    assert _STATIC.findall("{% static 'dashboard/documents.js' %}") == ["dashboard/documents.js"]
```

- [ ] **Step 2: Run it**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/test_static_references.py`
Expected: PASS (no references yet) — it starts guarding in Task 15. The second test pins that the pattern works, so the first cannot pass vacuously.

- [ ] **Step 3: CI step**

In `.github/workflows/ci.yml`, job `test`, after `- run: uv run python manage.py makemigrations --check --dry-run`:

```yaml
      # CompressedManifestStaticFilesStorage only exists under production
      # settings. collectstatic opens no database, cache or queue, so the
      # values below are placeholders that let production settings import.
      - name: collectstatic under production settings
        run: uv run python manage.py collectstatic --noinput
        env:
          DJANGO_SETTINGS_MODULE: config.settings.production
          DJANGO_SECRET_KEY: collectstatic-only
          DJANGO_ALLOWED_HOSTS: localhost
          DATABASE_ROLE: runtime_web
          POSTGRES_WEB_USER: collectstatic
          POSTGRES_WEB_PASSWORD: collectstatic
          POSTGRES_DB: tehsil
          POSTGRES_HOST: 127.0.0.1
          RESEARCH_QUEUE_URL: unused
          EUROPASS_QUEUE_URL: unused
          PORTAL_QUEUE_URL: unused
          DOCUMENT_QUEUE_URL: unused
          DOCUMENT_SCAN_QUEUE_URL: unused
          MAILBOX_QUEUE_URL: unused
          CACHE_URL: redis://127.0.0.1:6379/0
```

- [ ] **Step 4: The image collects its own static files**

In `Dockerfile`, stage `web`, immediately before `USER app`:

```dockerfile
# Production storage serves only what collectstatic wrote (CLAUDE.md, "Static
# files"). Production settings refuse to import without their environment, so
# the build passes placeholders: collectstatic opens no database, cache or queue.
RUN DJANGO_SECRET_KEY=collectstatic-only DJANGO_ALLOWED_HOSTS=localhost \
    DATABASE_ROLE=runtime_web POSTGRES_WEB_USER=collectstatic POSTGRES_WEB_PASSWORD=collectstatic \
    POSTGRES_DB=tehsil POSTGRES_HOST=localhost \
    RESEARCH_QUEUE_URL=unused EUROPASS_QUEUE_URL=unused PORTAL_QUEUE_URL=unused \
    DOCUMENT_QUEUE_URL=unused DOCUMENT_SCAN_QUEUE_URL=unused MAILBOX_QUEUE_URL=unused \
    CACHE_URL=redis://localhost:6379/0 \
    python manage.py collectstatic --noinput
```

- [ ] **Step 5: Run the CI step locally**

Run:
```bash
cd /home/orkhan/Desktop/student-dashboard && DJANGO_SETTINGS_MODULE=config.settings.production DJANGO_SECRET_KEY=collectstatic-only DJANGO_ALLOWED_HOSTS=localhost DATABASE_ROLE=runtime_web POSTGRES_WEB_USER=collectstatic POSTGRES_WEB_PASSWORD=collectstatic POSTGRES_DB=tehsil POSTGRES_HOST=127.0.0.1 RESEARCH_QUEUE_URL=unused EUROPASS_QUEUE_URL=unused PORTAL_QUEUE_URL=unused DOCUMENT_QUEUE_URL=unused DOCUMENT_SCAN_QUEUE_URL=unused MAILBOX_QUEUE_URL=unused CACHE_URL=redis://127.0.0.1:6379/0 uv run python manage.py collectstatic --noinput
```
Expected: `N static files copied to '.../staticfiles', M post-processed.` (`staticfiles/` is already in `.gitignore`). Then `docker build --target web -t tehsil-web:dashboard .` succeeds.

- [ ] **Step 6: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add .github/workflows/ci.yml Dockerfile tests/test_static_references.py && git commit -m "build(static): collectstatic under production settings in CI and the image

The web image now collects its static files (production storage serves nothing
else), CI runs collectstatic with production settings, and a test checks every
{% static %} path against the finders, which collectstatic itself never does.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: Data model — every new field, its migration, its erasure class, and the portal-less guards

All schema changes of the plan land here so later tasks are code only.

**`Application.portal_form` becomes nullable** (spec §7: a card without a known portal). The alternative — a placeholder `PortalForm` per unknown programme — would put a fake row in a platform-shared table, open a snapshot-learning door on a programme page, and make the extension treat a non-portal as a portal. Every code path that dereferences `application.portal_form` (`grep -rn "\.portal_form\b" apps`) and its guard:

| Path | Guard |
|---|---|
| `portals/packets.py::build_kit` | no form → no field map, `portal_host=""`, `form_url=""`, `not_fillable_reason="no_portal"` |
| `portals/packets.py::mint_packet` | `PacketRefused("no_portal")` before anything else |
| `portals/ext_api.py::_application_for` (packet, events, status, address, registration) | `portal_form__isnull=False` in the filter → 404 |
| `portals/ext_api.py::snapshot` | filters on `portal_form_id=<id>`, a NULL never matches — no change |
| `portals/tags.py::account_for`, `portal_address` | return `None` / `""` |
| `portals/escalation.py` (notification text, log line, `request_first_portal_review`) | `application.where`; review returns `None` with no portal |
| `portals/reminders.py` (4 sites) | `application.where` |
| `watch/watchdog.py` | `application.where` |
| `mailbox/sync.py:388`, `mailbox/filter.py:409` | query on `portal_form__portal_host`; a NULL row never matches or yields `None`, which `filter._key` already discards — no change |
| `portals/reporting.py` | `hosts.get(None)` is `None` and is skipped — no change |
| `portals/{services,resolve,auth,profiles,recovery,worker}.py` | the retiring server tier, reached only from the portal queue at `PortalDesiredCount: 0` and deleted by PR #169 — no change; an Application without a portal is never put on that queue |

**Files:**
- Modify: `apps/portals/models.py`, `apps/mailbox/models.py`, `apps/concierge/models.py`, `apps/funding/models.py`, `apps/audit/redaction.py`, `apps/portals/packets.py`, `apps/portals/ext_api.py`, `apps/portals/tags.py`, `apps/portals/escalation.py`, `apps/portals/reminders.py`, `apps/watch/watchdog.py`, `apps/documents/api.py`, `apps/documents/document_worker.py`
- Create (generated): `apps/portals/migrations/0022_dashboard_fields.py`, `apps/mailbox/migrations/0008_dashboard_fields.py`, `apps/concierge/migrations/0009_dashboard_fields.py`, `apps/funding/migrations/0057_dashboard_fields.py` (numbers are whatever `makemigrations` assigns on this branch)
- Create: `tests/portals/test_dashboard_fields.py`, `tests/audit/test_dashboard_redaction.py`
- Modify (tests): `tests/documents/test_document_worker.py`, `tests/documents/test_api.py`

**Interfaces (produced):**
- `Application.Outcome` (`ADMITTED`, `ADMITTED_CONDITIONAL`, `WAITLISTED`, `REJECTED`, `WITHDRAWN`), `Application.OutcomeSource` (`MAIL`, `PORTAL`, `PERSON`)
- `Application.portal_form: PortalForm | None`, `.candidate: RecommendationCandidate | None`, `.started_at`, `.decision_available_at`, `.outcome`, `.outcome_recorded_at`, `.outcome_source`, `.outcome_evidence: MailSignal | None`, `.name` (a card's own name when no candidate: an offer for another programme), properties `.where -> str` and `.title -> str`
- `DeviceAction.Kind.START_FILL`
- `MailSignal.document_name`, `.document_due`, `.interview_at`, `.decision_reading` (Jev's reading as JSON, Task 8), `.outcome`, `.outcome_conditions`, `.funding_outcome`, `.offered_programme`, `.offer_handled_at`
- `Notification.Action` (`OPEN_MESSAGE`, `OPEN_PORTAL`, `RECONNECT`), `Notification.application`, `Notification.action`
- `apps.concierge.models.UPLOAD_KINDS`, `DocumentVersion.expires_on`
- `RecommendationCandidate.institution_id`, `.institution_name`, `.country_code`, `.degree_level`, `.application_fee`, `.application_fee_currency`, `.funds_program_ids`, `.funding_card`

- [ ] **Step 1: Write the failing tests**

`tests/portals/test_dashboard_fields.py`:

```python
"""The fields the board reads, and every path a portal-less application reaches."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.concierge.models import RoadmapItem
from apps.portals import reminders, tags
from apps.portals.models import Application, DeviceAction
from apps.portals.packets import PacketRefused, build_kit, mint_packet
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_db_candidate, make_run

pytestmark = pytest.mark.django_db


def _portal_less(agency, student, **fields):
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), **fields
    )


def test_start_fill_is_a_device_action_kind() -> None:
    assert DeviceAction.Kind.START_FILL == "START_FILL"


def test_an_unknown_outcome_is_refused_by_the_database(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id), pytest.raises(IntegrityError), transaction.atomic():
        _portal_less(agency_a, membership_a, outcome="MAYBE")


def test_an_unknown_outcome_source_is_refused_by_the_database(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id), pytest.raises(IntegrityError), transaction.atomic():
        _portal_less(agency_a, membership_a, outcome_source="RUMOUR")


def test_one_application_per_candidate(agency_a, membership_a) -> None:
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run)
    with tenant_scope(agency_a.id):
        _portal_less(agency_a, membership_a, candidate=candidate)
        with pytest.raises(IntegrityError), transaction.atomic():
            _portal_less(agency_a, membership_a, candidate=candidate)


def test_a_portal_less_kit_degrades_and_says_why(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        kit = build_kit(_portal_less(agency_a, membership_a))
    assert kit.not_fillable_reason == "no_portal"
    assert kit.portal_host == ""
    assert kit.form_url == ""


def test_a_portal_less_application_mints_no_packet(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        application = _portal_less(agency_a, membership_a)
        with pytest.raises(PacketRefused) as refused:
            mint_packet(application)
    assert refused.value.reason == "no_portal"


def test_a_portal_less_application_has_no_portal_address(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        membership_a.application_email = "amina@example.test"
        membership_a.save(update_fields=["application_email"])
        application = _portal_less(agency_a, membership_a)
        assert tags.account_for(application) is None
        assert tags.portal_address(application) == ""


def test_a_reminder_for_a_portal_less_application_names_the_programme(
    agency_a, membership_a
) -> None:
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    with tenant_scope(agency_a.id):
        application = _portal_less(agency_a, membership_a, candidate=candidate)
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=membership_a,
            stage=RoadmapItem.Stage.SUBMISSION,
            owner=membership_a,
            deadline=timezone.now() + timedelta(days=3),
        )
        note = reminders.notify_student(application, item, timedelta(days=3))
    assert note.message.startswith("MSc Chemistry:")


def test_the_extension_cannot_reach_a_portal_less_application(
    client, agency_a, domain_a, membership_a
) -> None:
    from tests.portals.test_ext_api import _pair

    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        application = _portal_less(agency_a, membership_a)
    response = client.get(
        f"/ext/applications/{application.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 404
```

`tests/audit/test_dashboard_redaction.py`:

```python
"""Erasure reaches every field this plan adds (spec §4: REDACT for the outcome)."""

from datetime import date
from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from apps.audit.redaction import redact_student
from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant

pytestmark = pytest.mark.django_db


def test_erasure_empties_the_outcome_and_nulls_its_dates(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT",
            address="amina@outlook.test",
        )
        signal = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-1",
            sender_domain="tum.de", received_at=timezone.now(), label="DECISION",
            outcome="ADMITTED_CONDITIONAL", decision_reading={"is_decision": True, "p": {}},
            outcome_conditions=["final transcript"], funding_outcome="REJECTED",
            offered_programme="MSc Statistics", offer_handled_at=timezone.now(),
            document_name="Final transcript", document_due=date(2026, 12, 1),
            interview_at=timezone.now(),
        )
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), name="MSc Statistics",
            decision_available_at=timezone.now(), outcome="ADMITTED_CONDITIONAL",
            outcome_recorded_at=timezone.now(), outcome_source="MAIL",
            outcome_evidence=signal, started_at=timezone.now(),
        )
        document = register(agency_a.id, membership_a.id, kind="PASSPORT")
        DocumentVersion.objects.filter(id=document.id).update(expires_on=date(2030, 1, 1))

        with transaction.atomic():
            set_local_tenant(agency_a.id)
            redact_student(tenant_id=agency_a.id, student_id=membership_a.id)

        application.refresh_from_db()
        signal.refresh_from_db()
        document.refresh_from_db()

    assert (application.outcome, application.outcome_source) == ("", "")
    assert application.decision_available_at is None
    assert application.outcome_recorded_at is None
    assert application.started_at is not None
    assert (signal.outcome, signal.funding_outcome) == ("", "")
    assert signal.decision_reading == {}
    assert signal.outcome_conditions == {}
    assert signal.document_name == ""
    assert signal.document_due is None
    assert signal.interview_at is None
    assert signal.offered_programme == ""
    assert signal.offer_handled_at is not None
    assert application.name == "MSc Statistics"
    assert document.expires_on is None
```

Append to `tests/documents/test_document_worker.py`:

```python
def test_a_clean_passport_is_stored_and_never_read_as_a_cv(agency_a, membership_a, ingested):
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")

    document_worker.handle_scan_result(_event(document))

    document.refresh_from_db()
    assert document.state == "AVAILABLE"
    assert ingested == []
```

Append to `tests/documents/test_api.py`:

```python
def test_an_upload_may_be_any_document_the_table_lists(
    client, domain_a, user_a, membership_a, monkeypatch
):
    import apps.documents.api as api

    monkeypatch.setattr(
        api, "presigned_upload", lambda document: {"url": "https://s3.test/", "fields": {}}
    )
    client.force_login(user_a)
    for kind in ("PASSPORT", "DIPLOMA", "LANGUAGE_CERTIFICATE", "RECOMMENDATION", "OTHER"):
        response = _post(client, "/api/documents/uploads", {"kind": kind}, domain_a.host)
        assert response.status_code == 201, kind
    refused = _post(client, "/api/documents/uploads", {"kind": "SELFIE"}, domain_a.host)
    assert refused.status_code == 400
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/portals/test_dashboard_fields.py tests/audit/test_dashboard_redaction.py tests/documents/test_document_worker.py tests/documents/test_api.py`
Expected: FAIL — `TypeError: Application() got unexpected keyword arguments: 'outcome'` and friends; the passport is ingested; `PASSPORT` is `invalid_kind`.

- [ ] **Step 3: The models**

`apps/portals/models.py` — in `DeviceAction.Kind` add:

```python
        START_FILL = "START_FILL", "Open the portal and start filling"
```

In `Application`, after `class State(...)` add:

```python
    class Outcome(models.TextChoices):
        ADMITTED = "ADMITTED", "Admitted"
        ADMITTED_CONDITIONAL = "ADMITTED_CONDITIONAL", "Admitted with conditions"
        WAITLISTED = "WAITLISTED", "Waitlisted"
        REJECTED = "REJECTED", "Not admitted"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    class OutcomeSource(models.TextChoices):
        MAIL = "MAIL", "Email"
        PORTAL = "PORTAL", "Portal"
        PERSON = "PERSON", "Recorded by a person"
```

replace the `portal_form` line with:

```python
    #: NULL while nobody knows the programme's application portal (spec §7):
    #: the card offers "Open programme page" and a counsellor task asks for it.
    #: Every path that dereferences it is guarded (plan Task 4's table).
    portal_form = models.ForeignKey(PortalForm, null=True, blank=True, on_delete=models.PROTECT)
    #: The pack candidate this application was added from; the tenant copy the
    #: card reads its name, institution, fee and funding from. SET_NULL: the
    #: candidate is a recommendation, the application outlives it.
    candidate = models.ForeignKey(
        "funding.RecommendationCandidate",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
```

and after `kit_letter_cycle` add:

```python
    #: Start application was pressed (spec §7): the card leaves "To start".
    started_at = models.DateTimeField(null=True, blank=True)
    #: The card's own name when it has no candidate: a place offered for another
    #: programme, accepted from a decision letter (spec §4). A programme, not a person.
    name = models.CharField(max_length=300, blank=True)
    #: A trusted DECISION mail arrived (spec §4). Moves the card to Decision.
    decision_available_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=24, choices=Outcome.choices, blank=True)
    outcome_recorded_at = models.DateTimeField(null=True, blank=True)
    outcome_source = models.CharField(max_length=10, choices=OutcomeSource.choices, blank=True)
    #: The signal an automatic outcome came from -- never the letter's text.
    outcome_evidence = models.ForeignKey(
        "mailbox.MailSignal", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    @property
    def where(self) -> str:
        """Where this application happens, for a sentence: the portal's host, or
        the programme's name while no portal is known (spec §7)."""
        if self.portal_form_id is not None:
            assert self.portal_form is not None
            return self.portal_form.portal_host
        if self.candidate_id is not None:
            assert self.candidate is not None
            return self.candidate.program_name
        return self.name or "your application"

    @property
    def title(self) -> str:
        """What the card is headed with: the programme's or scholarship's name."""
        if self.candidate_id is not None:
            assert self.candidate is not None
            return self.candidate.program_name
        return self.where
```

and extend `Application.Meta.constraints`:

```python
            models.UniqueConstraint(
                fields=("student", "candidate"), name="portal_app_one_per_candidate"
            ),
            #: A person's correction reaches these columns (spec §4); an unknown
            #: value must be refused by the database, not only by the view.
            models.CheckConstraint(
                condition=models.Q(
                    outcome__in=(
                        "", "ADMITTED", "ADMITTED_CONDITIONAL", "WAITLISTED", "REJECTED",
                        "WITHDRAWN",
                    )
                ),
                name="portal_app_outcome_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(outcome_source__in=("", "MAIL", "PORTAL", "PERSON")),
                name="portal_app_outcome_source_valid",
            ),
```

`apps/mailbox/models.py`, in `MailSignal` after `classify_attempts`:

```python
    #: DOCUMENT_REQUEST on the content tier: the document's name as the mail
    #: words it (<= 120 characters) and its deadline. Never the mail's text.
    document_name = models.CharField(max_length=120, blank=True)
    document_due = models.DateField(null=True, blank=True)
    #: Jev's one reading of this mail (mailbox/decision_reader.py): the
    #: probabilities, whether it was a decision, whether Jev was unavailable.
    #: About the person's mail, so REDACT. {} for a mail never read.
    decision_reading = models.JSONField(default=dict, blank=True)
    #: What that reading says this card's outcome is (an Application.Outcome
    #: value or ""). Recorded on the Application only from trusted mail and
    #: measured bars (portals/outcome.py); otherwise shown for a person to confirm.
    outcome = models.CharField(max_length=24, blank=True)
    #: Code-verified quotes: the conditions of a conditional offer.
    outcome_conditions = models.JSONField(default=list, blank=True)
    #: The second decision in a two-decision letter (admitted, scholarship
    #: declined): the funding's, shown on the funding line of the card.
    funding_outcome = models.CharField(max_length=24, blank=True)
    #: DECISION: the other programme a letter offers a place on (spec §4,
    #: owner 2026-10-04), as the letter names it. Accept turns it into a card;
    #: Accept and Ignore both set offer_handled_at, which ends the Needs item.
    offered_programme = models.CharField(max_length=120, blank=True)
    offer_handled_at = models.DateTimeField(null=True, blank=True)
    #: INTERVIEW: when the interview is, if the mail states it (spec §8).
    interview_at = models.DateTimeField(null=True, blank=True)
```

`apps/concierge/models.py`, above `class DocumentVersion`:

```python
#: What a student may upload (spec §6). CV and TRANSCRIPT are read by the
#: document worker; every other kind is stored for the student to attach.
UPLOAD_KINDS = (
    ("CV", "CV"),
    ("TRANSCRIPT", "Transcript"),
    ("PASSPORT", "Passport"),
    ("DIPLOMA", "Diploma"),
    ("LANGUAGE_CERTIFICATE", "Language certificate"),
    ("RECOMMENDATION", "Recommendation letter"),
    ("OTHER", "Other document"),
)
```

in `DocumentVersion` replace the `kind` field's `choices=[("CV", "CV"), ("TRANSCRIPT", "Transcript")]` with `choices=UPLOAD_KINDS` and add after it:

```python
    #: Shown for a passport and a language certificate (spec §6). Typed by the
    #: student; nothing reads it out of the file.
    expires_on = models.DateField(null=True, blank=True)
```

in `Notification` add:

```python
    class Action(models.TextChoices):
        """The one button "Needs you now" shows for this notification (spec §3)."""

        OPEN_MESSAGE = "OPEN_MESSAGE", "Open message"
        OPEN_PORTAL = "OPEN_PORTAL", "Open portal"
        RECONNECT = "RECONNECT", "Reconnect"

    #: The application it is about, when it is about one. SET_NULL: removing a
    #: card must not take the student's notification history with it.
    application = models.ForeignKey(
        "portals.Application", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    action = models.CharField(max_length=20, choices=Action.choices, blank=True)
```

`apps/funding/models.py`, in `RecommendationCandidate` after `provenance_body_id`:

```python
    #: Tenant copies the dashboard renders (student-dashboard spec §4, §5),
    #: written by the worker in research.services._publish. Facts about the
    #: programme or the award, never the student.
    institution_id = models.UUIDField(null=True, blank=True)
    institution_name = models.CharField(max_length=300, blank=True)
    country_code = models.CharField(max_length=2, blank=True)
    #: A programme's Program.degree_level; "" for an award (its levels, when a
    #: reader ever supplies them, ride in funding_card["degree_levels"]).
    degree_level = models.CharField(max_length=20, blank=True)
    application_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    application_fee_currency = models.CharField(max_length=3, blank=True)
    #: An award's programmes (FundingOpportunity.programs + .program), so the
    #: pack can be grouped under the funding without the catalogue.
    funds_program_ids = ArrayField(models.UUIDField(), default=list, blank=True)
    #: An award's heading: holder, deadline, scope, route, tuition, living,
    #: amounts, unconfirmed. {} for a programme.
    funding_card = models.JSONField(default=dict, blank=True)
```

- [ ] **Step 4: Erasure classification**

`apps/audit/redaction.py` — in `REDACT` add:

```python
    # Whether and how a named institution decided about this person (spec §4):
    # the one fact this platform has no other record of, and about them.
    "portals.Application": RedactSpec(
        "student_id",
        ("decision_available_at", "outcome", "outcome_recorded_at", "outcome_source"),
    ),
```

extend the `mailbox.MailSignal` spec's fields to:

```python
        "connection__membership_id",
        (
            "provider_message_id", "sender_domain", "label", "document_name", "document_due",
            "interview_at", "decision_reading", "outcome", "outcome_conditions",
            "funding_outcome", "offered_programme",
        ),
```

extend `concierge.DocumentVersion` to `RedactSpec("student_id", ("object_key", "expires_on"))`.

In `KEEP`: add `"started_at", "name"` to `portals.Application` (`name` is a programme's name); add `"offer_handled_at"` to `mailbox.MailSignal` (when a button was pressed, an operational timestamp); add `"action"` to `concierge.Notification`; add `"institution_id", "institution_name", "country_code", "degree_level", "application_fee", "application_fee_currency", "funds_program_ids", "funding_card"` to `funding.RecommendationCandidate` with the comment `# the tenant copies: facts about the programme or award, not the person.`

`_empty_value`, replace its body with:

```python
    # cast: get_field also returns relations, which have no column to empty.
    # REDACT never names one -- classifiable_fields excludes relations and the
    # completeness test pins REDACT to those, so CI proves what this assumes.
    field = cast("Field[Any, Any]", model._meta.get_field(field_name))
    internal = field.get_internal_type()
    if internal == "JSONField":
        return {}
    if internal in ("CharField", "TextField"):
        return ""
    if internal == "TimeField":
        # Nullable by schema (quiet_hours_start/end): NULL already means
        # "no window set", so redacting to NULL does not collide with that
        # meaning the way it would for a NOT NULL column.
        return None
    if internal in ("DateField", "DateTimeField") and field.null:
        # Nullable by schema: NULL means "never happened", which is what an
        # erased person's decision and deadline dates must read as.
        return None
    raise RedactionIncomplete(
        f"no empty value defined for {model.__name__}.{field_name} ({internal})"
    )
```

- [ ] **Step 5: The portal-less guards**

`apps/portals/packets.py`:

```python
def _not_fillable_reason(form: PortalForm | None, field_map: FieldMap | None) -> str:
    if form is None:
        return "no_portal"
    if form.terms_posture == PortalForm.TermsPosture.PROHIBITS_AUTOMATION:
        return "automation_prohibited"
    if field_map is None:
        return "no_field_map"
    return ""
```

in `build_kit` replace `field_map = FieldMap.current_for(form, application.tenant_id)` with:

```python
    field_map = FieldMap.current_for(form, application.tenant_id) if form is not None else None
```

and in its `ApplicationKit(...)` call replace `portal_host=form.portal_host,` / `form_url=form.form_url,` with:

```python
        portal_host=form.portal_host if form is not None else "",
        form_url=form.form_url if form is not None else "",
```

in `mint_packet`, right after `form = application.portal_form`:

```python
    if form is None:
        raise PacketRefused("no_portal")
```

`apps/portals/ext_api.py::_application_for`:

```python
        Application.objects.filter(
            id=application_id, student=pairing.membership, portal_form__isnull=False
        )
```

and in `packet`'s `NoFieldMap` branch, `application.portal_form.form_url` stays (the filter guarantees a form) — add `assert application.portal_form is not None` above the `return JsonResponse(...)` for mypy.

`apps/portals/tags.py`:

```python
def account_for(application: Application) -> PortalAccount | None:
    """This student's account on this application's portal host, if issued."""
    if application.portal_form is None:
        return None
    return PortalAccount.objects.filter(
        student=application.student, portal_host=application.portal_form.portal_host
    ).first()
```

and in `portal_address`, replace `if not base:` / `return ""` with:

```python
    form = application.portal_form
    if not base or form is None:
        return ""
```

deleting the later `form = application.portal_form` line.

`apps/portals/escalation.py`: replace `{application.portal_form.portal_host}` in the escalation notification message and `application.portal_form.portal_host,` in its `logger.info` with `application.where`; at the top of `request_first_portal_review`:

```python
    portal_form = application.portal_form
    if portal_form is None or not portal_form.review_required:
        return None
```

and in `_request_first_portal_review` add `assert portal_form is not None` after `portal_form = application.portal_form`.

`apps/portals/reminders.py`: replace each `application.portal_form.portal_host` (in `notify_student`, `notify_counselor`, `email_student`'s `host = ...`, and the `ReminderSent` log line) with `application.where`.

`apps/watch/watchdog.py`: `host = application.where`.

`apps/documents/api.py::uploads` (add `from apps.concierge.models import UPLOAD_KINDS`):

```python
    kind = _json_body(request).get("kind", "CV")
    if not isinstance(kind, str) or kind not in {value for value, _label in UPLOAD_KINDS}:
        raise _ApiError(400, "invalid_kind")
```

`apps/documents/document_worker.py::handle_scan_result`, replace

```python
        if document.kind != "TRANSCRIPT":
            _ingest_cv(document, event.object_key)
            return
```

with

```python
        if document.kind == "CV":
            _ingest_cv(document, event.object_key)
            return
        if document.kind != "TRANSCRIPT":
            # A passport, diploma, certificate or letter is stored for the
            # student to attach (dashboard spec §6). Nothing reads its contents.
            return
```

- [ ] **Step 6: Generate the migrations**

Run: `cd /home/orkhan/Desktop/student-dashboard && uv run python manage.py makemigrations portals mailbox concierge funding --name dashboard_fields`
Expected: four migrations; the portals one depends on the mailbox and funding ones (string FKs, no import cycle). Then `uv run python manage.py makemigrations --check --dry-run` → `No changes detected`.

- [ ] **Step 7: Run the tests**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/portals tests/audit tests/documents tests/mailbox tests/watch`
Expected: PASS, including `tests/audit/test_redaction_classification.py` (every new column classified exactly once).

- [ ] **Step 8: Lint and types**

Run: `uv run ruff check . && uv run mypy apps config`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add -A apps tests && git commit -m "feat(models): the fields the student dashboard reads

Application: nullable portal (every dereference guarded), candidate, started_at,
its own name, decision_available_at and the outcome with its source and
evidence; START_FILL; MailSignal document, interview, outcome and
other-programme-offer readings; Notification application and action;
upload kinds beyond CV and transcript (stored, never read as a CV) with an
expiry date; RecommendationCandidate tenant copies. Erasure redacts the outcome,
the readings and the expiry; nullable dates redact to NULL.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: The worker writes the candidate tenant copies

`_publish` (`apps/research/services.py`) is the only writer of `RecommendationCandidate`s that came from the catalogue, and it runs in the worker, which may read the catalogue. It now copies what the board and the grouped pack show, so the web tier keeps reading tenant rows only. Candidates written before this change carry blanks and the pages degrade to "—".

**Files:**
- Modify: `apps/research/services.py`
- Create: `tests/research/test_candidate_copies.py`

**Interfaces:**
- Produces: `apps.research.services._program_copy(program: Program, application: PackedApplication) -> dict[str, object]`, `apps.research.services._award_copy(award: FundingOpportunity, packed: PackedAward) -> dict[str, object]`
- `funding_card` keys: `holder`, `deadline` (ISO date or `""`), `scope`, `route`, `tuition`, `living`, `amounts` (list of the page's own amount texts), `unconfirmed` (list), `degree_levels` (list; empty until a reader supplies it)

- [ ] **Step 1: Write the failing test**

`tests/research/test_candidate_copies.py`:

```python
import pytest

from apps.funding.models import RecommendationCandidate
from apps.tenancy.context import tenant_scope


@pytest.mark.django_db(transaction=True)
def test_the_worker_copies_what_the_board_shows_onto_each_candidate(slice_driver) -> None:
    run = slice_driver.student_submits_profile_and_starts_research()
    slice_driver.worker_processes(slice_driver.receive_message())

    with tenant_scope(run.tenant_id):
        programme = RecommendationCandidate.objects.get(run=run, program__isnull=False)
        award = RecommendationCandidate.objects.get(run=run, opportunity__isnull=False)

    assert programme.institution_name == "Example University"
    assert programme.country_code == "DE"
    assert programme.degree_level == "MASTER"
    assert programme.institution_id is not None
    assert programme.application_fee is not None
    assert programme.funding_card == {}
    assert award.funding_card["holder"] == "Example Foundation"
    assert award.funding_card["scope"] == "HOLDER"
    assert award.funds_program_ids == []
```

- [ ] **Step 2: Run it to see it fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/research/test_candidate_copies.py`
Expected: FAIL — `institution_name == ""`.

- [ ] **Step 3: Write the copies**

In `apps/research/services.py` add the imports `from apps.funding.pack import PackedApplication, PackedAward` (alongside the existing funding imports) and, above `_publish`:

```python
def _program_copy(program: Program, application: PackedApplication) -> dict[str, object]:
    """What the board and the pack show about a programme, copied so the web
    tier renders it without the catalogue (catalog-read-split)."""
    institution = program.institution
    return {
        "institution_id": program.institution_id,
        "institution_name": institution.name if institution is not None else "",
        "country_code": program.country_code,
        "degree_level": program.degree_level,
        "application_fee": application.application_fee,
        "application_fee_currency": application.application_fee_currency,
    }


def _award_copy(award: FundingOpportunity, packed: PackedAward) -> dict[str, object]:
    """An award's heading and the programmes it can pay for (dashboard spec §5)."""
    program_ids = list(award.programs.values_list("id", flat=True))
    if award.program_id is not None and award.program_id not in program_ids:
        program_ids.append(award.program_id)
    card = packed.card
    return {
        "institution_id": award.institution_id,
        "country_code": award.country_code or "",
        "funds_program_ids": program_ids,
        "funding_card": {
            "holder": packed.holder_name,
            "deadline": packed.deadline.isoformat() if packed.deadline else "",
            "scope": award.scope_type,
            "route": card.route if card is not None else award.route,
            "tuition": card.tuition if card is not None else "",
            "living": card.living if card is not None else "",
            "amounts": [line.amount_text for line in card.amounts] if card is not None else [],
            "unconfirmed": list(packed.unconfirmed),
            # No catalogue column says which degree levels an award covers yet;
            # grouping.funds() checks the level only when both sides carry one.
            "degree_levels": [],
        },
    }
```

(`Program` and `FundingOpportunity` are already imported in this module; if not, import them from `apps.funding.models`.) In `_publish`, add `**_program_copy(program, application),` as the last argument of the programme `RecommendationCandidate.objects.create(...)` and `**_award_copy(award, award_application),` as the last argument of the award one.

- [ ] **Step 4: Run it to see it pass, with the slice and the pack tests**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/research tests/acceptance tests/funding && uv run ruff check . && uv run mypy apps config`
Expected: PASS, no errors.

- [ ] **Step 5: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add apps/research/services.py tests/research/test_candidate_copies.py && git commit -m "feat(research): copy institution, fee and award heading onto each candidate

The worker writes what the board and the grouped pack show -- institution,
country, degree level, application fee, an award's heading and the programmes it funds -- so
the web tier still never reads the catalogue.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: The dashboard app, the `https_only` filter, and grouping under the funding

**Files:**
- Create: `apps/dashboard/__init__.py` (empty), `apps/dashboard/apps.py`, `apps/dashboard/templatetags/__init__.py` (empty), `apps/dashboard/templatetags/dashboard.py`, `apps/funding/grouping.py`, `tests/dashboard/__init__.py` (empty), `tests/dashboard/test_https_only.py`, `tests/funding/test_grouping.py`
- Modify: `config/settings/base.py` (`INSTALLED_APPS += ["apps.dashboard"]`)

**Interfaces:**
- Produces: `apps.dashboard.templatetags.dashboard.https_only(value: object) -> str` (template filter `{% load dashboard %}{{ url|https_only }}`, also imported by Python code)
- Produces: `apps.funding.grouping.funds(award: RecommendationCandidate, programme: RecommendationCandidate) -> bool`
- Produces: `apps.funding.grouping.group_under_funding(candidates: Sequence[RecommendationCandidate], *, extra: Sequence[RecommendationCandidate] = (), extra_label: str = "") -> list[FundingGroup]`; `FundingGroup(award: RecommendationCandidate | None, programmes: tuple[Placed, ...], label: str)`; `Placed(candidate: RecommendationCandidate, also_under: tuple[str, ...], elsewhere: str = "")`; `group_label(award: RecommendationCandidate | None) -> str`
- Open awards (owner, 2026-10-04): a HOLDER or COUNTRY award funds every programme in its `country_code` (and degree level, where both sides carry one) and is headed "Eligible programmes in <country>"; a GLOBAL award funds every programme. `extra` lets the pack's open awards list the pool's programmes too, and the pool's list the pack's, marked by `extra_label`.

- [ ] **Step 1: Write the failing tests**

`tests/dashboard/test_https_only.py`:

```python
import pytest

from apps.dashboard.templatetags.dashboard import https_only


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        " JAVASCRIPT:alert(1)",
        "http://www.tum.de/apply",
        "https://evil.example\\@tum.de/",
        "https://user:secret@tum.de/apply",
        "data:text/html,<script>alert(1)</script>",
        "tum.de/apply",
        "",
        None,
    ],
)
def test_https_only_refuses_everything_but_https(url) -> None:
    assert https_only(url) == ""


def test_https_only_keeps_a_plain_https_link() -> None:
    assert https_only("https://www.tum.de/en/apply?x=1") == "https://www.tum.de/en/apply?x=1"
```

`tests/funding/test_grouping.py`:

```python
from uuid import uuid4

from apps.funding.grouping import funds, group_under_funding
from apps.funding.models import RecommendationCandidate


def _programme(name: str, **fields) -> RecommendationCandidate:
    return RecommendationCandidate(program_name=name, program_id=uuid4(), **fields)


def _award(
    name: str, scope: str = "PROGRAM", deadline: str = "", levels: tuple[str, ...] = (), **fields
) -> RecommendationCandidate:
    return RecommendationCandidate(
        program_name=name,
        opportunity_id=uuid4(),
        funding_card={"scope": scope, "deadline": deadline, "degree_levels": list(levels)},
        **fields,
    )


def test_an_award_funds_the_programmes_it_lists() -> None:
    tum = _programme("TUM M.Sc.")
    daad = _award("DAAD", funds_program_ids=[tum.program_id])
    assert funds(daad, tum)
    assert not funds(daad, _programme("KTH M.Sc."))


def test_institution_country_global_and_holder_scopes() -> None:
    institution = uuid4()
    tum = _programme(
        "TUM M.Sc.", institution_id=institution, country_code="DE", degree_level="MASTER"
    )
    kth = _programme("KTH M.Sc.", institution_id=uuid4(), country_code="SE", degree_level="MASTER")
    assert funds(_award("TUM Excellence", scope="INSTITUTION", institution_id=institution), tum)
    assert not funds(_award("TUM Excellence", scope="INSTITUTION", institution_id=institution), kth)
    assert funds(_award("Germany grant", scope="COUNTRY", country_code="DE"), tum)
    assert not funds(_award("Germany grant", scope="COUNTRY", country_code="DE"), kth)
    assert funds(_award("Anywhere", scope="GLOBAL"), kth)
    # Owner, 2026-10-04: an open HOLDER award funds what the student could
    # apply to in its country; with no country it names nothing to match on.
    assert funds(_award("DAAD", scope="HOLDER", country_code="DE"), tum)
    assert not funds(_award("DAAD", scope="HOLDER", country_code="DE"), kth)
    assert not funds(_award("Own application", scope="HOLDER"), kth)


def test_the_degree_level_is_checked_only_where_both_sides_carry_one() -> None:
    tum = _programme("TUM M.Sc.", country_code="DE", degree_level="MASTER")
    unknown = _programme("TUM named", country_code="DE")
    doctoral = _award("Doctoral grant", scope="COUNTRY", country_code="DE", levels=("PHD",))
    assert not funds(doctoral, tum)
    assert funds(doctoral, unknown)
    assert funds(_award("Any level", scope="COUNTRY", country_code="DE"), tum)


def test_an_open_award_lists_every_eligible_programme_from_both_lists() -> None:
    tum = _programme("TUM M.Sc.", country_code="DE")
    lmu = _programme("LMU M.Sc.", country_code="DE")
    kth = _programme("KTH M.Sc.", country_code="SE")
    daad = _award("DAAD", scope="HOLDER", country_code="DE")

    groups = group_under_funding([tum, kth, daad], extra=[lmu], extra_label="in Other options")

    assert groups[0].label == "Eligible programmes in DE"
    assert [(p.candidate.program_name, p.elsewhere) for p in groups[0].programmes] == [
        ("TUM M.Sc.", ""),
        ("LMU M.Sc.", "in Other options"),
    ]
    assert groups[-1].label == "Programmes without separate funding"
    assert [p.candidate.program_name for p in groups[-1].programmes] == ["KTH M.Sc."]


def test_a_programme_under_two_awards_says_so_under_each() -> None:
    tum = _programme("TUM M.Sc.")
    daad = _award("DAAD", funds_program_ids=[tum.program_id], deadline="2026-11-01")
    erasmus = _award("Erasmus", funds_program_ids=[tum.program_id], deadline="2026-12-01")

    groups = group_under_funding([tum, erasmus, daad])

    assert [g.award.program_name if g.award else None for g in groups] == ["DAAD", "Erasmus", None]
    assert groups[0].programmes[0].also_under == ("Erasmus",)
    assert groups[1].programmes[0].also_under == ("DAAD",)
    assert groups[2].programmes == ()


def test_unfunded_programmes_close_the_list_and_undated_awards_come_last() -> None:
    kth = _programme("KTH M.Sc.")
    undated = _award("Undated", scope="HOLDER")
    dated = _award("Dated", scope="HOLDER", deadline="2026-10-30")

    groups = group_under_funding([kth, undated, dated])

    assert [g.award.program_name if g.award else None for g in groups] == ["Dated", "Undated", None]
    assert [p.candidate.program_name for p in groups[-1].programmes] == ["KTH M.Sc."]
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/dashboard/test_https_only.py tests/funding/test_grouping.py`
Expected: FAIL — `ModuleNotFoundError: apps.dashboard` / `apps.funding.grouping`.

- [ ] **Step 3: The app and the filter**

`apps/dashboard/apps.py`:

```python
from django.apps import AppConfig


class DashboardConfig(AppConfig):
    """The student dashboard's logic: board, needs, the counsellor's view.

    No models. It exists apart from apps/portals because the board names the
    submitted state, which tests/portals/test_boundary.py keeps out of that app.
    """

    name = "apps.dashboard"
```

`apps/dashboard/templatetags/dashboard.py`:

```python
"""`https_only`: the one gate between third-party URLs and an href.

Django escapes a URL as text, which keeps it from breaking out of the
attribute but not from being `javascript:` -- that scheme survives autoescaping
inside href (apps/funding/requirements.py says so of RequirementItem.source_url).
Every template that renders a URL it did not build passes it through here.
"""

from urllib.parse import urlsplit

from django import template
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

register = template.Library()
_validate = URLValidator(schemes=["https"])


@register.filter
def https_only(value: object) -> str:
    """The URL if it is a plain https link, else "".

    No userinfo and no backslash: a browser and Python's urlsplit disagree about
    both (apps/mailbox/actions.py::_verification_url measured it), so a URL
    carrying either is refused rather than parsed.
    """
    url = str(value or "").strip()
    if not url or "\\" in url or len(url) > 2048:
        return ""
    try:
        _validate(url)
        parts = urlsplit(url)
    except (ValidationError, ValueError):
        return ""
    if parts.username or parts.password:
        return ""
    return url
```

`config/settings/base.py`: append `"apps.dashboard",` to `INSTALLED_APPS` after `"apps.watch"`.

- [ ] **Step 4: Grouping**

`apps/funding/grouping.py`:

```python
"""The pack grouped under the funding (dashboard spec §5).

Pure: candidates in, groups out. Reads only the tenant copies the worker wrote
(funds_program_ids, funding_card, institution_id, country_code, degree_level),
so the page that calls it reads no catalogue table.

Open awards (owner, 2026-10-04): a HOLDER or COUNTRY award names no programme,
so it heads every programme the student has in its country (and degree level,
where both sides carry one) -- "Eligible programmes in <country>". A GLOBAL award
heads every programme.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .models import RecommendationCandidate


@dataclass(frozen=True)
class Placed:
    candidate: RecommendationCandidate
    #: The other awards this programme also appears under ("also under ...").
    also_under: tuple[str, ...]
    #: "" for a programme of this list; the other list's name ("in Other
    #: options", "in your pack") for one an open award pulled in from it.
    elsewhere: str = ""


@dataclass(frozen=True)
class FundingGroup:
    #: None for the last group, "Programmes without separate funding".
    award: RecommendationCandidate | None
    programmes: tuple[Placed, ...]
    #: The heading over the programmes (group_label).
    label: str


def _scope(award: RecommendationCandidate) -> str:
    return str((award.funding_card or {}).get("scope", ""))


def _levels_agree(award: RecommendationCandidate, programme: RecommendationCandidate) -> bool:
    levels = (award.funding_card or {}).get("degree_levels") or []
    return not levels or not programme.degree_level or programme.degree_level in levels


def funds(award: RecommendationCandidate, programme: RecommendationCandidate) -> bool:
    """Whether this award can pay for this programme, by the award's own scope."""
    if programme.program_id is not None and programme.program_id in award.funds_program_ids:
        return True
    scope = _scope(award)
    if scope == "INSTITUTION":
        return award.institution_id is not None and award.institution_id == programme.institution_id
    if scope in ("HOLDER", "COUNTRY"):
        return (
            bool(award.country_code)
            and award.country_code == programme.country_code
            and _levels_agree(award, programme)
        )
    if scope == "GLOBAL":
        return _levels_agree(award, programme)
    return False


def group_label(award: RecommendationCandidate | None) -> str:
    if award is None:
        return "Programmes without separate funding"
    scope = _scope(award)
    if scope in ("HOLDER", "COUNTRY") and award.country_code:
        return f"Eligible programmes in {award.country_code}"
    if scope == "GLOBAL":
        return "Eligible programmes"
    return "Programmes it can pay for"


def _award_order(award: RecommendationCandidate) -> tuple[str, str]:
    return ((award.funding_card or {}).get("deadline") or "9999-12-31", award.program_name)


def group_under_funding(
    candidates: Sequence[RecommendationCandidate],
    *,
    extra: Sequence[RecommendationCandidate] = (),
    extra_label: str = "",
) -> list[FundingGroup]:
    """One group per award, programmes beneath; unfunded programmes last.

    ``extra`` is the student's other list (the pool for the pack, the pack for
    the pool). Its programmes appear under every award here that funds them,
    marked ``extra_label``, and never in this list's unfunded group: they have
    their own list.
    """
    awards = sorted((c for c in candidates if c.opportunity_id is not None), key=_award_order)

    def _programmes(rows: Sequence[RecommendationCandidate]) -> list[RecommendationCandidate]:
        return sorted((c for c in rows if c.opportunity_id is None), key=lambda c: c.program_name)

    programmes, others = _programmes(candidates), _programmes(extra)
    under = {p.id: [a for a in awards if funds(a, p)] for p in (*programmes, *others)}

    def _placed(p: RecommendationCandidate, award: RecommendationCandidate, where: str) -> Placed:
        return Placed(p, tuple(o.program_name for o in under[p.id] if o.id != award.id), where)

    groups = [
        FundingGroup(
            award=award,
            programmes=tuple(
                [_placed(p, award, "") for p in programmes if award in under[p.id]]
                + [_placed(p, award, extra_label) for p in others if award in under[p.id]]
            ),
            label=group_label(award),
        )
        for award in awards
    ]
    groups.append(
        FundingGroup(
            award=None,
            programmes=tuple(Placed(p, ()) for p in programmes if not under[p.id]),
            label=group_label(None),
        )
    )
    return groups
```

- [ ] **Step 5: Run them to see them pass**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/dashboard tests/funding/test_grouping.py && uv run ruff check . && uv run mypy apps config && uv run python manage.py check`
Expected: PASS, no errors.

- [ ] **Step 6: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add apps/dashboard apps/funding/grouping.py config/settings/base.py tests/dashboard tests/funding/test_grouping.py && git commit -m "feat(dashboard): https_only filter and grouping under the funding

A dashboard app (no models) with the one filter every third-party URL passes
through before an href, and the pure grouping of the pack under each award by
its own scope -- open HOLDER, COUNTRY and GLOBAL awards head every eligible
programme from either list (owner, 2026-10-04) -- with 'also under' and a
closing unfunded group.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 7: The documents-by-application table

**Files:**
- Create: `apps/documents/table.py`, `tests/documents/test_table.py`

**Interfaces:**
- Produces: `class Cell(StrEnum)`: `NOT_NEEDED`, `MISSING`, `UPLOADED`, `APPROVED`, `CERTIFIED`
- Produces: `kinds_named(text: str) -> set[str]`
- Produces: `ApplicationNeeds(application_id: UUID, title: str, sentences: tuple[str, ...], unnamed_request: bool = False)`, `Held(kind: str, state: Cell, expires_on: date | None = None, application_id: UUID | None = None, document_id: UUID | None = None, source: str = "upload")`
- Produces: `build_table(columns: Sequence[ApplicationNeeds], held: Iterable[Held]) -> Table`; `Table.columns`, `Table.rows: tuple[Row, ...]`, `Table.missing_for(application_id) -> tuple[str, ...]`, `Table.counts_for(application_id) -> tuple[int, int]`, `Table.held_for(kind, application_id) -> Held | None`
- Produces: `table_for(student: Membership, applications: Sequence[Application], signals: Iterable[MailSignal]) -> Table` (queries tenant tables only)

- [ ] **Step 1: Write the failing tests**

`tests/documents/test_table.py`:

```python
from datetime import date
from uuid import uuid4

from apps.documents.table import ApplicationNeeds, Cell, Held, build_table, kinds_named


def _column(*sentences: str, unnamed: bool = False) -> ApplicationNeeds:
    return ApplicationNeeds(uuid4(), "TUM M.Sc.", tuple(sentences), unnamed)


def _row(table, kind):
    return next(row for row in table.rows if row.kind == kind)


def test_kinds_are_read_from_the_programme_s_own_sentences() -> None:
    assert kinds_named("Upload your Bachelor's diploma and transcript of records.") == {
        "DIPLOMA",
        "TRANSCRIPT",
    }
    assert kinds_named("IELTS 6.5 or TOEFL iBT 90 is required.") == {"LANGUAGE_CERTIFICATE"}
    assert kinds_named("A CV in English (max. 2 pages).") == {"CV"}
    assert kinds_named("A statement of purpose.") == {"MOTIVATION_LETTER"}
    assert kinds_named("Applications open in October.") == set()


def test_a_certified_copy_is_its_own_state_even_when_one_is_uploaded() -> None:
    column = _column("A certified copy of your diploma.")
    table = build_table([column], [Held("DIPLOMA", Cell.UPLOADED)])
    assert _row(table, "DIPLOMA").cells == (Cell.CERTIFIED,)


def test_one_upload_satisfies_every_application_that_needs_it() -> None:
    tum, kth = _column("Passport copy"), _column("A copy of your passport")
    table = build_table([tum, kth], [Held("PASSPORT", Cell.UPLOADED, expires_on=date(2030, 1, 1))])
    assert _row(table, "PASSPORT").cells == (Cell.UPLOADED, Cell.UPLOADED)
    assert _row(table, "PASSPORT").expires_on == date(2030, 1, 1)


def test_a_letter_belongs_to_one_application() -> None:
    tum, kth = _column("Motivation letter"), _column("Motivation letter")
    letter = Held("MOTIVATION_LETTER", Cell.APPROVED, application_id=tum.application_id)
    table = build_table([tum, kth], [letter])
    assert _row(table, "MOTIVATION_LETTER").cells == (Cell.APPROVED, Cell.MISSING)


def test_what_nobody_asked_for_is_not_needed() -> None:
    table = build_table([_column("Transcript")], [])
    assert _row(table, "PASSPORT").cells == (Cell.NOT_NEEDED,)
    assert _row(table, "TRANSCRIPT").cells == (Cell.MISSING,)


def test_counts_and_missing_labels_for_one_application() -> None:
    column = _column("Transcript", "CV", "Passport")
    table = build_table([column], [Held("CV", Cell.APPROVED)])
    assert table.counts_for(column.application_id) == (1, 3)
    assert table.missing_for(column.application_id) == ("Passport", "Transcript")
    assert table.held_for("CV", column.application_id) is not None
    assert table.held_for("PASSPORT", column.application_id) is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/documents/test_table.py`
Expected: FAIL — `ModuleNotFoundError: apps.documents.table`.

- [ ] **Step 3: Write the table**

`apps/documents/table.py`:

```python
"""Which document each application needs, and where the student stands (spec §6).

`build_table` is pure: rows in, a table out. `table_for` is the one function
that queries, and it reads tenant tables only -- the requirements are the copy
capture_requirements stored on the Application, never ProgramStatement.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from apps.mailbox.models import MailSignal
    from apps.portals.models import Application
    from apps.tenancy.models import Membership


class Cell(StrEnum):
    NOT_NEEDED = "not needed"
    MISSING = "missing"
    UPLOADED = "uploaded"
    APPROVED = "approved"
    CERTIFIED = "certified copy needed"


#: Rows in reading order: (kind, label). Kinds are concierge.UPLOAD_KINDS or,
#: for the generated documents, DocumentDraft.Kind.
ROWS: tuple[tuple[str, str], ...] = (
    ("PASSPORT", "Passport"),
    ("TRANSCRIPT", "Transcript"),
    ("DIPLOMA", "Diploma"),
    ("LANGUAGE_CERTIFICATE", "Language certificate"),
    ("CV", "CV"),
    ("MOTIVATION_LETTER", "Motivation letter"),
    ("RECOMMENDATION", "Recommendation letters"),
)
EXPIRING = frozenset({"PASSPORT", "LANGUAGE_CERTIFICATE"})
_HELD = frozenset({Cell.UPLOADED, Cell.APPROVED})
_WANTING = frozenset({Cell.MISSING, Cell.CERTIFIED})

# ponytail: keyword match over the programme's REQUIRED sentences and the mail's
# document name. It misses a requirement worded unlike these, and a sentence
# naming two documents marks both. Upgrade path: have the statement reader label
# the document kind a sentence names.
_WORDS: dict[str, re.Pattern[str]] = {
    "PASSPORT": re.compile(r"\bpassport", re.I),
    "TRANSCRIPT": re.compile(r"\btranscript|\brecord of (?:study|studies|grades)", re.I),
    "DIPLOMA": re.compile(r"\bdiploma|\bdegree certificate|\bbachelor'?s certificate", re.I),
    "LANGUAGE_CERTIFICATE": re.compile(
        r"\bielts\b|\btoefl\b|\blanguage (?:certificate|proficiency|test)|\bcefr\b", re.I
    ),
    "CV": re.compile(r"\bcv\b|\bcurriculum vitae\b|\br[ée]sum[ée]\b", re.I),
    "MOTIVATION_LETTER": re.compile(
        r"\bmotivation\b|\bstatement of purpose\b|\bpersonal statement\b|\bcover letter\b"
        r"|\bletter of intent\b",
        re.I,
    ),
    "RECOMMENDATION": re.compile(r"\brecommendation\b|\breference letter|\breferee", re.I),
}
_CERTIFIED = re.compile(r"\bcertified\b|\bnotari[sz]ed\b|\bapostille\b|\battested\b", re.I)


def kinds_named(text: str) -> set[str]:
    return {kind for kind, pattern in _WORDS.items() if pattern.search(text)}


@dataclass(frozen=True)
class ApplicationNeeds:
    application_id: UUID
    title: str
    #: What to send, in the sources' own words: kit requirements, mail requests.
    sentences: tuple[str, ...]
    #: A message for this application nothing could read (metadata tier).
    unnamed_request: bool = False


@dataclass(frozen=True)
class Held:
    kind: str
    state: Cell
    expires_on: date | None = None
    #: Set for a document that belongs to one application (a letter, a CV
    #: tailored to its programme); None for one every application may use.
    application_id: UUID | None = None
    document_id: UUID | None = None
    #: "upload" (DocumentVersion) or "draft" (DocumentDraft): what Submit sends.
    source: str = "upload"


@dataclass(frozen=True)
class Row:
    kind: str
    label: str
    cells: tuple[Cell, ...]
    expires_on: date | None


@dataclass(frozen=True)
class Table:
    columns: tuple[ApplicationNeeds, ...]
    rows: tuple[Row, ...]
    held: tuple[Held, ...]

    def _index(self, application_id: UUID) -> int:
        return next(i for i, c in enumerate(self.columns) if c.application_id == application_id)

    def missing_for(self, application_id: UUID) -> tuple[str, ...]:
        index = self._index(application_id)
        return tuple(sorted(row.label for row in self.rows if row.cells[index] in _WANTING))

    def counts_for(self, application_id: UUID) -> tuple[int, int]:
        """(held, needed) for one application: "Documents 4/6" on the card."""
        index = self._index(application_id)
        cells = [row.cells[index] for row in self.rows if row.cells[index] != Cell.NOT_NEEDED]
        return sum(1 for cell in cells if cell in _HELD), len(cells)

    def held_for(self, kind: str, application_id: UUID) -> Held | None:
        """The document Submit would send for this kind to this application."""
        own = next(
            (h for h in self.held if h.kind == kind and h.application_id == application_id), None
        )
        return own or next(
            (h for h in self.held if h.kind == kind and h.application_id is None), None
        )


def _needed(column: ApplicationNeeds) -> dict[str, bool]:
    """kind -> whether a certified copy is asked for, for every kind named."""
    out: dict[str, bool] = {}
    for sentence in column.sentences:
        certified = bool(_CERTIFIED.search(sentence))
        for kind in kinds_named(sentence):
            out[kind] = out.get(kind, False) or certified
    return out


def build_table(columns: Sequence[ApplicationNeeds], held: Iterable[Held]) -> Table:
    held_rows = tuple(held)
    table = Table(tuple(columns), (), held_rows)
    wanted = [_needed(column) for column in columns]
    rows = []
    for kind, label in ROWS:
        cells = []
        for column, needs in zip(columns, wanted, strict=True):
            if kind not in needs:
                cells.append(Cell.NOT_NEEDED)
            elif needs[kind]:
                cells.append(Cell.CERTIFIED)
            else:
                mine = table.held_for(kind, column.application_id)
                cells.append(mine.state if mine is not None else Cell.MISSING)
        general = next((h for h in held_rows if h.kind == kind and h.application_id is None), None)
        expires = general.expires_on if general is not None and kind in EXPIRING else None
        rows.append(Row(kind, label, tuple(cells), expires))
    return Table(tuple(columns), tuple(rows), held_rows)


def table_for(
    student: Membership, applications: Sequence[Application], signals: Iterable[MailSignal]
) -> Table:
    """The table from this student's own rows. Web-tier safe: tenant tables only."""
    from apps.concierge.models import DocumentVersion
    from apps.documents.models import DocumentDraft

    requests: dict[UUID, list[str]] = {}
    unnamed: set[UUID] = set()
    for signal in signals:
        if signal.application_id is None:
            continue
        if signal.label == "DOCUMENT_REQUEST" and signal.document_name:
            requests.setdefault(signal.application_id, []).append(signal.document_name)
        elif signal.label == "":
            unnamed.add(signal.application_id)
    columns = [
        ApplicationNeeds(
            application_id=application.id,
            title=application.title,
            sentences=(
                *(str(text) for text in application.kit_requirements if isinstance(text, str)),
                *requests.get(application.id, []),
            ),
            unnamed_request=application.id in unnamed,
        )
        for application in applications
    ]
    by_programme = {application.program_id: application.id for application in applications}
    held: list[Held] = []
    for draft in DocumentDraft.objects.filter(
        student=student,
        status=DocumentDraft.Status.APPROVED,
        kind__in=(DocumentDraft.Kind.CV, DocumentDraft.Kind.MOTIVATION_LETTER),
    ).order_by("-version"):
        application_id = by_programme.get(draft.programme_id) if draft.programme_id else None
        if draft.kind == DocumentDraft.Kind.MOTIVATION_LETTER and application_id is None:
            continue
        held.append(
            Held(draft.kind, Cell.APPROVED, application_id=application_id,
                 document_id=draft.id, source="draft")
        )
    for upload in DocumentVersion.objects.filter(student=student, state="AVAILABLE").order_by(
        "-created_at"
    ):
        held.append(
            Held(upload.kind, Cell.UPLOADED, expires_on=upload.expires_on,
                 document_id=upload.id, source="upload")
        )
    return build_table(columns, held)
```

- [ ] **Step 4: Run them to see them pass**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/documents/test_table.py && uv run ruff check . && uv run mypy apps config`
Expected: PASS, no errors.

- [ ] **Step 5: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add apps/documents/table.py tests/documents/test_table.py && git commit -m "feat(documents): the documents-by-application table

Pure build_table over the kit's requirement copy and mail document requests:
not needed, missing, uploaded, approved, certified copy needed; one upload
reused everywhere, letters per application, expiry for passport and language
certificate. table_for reads tenant tables only.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 8: Decisions from mail — one Jev reading that abstains, the correction service, and the eval harness

Spec §4, §6, §8, owner decisions of 2026-10-04: student mail may go to TypeSafe's Jev through OpenRouter (`docs/legal/2026-09-provider-terms.md`, with the identifier stripping below as the mitigation), and **one** reading must be enough. It is designed to the measured practices of the engine-eval work rather than doubled:

- **Jev decides, the OpenAI classifier extracts.** The existing classifier call keeps the label (the card text) and the free text only Jev cannot produce (rule 9: Jev generates no text): `document_name`, `document_due`, `interview_at`, `outcome_conditions`, `offered_programme`. Each quoted string is kept only when code finds it in the email (rule 14, `decision_reader.verified`). The classifier no longer reads an outcome.
- **One request of atomic questions** (rules 1, 5, 6, 8, 10) against a state with descriptive keys (rules 2–4): `{"email": {"from_domain", "subject"?, "body"}, "application": {"programme", "university", "funding"?}}`. `is_decision` (Noul, with true/false criteria naming acknowledgement, release-date notice, document request, interview invitation, stage result as false); `outcome` (Choice: `ADMITTED`, `ADMITTED_CONDITIONAL`, `WAITLISTED`, `REJECTED`, `NOT_STATED`, a literal definition per option); one gate Noul per outcome option (v5 measured per-option gates raising precision); the same Choice + gates for the funding when the card has one (`AWARDED`, `WAITLISTED`, `NOT_AWARDED`, `NOT_STATED`); `other_programme` (Noul). Forward option order only (no material order bias was measured); one wording ships (averaging wordings added nothing over the best single one); English questions over the original-language email (translation arms gained nothing).
- **Recording rule.** `is_decision` ≥ its bar, AND the outcome Choice's top option has its gate Noul ≥ that gate's bar → that outcome; anything else abstains. A decision is *available* only when `is_decision` cleared its bar. Bars live in `apps/mailbox/decision_bars.py` with the measurement date; until `manage.py decision_eval` has learned them (Learn-then-Test, `engine_eval.score.ltt_bar`, δ = 1/500 for anything that can make a wrong ADMITTED or REJECTED, 1/100 otherwise), every bar is the conservative 0.95 **and no outcome is recorded automatically**: the card reads "Decision available — the email reads: Admitted. Confirm it below." and the person confirms.
- **Jev unavailable** (`DecisionsUnavailable`, `DecisionBudgetExhausted`, `StateTooLarge`, our rate limit) → the reading is `UNAVAILABLE`: nothing moves, and a card with a `DECISION`-labelled mail reads "Decision available — confirm". Never a fallback to an unmeasured reader for the outcome.
- **Identifiers never reach Jev.** Before the call, code replaces the student's name words (`apps/documents/transcript.py::personal_names`: account name and CV identity facts), every email address (theirs and any other) and every phone number with placeholders; `record=False`, so no student text lands in the shared `DecisionRecord`.
- **Untrusted mail** is read too, so the item can say what it claims; nothing it reads is ever recorded (`record_from_mail` runs only behind the trust gate).

**Precondition (Step 0).** `apps/research/engine_eval/` and `research.GoldItem` exist on `origin/master` (PR #171) and not on this branch, which is stacked on #168/#170. Merge `origin/master` into `claude/student-dashboard` first; it also brings f7 (#172), whose acceptance lock the Task 12 lock test then exercises instead of skipping.

**Files:**
- Create: `apps/mailbox/decision_questions.py`, `apps/mailbox/decision_bars.py`, `apps/mailbox/decision_reader.py`, `apps/portals/outcome.py`, `apps/mailbox/management/commands/decision_eval.py`, `tests/mailbox/test_decision_reader.py`, `tests/mailbox/test_decision_board.py`, `tests/mailbox/decision_corpus.json`, `tests/mailbox/test_decision_eval.py`
- Modify: `apps/mailbox/classify.py`, `apps/mailbox/actions.py`, `apps/mailbox/sync.py`, `apps/research/models.py` (`GoldItem.Kind.DECISION_MAIL`), `tests/mailbox/test_classify.py`
- Create (generated): `apps/research/migrations/00NN_gold_item_decision_mail.py`

**Interfaces:**
- Produces: `decision_questions.DECISION = "mail_decision"`, `OUTCOMES`, `FUNDING_OUTCOMES`, `FUNDING_TO_OUTCOME`, `DELTAS: dict[str, float]`, `GATED: tuple[str, ...]`, `questions(wording: str = "a", *, funding: bool) -> dict[str, Question]`
- Produces: `decision_bars.MEASURED_ON: str`, `DEFAULT_BAR = 0.95`, `BARS: dict[str, float | None]`, `bar(question_id: str) -> float`, `measured() -> bool`
- Produces: `decision_reader.DecisionReading(is_decision: bool | None, outcome: str, funding_outcome: str, other_programme_offered: bool | None, p: Mapping[str, float], measured: bool, unavailable: bool)` with `.as_json()`; `UNAVAILABLE`; `strip_identifiers(text: str, *, names: frozenset[str], addresses: Iterable[str] = ()) -> str`; `verified(phrase: str, body: str) -> bool`; `keep_verified(verdict: MailVerdict, body: str) -> MailVerdict`; `reading_from_answers(answers: Mapping[str, Answer], *, funding: bool) -> DecisionReading`; `read_decision(email_text: str, sender_domain: str, programme: str, university: str, funding_name: str, *, student_id: UUID, subject: str = "", names: frozenset[str] = frozenset(), addresses: Iterable[str] = (), client: Client | None = None, wording: str = "a") -> DecisionReading`; `MailContext`; `mail_context(signal: MailSignal) -> MailContext | None`
- Produces: `apps.portals.outcome.is_funding_application(application) -> bool`, `record_from_mail(application: Application, signal: MailSignal, reading: DecisionReading) -> list[str]`, `correct_outcome(application: Application, outcome: str, *, actor: Membership) -> None`
- Produces: `apply_verdict(signal, verdict, *, reading: DecisionReading | None = None, link_hosts, authenticated, vouched=False, shared_portal=None)`
- Produces: `MailVerdict.document_name (≤120)`, `.document_due`, `.interview_at` (pattern-constrained ISO 8601 or ""), `.outcome_conditions (≤6 × ≤80)`, `.offered_programme (≤120)`; `MAX_OUTPUT_TOKENS = 600`
- Produces: `GoldItem.Kind.DECISION_MAIL = "decision_mail"`; `manage.py decision_eval {seed,read,score} --run <name> [--wording a|b] [--max-usd N] [--trust-corpus]`

- [ ] **Step 0: Bring `origin/master` in**

```bash
cd /home/orkhan/Desktop/student-dashboard && git fetch origin && git merge origin/master
```

Resolve conflicts keeping both sides (expect `apps/tenancy/middleware.py`, Open point 6). Then: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q` → PASS, and `uv run python -c "import apps.research.engine_eval.score"` succeeds.

- [ ] **Step 1: Write the failing reader tests**

`tests/mailbox/test_decision_reader.py`:

```python
"""One Jev reading that abstains (dashboard spec §4). A fake client stands in for
the decision layer's transport; ask() itself, the question shapes and the state
are real."""

from uuid import uuid4

import pytest
from django.core.cache import cache

from apps.mailbox import decision_bars
from apps.mailbox.classify import MailVerdict
from apps.mailbox.decision_reader import (
    UNAVAILABLE,
    keep_verified,
    read_decision,
    strip_identifiers,
)
from apps.research.decisions import Answer, Choice, DecisionsUnavailable

LETTER = (
    "Dear Amina Yusuf (amina.yusuf@gmail.com, +994 50 123 45 67),\n\n"
    "We are pleased to inform you that you have been admitted to the Master's programme "
    "Informatics at the Technical University of Munich for the winter semester 2027/28."
)


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


class FakeJev:
    """Answers every question asked; records the state it was sent."""

    def __init__(self, nouls: dict[str, float], choices: dict[str, str]) -> None:
        self.nouls, self.choices, self.states = nouls, choices, []

    def __call__(self, state, questions, *, model, provider):
        self.states.append(state)
        answers = {}
        for qid, question in questions.items():
            if isinstance(question, Choice):
                top = self.choices.get(qid, question.options[-1])
                answers[qid] = Answer(
                    id=qid, value=top, confidence=0.9,
                    probabilities={o: (0.9 if o == top else 0.1 / (len(question.options) - 1))
                                   for o in question.options},
                    model=model, provider=provider,
                )
            else:
                p = self.nouls.get(qid, 0.01)
                answers[qid] = Answer(
                    id=qid, value=p >= 0.5, confidence=max(p, 1 - p),
                    probabilities={"true": p, "false": 1 - p}, model=model, provider=provider,
                )
        return answers


def _read(fake, *, funding="", **kwargs):
    return read_decision(
        LETTER, "tum.de", "M.Sc. Informatics", "TUM", funding,
        student_id=uuid4(), names=frozenset({"amina", "yusuf"}),
        addresses=("amina.yusuf@gmail.com",), client=fake, **kwargs,
    )


@pytest.fixture
def measured(monkeypatch):
    monkeypatch.setattr(decision_bars, "MEASURED_ON", "2026-10-20")
    monkeypatch.setattr(decision_bars, "BARS", {})  # every bar at the 0.95 default


def test_no_name_address_or_phone_reaches_the_request() -> None:
    fake = FakeJev({"is_decision": 0.99, "gate:ADMITTED": 0.99}, {"outcome": "ADMITTED"})
    _read(fake)
    payload = repr(fake.states)
    for identifier in ("Amina", "Yusuf", "amina.yusuf@gmail.com", "123 45 67"):
        assert identifier not in payload
    assert "[name]" in payload and "[email]" in payload and "[phone]" in payload


def test_the_state_has_descriptive_keys_and_one_request_asks_everything() -> None:
    fake = FakeJev({}, {})
    _read(fake, funding="TUM Excellence Scholarship")
    (state,) = fake.states
    assert set(state) == {"email", "application"}
    assert state["email"]["from_domain"] == "tum.de"
    assert state["application"] == {
        "programme": "M.Sc. Informatics", "university": "TUM",
        "funding": "TUM Excellence Scholarship",
    }


def test_a_cleared_gate_that_agrees_with_the_choice_reads_the_outcome(measured) -> None:
    reading = _read(FakeJev({"is_decision": 0.99, "gate:ADMITTED": 0.97}, {"outcome": "ADMITTED"}))
    assert (reading.is_decision, reading.outcome, reading.measured) == (True, "ADMITTED", True)


@pytest.mark.parametrize(
    ("nouls", "choice"),
    [
        ({"is_decision": 0.99, "gate:ADMITTED": 0.80}, "ADMITTED"),   # gate under its bar
        ({"is_decision": 0.99, "gate:REJECTED": 0.99}, "ADMITTED"),   # gate for another option
        ({"is_decision": 0.99}, "NOT_STATED"),                        # nothing stated
        ({"is_decision": 0.70, "gate:ADMITTED": 0.99}, "ADMITTED"),   # not surely a decision
    ],
)
def test_anything_short_of_the_rule_abstains(measured, nouls, choice) -> None:
    reading = _read(FakeJev(nouls, {"outcome": choice}))
    assert reading.outcome == ""


def test_an_uncertain_decision_question_abstains_on_availability_too() -> None:
    reading = _read(FakeJev({"is_decision": 0.70}, {}))
    assert reading.is_decision is None


def test_the_funding_is_asked_only_when_the_card_has_one(measured) -> None:
    fake = FakeJev(
        {"is_decision": 0.99, "fgate:NOT_AWARDED": 0.99, "gate:ADMITTED": 0.99},
        {"outcome": "ADMITTED", "funding": "NOT_AWARDED"},
    )
    assert _read(fake, funding="TUM Excellence").funding_outcome == "REJECTED"
    assert _read(fake).funding_outcome == ""


def test_an_offer_of_another_programme_is_its_own_question(measured) -> None:
    reading = _read(FakeJev({"is_decision": 0.99, "other_programme": 0.98}, {}))
    assert reading.other_programme_offered is True


def test_jev_unavailable_is_an_abstention_never_a_fallback() -> None:
    def down(*_args, **_kwargs):
        raise DecisionsUnavailable("transport", kind="failed")

    assert _read(down) is UNAVAILABLE


def test_quotes_the_classifier_returns_are_kept_only_when_they_are_in_the_email() -> None:
    verdict = MailVerdict(
        label="DECISION", offered_programme="MSc Statistics",
        outcome_conditions=("final transcript", "a signed contract"),
    )
    kept = keep_verified(verdict, "We offer you MSc  Statistics, subject to your Final Transcript.")
    assert kept.offered_programme == "MSc Statistics"
    assert kept.outcome_conditions == ("final transcript",)


def test_a_date_is_not_mistaken_for_a_phone_number() -> None:
    assert strip_identifiers("Due 2027-06-15.", names=frozenset()) == "Due 2027-06-15."
```

- [ ] **Step 2: Write the failing board-effect tests**

`tests/mailbox/test_decision_board.py`:

```python
"""What a classified and Jev-read mail does to the board (spec §4, §6, §8)."""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from apps.mailbox.actions import apply_verdict
from apps.mailbox.classify import MailVerdict
from apps.mailbox.decision_reader import UNAVAILABLE, DecisionReading
from apps.portals.outcome import correct_outcome
from apps.tenancy.db import tenant_transaction

LINKS = frozenset({"tum.de"})


def _reading(**fields) -> DecisionReading:
    base = dict(is_decision=True, outcome="", funding_outcome="", other_programme_offered=False,
                p={}, measured=True, unavailable=False)
    return DecisionReading(**{**base, **fields})


def _apply(signal, *, trusted=True, reading=None, **verdict):
    with tenant_transaction(signal.tenant_id):
        apply_verdict(
            signal, MailVerdict(**verdict), reading=reading, link_hosts=LINKS,
            authenticated=trusted,
        )
    signal.refresh_from_db()
    signal.application.refresh_from_db()
    return signal.application


@pytest.mark.django_db
def test_a_cleared_decision_without_an_outcome_marks_it_available(signal_on_application) -> None:
    application = _apply(signal_on_application("tum.de"), label="DECISION", reading=_reading())
    assert application.decision_available_at is not None
    assert application.outcome == ""


@pytest.mark.django_db
def test_a_cleared_outcome_is_recorded_from_trusted_mail(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    application = _apply(signal, label="DECISION", reading=_reading(outcome="ADMITTED"))
    assert (application.outcome, application.outcome_source) == ("ADMITTED", "MAIL")
    assert application.outcome_evidence_id == signal.id
    assert signal.decision_reading["is_decision"] is True


@pytest.mark.django_db
def test_before_the_bars_are_learned_the_outcome_waits_for_a_person(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    application = _apply(
        signal, label="DECISION", reading=_reading(outcome="ADMITTED", measured=False)
    )
    assert application.decision_available_at is not None
    assert application.outcome == ""
    assert signal.outcome == "ADMITTED"  # what the card asks the person to confirm


@pytest.mark.django_db
def test_an_untrusted_decision_moves_no_card(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    application = _apply(
        signal, trusted=False, label="DECISION", reading=_reading(outcome="ADMITTED")
    )
    assert application.decision_available_at is None
    assert application.outcome == ""
    assert signal.outcome == "ADMITTED"  # the reading, a suggestion only


@pytest.mark.django_db
def test_an_abstaining_reading_moves_nothing(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    application = _apply(signal, label="DECISION", reading=_reading(is_decision=None))
    assert application.decision_available_at is None
    unavailable = signal_on_application("tum.de")
    _apply(unavailable, label="DECISION", reading=UNAVAILABLE)
    assert unavailable.decision_reading["unavailable"] is True


@pytest.mark.django_db
def test_a_person_recorded_outcome_survives_a_later_trusted_mail(
    signal_on_application, membership_a
) -> None:
    signal = signal_on_application("tum.de")
    with tenant_transaction(signal.tenant_id):
        correct_outcome(signal.application, "WAITLISTED", actor=membership_a)
    application = _apply(signal, label="DECISION", reading=_reading(outcome="REJECTED"))
    assert (application.outcome, application.outcome_source) == ("WAITLISTED", "PERSON")


@pytest.mark.django_db
def test_the_funding_half_of_a_letter_stays_on_the_signal(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    application = _apply(
        signal, label="DECISION", reading=_reading(outcome="ADMITTED", funding_outcome="REJECTED")
    )
    assert application.outcome == "ADMITTED"
    assert signal.funding_outcome == "REJECTED"


@pytest.mark.django_db
def test_an_offer_needs_jev_and_a_name_found_in_the_email(signal_on_application) -> None:
    signal = signal_on_application("lu.se")
    application = _apply(
        signal, label="DECISION", offered_programme="MSc Statistics",
        reading=_reading(outcome="REJECTED", other_programme_offered=True),
    )
    assert signal.offered_programme == "MSc Statistics"
    assert signal.offer_handled_at is None
    assert application.outcome == "REJECTED"
    no_offer = signal_on_application("lu.se")
    _apply(no_offer, label="DECISION", offered_programme="MSc Statistics",
           reading=_reading(other_programme_offered=None))
    assert no_offer.offered_programme == ""


@pytest.mark.django_db
def test_conditions_are_kept_only_for_a_conditional_admission(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    _apply(signal, label="DECISION", outcome_conditions=("final transcript",),
           reading=_reading(outcome="ADMITTED_CONDITIONAL"))
    assert signal.outcome_conditions == ["final transcript"]


@pytest.mark.django_db
def test_a_document_request_keeps_the_name_and_the_due_date(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    _apply(signal, label="DOCUMENT_REQUEST",
           document_name="Certified copy of your degree certificate", document_due="2027-06-15")
    assert signal.document_name == "Certified copy of your degree certificate"
    assert signal.document_due == date(2027, 6, 15)


@pytest.mark.django_db
def test_an_unreadable_due_date_is_dropped_not_guessed(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    _apply(signal, label="DOCUMENT_REQUEST", document_name="Transcript", document_due="15/06/2027")
    assert signal.document_due is None


@pytest.mark.django_db
def test_an_interview_keeps_its_time_and_its_item_carries_it(signal_on_application) -> None:
    from apps.concierge.models import Notification

    signal = signal_on_application("ethz.ch")
    _apply(signal, label="INTERVIEW", interview_at="2027-03-12T10:00+01:00")
    assert signal.interview_at == datetime(2027, 3, 12, 9, 0, tzinfo=UTC)
    note = Notification.objects.get(roadmap_item__student=signal.application.student)
    assert note.roadmap_item.deadline == signal.interview_at
    assert "12 Mar 2027, 09:00 UTC" in note.message


def test_the_schema_refuses_what_it_cannot_carry() -> None:
    with pytest.raises(ValidationError):
        MailVerdict(label="DOCUMENT_REQUEST", document_name="x" * 121)
    with pytest.raises(ValidationError):
        MailVerdict(label="INTERVIEW", interview_at="next Tuesday at ten")
    with pytest.raises(ValidationError):
        MailVerdict(label="DECISION", outcome="ADMITTED")  # the classifier reads no outcome
```

Append to `tests/mailbox/test_classify.py`:

```python
def test_the_prompt_asks_for_quotes_and_dates_and_the_cap_still_holds() -> None:
    fake = FakeOpenAI(_verdict())
    classify_message(body="x", sender_domain="tum.de", student_id=STUDENT, client=fake)
    call = fake.responses.calls[0]
    developer = call["input"][0]["content"]
    assert "will be released" in developer
    assert "offered_programme" in developer
    assert "interview_at" in developer
    assert "outcome_scope" not in developer
    assert call["max_output_tokens"] == 600
```

- [ ] **Step 3: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/mailbox/test_decision_reader.py tests/mailbox/test_decision_board.py tests/mailbox/test_classify.py`
Expected: FAIL — `ModuleNotFoundError: apps.mailbox.decision_reader`; `apply_verdict()` has no `reading`.

- [ ] **Step 4: The questions and the bars**

`apps/mailbox/decision_questions.py`:

```python
"""The mail decision questions (dashboard spec §4), in one place.

Written to docs/superpowers/research/2026-09-23-jev-question-engineering.md:
atomic questions (rule 1) pointing at the state by name (rule 2), options as
criteria keys with literal descriptions (rules 5, 8), a gate Noul per outcome
option (v5 measured per-option gates raising precision), everything in one
request (rule 10), forward order only (no material order bias measured), English
questions over the original-language email (translation arms gained nothing).
Wording "a" ships; "b" is Gate 12's alternative, kept so `decision_eval` can
compare them. Never change a wording without re-running it.
"""

from __future__ import annotations

from apps.research.decisions import Choice, Noul, Question

DECISION = "mail_decision"
OUTCOMES = ("ADMITTED", "ADMITTED_CONDITIONAL", "WAITLISTED", "REJECTED", "NOT_STATED")
FUNDING_OUTCOMES = ("AWARDED", "WAITLISTED", "NOT_AWARDED", "NOT_STATED")
#: A funding answer in Application.Outcome's vocabulary.
FUNDING_TO_OUTCOME = {"AWARDED": "ADMITTED", "WAITLISTED": "WAITLISTED", "NOT_AWARDED": "REJECTED"}

#: Learn-then-Test delta per barred question: anything that can put a wrong
#: ADMITTED or REJECTED in front of a family is the strictest (1/500, 1,497 clean
#: rows by zero_error_rows_needed); the rest 1/100 (299 rows).
STRICT, ORDINARY = 0.002, 0.01
DELTAS: dict[str, float] = {
    "is_decision": STRICT,
    "gate:ADMITTED": STRICT,
    "gate:REJECTED": STRICT,
    "gate:ADMITTED_CONDITIONAL": ORDINARY,
    "gate:WAITLISTED": ORDINARY,
    "fgate:AWARDED": STRICT,
    "fgate:NOT_AWARDED": STRICT,
    "fgate:WAITLISTED": ORDINARY,
    "other_programme": ORDINARY,
}
GATED = tuple(DELTAS)
_EMAIL = "`email`"

#: question id -> (wording a, wording b)
_NOULS: dict[str, tuple[str, str]] = {
    "is_decision": (
        "Does `email` give the final result of the application to `application.programme`?",
        "Is `email` the institution's decision on the application to `application.programme`?",
    ),
    "gate:ADMITTED": (
        "Does `email` say the applicant is admitted to `application.programme` without conditions?",
        "Is the applicant given an unconditional place on `application.programme` in `email`?",
    ),
    "gate:ADMITTED_CONDITIONAL": (
        "Does `email` offer a place on `application.programme` that depends on a condition the "
        "applicant must still meet?",
        "Is the place on `application.programme` in `email` conditional?",
    ),
    "gate:WAITLISTED": (
        "Does `email` say the applicant is on a waiting, reserve, ranking or pending list for "
        "`application.programme`?",
        "Is the applicant waitlisted for `application.programme` in `email`?",
    ),
    "gate:REJECTED": (
        "Does `email` say the applicant is not offered a place on `application.programme`?",
        "Is the application to `application.programme` refused in `email`?",
    ),
    "fgate:AWARDED": (
        "Does `email` say `application.funding` is awarded to the applicant?",
        "Is the applicant granted `application.funding` in `email`?",
    ),
    "fgate:WAITLISTED": (
        "Does `email` say the applicant is on a reserve or waiting list for `application.funding`?",
        "Is the applicant waitlisted for `application.funding` in `email`?",
    ),
    "fgate:NOT_AWARDED": (
        "Does `email` say `application.funding` is not awarded to the applicant?",
        "Is `application.funding` refused to the applicant in `email`?",
    ),
    "other_programme": (
        "Does `email` offer a place on a programme other than `application.programme`?",
        "Is the applicant offered a different programme than `application.programme` in `email`?",
    ),
}
_IS_DECISION_CRITERIA = {
    "true": "the email states the admission result, or says the result has been made and can "
            "be read in the applicant's portal",
    "false": "an acknowledgement of receipt, a notice of when results will be released, a "
             "document request, an interview invitation, a stage result such as passing "
             "pre-selection, a reminder, a deferral",
}
_OUTCOME_CRITERIA = {
    "ADMITTED": "the email says the applicant is offered or given a place on "
                "`application.programme`, with nothing left to meet",
    "ADMITTED_CONDITIONAL": "the email offers a place on `application.programme` that depends on "
                            "something still to be done or shown, such as a final transcript, a "
                            "grade or a language certificate",
    "WAITLISTED": "the email says there is no place on `application.programme` now and the "
                  "applicant is on a waiting, reserve, ranking or pending list",
    "REJECTED": "the email says the applicant is not offered a place on `application.programme`",
    "NOT_STATED": "the email does not state the result for `application.programme`: it says a "
                  "decision is available elsewhere, or it is about something else",
}
_FUNDING_CRITERIA = {
    "AWARDED": "the email says `application.funding` is awarded or granted to the applicant",
    "WAITLISTED": "the email says the applicant is on a reserve or waiting list for "
                  "`application.funding`",
    "NOT_AWARDED": "the email says `application.funding` is not awarded to the applicant",
    "NOT_STATED": "the email does not give the result for `application.funding`",
}
_CHOICES = {
    "outcome": ("Which result does `email` give for `application.programme`?",
                "What does `email` decide about `application.programme`?"),
    "funding": ("Which result does `email` give for `application.funding`?",
                "What does `email` decide about `application.funding`?"),
}


def questions(wording: str = "a", *, funding: bool) -> dict[str, Question]:
    """Every question, in one map: one request (rule 10)."""
    pick = 0 if wording == "a" else 1
    out: dict[str, Question] = {
        "is_decision": Noul(_NOULS["is_decision"][pick], criteria=_IS_DECISION_CRITERIA,
                            inspect=_EMAIL),
        "outcome": Choice(_CHOICES["outcome"][pick], options=OUTCOMES,
                          criteria=_OUTCOME_CRITERIA, inspect=_EMAIL),
        "other_programme": Noul(_NOULS["other_programme"][pick], inspect=_EMAIL),
    }
    for qid, texts in _NOULS.items():
        if qid.startswith("gate:") or (funding and qid.startswith("fgate:")):
            out[qid] = Noul(texts[pick], inspect=_EMAIL)
    if funding:
        out["funding"] = Choice(_CHOICES["funding"][pick], options=FUNDING_OUTCOMES,
                                criteria=_FUNDING_CRITERIA, inspect=_EMAIL)
    return out
```

`apps/mailbox/decision_bars.py`:

```python
"""The bar each mail decision question must clear, and when they were learned.

Written by hand from `manage.py decision_eval score`'s report (it prints this
dict). Until MEASURED_ON is set every bar is DEFAULT_BAR and no outcome is
recorded automatically: the card shows the reading and asks a person.
A bar of None means Learn-then-Test passed no bar: that question never acts.
"""

DEFAULT_BAR = 0.95
#: The date of the decision_eval run these bars came from, "" until one has.
MEASURED_ON = ""
BARS: dict[str, float | None] = {}


def bar(question_id: str) -> float:
    value = BARS.get(question_id, DEFAULT_BAR)
    return 1.01 if value is None else value


def measured() -> bool:
    return bool(MEASURED_ON)
```

- [ ] **Step 5: The reader**

`apps/mailbox/decision_reader.py`:

```python
"""One Jev reading of a mail about an application, that abstains (spec §4).

TypeSafe's Jev through OpenRouter (apps.research.decisions.ask, decision
"mail_decision"), owner decision 2026-10-04 (docs/legal/2026-09-provider-terms.md).
The mitigation is in this module: the student's name words, every email address
and every phone number are replaced before the state is built, and ask() runs
with record=False so no student text reaches the shared DecisionRecord.
Jev generates no text; the classifier's quotes are kept only when code finds
them in the email (rule 14).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from apps.documents.transcript import _fold, personal_names
from apps.mailbox import decision_bars as bars
from apps.mailbox.classify import MailVerdict
from apps.mailbox.providers import MAX_BODY_CHARS
from apps.ratelimit import rate_limited
from apps.research.decisions import (
    Answer,
    Client,
    DecisionBudgetExhausted,
    DecisionsUnavailable,
    StateTooLarge,
    ask,
)

from .decision_questions import DECISION, FUNDING_TO_OUTCOME, questions

if TYPE_CHECKING:
    from apps.mailbox.models import MailSignal

logger = logging.getLogger(__name__)

#: Forty an hour per student, the classifier's own ceiling: one reading per message.
READ_LIMIT = 40
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_RE = re.compile(r"(?<![\w-])\+?\d[\d\s().-]{6,}\d(?![\w-])")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


@dataclass(frozen=True)
class DecisionReading:
    is_decision: bool | None
    outcome: str
    funding_outcome: str
    other_programme_offered: bool | None
    p: Mapping[str, float] = field(default_factory=dict)
    #: The bars were learned; only then is an outcome recorded automatically.
    measured: bool = False
    unavailable: bool = False

    def as_json(self) -> dict[str, Any]:
        return {**asdict(self), "p": dict(self.p)}


UNAVAILABLE = DecisionReading(None, "", "", None, unavailable=True)


def strip_identifiers(text: str, *, names: frozenset[str], addresses: Iterable[str] = ()) -> str:
    """The student's name words, every email address and every phone number, replaced.

    A run of nine or more digits is a phone number; an ISO date (eight digits) is not.
    """
    for address in addresses:
        if address:
            text = re.sub(re.escape(address), "[email]", text, flags=re.IGNORECASE)
    text = _EMAIL_RE.sub("[email]", text)
    text = _PHONE_RE.sub(
        lambda m: "[phone]" if sum(c.isdigit() for c in m.group()) >= 9 else m.group(), text
    )
    return re.sub(r"\w+", lambda m: "[name]" if _fold(m.group()) in names else m.group(), text)


def _norm(text: str) -> str:
    return " ".join(text.translate(_QUOTES).split()).casefold()


def verified(phrase: str, body: str) -> bool:
    """Rule 14: a quote is checked by code, never by a model."""
    return bool(phrase.strip()) and _norm(phrase) in _norm(body)


def keep_verified(verdict: MailVerdict, body: str) -> MailVerdict:
    return verdict.model_copy(update={
        "document_name": verdict.document_name if verified(verdict.document_name, body) else "",
        "offered_programme": (
            verdict.offered_programme if verified(verdict.offered_programme, body) else ""
        ),
        "outcome_conditions": tuple(c for c in verdict.outcome_conditions if verified(c, body)),
    })


def _p_yes(answer: Answer) -> float:
    return float(answer.probabilities.get("true", 0.0))


def _decide(answers: Mapping[str, Answer], qid: str) -> bool | None:
    if qid not in answers:
        return None
    p, cut = _p_yes(answers[qid]), bars.bar(qid)
    if p >= cut:
        return True
    return False if p <= 1 - cut else None


def _gated(answers: Mapping[str, Answer], choice: str, prefix: str) -> str:
    """The Choice's top option, only when that option's own gate cleared its bar."""
    answer = answers.get(choice)
    if answer is None:
        return ""
    gate = answers.get(f"{prefix}{answer.value}")
    if gate is None or _p_yes(gate) < bars.bar(f"{prefix}{answer.value}"):
        return ""
    return str(answer.value)


def reading_from_answers(answers: Mapping[str, Answer], *, funding: bool) -> DecisionReading:
    is_decision = _decide(answers, "is_decision")
    outcome = _gated(answers, "outcome", "gate:") if is_decision else ""
    funding_top = _gated(answers, "funding", "fgate:") if is_decision and funding else ""
    return DecisionReading(
        is_decision=is_decision,
        outcome=outcome,
        funding_outcome=FUNDING_TO_OUTCOME.get(funding_top, ""),
        other_programme_offered=_decide(answers, "other_programme"),
        p={qid: (_p_yes(a) if "true" in a.probabilities else float(a.confidence))
           for qid, a in answers.items()},
        measured=bars.measured(),
    )


def read_decision(
    email_text: str,
    sender_domain: str,
    programme: str,
    university: str,
    funding_name: str,
    *,
    student_id: UUID,
    subject: str = "",
    names: frozenset[str] = frozenset(),
    addresses: Iterable[str] = (),
    client: Client | None = None,
    wording: str = "a",
) -> DecisionReading:
    """One request; any failure is an abstention, never another reader."""
    if rate_limited("mailbox-decision", student_id, limit=READ_LIMIT, window_seconds=3600):
        return UNAVAILABLE
    listed = tuple(addresses)
    email: dict[str, str] = {
        "from_domain": sender_domain,
        "body": strip_identifiers(email_text[:MAX_BODY_CHARS], names=names, addresses=listed),
    }
    if subject:
        email["subject"] = strip_identifiers(subject, names=names, addresses=listed)
    application = {"programme": programme, "university": university}
    if funding_name:
        application["funding"] = funding_name
    try:
        answers = ask(
            {"email": email, "application": application},
            questions(wording, funding=bool(funding_name)),
            decision=DECISION,
            record=False,
            client=client,
        )
    except (DecisionsUnavailable, DecisionBudgetExhausted, StateTooLarge) as error:
        logger.info("mail decision abstained: %s", type(error).__name__)
        return UNAVAILABLE
    return reading_from_answers(answers, funding=bool(funding_name))


@dataclass(frozen=True)
class MailContext:
    programme: str
    university: str
    funding: str
    names: frozenset[str]
    addresses: tuple[str, ...]


def mail_context(signal: MailSignal) -> MailContext | None:
    """What the reader needs about the card the mail belongs to. Inside a tenant
    transaction: every row read here is tenant-scoped.

    A scholarship card asks its own name as both programme and funding, and its
    outcome is the funding answer (portals/outcome.py)."""
    from apps.funding.grouping import funds
    from apps.funding.models import PackCandidate
    from apps.funding.services import current_pack
    from apps.mailbox.models import MailboxConnection
    from apps.portals.models import PortalAccount
    from apps.portals.outcome import is_funding_application

    application = signal.application
    if application is None:
        return None
    candidate, student = application.candidate, application.student
    funding = ""
    if is_funding_application(application):
        funding = application.title
    elif candidate is not None:
        pack = current_pack(student)
        awards = [
            m.candidate
            for m in PackCandidate.objects.filter(
                pack_version=pack, candidate__opportunity_id__isnull=False
            ).select_related("candidate")
        ] if pack is not None else []
        funded = sorted(
            (a for a in awards if funds(a, candidate)),
            key=lambda a: (a.funding_card or {}).get("route") != "AUTOMATIC_ON_ADMISSION",
        )
        funding = funded[0].program_name if funded else ""
    addresses = (
        student.application_email, student.academic_email, student.user.email,
        *MailboxConnection.objects.filter(membership=student).values_list("address", flat=True),
        *PortalAccount.objects.filter(student=student).values_list("address", flat=True),
    )
    return MailContext(
        programme=application.title,
        university=candidate.institution_name if candidate is not None else "",
        funding=funding,
        names=personal_names(student),
        addresses=tuple(a for a in addresses if a),
    )
```

(`_fold` is imported from `transcript.py` so a name matches exactly as `personal_names` folded it; it stays private there.)

- [ ] **Step 6: The outcome service**

`apps/portals/outcome.py` (`correct_outcome` unchanged from the previous design):

```python
"""Where an application's outcome comes from, and who may overwrite it (spec §4).

Two writers. Trusted mail, through one Jev reading that cleared its bars
(record_from_mail, called by mailbox/actions.py behind the trust gate), and a
person (correct_outcome). A person's entry is never overwritten by a later
automatic reading: the outcome is the one fact this platform has no other record
of (CLAUDE.md, "Derived data"), and a misread one tells a family the wrong thing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils import timezone

from apps.funding.models import AuditEvent
from apps.tenancy.models import Membership

from .models import Application

if TYPE_CHECKING:
    from apps.mailbox.decision_reader import DecisionReading
    from apps.mailbox.models import MailSignal


def is_funding_application(application: Application) -> bool:
    """A scholarship with its own application, rather than a study place."""
    candidate = application.candidate
    return candidate is not None and candidate.opportunity_id is not None


def record_from_mail(
    application: Application, signal: MailSignal, reading: DecisionReading
) -> list[str]:
    """Trusted mail, read by Jev. Returns the fields changed.

    A decision is available only when the decision question cleared its bar. The
    outcome is recorded only when it cleared its gate, the bars have been
    measured, and no person recorded one; a scholarship card's outcome is the
    funding answer, since its own name is asked as the funding.
    """
    if reading.is_decision is not True:
        return []
    person = application.outcome_source == Application.OutcomeSource.PERSON
    corrected_after = (
        person
        and application.outcome_recorded_at is not None
        and signal.received_at <= application.outcome_recorded_at
    )
    now = timezone.now()
    changed: list[str] = []
    if application.decision_available_at is None and not corrected_after:
        application.decision_available_at = now
        changed.append("decision_available_at")
    own = reading.funding_outcome if is_funding_application(application) else reading.outcome
    if own and reading.measured and not person:
        application.outcome = own
        application.outcome_recorded_at = now
        application.outcome_source = Application.OutcomeSource.MAIL
        application.outcome_evidence = signal
        changed += ["outcome", "outcome_recorded_at", "outcome_source", "outcome_evidence"]
    if changed:
        application.save(update_fields=changed)
    return changed


def correct_outcome(application: Application, outcome: str, *, actor: Membership) -> None:
    """A person records or corrects the outcome. Audited with the person as actor.

    Blank means "no decision yet" and also clears decision_available_at, so a
    false "Decision available" can be taken back.
    """
    if outcome not in ("", *Application.Outcome.values):
        raise ValueError("unknown outcome")
    application.outcome = outcome
    application.outcome_source = Application.OutcomeSource.PERSON
    application.outcome_recorded_at = timezone.now()
    application.outcome_evidence = None
    fields = ["outcome", "outcome_source", "outcome_recorded_at", "outcome_evidence"]
    if not outcome:
        application.decision_available_at = None
        fields.append("decision_available_at")
    application.save(update_fields=fields)
    AuditEvent.objects.create(
        actor=actor, event="application.outcome_recorded", object_id=application.id
    )
```

- [ ] **Step 7: The classifier keeps the label and the quotes, and reads no outcome**

`apps/mailbox/classify.py`: `from typing import Annotated, Literal`; `from pydantic import BaseModel, ConfigDict, Field`; `MAX_OUTPUT_TOKENS = 600` (`#: A label, one action, a document name, an offered programme, up to six conditions.`); in the module docstring replace "There is no free-text field the model can fill with anything it likes." with "Its only free text is a document's name, an offered programme's name and up to six offer conditions, each capped and kept only when code finds it in the email (decision_reader.verified). Whether a mail is a decision, and what it decides, is Jev's (decision_reader.py)."

Append to `_DEVELOPER`:

```python
    " Labels: DECISION only when the email says a decision on the application has been made, "
    "whether it states the result or says the result is waiting in the applicant's portal. "
    "An email that says when decisions will be released, confirms receipt, reminds of a "
    "deadline, defers a decision, or reports a stage result (passed pre-selection, invited to "
    "an interview) is not a DECISION. "
    "Copy text exactly as the email writes it. When the email offers a place that depends on "
    "conditions, list each condition in outcome_conditions as a short phrase copied from the "
    "email, for example 'final transcript'. When it offers a place on a different programme "
    "than the one applied for, copy that programme's name into offered_programme. "
    "For a DOCUMENT_REQUEST, document_name is the requested document as the email names it "
    "and document_due is its deadline as YYYY-MM-DD, or empty when the email gives none. "
    "For an INTERVIEW only, interview_at is when the interview takes place as "
    "YYYY-MM-DDTHH:MM with the UTC offset the email states (for example "
    "2027-03-12T10:00+01:00), only YYYY-MM-DD when it gives a date without a time, and empty "
    "when it gives no date or asks the applicant to choose one."
```

Above `class MailVerdict`:

```python
#: A date, or a date and time with an optional offset, or nothing.
_ISO_TIME = r"^$|^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})?)?$"
```

and at the end of `MailVerdict`:

```python
    #: DOCUMENT_REQUEST only: the document as the email names it, and its deadline.
    document_name: str = Field(default="", max_length=120)
    document_due: str = Field(default="", max_length=10)
    #: INTERVIEW only: when it takes place, if the email states it (spec §8).
    interview_at: str = Field(default="", max_length=25, pattern=_ISO_TIME)
    #: DECISION only: quotes, verified by code before use. The outcome is Jev's.
    outcome_conditions: tuple[Annotated[str, Field(max_length=80)], ...] = Field(
        default=(), max_length=6
    )
    offered_programme: str = Field(default="", max_length=120)
```

- [ ] **Step 8: Board effects in `apply_verdict` and the reading in `sync`**

`apps/mailbox/actions.py`: `from datetime import UTC, date, datetime, timedelta`; import `from apps.portals.outcome import record_from_mail` and, under `TYPE_CHECKING`, `from apps.mailbox.decision_reader import DecisionReading`. Add `_due_date` and `_interview_time`:

```python
def _due_date(value: str) -> date | None:
    """The model's YYYY-MM-DD, or nothing: a date written any other way is not guessed at."""
    try:
        return date.fromisoformat(value.strip()) if value.strip() else None
    except ValueError:
        return None


def _interview_time(value: str) -> datetime | None:
    """The model's ISO 8601 time, or nothing.

    # ponytail: a time with no offset is read as UTC; the prompt asks for the
    # offset the mail states, and a date alone becomes midnight UTC.
    """
    try:
        parsed = datetime.fromisoformat(value.strip()) if value.strip() else None
    except ValueError:
        return None
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
```

In `_alert_student`, after `deadline = application.deadline if application is not None else None`:

```python
    # An interview's own time is the date its item is about (spec §8): it is what
    # Needs you now shows and sorts by.
    interview = signal.interview_at if label == "INTERVIEW" else None
    if interview is not None and interview > now:
        deadline = interview
        if shared_portal is None:
            message = (
                f"{signal.sender_domain} invited you to an interview on "
                f"{interview.astimezone(UTC):%d %b %Y, %H:%M} UTC. Check the time and reply."
            )
```

`apply_verdict` gains the keyword `reading: DecisionReading | None = None` and its first lines become:

```python
    signal.label = verdict.label
    fields = ["label"]
    if verdict.label == "DOCUMENT_REQUEST":
        signal.document_name = verdict.document_name.strip()[:120]
        signal.document_due = _due_date(verdict.document_due)
        fields += ["document_name", "document_due"]
    if verdict.label == "INTERVIEW":
        signal.interview_at = _interview_time(verdict.interview_at)
        fields.append("interview_at")
    if reading is not None:
        # The reading, trusted or not: an untrusted one is shown as a claim and
        # never recorded (portals/outcome.py runs only behind the trust gate).
        signal.decision_reading = reading.as_json()
        signal.outcome = reading.outcome
        signal.funding_outcome = reading.funding_outcome
        signal.outcome_conditions = (
            [c.strip() for c in verdict.outcome_conditions if c.strip()]
            if reading.outcome == "ADMITTED_CONDITIONAL"
            else []
        )
        # Jev says an offer is there; the classifier's verified quote names it.
        signal.offered_programme = (
            verdict.offered_programme.strip()[:120] if reading.other_programme_offered else ""
        )
        fields += [
            "decision_reading", "outcome", "funding_outcome", "outcome_conditions",
            "offered_programme",
        ]
    signal.save(update_fields=fields)
```

and after the `if verdict.label == "RECEIVED" and ...` block inside `if application is not None:`:

```python
        if reading is not None:
            record_from_mail(application, signal, reading)
```

`apps/mailbox/sync.py::_classify` (import `from apps.mailbox.decision_reader import keep_verified, mail_context, read_decision`), the `else:` branch becomes:

```python
    else:
        # Jev reads every classified mail tied to a card: a decision the
        # classifier labelled OTHER still gets its one reading. Outside any
        # transaction, like the classify call; the context is read inside one.
        reading = None
        if signal.application_id is not None:
            with tenant_transaction(connection.tenant_id):
                context = mail_context(signal)
            if context is not None:
                reading = read_decision(
                    body, signal.sender_domain, context.programme, context.university,
                    context.funding, student_id=connection.membership_id,
                    names=context.names, addresses=context.addresses,
                )
        with tenant_transaction(connection.tenant_id):
            apply_verdict(
                signal,
                keep_verified(verdict, body),
                reading=reading,
                link_hosts=links,
                authenticated=signal.trusted,
                vouched=signal.sender_domain in vouched,
                shared_portal=shared_portal,
            )
```

- [ ] **Step 9: Run the unit tests**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/mailbox`
Expected: PASS (`tests/mailbox/test_sync.py`'s fake provider has no application on most signals; where one is set, `read_decision` runs with no key configured, `ask` raises `not_configured`, and the reading is `UNAVAILABLE` — the abstention path).

- [ ] **Step 10: The corpus, the gold kind and the eval command**

`apps/research/models.py`, `GoldItem.Kind` gains `DECISION_MAIL = "decision_mail"`; then `uv run python manage.py makemigrations research --name gold_item_decision_mail`.

`tests/mailbox/decision_corpus.json` — synthetic letters only (never a real student's mail; published university templates are added later through `decision_eval seed --extra <csv>`, rows of the same shape). Fields: `id`, `case`, `language`, `sender_domain`, `programme`, `university`, `funding` (`""` when the card has none), `body`, and the truths `is_decision`, `outcome` (one of `OUTCOMES`), `funding_outcome` (one of `FUNDING_OUTCOMES`, or `""`), `offer` (bool):

```json
[
  {"id": "admitted-en", "case": "admitted", "language": "en", "sender_domain": "tum.de", "programme": "M.Sc. Informatics", "university": "Technical University of Munich", "funding": "", "is_decision": true, "outcome": "ADMITTED", "funding_outcome": "", "offer": false,
   "body": "Dear applicant,\n\nWe are pleased to inform you that you have been admitted to the Master's programme Informatics for the winter semester 2027/28. Please accept your study place in TUMonline by 15 July 2027."},
  {"id": "admitted-de", "case": "admitted", "language": "de", "sender_domain": "uni-heidelberg.de", "programme": "M.Sc. Physik", "university": "Universität Heidelberg", "funding": "", "is_decision": true, "outcome": "ADMITTED", "funding_outcome": "", "offer": false,
   "body": "Zulassungsbescheid\n\nSehr geehrte Bewerberin,\nSie wurden zum Masterstudiengang Physik zum Wintersemester 2027/28 zugelassen. Bitte schreiben Sie sich bis zum 30. September 2027 ein."},
  {"id": "admitted-tr", "case": "admitted", "language": "tr", "sender_domain": "metu.edu.tr", "programme": "Computer Engineering (M.Sc.)", "university": "Middle East Technical University", "funding": "", "is_decision": true, "outcome": "ADMITTED", "funding_outcome": "", "offer": false,
   "body": "Sayın aday,\n\nBilgisayar Mühendisliği yüksek lisans programına kabul edildiğinizi bildirmekten memnuniyet duyarız. Kesin kayıt 10 Eylül 2027 tarihine kadar yapılmalıdır."},
  {"id": "rejected-en", "case": "rejected", "language": "en", "sender_domain": "kth.se", "programme": "Machine Learning, MSc", "university": "KTH", "funding": "", "is_decision": true, "outcome": "REJECTED", "funding_outcome": "", "offer": false,
   "body": "Dear applicant,\n\nThank you for your application to the Master's programme in Machine Learning. After careful review we regret to inform you that we are unable to offer you a place this year."},
  {"id": "rejected-nl", "case": "rejected", "language": "nl", "sender_domain": "tudelft.nl", "programme": "MSc Computer Science", "university": "TU Delft", "funding": "", "is_decision": true, "outcome": "REJECTED", "funding_outcome": "", "offer": false,
   "body": "Beste kandidaat,\n\nHelaas moeten wij u meedelen dat u niet bent toegelaten tot de masteropleiding Computer Science voor het studiejaar 2027-2028."},
  {"id": "reserve-sv", "case": "reserve_list", "language": "sv", "sender_domain": "universityadmissions.se", "programme": "Masterprogram i datavetenskap", "university": "Uppsala universitet", "funding": "", "is_decision": true, "outcome": "WAITLISTED", "funding_outcome": "", "offer": false,
   "body": "Antagningsbesked\n\nMasterprogram i datavetenskap, Uppsala universitet: Du är reserv (reservnummer 14). Du meddelas om en plats blir ledig."},
  {"id": "ranking-en", "case": "reserve_list", "language": "en", "sender_domain": "uva.nl", "programme": "MSc Data Science", "university": "University of Amsterdam", "funding": "", "is_decision": true, "outcome": "WAITLISTED", "funding_outcome": "", "offer": false,
   "body": "Dear applicant,\n\nThe selection committee has placed you on our ranking list at position 7 for the MSc Data Science. Should a place become available, we will contact you before 1 August."},
  {"id": "pending-nl", "case": "reserve_list", "language": "nl", "sender_domain": "rug.nl", "programme": "MSc Econometrics", "university": "University of Groningen", "funding": "", "is_decision": true, "outcome": "WAITLISTED", "funding_outcome": "", "offer": false,
   "body": "Beste kandidaat,\n\nU staat op de wachtlijst voor de master Econometrics. Wij kunnen u op dit moment geen plaats aanbieden; in juni hoort u meer."},
  {"id": "conditional-en", "case": "conditional", "language": "en", "sender_domain": "ed.ac.uk", "programme": "MSc Artificial Intelligence", "university": "University of Edinburgh", "funding": "", "is_decision": true, "outcome": "ADMITTED_CONDITIONAL", "funding_outcome": "", "offer": false,
   "body": "Dear applicant,\n\nWe are delighted to make you a conditional offer of a place on the MSc Artificial Intelligence. Your offer is subject to: a final degree transcript showing a 2:1 or equivalent; an IELTS Academic score of 7.0 overall."},
  {"id": "conditional-de", "case": "conditional", "language": "de", "sender_domain": "uni-mannheim.de", "programme": "M.Sc. Wirtschaftsinformatik", "university": "Universität Mannheim", "funding": "", "is_decision": true, "outcome": "ADMITTED_CONDITIONAL", "funding_outcome": "", "offer": false,
   "body": "Sie sind unter Vorbehalt zum Master Wirtschaftsinformatik zugelassen. Die Zulassung wird wirksam, wenn Sie bis zum 31. August 2027 Ihr Bachelorzeugnis nachreichen."},
  {"id": "two-decisions-en", "case": "two_decisions", "language": "en", "sender_domain": "uni-mannheim.de", "programme": "M.Sc. Business Informatics", "university": "University of Mannheim", "funding": "Mannheim Master Scholarship", "is_decision": true, "outcome": "ADMITTED", "funding_outcome": "NOT_AWARDED", "offer": false,
   "body": "Dear applicant,\n\nWe are happy to inform you that you have been admitted to the M.Sc. Business Informatics. Unfortunately, we are unable to award you the Mannheim Master Scholarship this year."},
  {"id": "two-decisions-sv", "case": "two_decisions", "language": "sv", "sender_domain": "lu.se", "programme": "Master's in Economics", "university": "Lunds universitet", "funding": "Lund University Global Scholarship", "is_decision": true, "outcome": "ADMITTED", "funding_outcome": "AWARDED", "offer": false,
   "body": "Grattis! Du är antagen till masterprogrammet i nationalekonomi och har tilldelats Lund University Global Scholarship som täcker hela studieavgiften."},
  {"id": "other-programme-en", "case": "other_programme", "language": "en", "sender_domain": "lu.se", "programme": "MSc Data Science", "university": "Lund University", "funding": "", "is_decision": true, "outcome": "REJECTED", "funding_outcome": "", "offer": true,
   "body": "Dear applicant,\n\nWe are unable to offer you a place in the MSc Data Science. However, the admissions committee would like to offer you a place in the MSc Statistics instead. Please reply within two weeks if you wish to accept this alternative offer."},
  {"id": "other-programme-de", "case": "other_programme", "language": "de", "sender_domain": "tu-berlin.de", "programme": "M.Sc. Informatik", "university": "TU Berlin", "funding": "", "is_decision": true, "outcome": "NOT_STATED", "funding_outcome": "", "offer": true,
   "body": "Für den Master Informatik können wir Ihnen leider keinen Platz anbieten. Wir bieten Ihnen stattdessen einen Studienplatz im Master Wirtschaftsinformatik an."},
  {"id": "available-only-nl", "case": "decision_available_only", "language": "nl", "sender_domain": "studielink.nl", "programme": "MSc Business Analytics", "university": "Vrije Universiteit Amsterdam", "funding": "", "is_decision": true, "outcome": "NOT_STATED", "funding_outcome": "", "offer": false,
   "body": "De instelling heeft een besluit genomen over je inschrijvingsverzoek voor 2027-2028. Log in op Studielink om het besluit te bekijken."},
  {"id": "available-only-en", "case": "decision_available_only", "language": "en", "sender_domain": "ox.ac.uk", "programme": "MSc Computer Science", "university": "University of Oxford", "funding": "", "is_decision": true, "outcome": "NOT_STATED", "funding_outcome": "", "offer": false,
   "body": "Dear applicant, a decision has been made on your graduate application. Please log in to the applicant self-service portal to view your decision letter."},
  {"id": "scholarship-awarded-de", "case": "funding_only", "language": "de", "sender_domain": "daad.de", "programme": "DAAD Study Scholarship", "university": "DAAD", "funding": "DAAD Study Scholarship", "is_decision": true, "outcome": "NOT_STATED", "funding_outcome": "AWARDED", "offer": false,
   "body": "Sehr geehrte Bewerberin,\n\nder Auswahlausschuss hat Ihnen ein DAAD-Studienstipendium für ein Masterstudium in Deutschland ab dem 1. Oktober 2027 bewilligt."},
  {"id": "scholarship-declined-en", "case": "funding_only", "language": "en", "sender_domain": "chevening.org", "programme": "Chevening Scholarship", "university": "Chevening", "funding": "Chevening Scholarship", "is_decision": true, "outcome": "NOT_STATED", "funding_outcome": "NOT_AWARDED", "offer": false,
   "body": "Thank you for applying for a Chevening Scholarship. We regret to inform you that you have not been selected for an award this year."},
  {"id": "acknowledgement-de", "case": "acknowledgement", "language": "de", "sender_domain": "uni-assist.de", "programme": "M.Sc. Maschinenbau", "university": "RWTH Aachen", "funding": "", "is_decision": false, "outcome": "NOT_STATED", "funding_outcome": "", "offer": false,
   "body": "Wir haben Ihre Bewerbung für den Masterstudiengang Maschinenbau erhalten. Ihre Unterlagen werden nun geprüft. Bewerbernummer: 1234567."},
  {"id": "release-date-sv", "case": "release_date", "language": "sv", "sender_domain": "universityadmissions.se", "programme": "Masterprogram i datavetenskap", "university": "Uppsala universitet", "funding": "", "is_decision": false, "outcome": "NOT_STATED", "funding_outcome": "", "offer": false,
   "body": "Antagningsbeskeden för höstterminen 2027 publiceras den 9 april 2027. Logga in på ditt konto den dagen för att se ditt resultat."},
  {"id": "deferred-en", "case": "release_date", "language": "en", "sender_domain": "ucas.com", "programme": "MSc Robotics", "university": "University of Bristol", "funding": "", "is_decision": false, "outcome": "NOT_STATED", "funding_outcome": "", "offer": false,
   "body": "The University of Bristol has deferred its decision on your application for MSc Robotics. You will hear from them by 30 April 2027."},
  {"id": "reminder-en", "case": "reminder", "language": "en", "sender_domain": "tum.de", "programme": "M.Sc. Informatics", "university": "Technical University of Munich", "funding": "", "is_decision": false, "outcome": "NOT_STATED", "funding_outcome": "", "offer": false,
   "body": "Reminder: the application deadline for the Master's programme Informatics is 31 May 2027. Please complete and submit your application in TUMonline."},
  {"id": "stage-result-en", "case": "stage_result", "language": "en", "sender_domain": "ethz.ch", "programme": "MSc Robotics, Systems and Control", "university": "ETH Zurich", "funding": "", "is_decision": false, "outcome": "NOT_STATED", "funding_outcome": "", "offer": false,
   "body": "Congratulations, you have passed the first selection stage for the MSc Robotics, Systems and Control. We invite you to an online interview on 12 March 2027 at 10:00 CET."},
  {"id": "stage-result-tr", "case": "stage_result", "language": "tr", "sender_domain": "boun.edu.tr", "programme": "Ekonomi Yüksek Lisans", "university": "Boğaziçi Üniversitesi", "funding": "", "is_decision": false, "outcome": "NOT_STATED", "funding_outcome": "", "offer": false,
   "body": "Yazılı sınavı başarıyla geçtiniz. Mülakat 20 Haziran 2027 saat 14:00'te yapılacaktır."},
  {"id": "document-request-de", "case": "document_request", "language": "de", "sender_domain": "tu-berlin.de", "programme": "M.Sc. Informatik", "university": "TU Berlin", "funding": "", "is_decision": false, "outcome": "NOT_STATED", "funding_outcome": "", "offer": false,
   "body": "Ihre Bewerbung ist unvollständig. Bitte laden Sie bis zum 15. Juni 2027 eine beglaubigte Kopie Ihres Bachelorzeugnisses hoch."},
  {"id": "open-day-en", "case": "newsletter", "language": "en", "sender_domain": "kth.se", "programme": "Machine Learning, MSc", "university": "KTH", "funding": "", "is_decision": false, "outcome": "NOT_STATED", "funding_outcome": "", "offer": false,
   "body": "Join our online open day on 20 November to meet students and teachers from our Master's programmes."}
]
```

`tests/mailbox/test_decision_eval.py`:

```python
"""The corpus covers every hard case, the harness scores a run, and a live run is opt-in."""

import json
from pathlib import Path

import pytest
from django.core.management import call_command

from apps.mailbox.decision_questions import FUNDING_OUTCOMES, OUTCOMES
from apps.research.models import GoldItem

CORPUS = json.loads((Path(__file__).parent / "decision_corpus.json").read_text(encoding="utf-8"))
HARD_CASES = {
    "conditional", "two_decisions", "other_programme", "stage_result", "reserve_list",
    "acknowledgement", "release_date", "reminder", "decision_available_only",
}


def test_the_corpus_covers_every_hard_case_in_five_languages() -> None:
    assert HARD_CASES <= {row["case"] for row in CORPUS}
    assert {"en", "de", "sv", "nl", "tr"} <= {row["language"] for row in CORPUS}
    for row in CORPUS:
        assert row["outcome"] in OUTCOMES
        assert row["funding_outcome"] in (*FUNDING_OUTCOMES, "")
        assert bool(row["funding"]) == bool(row["funding_outcome"])


@pytest.mark.django_db
def test_seeding_writes_one_gold_row_per_letter_and_question_once() -> None:
    call_command("decision_eval", "seed", "--run", "dm-test")
    call_command("decision_eval", "seed", "--run", "dm-test")
    rows = GoldItem.objects.filter(run="dm-test", kind="decision_mail")
    assert rows.filter(question="is_decision").count() == len(CORPUS)
    assert all(row.page_url.startswith("https://synthetic.invalid/decision-mail/") for row in rows)


@pytest.mark.django_db
def test_a_scored_run_reports_bars_rows_needed_and_cost(tmp_path, monkeypatch) -> None:
    from apps.mailbox.management.commands import decision_eval
    from tests.mailbox.test_decision_reader import FakeJev

    def truthful(state, questions, *, model, provider):
        row = next(r for r in CORPUS if r["body"] == state["email"]["body"])
        nouls = {"is_decision": 0.99 if row["is_decision"] else 0.01,
                 f"gate:{row['outcome']}": 0.99, f"fgate:{row['funding_outcome']}": 0.99,
                 "other_programme": 0.99 if row["offer"] else 0.01}
        return FakeJev(nouls, {"outcome": row["outcome"], "funding": row["funding_outcome"]})(
            state, questions, model=model, provider=provider)

    monkeypatch.setattr(decision_eval, "CLIENT", truthful)
    monkeypatch.setattr(decision_eval, "RUNS", tmp_path)
    call_command("decision_eval", "seed", "--run", "dm-fake")
    call_command("decision_eval", "read", "--run", "dm-fake", "--trust-corpus")
    call_command("decision_eval", "score", "--run", "dm-fake", "--trust-corpus")
    report = (tmp_path / "dm-fake" / "report.md").read_text()
    assert "zero-error rows needed: 299 (1/100), 1,497 (1/500)" in report
    assert "BARS = {" in report
    assert "USD" in report


@pytest.mark.live
@pytest.mark.django_db
def test_a_real_jev_run_over_the_corpus(tmp_path, monkeypatch) -> None:
    """Spends real tokens (~26 letters, about $0.001 at $0.042/1M). Never runs by default."""
    from apps.mailbox.management.commands import decision_eval

    monkeypatch.setattr(decision_eval, "RUNS", tmp_path)
    call_command("decision_eval", "seed", "--run", "dm-live")
    call_command("decision_eval", "read", "--run", "dm-live", "--wording", "a", "--trust-corpus")
    call_command("decision_eval", "read", "--run", "dm-live", "--wording", "b", "--trust-corpus")
    call_command("decision_eval", "score", "--run", "dm-live", "--trust-corpus")
    print((tmp_path / "dm-live" / "report.md").read_text())
```

`apps/mailbox/management/commands/decision_eval.py`:

```python
"""Measure the mail decision reader and learn its bars (dashboard spec §4).

    uv run python manage.py decision_eval seed  --run dm-1 [--extra templates.csv]
    uv run python manage.py decision_eval read  --run dm-1 --wording a [--max-usd 1]
    uv run python manage.py decision_eval score --run dm-1

`seed` writes one research.GoldItem per letter per question (kind decision_mail)
for the owner to check in /platform/gold/; the claim is the expected answer.
`read` asks Jev once per letter (record=False) and saves the answers under
.superpowers/engine-eval/<run>/. `score` splits letters into tune and score
halves by hash, learns each gated question's bar with engine_eval.score.ltt_bar
at its delta (decision_questions.DELTAS), and reports precision, coverage and the
95% upper error on the score half, per wording, with the zero-error row counts
and the spend. Rows count as truth when the owner labelled them correct (or
wrong, with a fix); --trust-corpus uses the corpus labels instead, for a
development run that certifies nothing. Synthetic and published-template letters
only: no student's mail is ever written to GoldItem, a platform table.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.mailbox.decision_questions import DECISION, DELTAS, GATED, questions
from apps.research.decisions import Answer, Client, ask
from apps.research.engine_eval.items import RUNS
from apps.research.engine_eval.jev_reader import jev_cost_usd
from apps.research.engine_eval.score import ltt_bar, upper_error, zero_error_rows_needed
from apps.research.models import GoldItem

CORPUS = Path(__file__).resolve().parents[4] / "tests" / "mailbox" / "decision_corpus.json"
#: None reaches Jev through the decision layer; a test swaps in a fake.
CLIENT: Client | None = None


def _truths(row: dict[str, Any]) -> dict[str, Any]:
    funding = bool(row["funding"])
    out: dict[str, Any] = {
        "is_decision": row["is_decision"], "outcome": row["outcome"],
        "other_programme": row["offer"],
        **{qid: row["outcome"] == qid.split(":")[1] for qid in GATED if qid.startswith("gate:")},
    }
    if funding:
        out["funding"] = row["funding_outcome"]
        out.update({qid: row["funding_outcome"] == qid.split(":")[1]
                    for qid in GATED if qid.startswith("fgate:")})
    return out


def _context(row: dict[str, Any]) -> str:
    return json.dumps({k: row[k] for k in ("sender_domain", "programme", "university", "funding",
                                           "id", "case")}, sort_keys=True)


class Command(BaseCommand):
    help = "Seed, read and score the mail decision reader."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("step", choices=["seed", "read", "score"])
        parser.add_argument("--run", required=True)
        parser.add_argument("--wording", choices=["a", "b"], default="a")
        parser.add_argument("--max-usd", type=float, default=1.0)
        parser.add_argument("--extra", default="", help="CSV of published templates, corpus shape")
        parser.add_argument("--trust-corpus", action="store_true")

    def handle(self, *args: object, **opts: Any) -> None:
        getattr(self, f"_{opts['step']}")(opts)

    def _rows(self, opts: dict[str, Any]) -> list[dict[str, Any]]:
        rows = json.loads(CORPUS.read_text(encoding="utf-8"))
        if opts["extra"]:
            with open(opts["extra"], encoding="utf-8") as handle:
                rows += [
                    {**r, **{k: r[k] == "true" for k in ("is_decision", "offer")}}
                    for r in csv.DictReader(handle)
                ]
        return rows

    def _seed(self, opts: dict[str, Any]) -> None:
        created = 0
        for row in self._rows(opts):
            for qid, truth in _truths(row).items():
                _, made = GoldItem.objects.get_or_create(
                    run=opts["run"], purpose=GoldItem.Purpose.IMPROVEMENT, round=1, question=qid,
                    page_url=f"https://synthetic.invalid/decision-mail/{row['id']}",
                    line_sha256=hashlib.sha256(row["body"].encode()).hexdigest(),
                    defaults={"kind": GoldItem.Kind.DECISION_MAIL, "language": row["language"],
                              "line_text": row["body"], "heading": _context(row),
                              "claim": json.dumps(truth)},
                )
                created += int(made)
        self.stdout.write(f"seeded {created} gold rows for {opts['run']}")

    def _letters(self, opts: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Per letter: its context, body and the truth per question."""
        letters: dict[str, dict[str, Any]] = {}
        for item in GoldItem.objects.filter(run=opts["run"], kind=GoldItem.Kind.DECISION_MAIL):
            if item.verdict == GoldItem.Verdict.CORRECT or opts["trust_corpus"]:
                truth = json.loads(item.claim)
            elif item.verdict == GoldItem.Verdict.WRONG and item.fix:
                truth = json.loads(item.fix)
            else:
                continue
            letter = letters.setdefault(item.line_sha256, {
                "context": json.loads(item.heading), "body": item.line_text,
                "language": item.language, "truth": {},
            })
            letter["truth"][item.question] = truth
        return letters

    def _read(self, opts: dict[str, Any]) -> None:
        out_dir = RUNS / opts["run"]
        out_dir.mkdir(parents=True, exist_ok=True)
        answers: dict[str, Any] = {}
        tokens = 0
        for key, letter in self._letters(opts).items():
            if jev_cost_usd(tokens) >= opts["max_usd"]:
                raise CommandError(f"spend cap {opts['max_usd']} USD reached")
            c = letter["context"]
            state = {"email": {"from_domain": c["sender_domain"], "body": letter["body"]},
                     "application": {"programme": c["programme"], "university": c["university"],
                                     **({"funding": c["funding"]} if c["funding"] else {})}}
            got: dict[str, Answer] = ask(
                state, questions(opts["wording"], funding=bool(c["funding"])),
                decision=DECISION, record=False, client=CLIENT,
            )
            tokens += sum(a.input_tokens for a in got.values())
            answers[key] = {qid: {"value": a.value, "p": a.probabilities} for qid, a in got.items()}
        (out_dir / f"jev-{opts['wording']}.json").write_text(
            json.dumps({"answers": answers, "tokens": tokens}, default=str)
        )
        self.stdout.write(f"read {len(answers)} letters, {tokens} tokens, "
                          f"{jev_cost_usd(tokens):.6f} USD")

    def _score(self, opts: dict[str, Any]) -> None:
        out_dir = RUNS / opts["run"]
        letters = self._letters(opts)
        lines = [f"# decision_eval {opts['run']}", "",
                 f"zero-error rows needed: {zero_error_rows_needed(0.01):,} (1/100), "
                 f"{zero_error_rows_needed(0.002):,} (1/500)", ""]
        for wording in ("a", "b"):
            path = out_dir / f"jev-{wording}.json"
            if not path.exists():
                continue
            saved = json.loads(path.read_text())
            lines += [f"## wording {wording} — {jev_cost_usd(saved['tokens']):.6f} USD", "",
                      "| question | bar | accepted (score half) | wrong | coverage | 95% upper error |",
                      "|---|---|---|---|---|---|"]
            bars: dict[str, float | None] = {}
            for qid in GATED:
                pairs = {"tune": [], "score": []}
                for key, letter in letters.items():
                    got = saved["answers"].get(key, {}).get(qid)
                    if got is None or qid not in letter["truth"]:
                        continue
                    half = "tune" if int(key, 16) % 2 == 0 else "score"
                    pairs[half].append((float(got["p"].get("true", 0.0)), bool(letter["truth"][qid])))
                bar = ltt_bar([p for p in pairs["tune"] if p[0] >= 0.5], DELTAS[qid])
                bars[qid] = bar
                accepted = [t for s, t in pairs["score"] if bar is not None and s >= bar]
                wrong = sum(1 for t in accepted if not t)
                positives = sum(1 for _s, t in pairs["score"] if t) or 1
                lines.append(
                    f"| {qid} | {bar} | {len(accepted)} | {wrong} | "
                    f"{(len(accepted) - wrong) / positives:.2f} | "
                    f"{upper_error(wrong, len(accepted)):.4f} |"
                )
            lines += ["", "```python", f"BARS = {json.dumps(bars, indent=4)}", "```", ""]
        (out_dir / "report.md").write_text("\n".join(lines))
        self.stdout.write(str(out_dir / "report.md"))
```

(`json.dumps` of the bars prints `null` for a question no bar passed; paste it into `decision_bars.py` as `None`, with `MEASURED_ON` set to the run's date. Certification wants the owner's labels: `--trust-corpus` reports, it never certifies.)

- [ ] **Step 11: Run everything**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/mailbox tests/portals tests/research tests/audit`
Expected: PASS (the live test is deselected).

Run once with a key (`OPENROUTER_API_KEY` set): `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q -m live tests/mailbox/test_decision_eval.py -s`
Expected: a report printed. Bars stay at the default until the owner has labelled the gold rows and a `score` run without `--trust-corpus` is pasted into `decision_bars.py`.

- [ ] **Step 12: Lint, types, migrations**

Run: `uv run ruff check . && uv run mypy apps config && uv run python manage.py makemigrations --check --dry-run`
Expected: no errors.

- [ ] **Step 13: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add -A apps/mailbox apps/portals/outcome.py apps/research/models.py apps/research/migrations tests/mailbox && git commit -m "feat(mailbox): one Jev reading decides a mail, and abstains

Jev (TypeSafe via OpenRouter, record=False, the student's name, addresses and
phone numbers stripped first) answers one request of atomic questions: is this
the decision, which outcome with a gate Noul per option, the same for the card's
funding, and is another programme offered. An outcome is recorded only when the
gate agrees with the choice and the bars have been learned; until then the card
asks a person. Jev unavailable abstains. The classifier keeps the label and the
code-verified quotes. decision_eval seeds GoldItem decision_mail rows from a
five-language synthetic corpus and learns each bar with Learn-then-Test.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 9: Application actions — add, remove, start, record the portal, correct the outcome, accept or ignore an offer

Spec §7, §4 (an offer for another programme, owner 2026-10-04) and §4a's write paths. One service module, each function audited with the actor who pressed; student views here, counsellor views reuse the same functions in Task 20. `capture_requirements` runs in the document worker (it runs as `runtime_engine`, which may read the catalogue — the same reason `_generate` lives there), reached through a new `DocumentWorkMessage.action`; `scripts/deploy.sh` already rolls the worker before the web tier, which `extra="forbid"` requires.

**Files:**
- Create: `apps/portals/applications.py`, `tests/portals/test_applications.py`
- Modify: `apps/portals/views.py`, `apps/portals/urls.py`, `apps/documents/document_queue.py`, `apps/documents/document_worker.py`, `tests/documents/test_document_worker.py`

**Interfaces:**
- Produces: `class ApplicationRefused(Exception)` with `.reason` ∈ {`not_found`, `comes_with_admission`, `no_portal`, `automation_prohibited`, `not_paired`, `rate_limited`, `bad_url`}; `REFUSALS: dict[str, str]` (the sentence for each)
- Produces: `add_application(*, student: Membership, candidate_id: UUID, actor: Membership) -> Application`
- Produces: `remove_application(application: Application, *, actor: Membership) -> None`
- Produces: `start_application(application: Application, *, actor: Membership) -> DeviceAction`
- Produces: `queue_upload(application: Application, *, document_id: UUID, source: str, actor: Membership) -> DeviceAction` (used in Task 15)
- Produces: `record_portal(application: Application, form_url: str, *, actor: Membership) -> PortalForm`
- Produces: `offer_for(student: Membership, signal_id: UUID) -> MailSignal | None` (an unhandled offer on one of this student's applications), `accept_offer(signal: MailSignal, *, actor: Membership) -> Application`, `ignore_offer(signal: MailSignal, *, actor: Membership) -> None`
- Produces URL names: `student-offer-accept`, `student-offer-ignore` (`student/offers/<uuid:signal_id>/{accept,ignore}/`)
- Produces URL names: `student-application-add` (`student/applications/add/<uuid:candidate_id>/`), `student-application-start`, `student-application-outcome`, `student-application-remove` (`student/applications/<uuid:application_id>/{start,outcome,remove}/`)
- Produces: `DocumentWorkMessage.action` gains `"capture_requirements"`, field `application_id: UUID | None = None`

- [ ] **Step 1: Write the failing tests**

`tests/portals/test_applications.py`:

```python
"""Add, remove, start, outcome: the student's write paths on the board (spec §7)."""

from uuid import uuid4

import pytest
from django.contrib.messages import get_messages
from django.utils import timezone

from apps.concierge.models import Notification
from apps.funding.models import AuditEvent, RecommendationCandidate
from apps.portals import applications as applications_module
from apps.portals.models import Application, ApplicationStep, DeviceAction, PortalForm
from apps.portals.pairing import issue_pairing_code, redeem_pairing_code
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment, Membership
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run

pytestmark = pytest.mark.django_db


@pytest.fixture
def candidate(agency_a, membership_a):
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    make_published_pack(agency_a, run, (candidate,))
    return candidate


@pytest.fixture
def captured(monkeypatch):
    sent = []
    monkeypatch.setattr(
        applications_module, "enqueue_document_work", lambda message, **_kw: sent.append(message)
    )
    return sent


@pytest.fixture
def signed_in(client, user_a, membership_a):
    client.force_login(user_a)
    return client


def _messages(response) -> list[str]:
    return [str(message) for message in get_messages(response.wsgi_request)]


def _application(agency, student, *, portal=True, **fields):
    form = (
        PortalForm.objects.create(
            portal_host="apply.example.edu", form_key=f"k-{uuid4()}",
            form_url="https://apply.example.edu/start",
        )
        if portal
        else None
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form, **fields
    )


def _pair(agency, membership):
    with tenant_scope(agency.id):
        redeem_pairing_code(issue_pairing_code(membership), "install-1")


def test_adding_creates_a_card_without_a_portal_and_asks_the_counsellor(
    signed_in, agency_a, domain_a, membership_a, counselor_membership, candidate, captured,
    django_capture_on_commit_callbacks,
) -> None:
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    with django_capture_on_commit_callbacks(execute=True):
        response = signed_in.post(
            f"/student/applications/add/{candidate.id}/", HTTP_HOST=domain_a.host
        )

    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        application = Application.objects.get(candidate=candidate)
        assert application.portal_form is None
        assert application.exception_item.owner_id == counselor_membership.id
        note = Notification.objects.get(application=application)
        assert note.message == "Find the application portal for MSc Chemistry."
        assert note.recipient_id == counselor_membership.id
        assert AuditEvent.objects.filter(
            event="application.added", actor=membership_a, object_id=application.id
        ).exists()
    assert [(m.action, m.application_id) for m in captured] == [
        ("capture_requirements", application.id)
    ]


def test_a_portal_recorded_for_the_programme_is_reused(
    signed_in, agency_a, domain_a, membership_a, candidate, captured, program_factory
) -> None:
    programme = program_factory()
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=candidate.id).update(program_id=programme.id)
        earlier = _application(agency_a, membership_a)
        Application.objects.filter(id=earlier.id).update(program_id=programme.id)

    signed_in.post(f"/student/applications/add/{candidate.id}/", HTTP_HOST=domain_a.host)

    with tenant_scope(agency_a.id):
        assert Application.objects.get(candidate=candidate).portal_form_id == earlier.portal_form_id


def test_adding_twice_is_one_card(signed_in, agency_a, domain_a, candidate, captured) -> None:
    for _ in range(2):
        signed_in.post(f"/student/applications/add/{candidate.id}/", HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        assert Application.objects.filter(candidate=candidate).count() == 1


def test_another_students_candidate_cannot_be_added(
    signed_in, agency_a, domain_a, user_b, captured
) -> None:
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(tenant=agency_a, user=user_b, role=Membership.Role.STUDENT)
    run = make_run(agency_a, other)
    theirs = make_db_candidate(agency_a, run)
    response = signed_in.post(f"/student/applications/add/{theirs.id}/", HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_funding_that_comes_with_the_admission_is_not_a_card(
    signed_in, agency_a, domain_a, candidate, captured
) -> None:
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=candidate.id).update(
            funding_card={"route": "AUTOMATIC_ON_ADMISSION"}
        )
    response = signed_in.post(f"/student/applications/add/{candidate.id}/", HTTP_HOST=domain_a.host)
    assert response["Location"] == "/student/recommendation/"
    assert "comes with the admission" in _messages(response)[0]
    with tenant_scope(agency_a.id):
        assert not Application.objects.filter(candidate=candidate).exists()


def test_start_is_refused_without_a_portal(signed_in, agency_a, domain_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, portal=False)
    response = signed_in.post(
        f"/student/applications/{application.id}/start/", HTTP_HOST=domain_a.host
    )
    assert "application portal" in _messages(response)[0]
    with tenant_scope(agency_a.id):
        assert not DeviceAction.objects.filter(application=application).exists()


def test_start_is_refused_until_the_extension_is_paired(
    signed_in, agency_a, domain_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    response = signed_in.post(
        f"/student/applications/{application.id}/start/", HTTP_HOST=domain_a.host
    )
    assert "extension" in _messages(response)[0]


def test_start_queues_one_fill_and_moves_the_card(
    signed_in, agency_a, domain_a, membership_a
) -> None:
    _pair(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

    signed_in.post(f"/student/applications/{application.id}/start/", HTTP_HOST=domain_a.host)

    with tenant_scope(agency_a.id):
        application.refresh_from_db()
        action = DeviceAction.objects.get(application=application)
        assert application.started_at is not None
        assert action.kind == DeviceAction.Kind.START_FILL
        assert AuditEvent.objects.filter(event="application.start_requested").exists()


def test_start_is_rate_limited(signed_in, agency_a, domain_a, membership_a, monkeypatch) -> None:
    from django.core.cache import cache

    cache.clear()
    monkeypatch.setattr(applications_module, "DEVICE_ACTION_LIMIT", 1)
    _pair(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    signed_in.post(f"/student/applications/{application.id}/start/", HTTP_HOST=domain_a.host)
    response = signed_in.post(
        f"/student/applications/{application.id}/start/", HTTP_HOST=domain_a.host
    )
    assert "Too many requests" in _messages(response)[-1]
    with tenant_scope(agency_a.id):
        assert DeviceAction.objects.filter(application=application).count() == 1


def test_a_person_corrects_the_outcome(signed_in, agency_a, domain_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, outcome="ADMITTED", outcome_source="MAIL")
    signed_in.post(
        f"/student/applications/{application.id}/outcome/",
        {"outcome": "WAITLISTED"},
        HTTP_HOST=domain_a.host,
    )
    with tenant_scope(agency_a.id):
        application.refresh_from_db()
    assert (application.outcome, application.outcome_source) == ("WAITLISTED", "PERSON")


def test_an_unknown_outcome_changes_nothing(signed_in, agency_a, domain_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    response = signed_in.post(
        f"/student/applications/{application.id}/outcome/", {"outcome": "MAYBE"},
        HTTP_HOST=domain_a.host,
    )
    assert "Choose an outcome" in _messages(response)[0]
    with tenant_scope(agency_a.id):
        application.refresh_from_db()
    assert application.outcome == ""


def test_removing_an_untouched_card_deletes_it_and_a_started_one_is_withdrawn(
    signed_in, agency_a, domain_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        untouched = _application(agency_a, membership_a)
        started = _application(agency_a, membership_a)
        ApplicationStep.objects.create(
            tenant=agency_a, application=started, sequence=1, kind="PACKET", detail={}
        )
    for application in (untouched, started):
        signed_in.post(
            f"/student/applications/{application.id}/remove/", HTTP_HOST=domain_a.host
        )
    with tenant_scope(agency_a.id):
        assert not Application.objects.filter(id=untouched.id).exists()
        started.refresh_from_db()
    assert (started.outcome, started.outcome_source) == ("WITHDRAWN", "PERSON")


@pytest.mark.parametrize("action", ["start", "outcome", "remove"])
def test_another_students_application_is_404_on_every_action(
    signed_in, agency_a, domain_a, user_b, action
) -> None:
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(tenant=agency_a, user=user_b, role=Membership.Role.STUDENT)
        theirs = _application(agency_a, other)
    response = signed_in.post(
        f"/student/applications/{theirs.id}/{action}/", {"outcome": "ADMITTED"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 404


def test_record_portal_reuses_a_shared_row_and_refuses_http(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, portal=False)
        with pytest.raises(applications_module.ApplicationRefused):
            applications_module.record_portal(
                application, "http://apply.tum.de/start", actor=membership_a
            )
        form = applications_module.record_portal(
            application, "https://campus.tum.de/apply", actor=membership_a
        )
        again = applications_module.record_portal(
            _application(agency_a, membership_a, portal=False),
            "https://campus.tum.de/apply",
            actor=membership_a,
        )
    assert (form.portal_host, form.form_key) == ("campus.tum.de", "/apply")
    assert again.id == form.id


def _offer(agency, student, original, *, sender: str, outcome: str = "REJECTED"):
    from apps.mailbox.models import MailboxConnection, MailSignal

    connection, _ = MailboxConnection.objects.get_or_create(
        tenant=agency, membership=student, provider="MICROSOFT",
        defaults={"address": "amina@outlook.test"},
    )
    return MailSignal.objects.create(
        tenant=agency, connection=connection, provider_message_id=f"m-{uuid4()}",
        sender_domain=sender, received_at=timezone.now(), application=original,
        label="DECISION", outcome=outcome,
        offered_programme="MSc Statistics", trusted=True,
    )


def test_accepting_an_offer_makes_a_card_on_the_same_portal_and_records_the_refusal(
    signed_in, agency_a, domain_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        original = _application(agency_a, membership_a)
        signal = _offer(agency_a, membership_a, original, sender="example.edu")

    response = signed_in.post(f"/student/offers/{signal.id}/accept/", HTTP_HOST=domain_a.host)

    assert response["Location"] == "/student/"
    with tenant_scope(agency_a.id):
        offered = Application.objects.get(student=membership_a, program_id=signal.id)
        original.refresh_from_db()
        signal.refresh_from_db()
        assert offered.title == "MSc Statistics"
        assert offered.portal_form_id == original.portal_form_id
        assert (original.outcome, original.outcome_source) == ("REJECTED", "PERSON")
        assert signal.offer_handled_at is not None
        assert AuditEvent.objects.filter(
            event="application.offer_accepted", actor=membership_a, object_id=offered.id
        ).exists()


def test_an_offer_from_another_institution_starts_without_a_portal(
    signed_in, agency_a, domain_a, membership_a, counselor_membership
) -> None:
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        original = _application(agency_a, membership_a)
        signal = _offer(agency_a, membership_a, original, sender="lu.se", outcome="")

    signed_in.post(f"/student/offers/{signal.id}/accept/", HTTP_HOST=domain_a.host)

    with tenant_scope(agency_a.id):
        offered = Application.objects.get(student=membership_a, program_id=signal.id)
        original.refresh_from_db()
        assert offered.portal_form is None
        assert offered.exception_item.owner_id == counselor_membership.id
        # The letter said nothing about the programme applied for: nothing is recorded.
        assert original.outcome == ""


def test_ignoring_an_offer_dismisses_it_and_makes_no_card(
    signed_in, agency_a, domain_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        original = _application(agency_a, membership_a)
        signal = _offer(agency_a, membership_a, original, sender="example.edu")
    signed_in.post(f"/student/offers/{signal.id}/ignore/", HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        signal.refresh_from_db()
        original.refresh_from_db()
        assert signal.offer_handled_at is not None
        assert not Application.objects.filter(program_id=signal.id).exists()
        assert original.outcome == ""
    again = signed_in.post(f"/student/offers/{signal.id}/accept/", HTTP_HOST=domain_a.host)
    assert again.status_code == 404


@pytest.mark.parametrize("action", ["accept", "ignore"])
def test_another_students_offer_is_404(signed_in, agency_a, domain_a, user_b, action) -> None:
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(tenant=agency_a, user=user_b, role=Membership.Role.STUDENT)
        signal = _offer(agency_a, other, _application(agency_a, other), sender="example.edu")
    response = signed_in.post(f"/student/offers/{signal.id}/{action}/", HTTP_HOST=domain_a.host)
    assert response.status_code == 404
```

Append to `tests/documents/test_document_worker.py`:

```python
def test_capture_requirements_runs_in_the_worker(agency_a, membership_a, monkeypatch):
    from uuid import uuid4

    from apps.portals import packets
    from apps.portals.models import Application

    calls = []
    monkeypatch.setattr(packets, "capture_requirements", lambda application: calls.append(application.id))
    with tenant_scope(agency_a.id):
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4()
        )

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="capture_requirements", kind="KIT", tenant_id=agency_a.id,
            student_id=membership_a.id, application_id=application.id,
        )
    )

    assert calls == [application.id]
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/portals/test_applications.py tests/documents/test_document_worker.py`
Expected: FAIL — `ImportError: apps.portals.applications`; `/student/applications/...` is 404 for every request.

- [ ] **Step 3: The service**

`apps/portals/applications.py`:

```python
"""A student's applications as the dashboard changes them (spec §7, §4a).

Every function takes the ``actor`` who pressed -- the student, or their assigned
counsellor -- and leaves an AuditEvent naming them. Nothing here names the
submitted state (tests/portals/test_boundary.py).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from functools import partial
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.dashboard.templatetags.dashboard import https_only
from apps.documents.document_queue import DocumentWorkMessage, enqueue_document_work
from apps.funding.models import AuditEvent, RecommendationCandidate
from apps.mailbox.models import MailSignal
from apps.ratelimit import rate_limited
from apps.tenancy.models import CounselorAssignment, Membership

from .actions import queue_action
from .models import Application, DeviceAction, ExtensionPairing, PortalForm
from .outcome import correct_outcome

logger = logging.getLogger(__name__)

#: Shared by Start application and Submit document: both put a device action in
#: front of the student's browser, so one budget covers both.
DEVICE_ACTION_LIMIT = 20
DEVICE_ACTION_WINDOW_SECONDS = 3600
_PORTAL_TASK_SLA = timedelta(days=3)

REFUSALS = {
    "not_found": "That programme is not in your list.",
    "comes_with_admission": (
        "This funding comes with the admission itself, so it has no application of its "
        "own: apply to the programme."
    ),
    "no_portal": (
        "We don't know this programme's application portal yet. Open the programme page; "
        "your counsellor has been asked to find it."
    ),
    "automation_prohibited": (
        "This portal does not allow filling tools. Use your Application Kit to apply by hand."
    ),
    "not_paired": "Connect the browser extension first (Settings, Extension).",
    "rate_limited": "Too many requests. Try again shortly.",
    "bad_url": "Enter the portal's full https:// address.",
}


class ApplicationRefused(Exception):
    """Refused, with a stable reason; REFUSALS holds the sentence for each."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _audit(actor: Membership, event: str, application: Application) -> None:
    AuditEvent.objects.create(actor=actor, event=event, object_id=application.id)


def _queue_capture(tenant_id: UUID, student_id: UUID, application_id: UUID) -> None:
    """After commit, so the worker finds the row. A queue failure must not turn
    a successful add into an error page; adding the same card again re-queues."""
    try:
        enqueue_document_work(
            DocumentWorkMessage(
                action="capture_requirements", kind="KIT", tenant_id=tenant_id,
                student_id=student_id, application_id=application_id,
            ),
            queue_url=settings.DOCUMENT_QUEUE_URL,
        )
    except Exception as error:
        logger.warning(
            "could not queue capture_requirements for application %s (%s)",
            application_id, type(error).__name__,
        )


def _known_portal(target: UUID) -> PortalForm | None:
    """A portal someone in this agency already recorded for the programme."""
    form_id = (
        Application.objects.filter(program_id=target, portal_form__isnull=False)
        .values_list("portal_form_id", flat=True)
        .first()
    )
    return PortalForm.objects.filter(id=form_id).first() if form_id else None


def _ask_for_portal(application: Application, programme_name: str) -> None:
    """The counsellor task of spec §7. A direct student has no counsellor: their
    card's "Open programme page" is the whole answer."""
    assignment = (
        CounselorAssignment.objects.filter(student=application.student, active=True)
        .select_related("counselor")
        .first()
    )
    if assignment is None:
        return
    item = RoadmapItem.objects.create(
        tenant_id=application.tenant_id,
        student=application.student,
        stage=RoadmapItem.Stage.APPLICATION_PREP,
        owner=assignment.counselor,
        owner_kind=RoadmapItem.OwnerKind.HUMAN,
        deadline=timezone.now() + _PORTAL_TASK_SLA,
    )
    Notification.objects.create(
        tenant_id=application.tenant_id,
        recipient=assignment.counselor,
        roadmap_item=item,
        application=application,
        message=f"Find the application portal for {programme_name}.",
    )
    application.exception_item = item
    application.save(update_fields=["exception_item"])


def add_application(*, student: Membership, candidate_id: UUID, actor: Membership) -> Application:
    """"Add to my applications" on a pack or pool item (spec §5, §7)."""
    candidate = RecommendationCandidate.objects.filter(
        id=candidate_id,
        run__profile_version__student=student,
        state=RecommendationCandidate.State.VISIBLE,
    ).first()
    if candidate is None:
        raise ApplicationRefused("not_found")
    if (candidate.funding_card or {}).get("route") == "AUTOMATIC_ON_ADMISSION":
        raise ApplicationRefused("comes_with_admission")
    existing = Application.objects.filter(student=student, candidate=candidate).first()
    if existing is not None:
        if not existing.kit_requirements and not existing.kit_letter_cycle:
            transaction.on_commit(
                partial(_queue_capture, existing.tenant_id, student.id, existing.id)
            )
        return existing
    # A named programme nobody resolved to a catalogue row has neither id; its
    # own id keeps program_id unique, and the kit then reads nothing for it.
    target = candidate.program_id or candidate.opportunity_id or candidate.id
    return _create(
        student, program_id=target, candidate=candidate, name="", portal=_known_portal(target),
        actor=actor, event="application.added", capture=True,
    )


def _create(
    student: Membership,
    *,
    program_id: UUID,
    candidate: RecommendationCandidate | None,
    name: str,
    portal: PortalForm | None,
    actor: Membership,
    event: str,
    capture: bool,
) -> Application:
    """The one way a card is made: from a pack item, or from an accepted offer."""
    application = Application.objects.create(
        tenant_id=student.tenant_id,
        student=student,
        program_id=program_id,
        candidate=candidate,
        name=name,
        portal_form=portal,
    )
    if portal is None:
        _ask_for_portal(application, application.title)
    _audit(actor, event, application)
    if capture:
        transaction.on_commit(
            partial(_queue_capture, application.tenant_id, student.id, application.id)
        )
    return application


def _same_institution(portal_host: str, sender_domain: str) -> bool:
    """The offer was mailed from the institution the original portal belongs to."""
    host, domain = portal_host.casefold(), sender_domain.casefold()
    return bool(domain) and (host == domain or host.endswith("." + domain))


def offer_for(student: Membership, signal_id: UUID) -> MailSignal | None:
    """An offer still waiting for Accept or Ignore, on one of this student's cards."""
    return (
        MailSignal.objects.select_related("application__portal_form", "application__candidate")
        .filter(
            id=signal_id,
            connection__membership=student,
            application__student=student,
            offer_handled_at__isnull=True,
        )
        .exclude(offered_programme="")
        .first()
    )


def accept_offer(signal: MailSignal, *, actor: Membership) -> Application:
    """Accept on "<University> offers you a place in <programme>" (owner, 2026-10-04).

    A new card for the offered programme, through the same path as Add to my
    applications. It has no candidate -- the programme is in no pack -- so it
    carries the letter's name for it, and the signal's id as its program_id: a
    stable id no catalogue row has, so nothing is captured for its kit. It takes
    the original card's portal when the offer came from that portal's
    institution, otherwise it starts without one and the counsellor is asked.
    The original card's outcome becomes REJECTED only when the letter said so.
    """
    original = signal.application
    assert original is not None
    student = original.student
    form = original.portal_form
    same = form is not None and _same_institution(form.portal_host, signal.sender_domain)
    application = Application.objects.filter(student=student, program_id=signal.id).first()
    if application is None:
        application = _create(
            student,
            program_id=signal.id,
            candidate=None,
            name=signal.offered_programme,
            portal=form if same else None,
            actor=actor,
            event="application.offer_accepted",
            capture=False,
        )
    # signal.outcome is Jev's reading about the original card's own programme.
    if (
        signal.outcome == Application.Outcome.REJECTED
        and original.outcome != Application.Outcome.REJECTED
    ):
        correct_outcome(original, Application.Outcome.REJECTED, actor=actor)
    signal.offer_handled_at = timezone.now()
    signal.save(update_fields=["offer_handled_at"])
    return application


def ignore_offer(signal: MailSignal, *, actor: Membership) -> None:
    """Ignore: the item goes away; the reading stays on the signal."""
    signal.offer_handled_at = timezone.now()
    signal.save(update_fields=["offer_handled_at"])
    assert signal.application is not None
    _audit(actor, "application.offer_ignored", signal.application)


def _close_portal_task(application: Application) -> None:
    if application.exception_item_id is not None:
        RoadmapItem.objects.filter(id=application.exception_item_id).update(
            state=RoadmapItem.State.DONE
        )
        application.exception_item = None
        application.save(update_fields=["exception_item"])


def remove_application(application: Application, *, actor: Membership) -> None:
    """An untouched card is deleted; anything the portal may have seen is
    withdrawn instead, so the §5.5 trail survives."""
    untouched = (
        application.state == Application.State.PREPARING
        and application.started_at is None
        and not application.steps.exists()
    )
    if not untouched:
        correct_outcome(application, Application.Outcome.WITHDRAWN, actor=actor)
        return
    _close_portal_task(application)
    _audit(actor, "application.removed", application)
    application.delete()


def _require_device_ready(application: Application) -> None:
    form = application.portal_form
    if form is None:
        raise ApplicationRefused("no_portal")
    if form.terms_posture == PortalForm.TermsPosture.PROHIBITS_AUTOMATION:
        raise ApplicationRefused("automation_prohibited")
    if not ExtensionPairing.objects.filter(
        membership=application.student, redeemed_at__isnull=False, revoked_at__isnull=True
    ).exists():
        raise ApplicationRefused("not_paired")
    if rate_limited(
        "device-action",
        application.student_id,
        limit=DEVICE_ACTION_LIMIT,
        window_seconds=DEVICE_ACTION_WINDOW_SECONDS,
    ):
        raise ApplicationRefused("rate_limited")


def start_application(application: Application, *, actor: Membership) -> DeviceAction:
    """Marks the card in progress and queues START_FILL; spec B makes the
    extension open the portal and fill. The student presses, never a counsellor
    (spec §4a) -- the counsellor views never call this."""
    _require_device_ready(application)
    if application.started_at is None:
        application.started_at = timezone.now()
        application.save(update_fields=["started_at"])
    action = queue_action(
        application.student, DeviceAction.Kind.START_FILL, {}, application=application
    )
    _audit(actor, "application.start_requested", application)
    return action


def queue_upload(
    application: Application, *, document_id: UUID, source: str, actor: Membership
) -> DeviceAction:
    """Spec §6 step 3: the extension opens this application's upload page.

    §5.6's "verify the document's intended application" is this argument: the
    caller resolved it from the item the student pressed, which names one
    application, never from the document.
    """
    _require_device_ready(application)
    action = queue_action(
        application.student,
        DeviceAction.Kind.OPEN_UPLOAD_PAGE,
        {"application_id": str(application.id), "document_id": str(document_id), "source": source},
        application=application,
    )
    _audit(actor, "application.upload_requested", application)
    return action


def record_portal(application: Application, form_url: str, *, actor: Membership) -> PortalForm:
    """A person recorded where this programme is applied for (spec §7).

    PortalForm is platform-shared: an existing (host, path) row is reused and
    never modified, so one agency's entry cannot rewrite a row another relies on.
    """
    url = https_only(form_url)
    if not url or len(url) > 500:
        raise ApplicationRefused("bad_url")
    parts = urlsplit(url)
    form, _created = PortalForm.objects.get_or_create(
        portal_host=(parts.hostname or "").casefold(),
        form_key=(parts.path or "/")[:200],
        defaults={"form_url": url},
    )
    application.portal_form = form
    application.save(update_fields=["portal_form"])
    _close_portal_task(application)
    _audit(actor, "application.portal_recorded", application)
    return form
```

- [ ] **Step 4: The worker action**

`apps/documents/document_queue.py`, in `DocumentWorkMessage`:

```python
    action: Literal["generate", "render", "capture_requirements"]
```

and after `programme_id`:

```python
    #: capture_requirements only: the Application whose kit copy to write.
    application_id: UUID | None = None
```

`apps/documents/document_worker.py`:

```python
def handle_document_work(message: DocumentWorkMessage) -> None:
    if message.action == "generate":
        _generate(message)
    elif message.action == "capture_requirements":
        _capture(message)
    else:
        _render(message)


def _capture(message: DocumentWorkMessage) -> None:
    """Copy the kit's catalogue parts onto a new Application (dashboard spec §7).

    Here because this worker runs as runtime_engine, which may read the
    catalogue; the web tier that created the Application may not.
    """
    from apps.portals import packets
    from apps.portals.models import Application

    if message.application_id is None:
        raise ValueError("capture message carries no application_id")
    with tenant_scope(message.tenant_id):
        with transaction.atomic():
            set_local_tenant(message.tenant_id)
            application = Application.objects.select_related("student").get(
                id=message.application_id
            )
        packets.capture_requirements(application)
```

- [ ] **Step 5: The student views and routes**

Append to `apps/portals/views.py` (imports: `from django.contrib import messages`, `from django.http import Http404`, `from django.shortcuts import redirect`, `from .applications import REFUSALS, ApplicationRefused, accept_offer, add_application, ignore_offer, offer_for, remove_application, start_application`, `from .outcome import correct_outcome`):

```python
def _own_application(request: HttpRequest, application_id: UUID) -> tuple[Membership, Application]:
    student = current_membership(request, Membership.Role.STUDENT)
    application = get_object_or_404(
        Application.objects.select_related("portal_form", "candidate"),
        id=application_id,
        student=student,
    )
    return student, application


@login_required
@require_POST
def application_add(request: HttpRequest, candidate_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    try:
        add_application(student=student, candidate_id=candidate_id, actor=student)
    except ApplicationRefused as refused:
        if refused.reason == "not_found":
            raise Http404 from refused
        messages.error(request, REFUSALS[refused.reason])
        return redirect("student-recommendation")
    messages.success(request, "Added to your applications.")
    return redirect("concierge-student-dashboard")


@login_required
@require_POST
def application_start(request: HttpRequest, application_id: UUID) -> HttpResponse:
    student, application = _own_application(request, application_id)
    try:
        start_application(application, actor=student)
    except ApplicationRefused as refused:
        messages.error(request, REFUSALS[refused.reason])
    else:
        messages.success(request, f"Your browser extension is opening {application.where}.")
    return redirect("concierge-student-dashboard")


@login_required
@require_POST
def application_outcome(request: HttpRequest, application_id: UUID) -> HttpResponse:
    student, application = _own_application(request, application_id)
    try:
        correct_outcome(application, request.POST.get("outcome", ""), actor=student)
    except ValueError:
        messages.error(request, "Choose an outcome from the list.")
    else:
        messages.success(request, "Saved.")
    return redirect("concierge-student-dashboard")


@login_required
@require_POST
def application_remove(request: HttpRequest, application_id: UUID) -> HttpResponse:
    student, application = _own_application(request, application_id)
    remove_application(application, actor=student)
    messages.success(request, "Removed from your applications.")
    return redirect("concierge-student-dashboard")


@login_required
@require_POST
def offer_accept(request: HttpRequest, signal_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    signal = offer_for(student, signal_id)
    if signal is None:
        raise Http404
    application = accept_offer(signal, actor=student)
    messages.success(request, f"{application.title} is on your board.")
    return redirect("concierge-student-dashboard")


@login_required
@require_POST
def offer_ignore(request: HttpRequest, signal_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    signal = offer_for(student, signal_id)
    if signal is None:
        raise Http404
    ignore_offer(signal, actor=student)
    return redirect("concierge-student-dashboard")
```

Append to `apps/portals/urls.py`'s `urlpatterns`:

```python
    path(
        "student/applications/add/<uuid:candidate_id>/",
        views.application_add,
        name="student-application-add",
    ),
    path(
        "student/applications/<uuid:application_id>/start/",
        views.application_start,
        name="student-application-start",
    ),
    path(
        "student/applications/<uuid:application_id>/outcome/",
        views.application_outcome,
        name="student-application-outcome",
    ),
    path(
        "student/applications/<uuid:application_id>/remove/",
        views.application_remove,
        name="student-application-remove",
    ),
    path("student/offers/<uuid:signal_id>/accept/", views.offer_accept, name="student-offer-accept"),
    path("student/offers/<uuid:signal_id>/ignore/", views.offer_ignore, name="student-offer-ignore"),
```

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/portals tests/documents tests/mailbox`
Expected: PASS (including `tests/portals/test_boundary.py`: no `SUBMITTED` in `applications.py`).

- [ ] **Step 7: Lint and types**

Run: `uv run ruff check . && uv run mypy apps config`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add apps/portals apps/documents/document_queue.py apps/documents/document_worker.py tests/portals/test_applications.py tests/documents/test_document_worker.py && git commit -m "feat(portals): add, remove, start and record the portal of an application

Add creates the card from a pack candidate, reusing a portal the agency already
recorded or asking the assigned counsellor to find one; capture_requirements is
queued to the document worker. Start needs a portal and a paired extension,
marks the card in progress and queues START_FILL under a per-student limit.
Accept on an offer for another programme makes its card (same portal when the
same institution offers it) and records the refusal the letter stated; Ignore
dismisses it. Every write is audited with the actor who pressed.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 10: The board — columns and cards

Spec §4. `column_for`, `outcome_line` and `build_card` are pure; `board_for` queries tenant tables only (`reads_no_catalogue` pins it). Paths to pages built later (documents, messages) are literal, like `base.html`'s nav; action URLs come from `routes.action_url`, which knows which actions each viewer gets (a counsellor never gets Start or the kit — spec §4a). Counsellor route names are registered in Task 20; until then only `counselor_view=False` is exercised.

**Files:**
- Create: `apps/dashboard/routes.py`, `apps/dashboard/board.py`, `tests/dashboard/conftest.py`, `tests/dashboard/test_board.py`

**Interfaces:**
- Produces: `routes.action_url(counselor_view: bool, action: str, student_id: UUID, *args: UUID) -> str` — actions `start`, `outcome`, `remove`, `kit`, `acknowledge`, `portal`, `accept_offer`, `ignore_offer`; `""` when the viewer does not get it
- Produces: `board.Column` (`TO_START`, `IN_PROGRESS`, `SUBMITTED`, `CONFIRMED`, `DECISION`; values are the column headings)
- Produces: `board.column_for(application: Application) -> Column`, `board.outcome_line(application: Application, evidence_domain: str) -> str`
- Produces: `board.Card` (fields below; `offer: Offer | None` is an unhandled offer of another programme), `board.Offer(signal_id: UUID, institution: str, programme: str, accept_url: str, ignore_url: str)`, `board.Button(label: str, url: str, method: str = "get")`, `board.FundingLine(name: str, covers: str, amounts: str)`, `board.Board(columns: tuple[tuple[Column, tuple[Card, ...]], ...])` with `.cards`
- Produces: `board.board_for(student: Membership, *, counselor_view: bool = False, now: datetime | None = None) -> Board`

- [ ] **Step 1: Shared fixtures for the dashboard tests**

`tests/dashboard/conftest.py`:

```python
"""A published pack with a programme and the award that funds it."""

from uuid import uuid4

import pytest

from apps.funding.models import FundingOpportunity, RecommendationCandidate
from apps.portals.models import Application, PortalForm
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run


@pytest.fixture
def pack(agency_a, membership_a, program_factory):
    programme_row = program_factory(name="M.Sc. Informatics")
    award_row = FundingOpportunity.objects.create(
        canonical_key=f"award:{uuid4()}", name="DAAD Study Scholarship",
        family="UNIVERSITY_WIDE", scope_type="GLOBAL",
    )
    run = make_run(agency_a, membership_a)
    programme = make_db_candidate(
        agency_a, run, program_name="M.Sc. Informatics", funding_gap="1200.00"
    )
    award = make_db_candidate(agency_a, run, program_name="DAAD Study Scholarship")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=programme.id).update(
            program_id=programme_row.id, institution_name="TUM", country_code="DE",
            application_fee="75.00", application_fee_currency="EUR",
        )
        RecommendationCandidate.objects.filter(id=award.id).update(
            opportunity_id=award_row.id,
            funds_program_ids=[programme_row.id],
            funding_card={
                "scope": "HOLDER", "holder": "DAAD", "tuition": "NONE", "living": "FULL",
                "amounts": ["934 EUR a month"], "deadline": "2026-11-15",
            },
        )
        programme.refresh_from_db()
        award.refresh_from_db()
    make_published_pack(agency_a, run, (programme, award))
    return programme, award


def add_card(agency, student, candidate, *, portal=True, **fields) -> Application:
    form = (
        PortalForm.objects.create(
            portal_host="campus.tum.de", form_key=f"k-{uuid4()}",
            form_url="https://campus.tum.de/apply",
        )
        if portal
        else None
    )
    return Application.objects.create(
        tenant=agency,
        student=student,
        program_id=candidate.program_id or candidate.opportunity_id,
        candidate=candidate,
        portal_form=form,
        **fields,
    )
```

- [ ] **Step 2: Write the failing tests**

`tests/dashboard/test_board.py`:

```python
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.dashboard.board import Column, board_for, column_for, outcome_line
from apps.funding.models import EvidenceClaim
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from tests.conftest import reads_no_catalogue

from .conftest import add_card

NOW = timezone.now()


def _app(**fields) -> Application:
    return Application(program_id=uuid4(), **fields)


@pytest.mark.parametrize(
    ("fields", "column"),
    [
        ({}, Column.TO_START),
        ({"started_at": NOW}, Column.IN_PROGRESS),
        ({"state": "READY_TO_SUBMIT"}, Column.IN_PROGRESS),
        ({"state": "BLOCKED_MISSING_FACT"}, Column.IN_PROGRESS),
        ({"state": "SUBMITTED"}, Column.SUBMITTED),
        ({"state": "CONFIRMED"}, Column.CONFIRMED),
        ({"state": "CONFIRMED", "decision_available_at": NOW}, Column.DECISION),
        ({"state": "SUBMITTED", "outcome": "REJECTED"}, Column.DECISION),
    ],
)
def test_column_for_follows_the_spec_table(fields, column) -> None:
    assert column_for(_app(**fields)) is column


def test_outcome_line_names_the_source_and_the_day() -> None:
    when = NOW.replace(month=10, day=3)
    application = _app(outcome="ADMITTED", outcome_source="MAIL", outcome_recorded_at=when)
    assert outcome_line(application, "tum.de") == "Admitted — from tum.de's email, 3 Oct"


def test_a_decision_without_an_outcome_says_where_to_read_it() -> None:
    assert outcome_line(_app(decision_available_at=NOW), "") == (
        "Decision available — open the email or your portal to read it"
    )


def test_an_unrecorded_reading_and_an_abstention_both_ask_the_person() -> None:
    assert outcome_line(_app(decision_available_at=NOW), "", read="ADMITTED") == (
        "Decision available — the email reads: Admitted. Confirm it below."
    )
    assert outcome_line(_app(), "", unconfirmed=True).startswith("Decision available — confirm")


@pytest.mark.django_db
def test_a_card_reads_its_copies_and_links_the_funding_both_ways(
    agency_a, membership_a, pack
) -> None:
    programme, award = pack
    with tenant_scope(agency_a.id):
        add_card(
            agency_a, membership_a, programme,
            deadline=NOW + timedelta(days=10), deadline_timezone="Europe/Berlin",
            kit_requirements=["Transcript of records", "A CV in English"],
        )
        add_card(agency_a, membership_a, award, portal=False)
        with reads_no_catalogue():
            board = board_for(membership_a)

    cards = {card.title: card for card in board.cards}
    card = cards["M.Sc. Informatics"]
    assert card.column is Column.TO_START
    assert (card.institution, card.country) == ("TUM", "DE")
    assert (card.fee, card.fee_currency) == (Decimal("75.00"), "EUR")
    assert card.gap == "1200.00 EUR"
    assert card.documents == (0, 2)
    assert card.missing == ("CV", "Transcript")
    assert card.needs == ("DAAD Study Scholarship",)
    assert cards["DAAD Study Scholarship"].funds == ("M.Sc. Informatics",)
    assert [(line.name, line.covers) for line in card.funding] == [
        ("DAAD Study Scholarship", "living: full")
    ]
    assert (card.button.label, card.button.method) == ("Start application", "post")
    assert card.deadline_local.tzinfo.key == "Europe/Berlin"


@pytest.mark.django_db
def test_a_card_without_a_portal_offers_the_programme_page(agency_a, membership_a, pack) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme, portal=False)
        card = board_for(membership_a).cards[0]
    assert card.has_portal is False
    assert card.button.label == "Open programme page"
    assert card.button.url == programme.evidence.source_url


@pytest.mark.django_db
def test_a_javascript_programme_url_gives_no_button(agency_a, membership_a, pack) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        EvidenceClaim.objects.filter(id=programme.evidence_id).update(
            source_url="javascript:alert(1)"
        )
        add_card(agency_a, membership_a, programme, portal=False)
        card = board_for(membership_a).cards[0]
    assert card.button is None
    assert card.programme_url == ""


@pytest.mark.django_db
def test_a_decision_card_reads_the_outcome_and_badges_recent_mail(
    agency_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, state="SUBMITTED")
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT",
            address="amina@outlook.test",
        )
        signal = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-1",
            sender_domain="tum.de", received_at=NOW, application=application,
            label="DECISION", outcome="ADMITTED",
            funding_outcome="REJECTED",
        )
        Application.objects.filter(id=application.id).update(
            outcome="ADMITTED", outcome_source="MAIL", outcome_recorded_at=NOW,
            outcome_evidence=signal,
        )
        card = board_for(membership_a).cards[0]
    assert card.column is Column.DECISION
    assert card.outcome_line.startswith("Admitted — from tum.de's email")
    assert card.badges == ("A decision",)
    assert card.funding_outcome_line == "Funding: Not admitted — from tum.de's email"
    assert (card.button.label, card.button.url) == ("Open portal", "https://campus.tum.de/apply")


@pytest.mark.django_db
def test_offer_conditions_are_missing_items(agency_a, membership_a, pack) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, state="SUBMITTED")
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT", address="a@o.test"
        )
        signal = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-2",
            sender_domain="ed.ac.uk", received_at=NOW, application=application,
            label="DECISION", outcome="ADMITTED_CONDITIONAL",
            outcome_conditions=["final transcript"],
        )
        Application.objects.filter(id=application.id).update(
            outcome="ADMITTED_CONDITIONAL", outcome_source="MAIL", outcome_recorded_at=NOW,
            outcome_evidence=signal,
        )
        card = board_for(membership_a).cards[0]
    assert "Condition: final transcript" in card.missing


@pytest.mark.django_db
def test_an_offer_for_another_programme_waits_on_its_card(agency_a, membership_a, pack) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, state="SUBMITTED")
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT", address="a@o.test"
        )
        signal = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-3",
            sender_domain="tum.de", received_at=NOW, application=application,
            label="DECISION", offered_programme="M.Sc. Data Engineering",
        )
        card = board_for(membership_a).cards[0]
        MailSignal.objects.filter(id=signal.id).update(offer_handled_at=NOW)
        handled = board_for(membership_a).cards[0]
    assert (card.offer.institution, card.offer.programme) == ("TUM", "M.Sc. Data Engineering")
    assert card.offer.accept_url == f"/student/offers/{signal.id}/accept/"
    assert card.offer.ignore_url == f"/student/offers/{signal.id}/ignore/"
    assert handled.offer is None
```

- [ ] **Step 3: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/dashboard/test_board.py`
Expected: FAIL — `ModuleNotFoundError: apps.dashboard.board`.

- [ ] **Step 4: Routes**

`apps/dashboard/routes.py`:

```python
"""Which URL each card and item action has, for the viewer (spec §4a)."""

from __future__ import annotations

from uuid import UUID

from django.urls import reverse

_STUDENT = {
    "start": "student-application-start",
    "outcome": "student-application-outcome",
    "remove": "student-application-remove",
    "kit": "portals-application-kit",
    "acknowledge": "concierge-acknowledge-notification",
    "accept_offer": "student-offer-accept",
    "ignore_offer": "student-offer-ignore",
}
#: No "start" and no "kit": the fill runs in the student's own browser through
#: the student's own extension (spec §4a), and the kit page is the student's.
_COUNSELOR = {
    "outcome": "counselor-student-outcome",
    "remove": "counselor-student-application-remove",
    "acknowledge": "counselor-student-acknowledge",
    "portal": "counselor-student-application-portal",
    "accept_offer": "counselor-student-offer-accept",
    "ignore_offer": "counselor-student-offer-ignore",
}


def action_url(counselor_view: bool, action: str, student_id: UUID, *args: UUID) -> str:
    """The URL for ``action``, or "" when this viewer does not get that action."""
    if counselor_view:
        name = _COUNSELOR.get(action)
        return reverse(name, args=[student_id, *args]) if name else ""
    name = _STUDENT.get(action)
    return reverse(name, args=list(args)) if name else ""
```

- [ ] **Step 5: The board**

`apps/dashboard/board.py`:

```python
"""The board: one card per application, in five columns (dashboard spec §4).

`column_for`, `outcome_line` and `build_card` are pure functions over rows the
caller has read. `board_for` is the one function that queries, and it reads
tenant tables only: the card's programme facts are the copies the worker wrote
onto RecommendationCandidate, and the kit is built from the Application's copy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from apps.documents.table import Table, table_for
from apps.funding.grouping import funds
from apps.funding.models import PackCandidate, RecommendationCandidate
from apps.funding.services import current_pack
from apps.mailbox.models import MailSignal
from apps.portals.models import Application
from apps.portals.outcome import is_funding_application
from apps.portals.packets import ApplicationKit, build_kit
from apps.tenancy.models import Membership

from .routes import action_url
from .templatetags.dashboard import https_only

# ponytail: a fixed window, not "unread" -- nothing records that the student
# opened a message. Add a seen-at on the signal if badges must clear on reading.
BADGE_WINDOW = timedelta(days=14)
_RECOGNISED = frozenset(
    {"RECEIVED", "DOCUMENT_REQUEST", "INTERVIEW", "DECISION", "VERIFICATION", "FEE"}
)


class Column(StrEnum):
    TO_START = "To start"
    IN_PROGRESS = "In progress"
    SUBMITTED = "Submitted"
    CONFIRMED = "Confirmed"
    DECISION = "Decision"


def column_for(application: Application) -> Column:
    """Spec §4's table: state plus decision_available_at and outcome."""
    if application.decision_available_at is not None or application.outcome:
        return Column.DECISION
    if application.state == Application.State.CONFIRMED:
        return Column.CONFIRMED
    if application.state == Application.State.SUBMITTED:
        return Column.SUBMITTED
    if application.state == Application.State.PREPARING and application.started_at is None:
        return Column.TO_START
    return Column.IN_PROGRESS


@dataclass(frozen=True)
class Button:
    label: str
    url: str
    method: str = "get"


@dataclass(frozen=True)
class FundingLine:
    name: str
    covers: str
    amounts: str


@dataclass(frozen=True)
class Offer:
    """A letter's offer of a place on another programme (owner, 2026-10-04)."""

    signal_id: UUID
    institution: str
    programme: str
    accept_url: str
    ignore_url: str


@dataclass(frozen=True)
class Card:
    application_id: UUID
    title: str
    institution: str
    country: str
    column: Column
    created_at: datetime
    deadline: datetime | None
    deadline_local: datetime | None
    days_left: int | None
    documents: tuple[int, int]
    answers: tuple[int, int]
    funding: tuple[FundingLine, ...]
    funding_outcome_line: str
    funds: tuple[str, ...]
    needs: tuple[str, ...]
    gap: str
    fee: Decimal | None
    fee_currency: str
    badges: tuple[str, ...]
    missing: tuple[str, ...]
    outcome_line: str
    offer: Offer | None
    button: Button | None
    has_portal: bool
    portal_url: str
    programme_url: str
    kit_url: str
    documents_url: str
    outcome_url: str
    remove_url: str
    portal_record_url: str


@dataclass(frozen=True)
class Board:
    columns: tuple[tuple[Column, tuple[Card, ...]], ...]

    @property
    def cards(self) -> tuple[Card, ...]:
        return tuple(card for _column, cards in self.columns for card in cards)


def _local(deadline: datetime | None, zone: str) -> datetime | None:
    """The deadline in the portal's own zone (spec §4), or as stored."""
    if deadline is None:
        return None
    try:
        return deadline.astimezone(ZoneInfo(zone)) if zone else deadline
    except (ZoneInfoNotFoundError, ValueError):
        return deadline


def _covers(card: dict[str, object]) -> str:
    return ", ".join(
        f"{name}: {str(card.get(name)).lower()}"
        for name in ("tuition", "living")
        if card.get(name) in ("FULL", "PARTIAL")
    )


def _source_text(source: str, domain: str) -> str:
    if source == Application.OutcomeSource.MAIL:
        return f"from {domain}'s email" if domain else "from an email"
    if source == Application.OutcomeSource.PORTAL:
        return "from your portal"
    if source == Application.OutcomeSource.PERSON:
        return "recorded by hand"
    return ""


def outcome_line(
    application: Application, evidence_domain: str, *, read: str = "", unconfirmed: bool = False
) -> str:
    """"Admitted — from tum.de's email, 3 Oct", or one of the "Decision available" lines.

    ``read`` is what Jev read the email as when it was not recorded (bars not yet
    learned): the person is asked to confirm it. ``unconfirmed`` is a DECISION
    mail Jev abstained on or could not read: the card asks too (spec §4).
    """
    if application.outcome:
        label = Application.Outcome(application.outcome).label
        source = _source_text(application.outcome_source, evidence_domain)
        when = application.outcome_recorded_at
        day = f", {when.day} {when:%b}" if when is not None else ""
        return f"{label} — {source}{day}" if source else label
    if application.decision_available_at is not None and read:
        label = Application.Outcome(read).label
        return f"Decision available — the email reads: {label}. Confirm it below."
    if application.decision_available_at is not None:
        return "Decision available — open the email or your portal to read it"
    if unconfirmed:
        return "Decision available — confirm: open the email or your portal, then record it below."
    return ""


def _conditions(application: Application) -> tuple[str, ...]:
    """Spec §4: each condition of a conditional offer is a missing item."""
    signal = application.outcome_evidence
    if application.outcome != Application.Outcome.ADMITTED_CONDITIONAL or signal is None:
        return ()
    raw = signal.outcome_conditions
    if not isinstance(raw, list):  # an erased signal's JSON is {}
        return ()
    return tuple(f"Condition: {condition}" for condition in raw if isinstance(condition, str))


def _funding_outcome_line(signals: Sequence[MailSignal]) -> str:
    for signal in signals:
        value = signal.funding_outcome
        if value:
            label = Application.Outcome(value).label
            return f"Funding: {label} — from {signal.sender_domain}'s email"
    return ""


def _offer(
    application: Application, signals: Sequence[MailSignal], *, counselor_view: bool
) -> Offer | None:
    """The newest offer of another programme still waiting for Accept or Ignore."""
    signal = next(
        (s for s in signals if s.offered_programme and s.offer_handled_at is None), None
    )
    if signal is None:
        return None
    candidate = application.candidate
    institution = (
        candidate.institution_name
        if candidate is not None and candidate.institution_name
        else signal.sender_domain
    )
    return Offer(
        signal_id=signal.id,
        institution=institution,
        programme=signal.offered_programme,
        accept_url=action_url(counselor_view, "accept_offer", application.student_id, signal.id),
        ignore_url=action_url(counselor_view, "ignore_offer", application.student_id, signal.id),
    )


def _button(
    column: Column, *, has_portal: bool, start_url: str, portal_url: str,
    programme_url: str, documents_url: str, missing: tuple[str, ...],
) -> Button | None:
    """One main button by column (spec §4)."""
    if column is Column.TO_START:
        if has_portal:
            return Button("Start application", start_url, "post") if start_url else None
        return Button("Open programme page", programme_url) if programme_url else None
    if column is Column.IN_PROGRESS:
        return Button("Continue filling", start_url, "post") if start_url else None
    if column in (Column.SUBMITTED, Column.CONFIRMED) and missing:
        return Button("Submit document", documents_url)
    return Button("Open portal", portal_url) if portal_url else None


def build_card(
    application: Application,
    *,
    kit: ApplicationKit,
    table: Table,
    signals: Sequence[MailSignal],
    awards: Sequence[RecommendationCandidate],
    linked: tuple[tuple[str, ...], tuple[str, ...]],
    counselor_view: bool,
    now: datetime,
) -> Card:
    candidate = application.candidate
    column = column_for(application)
    missing = (*table.missing_for(application.id), *_conditions(application))
    form = application.portal_form
    portal_url = https_only(form.form_url) if form is not None else ""
    programme_url = https_only(candidate.evidence.source_url) if candidate is not None else ""
    student_id = application.student_id
    documents_url = (
        f"/counselor/students/{student_id}/#application-{application.id}"
        if counselor_view
        else f"/student/documents/#application-{application.id}"
    )
    is_programme = candidate is not None and candidate.opportunity_id is None
    deadline = application.deadline
    evidence = application.outcome_evidence
    return Card(
        application_id=application.id,
        title=application.title,
        institution=candidate.institution_name if candidate is not None else "",
        country=candidate.country_code if candidate is not None else "",
        column=column,
        created_at=application.created_at,
        deadline=deadline,
        deadline_local=_local(deadline, application.deadline_timezone),
        days_left=(deadline - now).days if deadline is not None else None,
        documents=table.counts_for(application.id),
        answers=(sum(1 for q in kit.questions if not q.missing), len(kit.questions)),
        funding=tuple(
            FundingLine(
                award.program_name,
                _covers(award.funding_card or {}),
                "; ".join(str(a) for a in (award.funding_card or {}).get("amounts", [])),
            )
            for award in awards
            if is_programme and candidate is not None and funds(award, candidate)
        ),
        funding_outcome_line=(
            "" if is_funding_application(application) else _funding_outcome_line(signals)
        ),
        funds=linked[0],
        needs=linked[1],
        gap=(
            f"{candidate.funding_gap} {candidate.currency}"
            if candidate is not None and not candidate.funding_gap_is_placeholder
            else ""
        ),
        fee=candidate.application_fee if candidate is not None else None,
        fee_currency=candidate.application_fee_currency if candidate is not None else "",
        badges=tuple(
            MailSignal.Label(signal.label).label
            for signal in signals
            if signal.label in _RECOGNISED and signal.received_at >= now - BADGE_WINDOW
        ),
        missing=missing,
        outcome_line=outcome_line(
            application,
            evidence.sender_domain if evidence else "",
            read=next((s.outcome for s in signals if s.outcome), ""),
            unconfirmed=any(
                s.label == "DECISION" and (s.decision_reading or {}).get("is_decision") is not True
                for s in signals
            ),
        ),
        offer=_offer(application, signals, counselor_view=counselor_view),
        button=_button(
            column,
            has_portal=form is not None,
            start_url=action_url(counselor_view, "start", student_id, application.id),
            portal_url=portal_url,
            programme_url=programme_url,
            documents_url=documents_url,
            missing=missing,
        ),
        has_portal=form is not None,
        portal_url=portal_url,
        programme_url=programme_url,
        kit_url=action_url(counselor_view, "kit", student_id, application.id),
        documents_url=documents_url,
        outcome_url=action_url(counselor_view, "outcome", student_id, application.id),
        remove_url=action_url(counselor_view, "remove", student_id, application.id),
        portal_record_url=(
            action_url(counselor_view, "portal", student_id, application.id)
            if form is None
            else ""
        ),
    )


def _links(applications: Sequence[Application]) -> dict[UUID, tuple[list[str], list[str]]]:
    """"funds: TUM M.Sc." on the award's card, "needs: DAAD" on the programme's."""
    links: dict[UUID, tuple[list[str], list[str]]] = {a.id: ([], []) for a in applications}
    for award_app in applications:
        award = award_app.candidate
        if award is None or award.opportunity_id is None:
            continue
        for programme_app in applications:
            programme = programme_app.candidate
            if programme is None or programme.opportunity_id is not None:
                continue
            if funds(award, programme):
                links[award_app.id][0].append(programme_app.title)
                links[programme_app.id][1].append(award_app.title)
    return links


def board_for(
    student: Membership, *, counselor_view: bool = False, now: datetime | None = None
) -> Board:
    now = now or timezone.now()
    applications = list(
        Application.objects.filter(student=student)
        .select_related("portal_form", "candidate__evidence", "outcome_evidence")
        .order_by("created_at")
    )
    signals = list(
        MailSignal.objects.filter(application__in=applications).order_by("-received_at")
    )
    by_application: dict[UUID, list[MailSignal]] = {}
    for signal in signals:
        if signal.application_id is not None:
            by_application.setdefault(signal.application_id, []).append(signal)
    table = table_for(student, applications, signals)
    pack = current_pack(student)
    awards = (
        [
            member.candidate
            for member in PackCandidate.objects.filter(
                pack_version=pack, candidate__opportunity_id__isnull=False
            ).select_related("candidate")
        ]
        if pack is not None
        else []
    )
    links = _links(applications)
    cards = [
        build_card(
            application,
            kit=build_kit(application),
            table=table,
            signals=by_application.get(application.id, []),
            awards=awards,
            linked=(tuple(links[application.id][0]), tuple(links[application.id][1])),
            counselor_view=counselor_view,
            now=now,
        )
        for application in applications
    ]
    far = now + timedelta(days=36500)
    return Board(
        columns=tuple(
            (
                column,
                tuple(
                    sorted(
                        (card for card in cards if card.column is column),
                        key=lambda card: (card.deadline or far, card.created_at),
                    )
                ),
            )
            for column in Column
        )
    )
```

- [ ] **Step 6: Run them to see them pass**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/dashboard && uv run ruff check . && uv run mypy apps config`
Expected: PASS, no errors. (`apps/dashboard/board.py` may name `SUBMITTED`; the boundary test covers `apps/portals` only.)

- [ ] **Step 7: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add apps/dashboard tests/dashboard && git commit -m "feat(dashboard): the board's columns and cards

Pure column mapping per the spec's table and card building from tenant rows:
deadline in the portal's zone, documents and answers readiness, funding lines
and needs/funds links both ways, fee, mail badges, offer conditions as missing
items, outcome line with its source, one main button by column. https-only
links throughout; board_for reads no catalogue table.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 11: Needs you now

Spec §3. One list across everything, dated items by deadline, undated last and newest first, each with one button. A `Notification` still underlies each alert and Acknowledge still writes `acknowledged_at`; its `action` (Task 4) says which button it gets, so the writers that create the alerts set it here.

| Item | Source | Button |
|---|---|---|
| Document missing / offer condition | card `missing` | Submit document |
| Answers missing | card `answers` (kit questions) | Answer (gap interview) |
| An institution wrote; verify email | `Notification.action = OPEN_MESSAGE` (`mailbox/actions.py::_alert_student`, `sync.announce`) | Open message |
| Not started, deadline ≤ 14 days | card in To start | Start application / Open programme page |
| Fee due | card `fee`, To start or In progress | Open portal (or kit) |
| Draft to approve | `DocumentDraft` CV in `DRAFT` | Review |
| Lost grant, stale inbox | `Notification.action = RECONNECT` (`sync.announce_lost_grant`, `watch/mailbox_health.py`) | Reconnect |
| Unpaired extension | an application with a portal, no live pairing | Pair |
| Confirmation overdue | `Notification.action = OPEN_PORTAL` (`watch/watchdog.py`) | Open portal |
| Offer for another programme | card `offer` | Accept (creates the card) / Ignore (owner, 2026-10-04) |

**Files:**
- Create: `apps/dashboard/needs.py`, `tests/dashboard/test_needs.py`
- Modify: `apps/mailbox/actions.py`, `apps/mailbox/sync.py`, `apps/watch/mailbox_health.py`, `apps/watch/watchdog.py`

**Interfaces:**
- Produces: `needs.NeedItem(text: str, button: str, url: str, method: str, deadline: datetime | None, created_at: datetime, acknowledge_url: str = "", ignore_url: str = "")`
- Produces: `needs.sort_items(items: Iterable[NeedItem]) -> list[NeedItem]`
- Produces: `needs.items_from_cards(cards: Iterable[Card], *, now: datetime, answer_url: str, messages_url: str) -> list[NeedItem]`
- Produces: `needs.items_for(student: Membership, *, board: Board, counselor_view: bool = False, now: datetime | None = None) -> list[NeedItem]`

- [ ] **Step 1: Write the failing tests**

`tests/dashboard/test_needs.py`:

```python
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.dashboard.board import Board, Button, Card, Column, Offer, board_for
from apps.dashboard.needs import NeedItem, items_for, items_from_cards, sort_items
from apps.tenancy.context import tenant_scope

from .conftest import add_card

NOW = timezone.now()


def _card(**overrides) -> Card:
    fields = dict(
        application_id=uuid4(), title="TUM M.Sc.", institution="TUM", country="DE",
        column=Column.TO_START, created_at=NOW, deadline=None, deadline_local=None,
        days_left=None, documents=(0, 0), answers=(0, 0), funding=(),
        funding_outcome_line="", funds=(), needs=(), gap="", fee=None, fee_currency="",
        badges=(), missing=(), outcome_line="", offer=None,
        button=Button("Start application", "/start", "post"), has_portal=True,
        portal_url="https://campus.tum.de/apply", programme_url="", kit_url="/kit",
        documents_url="/student/documents/#application-x", outcome_url="", remove_url="",
        portal_record_url="",
    )
    fields.update(overrides)
    return Card(**fields)


def _need(text, deadline=None, created_at=NOW) -> NeedItem:
    return NeedItem(text, "", "", "get", deadline, created_at)


def test_dated_items_by_deadline_then_undated_newest_first() -> None:
    items = [
        _need("old undated", created_at=NOW - timedelta(days=2)),
        _need("late", deadline=NOW + timedelta(days=9)),
        _need("new undated", created_at=NOW),
        _need("soon", deadline=NOW + timedelta(days=1)),
    ]
    assert [i.text for i in sort_items(items)] == ["soon", "late", "new undated", "old undated"]


def test_each_card_gives_its_items_with_one_button() -> None:
    card = _card(
        deadline=NOW + timedelta(days=5), missing=("Transcript",), answers=(10, 12),
        fee=75, fee_currency="EUR",
    )
    items = items_from_cards([card], now=NOW, answer_url="/answer", messages_url="/messages")
    by_button = {item.button: item for item in items}
    assert by_button["Submit document"].text == "Transcript — needed for TUM M.Sc."
    assert by_button["Answer"].text == "2 answers missing for TUM M.Sc."
    assert by_button["Start application"].method == "post"
    assert by_button["Open portal"].url == "https://campus.tum.de/apply"


def test_a_far_deadline_does_not_ask_to_start_yet() -> None:
    card = _card(deadline=NOW + timedelta(days=30))
    items = items_from_cards([card], now=NOW, answer_url="", messages_url="")
    assert [i.button for i in items] == []


def test_an_offer_for_another_programme_asks_accept_or_ignore() -> None:
    offer = Offer(uuid4(), "Lund University", "MSc Statistics", "/accept", "/ignore")
    items = items_from_cards(
        [replace(_card(), offer=offer, column=Column.DECISION, button=None)],
        now=NOW, answer_url="", messages_url="/messages",
    )
    assert items[0].text == "Lund University offers you a place in MSc Statistics"
    assert (items[0].button, items[0].url, items[0].method) == ("Accept", "/accept", "post")
    assert items[0].ignore_url == "/ignore"


@pytest.mark.django_db
def test_an_interview_item_shows_its_time_and_sorts_by_it(agency_a, membership_a) -> None:
    from apps.mailbox.actions import apply_verdict
    from apps.mailbox.classify import MailVerdict
    from apps.mailbox.models import MailboxConnection, MailSignal
    from apps.tenancy.db import tenant_transaction

    with tenant_scope(agency_a.id):
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT", address="a@o.test"
        )
        signal = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-1",
            sender_domain="ethz.ch", received_at=NOW, trusted=True,
        )
        with tenant_transaction(agency_a.id):
            apply_verdict(
                signal, MailVerdict(label="INTERVIEW", interview_at="2027-03-12T10:00+01:00"),
                link_hosts=frozenset(), authenticated=True,
            )
        later = RoadmapItem.objects.create(
            tenant=agency_a, student=membership_a, stage=RoadmapItem.Stage.DOCUMENTS,
            owner=membership_a, deadline=NOW.replace(year=2027, month=6, day=1),
        )
        Notification.objects.create(
            tenant=agency_a, recipient=membership_a, roadmap_item=later, message="Later item"
        )
        items = items_for(membership_a, board=Board(columns=()))
    assert items[0].text.startswith("ethz.ch invited you to an interview on 12 Mar 2027, 09:00 UTC")
    assert items[0].deadline.isoformat().startswith("2027-03-12T09:00")
    assert items[1].text == "Later item"


@pytest.mark.django_db
def test_notifications_carry_their_button_and_acknowledge(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        item = RoadmapItem.objects.create(
            tenant=agency_a, student=membership_a, stage=RoadmapItem.Stage.PERSONAL_ACTION,
            owner=membership_a, deadline=NOW + timedelta(days=1),
        )
        note = Notification.objects.create(
            tenant=agency_a, recipient=membership_a, roadmap_item=item,
            message="Your Microsoft mailbox connection stopped working.",
            action=Notification.Action.RECONNECT,
        )
        items = items_for(membership_a, board=Board(columns=()))
    assert (items[0].button, items[0].url) == ("Reconnect", "/student/settings/mailbox/")
    assert items[0].acknowledge_url == f"/student/notifications/{note.id}/acknowledge/"


@pytest.mark.django_db
def test_an_unpaired_extension_asks_to_pair(agency_a, membership_a, pack) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme)
        items = items_for(membership_a, board=board_for(membership_a))
    assert ("Pair", "/student/settings/extension/") in [(i.button, i.url) for i in items]
```

Append to `tests/mailbox/test_decision_board.py`:

```python
@pytest.mark.django_db
def test_a_label_card_says_open_message_and_names_its_application(signal_on_application) -> None:
    from apps.concierge.models import Notification

    signal = signal_on_application("tum.de")
    _apply(signal, label="INTERVIEW")
    note = Notification.objects.get(application=signal.application)
    assert note.action == Notification.Action.OPEN_MESSAGE
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/dashboard/test_needs.py tests/mailbox/test_decision_board.py`
Expected: FAIL — `ModuleNotFoundError: apps.dashboard.needs`; the label card has no `application`.

- [ ] **Step 3: The notification writers set the button**

`apps/mailbox/actions.py::_alert_student`, the `Notification.objects.create(...)` call gains:

```python
        application=application,
        action=Notification.Action.OPEN_MESSAGE,
```

`apps/mailbox/sync.py::_card` gains a keyword `action: str = ""` passed as `action=action` to `Notification.objects.create`; `announce` passes `action=Notification.Action.OPEN_MESSAGE`; `announce_lost_grant` passes `action=Notification.Action.RECONNECT`; the classification-failure `_card(...)` in `_classify` passes `action=Notification.Action.OPEN_MESSAGE`.

`apps/watch/mailbox_health.py`, the stale-inbox `Notification.objects.create(...)` gains `action=Notification.Action.RECONNECT,`.

`apps/watch/watchdog.py`, the confirmation-overdue `Notification.objects.create(...)` gains `application=application,` and `action=Notification.Action.OPEN_PORTAL,`.

- [ ] **Step 4: Needs**

`apps/dashboard/needs.py`:

```python
"""Needs you now: one list across everything, sorted by deadline (spec §3).

Items come from the board's cards (pure: `items_from_cards`) and from three
queries -- unacknowledged notifications, drafts awaiting approval, the
extension's pairing. Paths to pages built in later tasks are literal.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

from apps.concierge.models import Notification
from apps.documents.models import DocumentDraft
from apps.portals.models import ExtensionPairing
from apps.tenancy.models import Membership

from .board import Board, Card, Column
from .routes import action_url
from .templatetags.dashboard import https_only

#: "Application not started, deadline near" (spec §3).
START_SOON = timedelta(days=14)
MAILBOX_URL = "/student/settings/mailbox/"
EXTENSION_URL = "/student/settings/extension/"


@dataclass(frozen=True)
class NeedItem:
    text: str
    button: str
    #: "" means no main button (Acknowledge may still be offered).
    url: str
    method: str
    deadline: datetime | None
    created_at: datetime
    acknowledge_url: str = ""
    #: A second, dismissing button ("Ignore") -- only an offer has one.
    ignore_url: str = ""


def sort_items(items: Iterable[NeedItem]) -> list[NeedItem]:
    """Dated items by deadline, then undated ones newest first (spec §3)."""
    listed = list(items)
    dated = sorted((i for i in listed if i.deadline is not None), key=lambda i: i.deadline)  # type: ignore[arg-type, return-value]
    undated = sorted(
        (i for i in listed if i.deadline is None), key=lambda i: i.created_at, reverse=True
    )
    return [*dated, *undated]


def items_from_cards(
    cards: Iterable[Card], *, now: datetime, answer_url: str, messages_url: str
) -> list[NeedItem]:
    items: list[NeedItem] = []
    for card in cards:
        for label in card.missing:
            items.append(NeedItem(
                f"{label} — needed for {card.title}", "Submit document", card.documents_url,
                "get", card.deadline, card.created_at,
            ))
        given, total = card.answers
        if total > given:
            items.append(NeedItem(
                f"{total - given} answers missing for {card.title}", "Answer", answer_url,
                "get", card.deadline, card.created_at,
            ))
        if (
            card.column is Column.TO_START
            and card.deadline is not None
            and card.deadline - now <= START_SOON
            and card.button is not None
        ):
            items.append(NeedItem(
                f"{card.title} is not started yet", card.button.label, card.button.url,
                card.button.method, card.deadline, card.created_at,
            ))
        if card.fee and card.column in (Column.TO_START, Column.IN_PROGRESS):
            items.append(NeedItem(
                f"Application fee for {card.title}: {card.fee} {card.fee_currency} — "
                "you pay this at submission",
                "Open portal", card.portal_url or card.kit_url, "get", card.deadline,
                card.created_at,
            ))
        if card.offer is not None:
            # Owner, 2026-10-04: Accept makes the offered programme a card.
            items.append(NeedItem(
                f"{card.offer.institution} offers you a place in {card.offer.programme}",
                "Accept", card.offer.accept_url, "post", None, card.created_at,
                ignore_url=card.offer.ignore_url,
            ))
    return items


def _notification_button(
    note: Notification, *, counselor_view: bool, messages_url: str
) -> tuple[str, str]:
    if note.action == Notification.Action.OPEN_MESSAGE:
        return "Open message", messages_url
    if note.action == Notification.Action.OPEN_PORTAL:
        application = note.application
        form = application.portal_form if application is not None else None
        return "Open portal", https_only(form.form_url) if form is not None else ""
    if note.action == Notification.Action.RECONNECT and not counselor_view:
        return "Reconnect", MAILBOX_URL
    return "", ""


def items_for(
    student: Membership,
    *,
    board: Board,
    counselor_view: bool = False,
    now: datetime | None = None,
) -> list[NeedItem]:
    now = now or timezone.now()
    base = f"/counselor/students/{student.id}/"
    messages_url = f"{base}#messages" if counselor_view else "/student/messages/"
    answer_url = f"{base}gap-interview/" if counselor_view else "/student/gap-interview/"
    review_url = f"{base}#documents" if counselor_view else "/student/documents/#drafts"
    items = items_from_cards(
        board.cards, now=now, answer_url=answer_url, messages_url=messages_url
    )
    for note in (
        Notification.objects.filter(recipient=student, acknowledged_at__isnull=True)
        .select_related("roadmap_item", "application__portal_form")
        .order_by("-created_at")
    ):
        label, url = _notification_button(
            note, counselor_view=counselor_view, messages_url=messages_url
        )
        items.append(NeedItem(
            note.message, label, url, "get", note.roadmap_item.deadline, note.created_at,
            action_url(counselor_view, "acknowledge", student.id, note.id),
        ))
    for draft in DocumentDraft.objects.filter(
        student=student, kind=DocumentDraft.Kind.CV, status=DocumentDraft.Status.DRAFT
    ).order_by("-created_at"):
        items.append(NeedItem(
            f"Your CV (version {draft.version}) is waiting for approval", "Review",
            review_url, "get", None, draft.created_at,
        ))
    if (
        not counselor_view
        and any(card.has_portal for card in board.cards)
        and not ExtensionPairing.objects.filter(
            membership=student, redeemed_at__isnull=False, revoked_at__isnull=True
        ).exists()
    ):
        items.append(NeedItem(
            "Connect the browser extension so it can fill your applications", "Pair",
            EXTENSION_URL, "get", None, now,
        ))
    return sort_items(items)
```

If mypy accepts `key=lambda i: i.deadline` after narrowing with a typed helper, drop the `type: ignore`; otherwise keep it as written (`deadline` is `datetime | None` and the generator filters `None`).

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/dashboard tests/mailbox tests/watch && uv run ruff check . && uv run mypy apps config`
Expected: PASS, no errors.

- [ ] **Step 6: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add apps/dashboard/needs.py apps/mailbox/actions.py apps/mailbox/sync.py apps/watch tests/dashboard/test_needs.py tests/mailbox/test_decision_board.py && git commit -m "feat(dashboard): Needs you now

One list from the cards (missing documents and conditions, answers, start soon,
fee due, another programme's offer), unacknowledged notifications with the
button their writer chose, CV drafts to approve and an unpaired extension;
dated by deadline, undated newest first. The mail, watchdog and inbox-health
writers now set each notification's button and application.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 12: Home — Needs you now, the board, the message form

Spec §2, §3, §4. `/student/` keeps its view and URL name (`concierge-student-dashboard`, which every redirect already uses); its context becomes the board and the needs list. Acknowledge and the message form are unchanged server-side. The card and needs templates are includes so the counsellor's board (Task 20) renders the same markup.

**Files:**
- Modify: `apps/concierge/views.py`, `tests/concierge/test_roadmap.py` (remove two `xfail` markers)
- Create: `templates/student/dashboard.html`, `templates/student/_needs.html`, `templates/student/_board.html`, `templates/student/_card.html`, `tests/dashboard/test_home.py`, `tests/dashboard/test_locks.py`
- Delete: `tests/templates/student/dashboard.html`

**Interfaces:**
- Consumes: `board_for`, `items_for`, `Application.Outcome.choices`
- Template context of `student/dashboard.html`: `board`, `needs`, `outcome_choices`, `error`, `error_form`, `error_field`, `form_values`

- [ ] **Step 1: Write the failing tests**

`tests/dashboard/test_home.py`:

```python
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.conftest import reads_no_catalogue

from .conftest import add_card

pytestmark = pytest.mark.django_db


def test_home_shows_needs_then_the_board(client, agency_a, domain_a, user_a, membership_a, pack):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, programme, deadline=timezone.now() + timedelta(days=5),
            kit_requirements=["Transcript of records"],
        )
    client.force_login(user_a)
    with reads_no_catalogue():
        response = client.get("/student/", HTTP_HOST=domain_a.host)
    body = response.content.decode()
    assert response.status_code == 200
    assert body.index("Needs you now") < body.index("Your applications")
    for heading in ("To start", "In progress", "Submitted", "Confirmed", "Decision"):
        assert heading in body
    assert "M.Sc. Informatics" in body
    assert "Transcript — needed for M.Sc. Informatics" in body
    assert f'action="/student/applications/{application.id}/start/"' in body
    assert "Application fee: 75.00 EUR — you pay this at submission" in body


def test_home_never_shows_another_students_card(
    client, agency_a, domain_a, user_a, membership_a, user_b, pack
):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(tenant=agency_a, user=user_b, role=Membership.Role.STUDENT)
        add_card(agency_a, other, programme)
    client.force_login(user_a)
    body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "M.Sc. Informatics" not in body


def test_a_decision_card_offers_not_right(client, agency_a, domain_a, user_a, membership_a, pack):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, programme, state="SUBMITTED", outcome="ADMITTED",
            outcome_source="MAIL", outcome_recorded_at=timezone.now(),
        )
    client.force_login(user_a)
    body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "Not right?" in body
    assert f'action="/student/applications/{application.id}/outcome/"' in body
    assert '<label for="outcome-' in body


def test_an_offer_asks_accept_or_ignore(client, agency_a, domain_a, user_a, membership_a, pack):
    from apps.mailbox.models import MailboxConnection, MailSignal

    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, state="SUBMITTED")
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT", address="a@o.test"
        )
        signal = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-1",
            sender_domain="tum.de", received_at=timezone.now(), application=application,
            label="DECISION", offered_programme="M.Sc. Data Engineering",
        )
    client.force_login(user_a)
    body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "TUM offers you a place in M.Sc. Data Engineering" in body
    assert f'action="/student/offers/{signal.id}/accept/"' in body
    assert f'action="/student/offers/{signal.id}/ignore/"' in body
```

`tests/dashboard/test_locks.py`:

```python
"""Every student page is behind the deletion lock, and the acceptance lock once f7 lands."""

import pytest

from apps.audit.models import DeletionRequest
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db

#: Each page task appends its URL (Tasks 12-19).
STUDENT_PAGES = ["/student/"]


@pytest.fixture
def locked(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED", reason="OTHER"
        )


@pytest.mark.parametrize("path", STUDENT_PAGES)
def test_every_student_page_is_behind_the_deletion_lock(
    client, domain_a, user_a, membership_a, locked, path
) -> None:
    client.force_login(user_a)
    response = client.get(path, HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert response["Location"] == "/student/account/deletion/"


@pytest.mark.parametrize("path", STUDENT_PAGES)
def test_every_student_page_is_behind_the_acceptance_lock(
    client, domain_a, user_a, membership_a, monkeypatch, path
) -> None:
    acceptance = pytest.importorskip("apps.privacy.acceptance")
    monkeypatch.setattr(acceptance, "needs_acceptance", lambda _membership: True)
    client.force_login(user_a)
    response = client.get(path, HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert response["Location"] == "/privacy/accept/"
```

In `tests/concierge/test_roadmap.py` delete the two `@pytest.mark.xfail(strict=True, reason="home page built in Task 12")` lines.

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/dashboard/test_home.py tests/dashboard/test_locks.py tests/concierge/test_roadmap.py`
Expected: FAIL — the stub `tests/templates/student/dashboard.html` renders nothing ("Needs you now" not in body); the lock test passes already (the middleware locks every path) and the acceptance test is skipped.

- [ ] **Step 3: The view**

`apps/concierge/views.py` (imports: `from apps.dashboard.board import board_for`, `from apps.dashboard.needs import items_for`, `from apps.portals.models import Application`), replace `_student_dashboard_page`'s body with:

```python
    board = board_for(student)
    return render(
        request,
        "student/dashboard.html",
        {
            "board": board,
            "needs": items_for(student, board=board),
            "outcome_choices": Application.Outcome.choices,
            "error": error,
            "error_form": error_form,
            "error_field": error_field,
            "form_values": form_values or {},
        },
        status=status,
    )
```

(`RoadmapItem` stays imported for `mark_roadmap_item_done`; `Notification` stays for the acknowledge view.)

- [ ] **Step 4: The templates**

`templates/student/dashboard.html`:

```html
{% extends "base.html" %}
{% block title %}Home{% endblock %}
{% block content %}
  <h1>Home</h1>
  {% include "student/_needs.html" %}
  {% include "student/_board.html" %}
  <section aria-labelledby="message-heading">
    <h2 id="message-heading">Write to your counsellor</h2>
    <form method="post" action="{% url 'concierge-send-student-message' %}">
      {% csrf_token %}
      {% if error and error_form == "message" %}<p role="alert" id="message-error">{{ error }}</p>{% endif %}
      <p>
        <label for="message-body">Message</label><br>
        <textarea id="message-body" name="body" rows="4" maxlength="4000"{% if error and error_form == "message" %} aria-describedby="message-error"{% endif %}>{{ form_values.body }}</textarea>
      </p>
      <button type="submit">Send</button>
    </form>
  </section>
{% endblock %}
```

`templates/student/_needs.html`:

```html
<section aria-labelledby="needs-heading">
  <h2 id="needs-heading">Needs you now</h2>
  {% if needs %}
    <ul>
      {% for item in needs %}
        <li>
          {{ item.text }}{% if item.deadline %} — due {{ item.deadline|date:"j M Y" }}{% endif %}
          {% if item.url %}
            {% if item.method == "post" %}
              {% if not read_only %}<form method="post" action="{{ item.url }}">{% csrf_token %}<button type="submit">{{ item.button }}</button></form>{% endif %}
            {% else %}
              <a href="{{ item.url }}">{{ item.button }}</a>
            {% endif %}
          {% endif %}
          {% if item.ignore_url and not read_only %}
            <form method="post" action="{{ item.ignore_url }}">{% csrf_token %}<button type="submit">Ignore</button></form>
          {% endif %}
          {% if item.acknowledge_url and not read_only %}
            <form method="post" action="{{ item.acknowledge_url }}">{% csrf_token %}<button type="submit">Acknowledge</button></form>
          {% endif %}
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <p>Nothing needs you right now.</p>
  {% endif %}
</section>
```

`templates/student/_board.html`:

```html
<section aria-labelledby="board-heading">
  <h2 id="board-heading">Your applications</h2>
  {% if not board.cards %}<p>No applications yet. Add one from Programmes &amp; funding.</p>{% endif %}
  {% for column, cards in board.columns %}
    <section aria-labelledby="column-{{ forloop.counter }}">
      <h3 id="column-{{ forloop.counter }}">{{ column }} ({{ cards|length }})</h3>
      {% for card in cards %}
        {% include "student/_card.html" %}
      {% empty %}
        <p>Nothing here.</p>
      {% endfor %}
    </section>
  {% endfor %}
</section>
```

`templates/student/_card.html` (every URL on it was built by `board.py` and passed `https_only` where it came from a third party; `read_only` is set only by the counsellor's view of a student who asked to be deleted, Task 20, and hides every form):

```html
<article id="card-{{ card.application_id }}" aria-labelledby="card-title-{{ card.application_id }}">
  <h4 id="card-title-{{ card.application_id }}">{{ card.title }}</h4>
  {% if card.institution or card.country %}<p>{{ card.institution }}{% if card.institution and card.country %} · {% endif %}{{ card.country }}</p>{% endif %}
  {% if card.deadline_local %}
    <p>Deadline: {{ card.deadline_local|date:"j M Y, H:i e" }} — {% if card.days_left < 0 %}passed{% else %}{{ card.days_left }} days left{% endif %}</p>
  {% endif %}
  <p>Documents {{ card.documents.0 }}/{{ card.documents.1 }} · Answers {{ card.answers.0 }}/{{ card.answers.1 }}</p>
  {% for line in card.funding %}
    <p>Funding: {{ line.name }}{% if line.covers %} — covers {{ line.covers }}{% endif %}{% if line.amounts %} — {{ line.amounts }}{% endif %}</p>
  {% endfor %}
  {% if card.gap %}<p>Remaining gap: {{ card.gap }}</p>{% endif %}
  {% if card.funding_outcome_line %}<p>{{ card.funding_outcome_line }}</p>{% endif %}
  {% if card.funds %}<p>Funds: {{ card.funds|join:", " }}</p>{% endif %}
  {% if card.needs %}<p>Needs: {{ card.needs|join:", " }}</p>{% endif %}
  {% if card.fee %}<p>Application fee: {{ card.fee }} {{ card.fee_currency }} — you pay this at submission</p>{% endif %}
  {% if card.badges %}<p>New mail: {{ card.badges|join:", " }}</p>{% endif %}
  {% if card.missing %}
    <p>Missing:</p>
    <ul>{% for item in card.missing %}<li>{{ item }}</li>{% endfor %}</ul>
  {% endif %}
  {% if card.outcome_line %}<p>{{ card.outcome_line }}</p>{% endif %}
  {% if card.offer %}<p>{{ card.offer.institution }} offers you a place in {{ card.offer.programme }} — accept or ignore it under Needs you now.</p>{% endif %}
  {% if card.button %}
    {% if card.button.method == "post" %}
      {% if not read_only %}<form method="post" action="{{ card.button.url }}">{% csrf_token %}<button type="submit">{{ card.button.label }}</button></form>{% endif %}
    {% else %}
      <p><a href="{{ card.button.url }}">{{ card.button.label }}</a></p>
    {% endif %}
  {% endif %}
  {% if card.kit_url %}<p><a href="{{ card.kit_url }}">Application Kit</a></p>{% endif %}
  {% if card.portal_record_url and not read_only %}
    <form method="post" action="{{ card.portal_record_url }}">
      {% csrf_token %}
      <p>
        <label for="portal-{{ card.application_id }}">Application portal address</label>
        <input type="url" id="portal-{{ card.application_id }}" name="form_url" required>
      </p>
      <button type="submit">Record the portal</button>
    </form>
  {% endif %}
  {% if card.outcome_url and card.column != "To start" and not read_only %}
    <details>
      <summary>{% if card.outcome_line %}Not right?{% else %}Record a decision{% endif %}</summary>
      <form method="post" action="{{ card.outcome_url }}">
        {% csrf_token %}
        <p>
          <label for="outcome-{{ card.application_id }}">Decision</label>
          <select id="outcome-{{ card.application_id }}" name="outcome">
            <option value="">No decision yet</option>
            {% for value, label in outcome_choices %}<option value="{{ value }}">{{ label }}</option>{% endfor %}
          </select>
        </p>
        <button type="submit">Save</button>
      </form>
    </details>
  {% endif %}
  {% if card.remove_url and card.column == "To start" and not read_only %}
    <form method="post" action="{{ card.remove_url }}">{% csrf_token %}<button type="submit">Remove from my applications</button></form>
  {% endif %}
</article>
```

```bash
cd /home/orkhan/Desktop/student-dashboard && git rm tests/templates/student/dashboard.html
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/dashboard tests/concierge tests/audit`
Expected: PASS — including the two un-xfailed roadmap tests (student nav, message rate limit with the typed text kept).

- [ ] **Step 6: Lint, types, checks**

Run: `uv run ruff check . && uv run mypy apps config && uv run python manage.py check`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add -A apps/concierge/views.py templates/student tests/dashboard tests/concierge/test_roadmap.py tests/templates && git commit -m "feat(dashboard): home page -- Needs you now above the board

The student's home renders the needs list and the five-column board with one
card per application, the outcome correction behind 'Not right?', Start
application as a POST, and the counsellor message form with its inline error.
Two kept frontend tests now run; a lock test lists every student page.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 13: Programmes & funding — the pack grouped under the funding

Spec §5. The page keeps its route and views; `_pack_context` gains the groups (pack and pool, each through `group_under_funding`), the candidates already added as applications, and `research_pending` for the meta refresh. Funding headings render the award's tenant copy; eligibility renders from the evidence claim marked *unstructured*, as the P1-9 amendment allows until the catalogue carries the structured columns. A `CHECKING` candidate never shows its placeholder source as a link (P1-7). Also the consultation report template, whose two kept tests are content rules.

**Files:**
- Modify: `apps/funding/views.py`, `apps/dashboard/templatetags/dashboard.py` (`lookup` filter), `tests/acceptance/test_vertical_slice.py`, `tests/funding/test_student_controls.py`, `tests/reports/test_consultation_report.py` (remove `xfail` markers naming Task 13; one assertion inverted), `tests/dashboard/test_locks.py`, `phased requirements.md` (P1-7 amendment)
- Create: `templates/student/recommendation_pool.html`, `templates/student/_pack.html`, `templates/student/_funding_group.html`, `templates/student/_candidate.html`, `templates/reports/consultation_report.html`, `tests/funding/test_grouped_page.py`
- Delete: `tests/templates/student/recommendation_pool.html`, `tests/templates/student/_pack.html`, `tests/templates/reports/consultation_report.html`

**Interfaces:**
- Produces: `_pack_context` keys `groups: list[FundingGroup]` (pack, with the pool as `extra`), `other_groups: list[FundingGroup]` (pool, with the pack as `extra`), `applied: set[UUID]`, `research_pending: bool` (alongside the existing `pack`, `pool`, `considered`, `totals`, `pending_count`, `recognition_notes`, `pending_line`)
- Produces: template filter `lookup(mapping, key)`

- [ ] **Step 1: Write the failing tests**

`tests/funding/test_grouped_page.py`:

```python
import pytest

from apps.funding.models import EvidenceClaim, RecommendationCandidate, RecommendationRun
from apps.funding.views import _pack_context
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from tests.conftest import reads_no_catalogue
from tests.dashboard.conftest import add_card
from tests.funding.conftest import make_db_candidate, make_run

pytestmark = pytest.mark.django_db
PAGE = "/student/recommendation/"


def test_programmes_are_grouped_under_the_funding_that_pays_for_them(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    client.force_login(user_a)
    with reads_no_catalogue():
        response = client.get(PAGE, HTTP_HOST=domain_a.host)
    body = response.content.decode()
    assert "<h1>Programmes &amp; funding</h1>" in body
    heading = body.index("<h3>DAAD Study Scholarship</h3>")
    assert body.index("M.Sc. Informatics", heading) > heading
    assert "Holder" in body and "DAAD" in body
    assert "934 EUR a month" in body
    assert "(unstructured)" in body
    assert "Programmes without separate funding" in body


def test_add_to_my_applications_and_already_added(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, award, portal=False)
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert f'action="/student/applications/add/{programme.id}/"' in body
    assert f'action="/student/applications/add/{award.id}/"' not in body
    assert "In your applications." in body


def test_funding_that_comes_with_admission_offers_no_add(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    _programme, award = pack
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=award.id).update(
            funding_card={**award.funding_card, "route": "AUTOMATIC_ON_ADMISSION"}
        )
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert f'action="/student/applications/add/{award.id}/"' not in body
    assert "Comes with the admission" in body


def test_a_javascript_source_url_is_never_a_link(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        EvidenceClaim.objects.filter(id=programme.evidence_id).update(
            source_url="javascript:alert(1)"
        )
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert 'href="javascript:' not in body


def test_the_page_reloads_itself_only_while_research_runs(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    run = make_run(agency_a, membership_a)
    client.force_login(user_a)
    assert '<meta http-equiv="refresh" content="15">' in client.get(
        PAGE, HTTP_HOST=domain_a.host
    ).content.decode()
    with tenant_scope(agency_a.id):
        RecommendationRun.objects.filter(id=run.id).update(state="DRAFT_READY")
    assert 'http-equiv="refresh"' not in client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()


def test_an_open_award_heads_every_eligible_programme_in_its_country(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, award = pack
    pool_only = make_db_candidate(agency_a, programme.run, program_name="LMU M.Sc. Physics")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=award.id).update(
            funds_program_ids=[], country_code="DE",
            funding_card={**award.funding_card, "scope": "HOLDER"},
        )
        RecommendationCandidate.objects.filter(id=pool_only.id).update(country_code="DE")
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    heading = body.index("<h3>DAAD Study Scholarship</h3>")
    label = body.index("Eligible programmes in DE:", heading)
    assert body.index("M.Sc. Informatics", label) > label
    assert body.index("(in Other options)", label) < body.index("LMU M.Sc. Physics", label)


def test_the_context_reads_no_catalogue(agency_a, membership_a, pack) -> None:
    with tenant_scope(agency_a.id), reads_no_catalogue():
        context = _pack_context(membership_a)
    assert [g.award.program_name if g.award else None for g in context["groups"]] == [
        "DAAD Study Scholarship", None,
    ]
    assert context["research_pending"] is False
```

Append `"/student/recommendation/"` to `STUDENT_PAGES` in `tests/dashboard/test_locks.py`. Delete the `xfail` markers that name Task 13.

In `tests/reports/test_consultation_report.py::test_report_content_has_required_sections_and_no_internal_reasoning` replace `assert candidate.evidence.source_url in body` with:

```python
        # P1-7.1, amendment 2026-08-28: official source URLs stay out of the
        # student-facing report; its last-checked dates stay in. The dashboard
        # amendment of 2026-10-04 lifts this for the pages, not the report.
        assert candidate.evidence.source_url not in body
        assert "last checked" in body
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/funding tests/acceptance tests/reports`
Expected: FAIL — `KeyError: 'groups'`; the stub templates render nothing.

- [ ] **Step 3: The context**

`apps/funding/views.py` (imports: `from apps.portals.models import Application`, `from .grouping import group_under_funding`; `RecommendationRun` is already imported), at the end of `_pack_context` before `return`:

```python
    research_pending = (
        pack is None
        and RecommendationRun.objects.filter(
            profile_version__student=student, state=RecommendationRun.State.QUEUED
        ).exists()
    )
    applied = set(
        Application.objects.filter(student=student, candidate__isnull=False).values_list(
            "candidate_id", flat=True
        )
    )
```

and add to the returned dict:

```python
        # Open awards head eligible programmes from both lists (owner,
        # 2026-10-04): the pack's awards also list the pool's programmes, and
        # the other way round, each marked with the list it lives in.
        "groups": group_under_funding(
            [member.candidate for member in pool],
            extra=list(considered),
            extra_label="in Other options",
        ),
        "other_groups": group_under_funding(
            list(considered),
            extra=[member.candidate for member in pool],
            extra_label="in your pack",
        ),
        "applied": applied,
        "research_pending": research_pending,
```

`apps/dashboard/templatetags/dashboard.py`, append:

```python
@register.filter
def lookup(mapping: object, key: object) -> object:
    """mapping[key], or "" -- for the dicts keyed by id that views pass."""
    return mapping.get(key, "") if isinstance(mapping, dict) else ""
```

- [ ] **Step 4: The templates**

`templates/student/recommendation_pool.html`:

```html
{% extends "base.html" %}
{% block title %}Programmes &amp; funding{% endblock %}
{% block head %}{% if research_pending %}<meta http-equiv="refresh" content="15">{% endif %}{% endblock %}
{% block content %}
  <h1>Programmes &amp; funding</h1>
  {% if research_pending %}
    <p role="status">We are still researching your programmes. This page reloads itself every 15 seconds.</p>
  {% elif not pack %}
    <p>No recommendations yet. Finish your <a href="/student/profile/">profile</a> to start.</p>
  {% endif %}
  {% include "student/_pack.html" %}
{% endblock %}
```

`templates/student/_pack.html` (also the htmx fragment the kept tests request; it carries no `<h1>`):

```html
<div id="pack">
  {% if pack %}
    <p>{% if pack.published_at %}Approved v{{ pack.version }}{% else %}Version {{ pack.version }}{% endif %}</p>
    {% if pending_line %}<p role="status">{{ pending_line }}</p>{% endif %}
    {% for currency, total in totals.items %}<p>Total funding gap: {{ total }} {{ currency }}</p>{% endfor %}
    {% if error and not error_form %}<p role="alert">{{ error }}</p>{% endif %}
    <h2>Your pack</h2>
    {% for group in groups %}{% include "student/_funding_group.html" with in_pack=True %}{% endfor %}
    <h2>Other options</h2>
    {% for group in other_groups %}{% include "student/_funding_group.html" with in_pack=False %}{% endfor %}
    <section aria-labelledby="named-heading">
      <h2 id="named-heading">Ask us to consider a programme</h2>
      <form method="post" action="{% url 'student-consider-named-program' %}">
        {% csrf_token %}
        {% if error and error_form == "named-program" %}<p role="alert" id="program-name-error">{{ error }}</p>{% endif %}
        <p>
          <label for="program-name">Programme name</label>
          <input type="text" id="program-name" name="program_name" maxlength="150" value="{{ form_values.program_name|default:'' }}"{% if error and error_form == "named-program" %} aria-describedby="program-name-error"{% endif %}>
        </p>
        <button type="submit">Ask</button>
      </form>
    </section>
  {% endif %}
</div>
```

`templates/student/_funding_group.html`:

```html
<section>
  {% if group.award %}
    {% with award=group.award card=group.award.funding_card %}
      <h3>{{ award.program_name }}</h3>
      <dl>
        {% if card.holder %}<dt>Holder</dt><dd>{{ card.holder }}</dd>{% endif %}
        <dt>Covers</dt><dd>Tuition: {{ card.tuition|default:"not stated"|lower }}; living: {{ card.living|default:"not stated"|lower }}</dd>
        {% if card.amounts %}<dt>Amount</dt><dd>{{ card.amounts|join:"; " }}</dd>{% endif %}
        <dt>Deadline</dt><dd>{{ card.deadline|default:"not stated" }}</dd>
        <dt>Eligibility <small>(unstructured)</small></dt><dd>{{ award.evidence.claim }}</dd>
        {% if card.unconfirmed %}<dt>Not confirmed</dt><dd>{{ card.unconfirmed|join:", " }}</dd>{% endif %}
      </dl>
      {% include "student/_candidate.html" with candidate=award also_under=None %}
    {% endwith %}
    <p>{{ group.label }}:</p>
  {% else %}
    <h3>{{ group.label }}</h3>
  {% endif %}
  {% if group.programmes %}
    <ul>
      {% for placed in group.programmes %}
        <li>
          {% if placed.elsewhere %}
            <p>({{ placed.elsewhere }})</p>
            {% include "student/_candidate.html" with candidate=placed.candidate also_under=placed.also_under in_pack=False %}
          {% else %}
            {% include "student/_candidate.html" with candidate=placed.candidate also_under=placed.also_under %}
          {% endif %}
        </li>
      {% endfor %}
    </ul>
  {% elif group.award %}
    <p>No programme in your list is tied to this funding. Check its eligibility.</p>
  {% else %}
    <p>None.</p>
  {% endif %}
</section>
```

`templates/student/_candidate.html`:

```html
{% load dashboard %}
<article id="candidate-{{ candidate.id }}">
  {% if candidate.opportunity_id is None %}<h4>{{ candidate.program_name }}</h4>{% endif %}
  {% if candidate.institution_name or candidate.country_code %}<p>{{ candidate.institution_name }}{% if candidate.institution_name and candidate.country_code %} · {% endif %}{{ candidate.country_code }}</p>{% endif %}
  {% if candidate.state == "CHECKING" %}<p>Under review</p>{% endif %}
  <p>Fit: {{ candidate.eligibility_status.label }}</p>
  {% if candidate.application_fee %}<p>Application fee: {{ candidate.application_fee }} {{ candidate.application_fee_currency }} — you pay this at submission</p>{% endif %}
  {% if candidate.opportunity_id is None %}
    <p>Funding gap: {% if candidate.funding_gap_is_placeholder %}not yet costed{% else %}{{ candidate.funding_gap }} {{ candidate.currency }}{% endif %}</p>
  {% endif %}
  {% if also_under %}<p>Also under {{ also_under|join:", " }}</p>{% endif %}
  {% with note=recognition_notes|lookup:candidate.id %}{% if note %}<p>{{ note }}</p>{% endif %}{% endwith %}
  {% if candidate.state != "CHECKING" %}
    <p>{{ candidate.evidence.claim }}</p>
    {% with url=candidate.evidence.source_url|https_only %}
      <p>{% if url %}<a href="{{ url }}">Official source</a> · {{ candidate.evidence.source_domain }}{% else %}Official source: {{ candidate.evidence.source_domain }}{% endif %} · Last checked {{ candidate.evidence.last_checked_at|date:"j M Y" }}</p>
    {% endwith %}
  {% endif %}
  {% if candidate.state == "VISIBLE" %}
    {% if candidate.id in applied %}
      <p>In your applications.</p>
    {% elif candidate.funding_card.route == "AUTOMATIC_ON_ADMISSION" %}
      <p>Comes with the admission: apply to the programme.</p>
    {% else %}
      <form method="post" action="{% url 'student-application-add' candidate.id %}">{% csrf_token %}<button type="submit">Add to my applications</button></form>
    {% endif %}
    {% if in_pack %}
      <form method="post" action="{% url 'student-reject-candidate' candidate.id %}">{% csrf_token %}<button type="submit">Reject</button></form>
      {% if considered %}
        <form method="post" action="{% url 'student-replace-candidate' candidate.id %}">
          {% csrf_token %}
          <label for="replace-{{ candidate.id }}">Replace with</label>
          <select id="replace-{{ candidate.id }}" name="replacement_candidate_id">
            {% for option in considered %}<option value="{{ option.id }}">{{ option.program_name }}</option>{% endfor %}
          </select>
          <button type="submit">Replace</button>
        </form>
      {% endif %}
    {% endif %}
  {% endif %}
  {% if error and error_form == candidate.id|stringformat:"s" %}<p role="alert">{{ error }}</p>{% endif %}
</article>
```

`templates/reports/consultation_report.html` (a stored document, not a page, so it does not extend `base.html`; no source URL, per P1-7.1's 2026-08-28 amendment):

```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Consultation report</title></head>
<body>
  <h1>Consultation report</h1>
  <p>Prepared by {{ pack.tenant.name }} · pack version {{ pack.version }}</p>
  {% for member in pack.pack_candidates.all %}
    <section>
      <h2>{{ member.candidate.program_name }}</h2>
      <p>Funding gap: {% if member.candidate.funding_gap_is_placeholder %}not yet costed{% else %}{{ member.candidate.funding_gap }} {{ member.candidate.currency }}{% endif %}</p>
      <p>{{ member.candidate.evidence.claim }} (last checked {{ member.candidate.evidence.last_checked_at|date:"j M Y" }})</p>
    </section>
  {% endfor %}
</body>
</html>
```

```bash
cd /home/orkhan/Desktop/student-dashboard && git rm tests/templates/student/recommendation_pool.html tests/templates/student/_pack.html tests/templates/reports/consultation_report.html
```

`phased requirements.md`, in P1-7 replace the sentence "Per the P1-7.1 amendment of 2026-08-28, the explanation is evidence-backed but does not display the official source URLs behind it." with:

```markdown
Per the P1-7.1 amendment of 2026-08-28, the explanation is evidence-backed. Amendment, 2026-10-04 (owner, `docs/superpowers/specs/2026-10-04-student-dashboard-design.md` §5): the dashboard's programme and funding pages show each item's official source link and its last-checked date, `https` links only; the student-facing report keeps the 2026-08-28 rule.
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/funding tests/acceptance tests/reports tests/dashboard`
Expected: PASS — the vertical slice, seven student-control tests and two report tests now run without `xfail`.

- [ ] **Step 6: Lint, types, checks**

Run: `uv run ruff check . && uv run mypy apps config && uv run python manage.py check`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add -A apps/funding/views.py apps/dashboard templates/student templates/reports tests "phased requirements.md" && git commit -m "feat(funding): programmes and funding, grouped under the funding

The pack and the pool render as one group per award (holder, what it covers,
amount, deadline, eligibility marked unstructured) with the programmes it pays
for beneath -- an open award heads every eligible programme in its country from
both lists -- 'also under' and a closing unfunded group; Add to my applications,
Reject and Replace on each item; official source links https-only; a meta
refresh only while research runs. The consultation report template lands too.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 14: Uploads reach the extension — check the file, promote the clean copy, serve it to the paired device

Spec §6 step 3 and "Upload safety" (owner, 2026-10-04). An upload stays at `quarantine/{tenant}/{document}` forever, and the web tier may only *write* there (`WebTaskRole`); `download_document` serves approved drafts only. So a scanned-clean upload that passes the upload check is copied to the student's own prefix, `tenants/{tenant}/students/{student}/uploads/{document_id}/{version}`, and a device-token route streams it to the paired extension (spec B attaches it).

**Who copies, and the IAM it needs — a correction to the brief.** `DocumentScanRole` is GuardDuty's service role (`Principal: malware-protection-plan.guardduty.amazonaws.com`, `infra/template.yaml` ~602): it runs no code of ours, so a `PutObject` grant there would hand a third party's role a write capability and copy nothing. The scan *result* is handled by `apps/documents/document_worker.py::handle_scan_result` under `DocumentWorkerTaskRole`, which already holds `s3:GetObject` on `quarantine/*` and `s3:GetObject`/`s3:PutObject` on `tenants/*` (pinned by `tests/infra/test_template.py::test_the_document_worker_reads_quarantine_and_writes_tenant_objects`). Promotion therefore needs **no new grant**. The infra test added here pins that `DocumentScanRole` holds no `s3:Put*` on objects and that the document worker still has exactly the two grants promotion uses; the web tier already reads `tenants/*`.

**The upload check, and where it runs.** Promotion happens only when all three hold: GuardDuty said `NO_THREATS_FOUND`, the file's own first bytes are PDF (`%PDF-`), JPEG (`FF D8 FF`) or PNG (`89 50 4E 47 0D 0A 1A 0A`), and a PDF carries no active content (`/JS`, `/JavaScript`, an `/OpenAction` or `/AA` that runs a script or a program, `/Launch`, `/EmbeddedFiles`/`/EmbeddedFile`, `/RichMedia`, an XFA form). Anything else ends in a terminal state the student sees with what to do: `REJECTED_TYPE` ("Upload a PDF, JPEG or PNG") or `REJECTED_ACTIVE_CONTENT` ("This PDF contains active content; save it again as a plain PDF (Print → Save as PDF) and upload that"). A PDF is **never rewritten**: stripping its content breaks a signed document (Azerbaijan's TMİS e-diplomas verify only byte for byte), so a clean one is copied unchanged. Parsing a hostile PDF is the risky act, so the check runs where this system already parses untrusted uploads — the isolated OCR function (`OcrPrivateSubnet*`, a route table with no default route, an S3 endpoint allowing only `GetObject` on `quarantine/*`, and a role that reads only objects GuardDuty tagged clean). It is a second operation on the existing entry point, `{"key": ..., "op": "inspect"}` → `{"type": ..., "active_content": [...]}`; locally it is the same child process the OCR path runs, with `--inspect`. The function writes nothing, so the worker does the copy. No infra change: same function, same role, same subnets.

**The library: pypdf, added to the OCR image, and why.** The image carries pypdfium2 (`ocr/read_pages.py` imports it), but pdfium's public API has no getter for the document's `/OpenAction` — only `FORM_DoDocumentOpenAction`, which *runs* it inside a form-fill environment — and no general walk of the object tree for `/Launch` in an annotation's `/AA` or a `/RichMedia` annotation (checked against `pypdfium2_raw/bindings.py`: the action and JavaScript surface is `FPDFDoc_GetJavaScriptActionCount` for the name tree, `FPDFAction_GetType` for links and bookmarks, `FPDF_GetFormType`, `FPDF_GetPageAAction`). pypdf reads the object tree without executing anything, is pure Python (no native code added to the image), and is already this app's dependency on the same line (`pypdf>=6.19.0,<7`). It is added with `uv add --project ocr`, which rewrites `ocr/uv.lock` — never by hand — and CI's `pip-audit` step over the OCR graph (`ci.yml` ~44-49) audits it from then on. `bake()` gains one inspection, so the image build proves pypdf is importable with `--network=none`.

`{version}` is the first 16 hex characters of the content's SHA-256: the key is fixed by the bytes, so a redelivered scan message writes the same key, and the row's `promoted_key` makes a redelivery a no-op. Erasure needs no new code: `delete_student_documents` purges `tenants/{t}/students/{s}/` with every version, which covers `uploads/`.

**A new state, `CHECKING`, so `AVAILABLE` always means checked and promoted.** A clean verdict for an upload not yet promoted commits `CHECKING`, never `AVAILABLE`, and only `_check_and_promote` leaves it: to `AVAILABLE` (promoted, in the same transaction as the copy's key), to `REJECTED_TYPE` / `REJECTED_ACTIVE_CONTENT`, or — when the check never answers — to `REVIEW_REQUIRED` via `mark_read_failed` on the last delivery. So every consumer that reads `AVAILABLE` — `open_document` (and through it CV ingestion and the transcript read), the documents table (Task 7's `table_for`), `upload_status`, Submit document (Task 15), `/ext/documents` — sees an unchecked file as not usable, whether or not it reads `promoted_key`. The minimal place for it is `handle_scan_result`, not `SCAN_STATES`: `apply_scan_result` has no other production caller, and about twenty existing tests use `apply_scan_result(..., "NO_THREATS_FOUND")` as the fixture for "an AVAILABLE document" before calling ingestion directly; remapping `SCAN_STATES` would break every one for no gain. `handle_scan_result` overwrites `AVAILABLE` with `CHECKING` inside the transaction `apply_scan_result` writes in, so `AVAILABLE` is never committed for an unchecked file. The `CHECKING` state is committed before the check, in its own short transaction, as the transcript read already does: the check is a call to the function (a cold start can take seconds), and a task that dies during it leaves the document `CHECKING` for the redelivery to check again. A redelivered clean verdict never reopens a rejected upload. Ingestion and the transcript read are triggered after promotion, in a second transaction, and `open_document` (`AVAILABLE` only) keeps guarding them; `_check_and_promote` reads the quarantined bytes from the store directly, because deciding whether the file may become `AVAILABLE` is its job. An HTML file named `cv.pdf` is therefore never parsed by either reader.

**Files:**
- Modify: `apps/concierge/models.py`, `apps/audit/redaction.py`, `apps/documents/storage.py`, `apps/documents/ocr.py`, `apps/documents/document_worker.py`, `apps/documents/api.py`, `apps/documents/table.py`, `apps/portals/ext_api.py`, `apps/portals/urls.py`, `ocr/read_pages.py`, `ocr/test_read_pages.py`, `tests/documents/conftest.py`, `tests/documents/test_ocr.py`, `tests/documents/test_table.py`, `tests/documents/test_document_worker.py` (one stale docstring sentence), `tests/infra/test_template.py`, `tests/audit/test_deletion_purges_documents.py`
- Modify (by `uv add --project ocr`, never by hand): `ocr/pyproject.toml`, `ocr/uv.lock`
- Create (generated): `apps/concierge/migrations/0010_upload_promotion.py`
- Create: `ocr/pdf_fixtures.py`, `tests/documents/test_upload_promotion.py`, `tests/portals/test_ext_document.py`

**Interfaces:**
- Produces: `DocumentVersion.promoted_key` (REDACT), `DocumentVersion.content_type` (KEEP), `DocumentVersion.state` widened to 30 characters (`REJECTED_ACTIVE_CONTENT` is 23), `DocumentVersion.rejection_message` (property, `""` unless rejected)
- Produces: the `DocumentVersion.state` value `CHECKING` (scanned clean, check pending). From this task on, `AVAILABLE` means scanned clean, checked and promoted
- Produces: `apps.documents.table.Cell.CHECKING` (`"checking…"`): shown in the table, counted neither held nor missing
- Produces: `apps.concierge.models.UPLOAD_REJECTIONS: dict[str, str]` — `REJECTED_TYPE` and `REJECTED_ACTIVE_CONTENT` → the student's message
- Produces: `ocr/read_pages.py::inspect(data: bytes) -> dict` (`{"type": "application/pdf" | "image/jpeg" | "image/png" | None, "active_content": [names]}`); the Lambda event `{"key": ..., "op": "inspect"}`; the child flag `--inspect`
- Produces: `apps.documents.ocr.UploadVerdict` (`type`, `active_content`; `extra="forbid"`), `inspect_upload(document: DocumentVersion, content: bytes) -> UploadVerdict` (raises `OcrUnavailable`)
- Produces: `apps.documents.storage.upload_key(*, tenant_id: UUID, student_id: UUID, document_id: UUID, version: str) -> str`, `promote_upload(document: DocumentVersion, body: bytes, *, content_type: str, store: S3ObjectStore) -> str` (worker side), `read_upload(document: DocumentVersion) -> bytes` (web side, `tenants/` only)
- Produces: `apps.documents.document_worker._check_and_promote(tenant_id: UUID, document: DocumentVersion) -> bool` (the only way out of `CHECKING`); `mark_read_failed` also ends a `CHECKING` upload `REVIEW_REQUIRED`
- Produces: `upload_status` answers `"message"` for a rejected upload
- Produces: `GET /ext/documents/<uuid:document_id>`, URL name `portals-ext-document`, sending `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox; default-src 'none'`; 404 unless the document is the paired membership's, `AVAILABLE` (so checked) with scan `NO_THREATS_FOUND`, promoted, and named for one of the student's applications — by a live `OPEN_UPLOAD_PAGE` action (Task 15's Submit document) or by the latest `PACKET` step's `uploads` list (spec B's packet)
- Consumes: `OcrFunction` (unchanged), `_invoke`, `_run_child`, `apply_scan_result` (unchanged), `document_worker._object_store`, `table_for` (Task 7), `_device_endpoint`, `_limit`, `S3ObjectStore`

- [ ] **Step 1: Add pypdf to the OCR program**

Run: `cd /home/orkhan/Desktop/student-dashboard && uv add --project ocr "pypdf>=6.19.0,<7" && uv sync --project ocr --frozen`
Expected: `ocr/pyproject.toml` lists `pypdf>=6.19.0,<7`; `ocr/uv.lock` gains pypdf and nothing else changes version (`git diff --stat ocr/uv.lock`). Then `uv export --project ocr --frozen --no-hashes --no-dev -o /tmp/ocr-requirements.txt && uv run pip-audit -r /tmp/ocr-requirements.txt --no-deps --disable-pip` → no known vulnerabilities.

- [ ] **Step 2: Write the failing tests**

`ocr/pdf_fixtures.py` (test code both suites import; the image copies `read_pages.py` alone):

```python
"""PDFs written with pypdf for the upload check's tests; both suites import this file.

ocr/test_read_pages.py checks that inspect() names what each one carries;
tests/documents/test_upload_promotion.py runs the real check over them through the document
worker. Test code only: the image copies read_pages.py alone (ocr/Dockerfile).
"""

import io
from collections.abc import Callable

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)


def written(edit: Callable[[PdfWriter], None] = lambda writer: None) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    edit(writer)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _name(value: str) -> NameObject:
    return NameObject(value)


def _action(kind: str, **entries: object) -> DictionaryObject:
    action = DictionaryObject({_name("/S"): _name(kind)})
    action.update({_name(f"/{key}"): value for key, value in entries.items()})
    return action


def open_action_javascript(writer: PdfWriter) -> None:
    writer.root_object[_name("/OpenAction")] = _action(
        "/JavaScript", JS=TextStringObject("app.alert(1)")
    )


def named_javascript(writer: PdfWriter) -> None:
    writer.add_js("app.alert(1)")


def page_action_javascript(writer: PdfWriter) -> None:
    writer.pages[0][_name("/AA")] = DictionaryObject(
        {_name("/O"): _action("/JavaScript", JS=TextStringObject("app.alert(1)"))}
    )


def launch(writer: PdfWriter) -> None:
    writer.root_object[_name("/OpenAction")] = _action("/Launch", F=TextStringObject("calc.exe"))


def embedded_file(writer: PdfWriter) -> None:
    writer.add_attachment("tool.exe", b"MZ\x90\x00")


def rich_media(writer: PdfWriter) -> None:
    annotation = DictionaryObject(
        {
            _name("/Type"): _name("/Annot"),
            _name("/Subtype"): _name("/RichMedia"),
            _name("/Rect"): ArrayObject([NumberObject(0)] * 4),
        }
    )
    writer.pages[0][_name("/Annots")] = ArrayObject([annotation])


def xfa(writer: PdfWriter) -> None:
    writer.root_object[_name("/AcroForm")] = DictionaryObject(
        {_name("/Fields"): ArrayObject(), _name("/XFA"): ArrayObject()}
    )


def signature_field(writer: PdfWriter) -> None:
    """What a signed e-diploma carries: a /Sig field and its value, and an open action that
    only shows the first page. None of it runs anything."""
    signature = DictionaryObject(
        {
            _name("/Type"): _name("/Sig"),
            _name("/Filter"): _name("/Adobe.PPKLite"),
            _name("/SubFilter"): _name("/adbe.pkcs7.detached"),
            _name("/ByteRange"): ArrayObject([NumberObject(0)] * 4),
            _name("/Contents"): ByteStringObject(b"\x00" * 64),
        }
    )
    field = DictionaryObject(
        {
            _name("/FT"): _name("/Sig"),
            _name("/T"): TextStringObject("Signature1"),
            _name("/V"): signature,
        }
    )
    writer.root_object[_name("/AcroForm")] = DictionaryObject(
        {_name("/Fields"): ArrayObject([field]), _name("/SigFlags"): NumberObject(3)}
    )
    writer.root_object[_name("/OpenAction")] = ArrayObject(
        [writer.pages[0].indirect_reference, _name("/Fit")]
    )


#: Every active-content PDF, and exactly the names inspect() reports for it.
ACTIVE = {
    "open_action_javascript": (open_action_javascript, ["/JS", "/JavaScript", "/OpenAction"]),
    "named_javascript": (named_javascript, ["/JS", "/JavaScript"]),
    "page_action_javascript": (page_action_javascript, ["/AA", "/JS", "/JavaScript"]),
    "launch": (launch, ["/Launch", "/OpenAction"]),
    "embedded_file": (embedded_file, ["/EmbeddedFile", "/EmbeddedFiles"]),
    "rich_media": (rich_media, ["/RichMedia"]),
    "xfa": (xfa, ["/XFA"]),
}
```

(Every expected list above was measured with this exact code and the `inspect` in Step 4 under pypdf 6.19.0, 2026-10-04.)

Append to `ocr/test_read_pages.py` (after the `_S3` helper; `import pdf_fixtures` resolves the same way `import read_pages` does):

```python
import pdf_fixtures  # noqa: E402


@pytest.mark.parametrize("name", sorted(pdf_fixtures.ACTIVE))
def test_a_pdf_with_active_content_is_named(name):
    edit, named = pdf_fixtures.ACTIVE[name]
    assert rp.inspect(pdf_fixtures.written(edit)) == {
        "type": "application/pdf",
        "active_content": named,
    }


def test_a_plain_pdf_and_a_signed_looking_one_carry_none():
    """A /Sig field and an open action that only shows a page run nothing: a signed diploma
    passes, and nothing about it is touched."""
    for data in (pdf_fixtures.written(), pdf_fixtures.written(pdf_fixtures.signature_field)):
        assert rp.inspect(data) == {"type": "application/pdf", "active_content": []}


def test_a_pdf_nothing_can_parse_is_refused_not_passed():
    assert rp.inspect(b"%PDF-1.7\n garbage")["active_content"] == ["/Unreadable"]


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (b"\x89PNG\r\n\x1a\nrest", "image/png"),
        (b"\xff\xd8\xff\xe0rest", "image/jpeg"),
        # An HTML page the student named passport.pdf: the name is never read.
        (b"<html><body><script>alert(1)</script></body></html>", None),
        (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>', None),
        (b"MZ\x90\x00", None),
    ],
)
def test_the_type_is_read_from_the_bytes_and_only_three_pass(data, kind):
    assert rp.inspect(data) == {"type": kind, "active_content": []}


def test_the_lambda_inspects_without_loading_a_model(monkeypatch):
    monkeypatch.setenv("DOCUMENT_BUCKET", "evidence")
    monkeypatch.setattr(rp, "_ENGINES", None)
    monkeypatch.setattr(rp, "Engines", lambda: pytest.fail("loaded the models"))
    s3 = _S3(pdf_fixtures.written(pdf_fixtures.launch))
    answer = rp.handler({"key": "quarantine/t/d", "op": "inspect"}, None, s3=s3)
    assert s3.asked == [("evidence", "quarantine/t/d")]
    assert answer == {"type": "application/pdf", "active_content": ["/Launch", "/OpenAction"]}
```

Append to `tests/documents/test_ocr.py` (import `UploadVerdict, inspect_upload` from `apps.documents.ocr`):

```python
def test_the_upload_check_sends_the_key_and_the_operation_never_the_bytes(monkeypatch):
    client = _Lambda({"type": "application/pdf", "active_content": ["/Launch"]})
    _function(monkeypatch, client)
    verdict = inspect_upload(_DOCUMENT, b"%PDF the whole upload")
    assert verdict == UploadVerdict(type="application/pdf", active_content=("/Launch",))
    [call] = client.calls
    assert json.loads(call["Payload"]) == {"key": "quarantine/tenant/document", "op": "inspect"}


def test_locally_the_upload_check_is_the_same_child_with_one_flag(tmp_path, monkeypatch):
    _child(
        tmp_path,
        monkeypatch,
        """
        import json, sys
        assert sys.argv[1:] == ["--inspect"], sys.argv
        assert sys.stdin.buffer.read() == b"\\x89PNG\\r\\n\\x1a\\n"
        print(json.dumps({"type": "image/png", "active_content": []}))
        """,
    )
    assert inspect_upload(_DOCUMENT, b"\x89PNG\r\n\x1a\n").type == "image/png"


@pytest.mark.parametrize(
    "output",
    [
        {},
        {"type": "text/html", "active_content": []},
        {"type": None},
        {"type": None, "active_content": [], "pages": []},
    ],
)
def test_an_answer_outside_the_contract_is_unavailable_never_clean(tmp_path, monkeypatch, output):
    _answering(tmp_path, monkeypatch, output)
    with pytest.raises(OcrUnavailable):
        inspect_upload(_DOCUMENT, b"%PDF")
```

In `tests/documents/conftest.py`, add (imports: `from apps.concierge.models import DocumentVersion`, `from apps.documents import document_worker`, `from apps.tenancy.context import tenant_scope`):

```python
@pytest.fixture(autouse=True)
def _uploads_pass_the_upload_check(monkeypatch):
    """Every worker test that is not about the upload check gets a passed check and a
    recorded promotion, so none reaches S3 or the OCR child. test_upload_promotion.py
    overrides this fixture by name to test the real one."""

    def _promoted(tenant_id, document):
        key = f"tenants/{tenant_id}/students/{document.student_id}/uploads/{document.id}/stub"
        with tenant_scope(tenant_id):
            DocumentVersion.objects.filter(id=document.id).update(
                state="AVAILABLE", promoted_key=key, content_type="application/pdf"
            )
        document.state, document.promoted_key = "AVAILABLE", key
        return True

    monkeypatch.setattr(document_worker, "_check_and_promote", _promoted)
```

`tests/documents/test_upload_promotion.py`:

```python
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.conf import settings

from apps.concierge.documents import register
from apps.concierge.models import UPLOAD_REJECTIONS, DocumentVersion
from apps.documents import document_worker
from apps.documents.document_queue import ScanResultEvent
from apps.documents.ocr import OcrUnavailable, UploadVerdict
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db
PDF = b"%PDF-1.7 passport scan"
CLEAN = UploadVerdict(type="application/pdf", active_content=())


@pytest.fixture(autouse=True)
def _uploads_pass_the_upload_check():
    """Overrides tests/documents/conftest.py's stub: this module is about the real check."""


@pytest.fixture
def bucket(monkeypatch, fake_store):
    monkeypatch.setattr(document_worker, "_object_store", lambda: fake_store)
    return fake_store


@pytest.fixture
def ingested(monkeypatch):
    calls = []
    monkeypatch.setattr(
        document_worker, "ingest_uploaded_cv", lambda **kwargs: calls.append(kwargs) or ()
    )
    return calls


@pytest.fixture
def check(monkeypatch):
    """The isolated function's answer, set per test. What it was handed is recorded, and
    the state every other reader could see while it ran -- the committed row."""
    state = SimpleNamespace(answer=CLEAN, handed=[], committed=[])

    def _inspect(document, content):
        state.handed.append(content)
        with tenant_scope(document.tenant_id):
            state.committed.append(DocumentVersion.objects.get(id=document.id).state)
        if isinstance(state.answer, Exception):
            raise state.answer
        return state.answer

    monkeypatch.setattr(document_worker, "inspect_upload", _inspect)
    return state


def _event(document, status="NO_THREATS_FOUND") -> ScanResultEvent:
    return ScanResultEvent(
        object_key=document.object_key, scan_result=status,
        bucket_name=settings.EVIDENCE_BUCKET_NAME,
    )


def _uploaded(agency, student, bucket, body=PDF, kind="PASSPORT"):
    document = register(agency.id, student.id, kind=kind)
    bucket.put(document.object_key, body)
    return document


def _reloaded(document):
    with tenant_scope(document.tenant_id):
        document.refresh_from_db()
    return document


def test_a_clean_upload_is_copied_under_the_students_prefix_byte_for_byte(
    agency_a, membership_a, bucket, check
):
    document = _uploaded(agency_a, membership_a, bucket)

    document_worker.handle_scan_result(_event(document))

    document = _reloaded(document)
    prefix = f"tenants/{agency_a.id}/students/{membership_a.id}/uploads/{document.id}/"
    assert document.promoted_key.startswith(prefix)
    assert bucket.get(document.promoted_key) == PDF
    assert (document.state, document.content_type) == ("AVAILABLE", "application/pdf")
    assert check.handed == [PDF]
    # While the check ran, nothing could read the upload as usable.
    assert check.committed == ["CHECKING"]


def test_a_file_of_another_type_is_rejected_never_copied_and_never_read_as_a_cv(
    agency_a, membership_a, bucket, check, ingested
):
    """The check's type, never the name: an HTML page called cv.pdf stops here."""
    document = _uploaded(agency_a, membership_a, bucket, body=b"<html>", kind="CV")
    check.answer = UploadVerdict(type=None, active_content=())

    document_worker.handle_scan_result(_event(document))

    document = _reloaded(document)
    assert (document.state, document.promoted_key) == ("REJECTED_TYPE", "")
    assert document.rejection_message == "Upload a PDF, JPEG or PNG"
    assert ingested == []


def test_a_pdf_with_active_content_is_rejected_and_never_copied(
    agency_a, membership_a, bucket, check
):
    document = _uploaded(agency_a, membership_a, bucket)
    check.answer = UploadVerdict(type="application/pdf", active_content=("/Launch", "/OpenAction"))

    document_worker.handle_scan_result(_event(document))

    document = _reloaded(document)
    assert (document.state, document.promoted_key) == ("REJECTED_ACTIVE_CONTENT", "")
    assert document.rejection_message == UPLOAD_REJECTIONS["REJECTED_ACTIVE_CONTENT"]
    assert "Print → Save as PDF" in document.rejection_message


def test_a_redelivered_clean_verdict_never_reopens_a_rejected_upload(
    agency_a, membership_a, bucket, check
):
    document = _uploaded(agency_a, membership_a, bucket)
    check.answer = UploadVerdict(type=None, active_content=())
    document_worker.handle_scan_result(_event(document))
    check.answer = CLEAN
    document_worker.handle_scan_result(_event(document))
    assert _reloaded(document).state == "REJECTED_TYPE"
    assert len(check.handed) == 1


def test_a_blocked_upload_is_never_checked_or_copied(agency_a, membership_a, bucket, check):
    document = _uploaded(agency_a, membership_a, bucket)
    document_worker.handle_scan_result(_event(document, "THREATS_FOUND"))
    assert _reloaded(document).promoted_key == ""
    assert check.handed == []


def test_a_redelivered_clean_verdict_checks_and_copies_once(
    agency_a, membership_a, bucket, check
):
    document = _uploaded(agency_a, membership_a, bucket)
    document_worker.handle_scan_result(_event(document))
    document_worker.handle_scan_result(_event(document))
    assert len(check.handed) == 1


def test_a_check_that_does_not_answer_promotes_nothing_and_ends_review_required(
    agency_a, membership_a, bucket, check, ingested
):
    """Never clean by default: CHECKING until the last retry, then REVIEW_REQUIRED."""
    document = _uploaded(agency_a, membership_a, bucket, kind="CV")
    check.answer = OcrUnavailable("exit 1")
    with pytest.raises(OcrUnavailable):
        document_worker.handle_scan_result(_event(document))
    assert (_reloaded(document).state, document.promoted_key) == ("CHECKING", "")
    assert ingested == []

    document_worker.mark_read_failed(_event(document))
    assert _reloaded(document).state == "REVIEW_REQUIRED"


def test_the_poll_says_what_to_do_with_a_rejected_upload(
    client, agency_a, domain_a, user_a, membership_a, bucket, check
):
    document = _uploaded(agency_a, membership_a, bucket)
    check.answer = UploadVerdict(type=None, active_content=())
    document_worker.handle_scan_result(_event(document))
    client.force_login(user_a)
    body = client.get(f"/api/documents/uploads/{document.id}", HTTP_HOST=domain_a.host).json()
    assert body == {
        "state": "REJECTED_TYPE",
        "scan_result": "NO_THREATS_FOUND",
        "message": "Upload a PDF, JPEG or PNG",
    }


_OCR_VENV = Path(settings.OCR_PYTHON)


@pytest.mark.skipif(not _OCR_VENV.exists(), reason="no OCR venv: uv sync --project ocr")
class TestTheRealCheck:
    """The real ocr/read_pages.py --inspect child, over PDFs pypdf wrote. No model loads."""

    @pytest.fixture(autouse=True)
    def _child(self, monkeypatch):
        monkeypatch.setattr(settings, "OCR_FUNCTION_NAME", "")
        monkeypatch.syspath_prepend(str(settings.BASE_DIR / "ocr"))  # for pdf_fixtures

    @pytest.mark.parametrize("name", ["open_action_javascript", "embedded_file", "launch", "xfa"])
    def test_an_active_pdf_is_rejected(self, agency_a, membership_a, bucket, name):
        import pdf_fixtures

        edit, _named = pdf_fixtures.ACTIVE[name]
        document = _uploaded(agency_a, membership_a, bucket, body=pdf_fixtures.written(edit))
        document_worker.handle_scan_result(_event(document))
        document = _reloaded(document)
        assert (document.state, document.promoted_key) == ("REJECTED_ACTIVE_CONTENT", "")

    @pytest.mark.parametrize("signed", [False, True])
    def test_a_plain_or_signed_pdf_is_promoted_byte_identical(
        self, agency_a, membership_a, bucket, signed
    ):
        import pdf_fixtures

        body = pdf_fixtures.written(pdf_fixtures.signature_field if signed else lambda w: None)
        document = _uploaded(agency_a, membership_a, bucket, body=body)
        document_worker.handle_scan_result(_event(document))
        document = _reloaded(document)
        assert document.state == "AVAILABLE"
        assert bucket.get(document.promoted_key) == body

    def test_an_html_file_named_passport_pdf_is_rejected(self, agency_a, membership_a, bucket):
        document = _uploaded(agency_a, membership_a, bucket, body=b"<html><script>1</script>")
        document_worker.handle_scan_result(_event(document))
        assert _reloaded(document).state == "REJECTED_TYPE"
```

(`ingest_uploaded_cv` is not reached in `TestTheRealCheck`: every upload there is a `PASSPORT`. The class needs only the OCR venv, not the baked models, because `inspect` never builds `Engines`; CI's `uv sync --project ocr` step creates that venv, and `ocr/test_read_pages.py` covers `inspect` itself wherever the class skips.)

`tests/portals/test_ext_document.py`:

```python
from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.audit.models import DeletionRequest
from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.documents import storage
from apps.portals.models import Application, ApplicationStep, DeviceAction
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.portals.test_ext_api import _pair

pytestmark = pytest.mark.django_db
PDF = b"%PDF-1.7 passport scan"


@pytest.fixture
def bucket(monkeypatch, fake_store):
    monkeypatch.setattr(storage, "_object_store", lambda: fake_store)
    return fake_store


def _promoted(agency, student, bucket, *, state="AVAILABLE", scan="NO_THREATS_FOUND"):
    document = register(agency.id, student.id, kind="PASSPORT")
    key = storage.upload_key(
        tenant_id=agency.id, student_id=student.id, document_id=document.id, version="abc"
    )
    bucket.put(key, PDF)
    DocumentVersion.objects.filter(id=document.id).update(
        state=state, scan_result=scan, promoted_key=key, content_type="application/pdf"
    )
    return document


def _named(agency, student, document, *, expires_in=timedelta(minutes=15)):
    application = Application.objects.create(tenant=agency, student=student, program_id=uuid4())
    DeviceAction.objects.create(
        tenant=agency, membership=student, application=application,
        kind=DeviceAction.Kind.OPEN_UPLOAD_PAGE,
        payload={"application_id": str(application.id), "document_id": str(document.id),
                 "source": "upload"},
        expires_at=timezone.now() + expires_in,
    )
    return application


def _get(client, domain, token, document_id):
    return client.get(
        f"/ext/documents/{document_id}", HTTP_HOST=domain.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def test_a_named_promoted_upload_is_streamed_as_an_inert_attachment(
    client, agency_a, domain_a, membership_a, bucket
) -> None:
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        document = _promoted(agency_a, membership_a, bucket)
        _named(agency_a, membership_a, document)
    response = _get(client, domain_a, token, document.id)
    assert response.status_code == 200
    assert response.content == PDF
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == f'attachment; filename="passport-{document.id}.pdf"'
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Security-Policy"] == "sandbox; default-src 'none'"


def test_a_document_named_by_the_latest_packet_is_served(
    client, agency_a, domain_a, membership_a, bucket
) -> None:
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        document = _promoted(agency_a, membership_a, bucket)
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4()
        )
        ApplicationStep.objects.create(
            tenant=agency_a, application=application, sequence=1, kind="PACKET",
            detail={"uploads": [{"upload_id": str(document.id)}]},
        )
    assert _get(client, domain_a, token, document.id).status_code == 200


@pytest.mark.parametrize(
    "case",
    ["unnamed", "expired", "quarantined", "checking", "blocked", "rejected", "theirs", "absent"],
)
def test_every_refusal_is_a_404(
    client, agency_a, domain_a, membership_a, user_b, bucket, case
) -> None:
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        if case == "theirs":
            other = Membership.objects.create(
                tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
            )
            document = _promoted(agency_a, other, bucket)
            _named(agency_a, other, document)
        elif case == "quarantined":
            document = register(agency_a.id, membership_a.id, kind="PASSPORT")
            DocumentVersion.objects.filter(id=document.id).update(
                state="AVAILABLE", scan_result="NO_THREATS_FOUND"
            )
            _named(agency_a, membership_a, document)
        else:
            state = {
                "blocked": "BLOCKED", "rejected": "REJECTED_ACTIVE_CONTENT", "checking": "CHECKING"
            }.get(case, "AVAILABLE")
            document = _promoted(
                agency_a, membership_a, bucket, state=state,
                scan="THREATS_FOUND" if case == "blocked" else "NO_THREATS_FOUND",
            )
            if case in ("expired", "blocked", "rejected", "checking"):
                _named(agency_a, membership_a, document,
                       expires_in=timedelta(minutes=-1 if case == "expired" else 15))
    document_id = uuid4() if case == "absent" else document.id
    assert _get(client, domain_a, token, document_id).status_code == 404


def test_no_token_is_401_and_a_locked_student_is_403(
    client, agency_a, domain_a, membership_a, bucket
) -> None:
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        document = _promoted(agency_a, membership_a, bucket)
        _named(agency_a, membership_a, document)
    assert client.get(f"/ext/documents/{document.id}", HTTP_HOST=domain_a.host).status_code == 401
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED", reason="OTHER"
        )
    assert _get(client, domain_a, token, document.id).status_code in (401, 403)
```

(`request_deletion` revokes every pairing, so a real locked student's token is already dead — 401; a row created by hand leaves it live and `_device_endpoint` answers 403. Either is a refusal. The `rejected` and `checking` cases are rows that carry a `promoted_key` and a live upload action while not `AVAILABLE` — the route's own state filter refuses them, whatever else the row says.)

Append to `tests/documents/test_table.py` (Task 7's module):

```python
def test_an_upload_being_checked_is_shown_but_neither_held_nor_missing() -> None:
    column = _column("Passport copy")
    table = build_table([column], [Held("PASSPORT", Cell.CHECKING)])
    assert _row(table, "PASSPORT").cells == (Cell.CHECKING,)
    assert str(Cell.CHECKING) == "checking…"
    assert table.counts_for(column.application_id) == (0, 1)
    assert table.missing_for(column.application_id) == ()
```

Append to `tests/infra/test_template.py`:

```python
def test_promotion_needs_no_grant_on_guarddutys_role(template: Template) -> None:
    """Uploads are promoted to tenants/ by handle_scan_result, which runs under
    DocumentWorkerTaskRole (get quarantine/*, get+put tenants/*). DocumentScanRole
    is GuardDuty's service role: it runs none of our code and keeps no write
    beyond the scan tag. The upload check runs in OcrFunction, which can write
    nothing at all (test_the_ocr_function_holds_no_secret_and_reads_only_cleared_uploads,
    unchanged)."""
    assert "s3:PutObject" not in _policy_actions(template.resource("DocumentScanRole"))
    worker = template.resource("DocumentWorkerTaskRole")
    assert "s3:GetObject" in _object_actions(worker, "${EvidenceBucket.Arn}/quarantine/*")
    assert "s3:PutObject" in _object_actions(worker, "${EvidenceBucket.Arn}/tenants/*")
    web = template.resource("WebTaskRole")
    assert "s3:GetObject" in _object_actions(web, "${EvidenceBucket.Arn}/tenants/*")
```

Append to `tests/audit/test_deletion_purges_documents.py`:

```python
def test_erasure_reaches_a_promoted_upload(agency_a):
    """No new deletion code: the student prefix the purge already walks holds uploads/."""
    from apps.documents.storage import upload_key

    tenant_id, student_id, document_id = agency_a.id, uuid4(), uuid4()
    key = upload_key(tenant_id=tenant_id, student_id=student_id, document_id=document_id,
                     version="abc")
    assert key.startswith(f"tenants/{tenant_id}/students/{student_id}/")
    client = MagicMock()
    client.list_object_versions.return_value = {
        "Versions": [{"Key": key, "VersionId": "v1"}], "DeleteMarkers": [], "IsTruncated": False,
    }
    delete_student_documents(tenant_id=tenant_id, student_id=student_id, client=client)
    deleted = client.delete_objects.call_args_list[0].kwargs["Delete"]["Objects"]
    assert {"Key": key, "VersionId": "v1"} in deleted
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd /home/orkhan/Desktop/student-dashboard && uv run --project ocr pytest ocr -q`
Expected: FAIL — `read_pages` has no `inspect`.

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/documents tests/portals/test_ext_document.py tests/infra/test_template.py tests/audit/test_deletion_purges_documents.py`
Expected: FAIL — `apps.documents.ocr` has no `inspect_upload`; `DocumentVersion` has no `promoted_key`; `Cell` has no `CHECKING`; `/ext/documents/...` is 404 for every request; `upload_key` does not exist; the conftest stub cannot patch a missing `_check_and_promote`. The infra test passes already (it pins today's shape).

- [ ] **Step 4: The check, inside the isolated function**

`ocr/read_pages.py`: add `from pypdf import PdfReader` and `from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject` to the top imports (at module level, so an image missing pypdf fails at import — loudly, as `OcrUnavailable` — instead of every PDF reading as unparseable), extend the module docstring's usage line to `python read_pages.py < upload  |  python read_pages.py --inspect < upload  |  python read_pages.py --bake  |  Lambda: read_pages.handler`, and add after `read_document`:

```python
#: The three types an upload may be, by the file's own first bytes. The filename and the type the
#: browser declared are the client's to choose, so neither is ever read.
ALLOWED_TYPES = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)
#: A key whose presence is active content: a script, an embedded file, rich media, an XFA form.
_ACTIVE_KEYS = {
    "/JS": "/JS",
    "/JavaScript": "/JavaScript",
    "/EmbeddedFiles": "/EmbeddedFiles",
    "/EF": "/EmbeddedFile",
    "/RichMediaContent": "/RichMedia",
    "/XFA": "/XFA",
}
#: A key whose value makes it active: an action that runs a script or a program, an embedded
#: file stream, a rich-media annotation.
_ACTIVE_VALUES = {
    ("/S", "/JavaScript"): "/JavaScript",
    ("/S", "/Launch"): "/Launch",
    ("/Type", "/EmbeddedFile"): "/EmbeddedFile",
    ("/Subtype", "/RichMedia"): "/RichMedia",
}
#: The two triggers, named alongside whatever they run. An /OpenAction that only shows a page
#: (what a signed diploma carries) runs nothing and is not named.
_TRIGGERS = ("/OpenAction", "/AA")
#: ponytail: a walk past this many objects is refused rather than finished; a 10 MB file can
#: declare millions. Raise it if a real document is refused for size alone.
MAX_OBJECTS = 100_000


def inspect(data: bytes) -> dict:
    """The upload check (dashboard spec §6, "Upload safety"): the type the bytes are, and every
    kind of active content a PDF carries. Reads only; a PDF is never rewritten, because
    rewriting breaks a signed one (Azerbaijan's TMIS e-diplomas verify byte for byte).

    pypdf, not pdfium: pdfium can run a document's open action but cannot report one.
    """
    kind = next((name for magic, name in ALLOWED_TYPES if data.startswith(magic)), None)
    active = sorted(_active_content(data)) if kind == "application/pdf" else []
    return {"type": kind, "active_content": active}


def _active_content(data: bytes) -> set[str]:
    """Walk every object reachable from the trailer; nothing is executed or decompressed for
    its own sake. Fails closed: a PDF that cannot be parsed or decrypted is named, so it is
    refused, never passed."""
    found: set[str] = set()
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            return {"/Encrypt"}
        seen: set[tuple[int, int]] = set()
        stack: list[tuple[object, str]] = [(reader.trailer, "")]
        while stack:
            node, trigger = stack.pop()
            if isinstance(node, IndirectObject):
                if (node.idnum, node.generation) in seen:
                    continue
                seen.add((node.idnum, node.generation))
                if len(seen) > MAX_OBJECTS:
                    return found | {"/TooManyObjects"}
                node = node.get_object()
            if isinstance(node, DictionaryObject):
                for key, value in node.items():
                    named = _ACTIVE_KEYS.get(key)
                    if named is None and isinstance(value, NameObject):
                        named = _ACTIVE_VALUES.get((key, value))
                    if named:
                        found.update({named, trigger} - {""})
                    stack.append((value, key if key in _TRIGGERS else trigger))
            elif isinstance(node, ArrayObject):
                stack.extend((item, trigger) for item in node)
    except Exception:
        # Not swallowed: whatever pypdf raises on a malformed file, the answer is "refuse".
        return found | {"/Unreadable"}
    return found
```

(add `import io` to the imports; the module has none today). In `handler`, after the size check and before the models load:

```python
    if event.get("op") == "inspect":
        return inspect(data)
```

and extend its docstring: "`op: inspect` runs the upload check instead of the OCR read; it loads no model." In `main`, before the `--bake` branch:

```python
    if sys.argv[1:] == ["--inspect"]:
        json.dump(inspect(sys.stdin.buffer.read()), answer)
        answer.flush()
        return
```

and at the end of `bake()`, before the `print`:

```python
    # The upload check's library is in the image and works offline.
    assert inspect(png.tobytes()) == {"type": "image/png", "active_content": []}
    assert inspect(b"%PDF-1.7\n garbage")["active_content"] == ["/Unreadable"]
```

(The second assertion would pass even without pypdf only if the import were lazy; with the top-level import, a missing pypdf fails the `--network=none` bake.)

`apps/documents/ocr.py`: change `_invoke(key: str) -> bytes` to `_invoke(key: str, op: str = "") -> bytes`, building the payload as `json.dumps({"key": key} | ({"op": op} if op else {}))`; change `_run_child(content: bytes) -> bytes` to `_run_child(content: bytes, *flags: str) -> bytes` with argv `[settings.OCR_PYTHON, str(settings.BASE_DIR / "ocr" / "read_pages.py"), *flags]` and the nosec note "argv is two paths from settings and a fixed flag, never the upload". Then append:

```python
class UploadVerdict(BaseModel):
    """ocr/read_pages.py::inspect's answer: the type the bytes are (None: not one of the three),
    and every kind of active content a PDF carries."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["application/pdf", "image/jpeg", "image/png"] | None
    active_content: tuple[str, ...]


def inspect_upload(document: DocumentVersion, content: bytes) -> UploadVerdict:
    """The upload check, run where the OCR runs: the isolated function (the key, never the
    bytes), or locally the same child with --inspect. Anything but a valid answer is
    OcrUnavailable -- an unchecked file is never treated as a clean one."""
    if settings.OCR_FUNCTION_NAME:
        raw = _invoke(document.object_key, op="inspect")
    else:
        raw = _run_child(content, "--inspect")
    try:
        return UploadVerdict.model_validate_json(raw)
    except ValidationError as error:
        raise OcrUnavailable("unparseable output") from error
```

- [ ] **Step 5: The fields, the states and their erasure class**

`apps/concierge/models.py`, above `class DocumentVersion`:

```python
#: An upload the check refused, and what the student is told to do instead
#: (dashboard spec §6, "Upload safety"). Terminal: a redelivered scan verdict
#: never reopens one; the student uploads again.
UPLOAD_REJECTIONS = {
    "REJECTED_TYPE": "Upload a PDF, JPEG or PNG",
    "REJECTED_ACTIVE_CONTENT": (
        "This PDF contains active content; save it again as a plain PDF "
        "(Print → Save as PDF) and upload that"
    ),
}
```

In `DocumentVersion`, change `state = models.CharField(max_length=20, default="QUARANTINED")` to `max_length=30`, and after `expires_on` add:

```python
    #: Where the scanned-clean, checked copy lives, under the student's own prefix
    #: (documents/storage.py::promote_upload). Empty until promoted. What the
    #: extension downloads; the quarantine original stays where it is.
    promoted_key = models.CharField(max_length=500, blank=True)
    #: The upload check's reading of the file's own first bytes, never the client's.
    content_type = models.CharField(max_length=100, blank=True)

    @property
    def rejection_message(self) -> str:
        return UPLOAD_REJECTIONS.get(self.state, "")
```

`apps/audit/redaction.py`: `concierge.DocumentVersion` REDACT fields become `("object_key", "expires_on", "promoted_key")`; add `"content_type"` to its KEEP tuple. (`object_key`'s comment applies to `promoted_key` too: the purge walks the student prefix, so it never needs the column.)

Run: `uv run python manage.py makemigrations concierge --name upload_promotion`
Expected: one migration adding the two fields and altering `state`.

- [ ] **Step 6: Promotion, the worker's order, and the read**

Append to `apps/documents/storage.py` (add `import hashlib` to the imports):

```python
#: A scanned-clean, checked upload's copy, under the student's own prefix so the web
#: tier (tenants/* read) can serve it and erasure's prefix purge removes it.
_UPLOAD_TEMPLATE = "tenants/{tenant_id}/students/{student_id}/uploads/{document_id}/{version}"


def upload_key(*, tenant_id: UUID, student_id: UUID, document_id: UUID, version: str) -> str:
    return _UPLOAD_TEMPLATE.format(
        tenant_id=tenant_id, student_id=student_id, document_id=document_id, version=version
    )


def promote_upload(
    document: DocumentVersion, body: bytes, *, content_type: str, store: S3ObjectStore
) -> str:
    """Copy a checked upload, byte for byte, under the student's prefix. Worker side only:
    the caller read `body` from quarantine/ (DocumentWorkerTaskRole's grant, never the web
    tier's) and `content_type` is the upload check's. Nothing here rewrites the file.

    The version segment is the content's own digest, so a redelivered verdict writes the
    same key. This is the one write that makes an upload AVAILABLE: the key, the type and
    the state land together, so AVAILABLE always means checked and promoted.
    """
    if document.state != "CHECKING":
        raise DocumentStoreRefused(f"document is {document.state}, not CHECKING")
    key = upload_key(
        tenant_id=document.tenant_id, student_id=document.student_id, document_id=document.id,
        version=hashlib.sha256(body).hexdigest()[:16],
    )
    store.put(key, body)
    DocumentVersion.objects.filter(id=document.id).update(
        state="AVAILABLE", promoted_key=key, content_type=content_type
    )
    document.state, document.promoted_key, document.content_type = "AVAILABLE", key, content_type
    return key


def read_upload(document: DocumentVersion) -> bytes:
    """The promoted copy's bytes, for the extension route. tenants/ only."""
    if not document.promoted_key.startswith(f"tenants/{document.tenant_id}/students/"):
        raise KeyError(document.promoted_key)
    return _object_store().get(document.promoted_key)
```

`apps/documents/document_worker.py`: imports become `from apps.concierge.models import UPLOAD_REJECTIONS, DocumentVersion` (the `apply_scan_result` import is unchanged), `from . import storage`, `from .ocr import PageRefused, inspect_upload`. Replace the body of `handle_scan_result` from `with tenant_scope(tenant_id), transaction.atomic():` to the end with:

```python
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        document = DocumentVersion.objects.filter(object_key=event.object_key).first()
        if document is None:
            logger.warning("DocumentScanUnknownKey key=%s", event.object_key)
            return
        if document.state in UPLOAD_REJECTIONS:
            # A redelivered clean verdict never reopens an upload the check refused.
            return
        apply_scan_result(document, event.scan_result)
        if document.state != "AVAILABLE":
            return
        if not document.promoted_key:
            # AVAILABLE means checked and promoted. Until _check_and_promote answers, a
            # clean upload is CHECKING; this overwrite shares apply_scan_result's
            # transaction, so AVAILABLE is never committed for an unchecked file.
            document.state = "CHECKING"
            document.save(update_fields=["state"])
    # CHECKING is committed before the check, as the transcript read does: the check is a
    # call to the isolated function, and a task that dies during it leaves the document
    # CHECKING for the redelivery. Nothing below runs on an unchecked file.
    if document.state == "CHECKING" and not _check_and_promote(tenant_id, document):
        return
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        if document.kind == "CV":
            _ingest_cv(document, event.object_key)
            return
        if document.kind != "TRANSCRIPT":
            # A passport, diploma, certificate or letter is stored for the
            # student to attach (dashboard spec §6). Nothing reads its contents.
            return
        if TranscriptReading.objects.filter(document=document).exists():
            logger.info("DocumentScanAlreadyIngested document=%s", document.id)
            return
        names = personal_names(document.student)
    _read_transcript(tenant_id, document, names)


def _check_and_promote(tenant_id: UUID, document: DocumentVersion) -> bool:
    """The upload check, then the copy the extension fetches (dashboard spec §6, "Upload
    safety"). The only way out of CHECKING: AVAILABLE (promoted) only on NO_THREATS_FOUND
    AND an allowed type AND no active content; otherwise a terminal state the student sees.

    The check runs in the isolated OCR function, which can write nothing, so the copy is
    ours. The bytes are read from the store directly: open_document serves AVAILABLE only,
    and whether this file may become AVAILABLE is what is being decided here. OcrUnavailable
    is not caught: the file stays CHECKING, the message is redelivered, and the last
    delivery's mark_read_failed ends it REVIEW_REQUIRED.
    """
    store = _object_store()
    body = store.get(document.object_key)
    verdict = inspect_upload(document, body)
    if verdict.type is None:
        rejected = "REJECTED_TYPE"
    elif verdict.active_content:
        rejected = "REJECTED_ACTIVE_CONTENT"
    else:
        with tenant_scope(tenant_id), transaction.atomic():
            set_local_tenant(tenant_id)
            storage.promote_upload(document, body, content_type=verdict.type, store=store)
        return True
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        DocumentVersion.objects.filter(id=document.id).update(state=rejected)
    document.state = rejected
    logger.warning(
        "DocumentUploadRejected document=%s state=%s found=%s",
        document.id, rejected, ",".join(verdict.active_content),
    )
    return False
```

In `_ingest_cv`'s `UnsupportedUpload` comment, replace "and, because this whole handler is one transaction, the apply_scan_result above ROLLS BACK with it" with "and the ingestion's transaction rolls back with it"; in `tests/documents/test_document_worker.py`'s docstring (~162), replace "the whole handler is one transaction, so apply_scan_result rolls back with it and" with "the ingestion's transaction rolls back with it and". In `mark_read_failed`, inside its transaction and before the transcript update, add:

```python
        unchecked = DocumentVersion.objects.filter(
            object_key=event.object_key, state="CHECKING"
        ).update(state="REVIEW_REQUIRED")
```

and after the block `if unchecked: logger.warning("DocumentUploadUnchecked key=%s", event.object_key)`; its docstring gains: "An upload the check never answered for leaves CHECKING for REVIEW_REQUIRED: a person looks, and nothing was promoted."

`apps/documents/table.py` (Task 7): add to `Cell`, after `UPLOADED`:

```python
    #: Scanned clean, upload check pending (Task 14). Shown so the student knows the
    #: file arrived; neither held (no Submit) nor missing (not asked for again).
    CHECKING = "checking…"
```

and in `table_for` replace the uploads loop with:

```python
    uploads = DocumentVersion.objects.filter(
        student=student, state__in=("AVAILABLE", "CHECKING")
    ).order_by("-created_at")
    # A usable upload is listed before one still being checked: held_for takes the first,
    # so a re-upload under check never hides the copy Submit can already send.
    for upload in sorted(uploads, key=lambda upload: upload.state != "AVAILABLE"):
        held.append(
            Held(upload.kind, Cell.UPLOADED if upload.state == "AVAILABLE" else Cell.CHECKING,
                 expires_on=upload.expires_on, document_id=upload.id, source="upload")
        )
```

`apps/documents/api.py::upload_status`, after `body` is built:

```python
    if document.rejection_message:
        body["message"] = document.rejection_message
```

- [ ] **Step 7: The route**

`apps/portals/ext_api.py` (imports: `from apps.concierge.models import DocumentVersion`, `from apps.documents.storage import read_upload, store_submission_image`):

```python
#: An attachment is a whole file. Thirty an hour is a student attaching every
#: document of several applications, and stops a loop pulling the bucket.
_DOCUMENT_RATE_LIMIT = 30
_EXTENSIONS = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}


def _named_for_upload(membership: object, document_id: UUID) -> bool:
    """Named for one of this student's applications: by a live OPEN_UPLOAD_PAGE
    action (Submit document) or by the latest PACKET step's uploads (spec B)."""
    if DeviceAction.objects.filter(
        membership=membership,
        kind=DeviceAction.Kind.OPEN_UPLOAD_PAGE,
        completed_at__isnull=True,
        expires_at__gt=timezone.now(),
        payload__document_id=str(document_id),
        payload__source="upload",
    ).exists():
        return True
    for application in Application.objects.filter(student=membership):
        packet = (
            ApplicationStep.objects.filter(
                application=application, kind=ApplicationStep.Kind.PACKET
            )
            .order_by("-sequence")
            .first()
        )
        uploads = (packet.detail or {}).get("uploads", []) if packet is not None else []
        if any(isinstance(u, dict) and u.get("upload_id") == str(document_id) for u in uploads):
            return True
    return False


@require_GET
@_device_endpoint
def document(request: HttpRequest, pairing: ExtensionPairing, document_id: UUID) -> HttpResponse:
    """A scanned-clean, checked upload, for the extension to attach (spec §6 step 3).

    404 for every refusal, never 403: the id of a document that is not yours,
    not clean, not promoted or not asked for is not a fact you get to confirm.
    """
    _limit("ext-document", pairing, _DOCUMENT_RATE_LIMIT)
    with tenant_transaction(pairing.tenant_id):
        upload = (
            DocumentVersion.objects.filter(
                id=document_id, student=pairing.membership, state="AVAILABLE",
                scan_result="NO_THREATS_FOUND",
            )
            .exclude(promoted_key="")
            .first()
        )
        named = upload is not None and _named_for_upload(pairing.membership, document_id)
    if upload is None or not named or upload.content_type not in _EXTENSIONS:
        raise _ApiError(404, "not_found")
    try:
        body = read_upload(upload)
    except KeyError:
        raise _ApiError(404, "not_found") from None
    response = HttpResponse(body, content_type=upload.content_type)
    filename = f"{upload.kind.lower()}-{upload.id}{_EXTENSIONS[upload.content_type]}"
    # Every route that serves an upload sends all three (spec §6, "Upload safety"): a file
    # is saved, never rendered; its type is never guessed; and if anything renders it
    # anyway, it runs no script and loads nothing.
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response
```

(`membership: object` keeps the helper free of a `Membership` import cycle; type it `Membership` if `apps.tenancy.models` is already imported there. `content_type not in _EXTENSIONS` is belt and braces: the worker stores only the check's three types.) `apps/portals/urls.py`:

```python
    path("ext/documents/<uuid:document_id>", ext_api.document, name="portals-ext-document"),
```

- [ ] **Step 8: Run the tests**

Run: `cd /home/orkhan/Desktop/student-dashboard && uv run --project ocr pytest ocr -q`
Expected: PASS.

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/documents tests/portals tests/infra tests/audit`
Expected: PASS, including `tests/audit/test_redaction_classification.py`, the existing worker and transcript tests (the conftest stub promotes for them), and `TestTheRealCheck` wherever `ocr/.venv` exists — it must not be skipped on the implementer's machine: run `uv sync --project ocr --frozen` first if it is.

- [ ] **Step 9: Lint, types, checks**

Run: `uv run ruff check . && uv run mypy apps config && uv run bandit -c pyproject.toml -r apps config ocr/read_pages.py && uv run python manage.py makemigrations --check --dry-run && uv run cfn-lint`
Expected: no errors (the template is unchanged).

- [ ] **Step 10: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add -A apps/concierge apps/audit/redaction.py apps/documents/storage.py apps/documents/ocr.py apps/documents/document_worker.py apps/documents/api.py apps/documents/table.py apps/portals/ext_api.py apps/portals/urls.py ocr/read_pages.py ocr/test_read_pages.py ocr/pdf_fixtures.py ocr/pyproject.toml ocr/uv.lock tests && git commit -m "feat(documents): checked, scanned-clean uploads reach the paired extension

After GuardDuty's clean verdict the isolated OCR function runs a second
operation, inspect: the type from the file's own magic bytes (PDF, JPEG
or PNG only) and any active content in a PDF (JavaScript, launch,
embedded files, rich media, XFA), read with pypdf -- added to the OCR
image because pdfium can run an open action but not report one. A
refused file ends REJECTED_TYPE or REJECTED_ACTIVE_CONTENT with what to
do; a PDF is never rewritten, so a signed diploma is copied byte for
byte. Only then does the document worker copy it under the student's
prefix with the grants it already holds, and GET /ext/documents/<id>
streams it to the paired device as an attachment with nosniff and a
sandboxing CSP. A clean verdict commits CHECKING, and only the check
moves it on, so AVAILABLE always means checked and promoted for every
reader; a check that never answers ends REVIEW_REQUIRED.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 15: Documents — the table, uploads, drafts, Submit document

Spec §6. Plain HTML plus `static/dashboard/documents.js`, which calls the existing JSON door (`/api/documents/uploads`, `/facts/confirm`, `/generate`, `/drafts/<id>/approve`) and reloads. **Submit document** posts the cell's application, document and source; the server re-checks ownership of both and that the document is usable (an `AVAILABLE` upload — since Task 14 that means scanned clean, checked and promoted — or an `APPROVED` draft) before queueing `OPEN_UPLOAD_PAGE` through `queue_upload` — the intended application of §5.6 is the one the pressed cell names. An upload still `CHECKING` reads "checking…" and offers no Submit; a rejected one shows what to do instead (`DocumentVersion.rejection_message`). A message nothing could read (metadata tier) can be told which document it asked for.

**Files:**
- Modify: `apps/documents/views.py`, `apps/documents/urls.py`, `tests/dashboard/test_locks.py`
- Create: `templates/student/documents.html`, `templates/student/_documents.html`, `static/dashboard/documents.js`, `tests/documents/test_documents_page.py`

**Interfaces:**
- Produces: `apps.documents.views.page_context(student: Membership, *, counselor_view: bool) -> dict[str, object]` (reused by Task 20)
- Produces URL names: `student-documents` (`student/documents/`), `student-document-submit` (`student/documents/submit/`), `student-document-expiry` (`student/documents/<uuid:document_id>/expiry/`), `student-document-request` (`student/documents/requests/<uuid:signal_id>/`)

- [ ] **Step 1: Write the failing tests**

`tests/documents/test_documents_page.py`:

```python
from datetime import date
from uuid import uuid4

import pytest
from django.contrib.messages import get_messages
from django.utils import timezone

from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.portals.models import DeviceAction
from apps.portals.pairing import issue_pairing_code, redeem_pairing_code
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.dashboard.conftest import add_card

pytestmark = pytest.mark.django_db
PAGE = "/student/documents/"
SUBMIT = "/student/documents/submit/"


def _available(agency, student, kind):
    """Scanned clean, checked and promoted (Task 14): what the extension can fetch."""
    document = register(agency.id, student.id, kind=kind)
    DocumentVersion.objects.filter(id=document.id).update(
        state="AVAILABLE", scan_result="NO_THREATS_FOUND", content_type="application/pdf",
        promoted_key=f"tenants/{agency.id}/students/{student.id}/uploads/{document.id}/abc",
    )
    return document


def test_the_table_has_a_column_per_application_and_a_row_per_document(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, kit_requirements=["Passport copy"])
        _available(agency_a, membership_a, "PASSPORT")
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert f'<th scope="col" id="application-{application.id}">M.Sc. Informatics</th>' in body
    assert '<th scope="row">Passport' in body
    assert "Submit document to M.Sc. Informatics" in body
    assert "dashboard/documents.js" in body
    assert '<label for="upload-kind">' in body


def test_submit_document_queues_the_upload_page_for_that_application(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        passport = _available(agency_a, membership_a, "PASSPORT")
        redeem_pairing_code(issue_pairing_code(membership_a), "install-1")
    client.force_login(user_a)
    response = client.post(
        SUBMIT,
        {"application_id": application.id, "document_id": passport.id, "source": "upload"},
        HTTP_HOST=domain_a.host,
    )
    assert response["Location"] == PAGE
    with tenant_scope(agency_a.id):
        action = DeviceAction.objects.get(application=application)
    assert action.kind == DeviceAction.Kind.OPEN_UPLOAD_PAGE
    assert action.payload == {
        "application_id": str(application.id), "document_id": str(passport.id), "source": "upload",
    }


def test_submit_document_without_a_portal_says_why(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, portal=False)
        passport = _available(agency_a, membership_a, "PASSPORT")
    client.force_login(user_a)
    response = client.post(
        SUBMIT,
        {"application_id": application.id, "document_id": passport.id, "source": "upload"},
        HTTP_HOST=domain_a.host,
    )
    assert "application portal" in str(list(get_messages(response.wsgi_request))[0])


def test_submitting_another_students_document_is_404(
    client, agency_a, domain_a, user_a, membership_a, user_b, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        other = Membership.objects.create(tenant=agency_a, user=user_b, role=Membership.Role.STUDENT)
        theirs = _available(agency_a, other, "PASSPORT")
        quarantined = register(agency_a.id, membership_a.id, kind="PASSPORT")
        # Clean but still being checked: nothing the extension could fetch.
        checking = register(agency_a.id, membership_a.id, kind="PASSPORT")
        DocumentVersion.objects.filter(id=checking.id).update(
            state="CHECKING", scan_result="NO_THREATS_FOUND"
        )
    client.force_login(user_a)
    for document in (theirs, quarantined, checking):
        response = client.post(
            SUBMIT,
            {"application_id": application.id, "document_id": document.id, "source": "upload"},
            HTTP_HOST=domain_a.host,
        )
        assert response.status_code == 404
    bad = client.post(
        SUBMIT, {"application_id": uuid4(), "document_id": uuid4(), "source": "upload"},
        HTTP_HOST=domain_a.host,
    )
    assert bad.status_code == 404


def test_the_expiry_of_a_passport_is_saved(client, agency_a, domain_a, user_a, membership_a):
    with tenant_scope(agency_a.id):
        passport = _available(agency_a, membership_a, "PASSPORT")
    client.force_login(user_a)
    client.post(
        f"/student/documents/{passport.id}/expiry/", {"expires_on": "2031-05-01"},
        HTTP_HOST=domain_a.host,
    )
    passport.refresh_from_db()
    assert passport.expires_on == date(2031, 5, 1)


def test_an_upload_being_checked_reads_checking_and_offers_no_submit(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme, kit_requirements=["Passport copy"])
        document = register(agency_a.id, membership_a.id, kind="PASSPORT")
        DocumentVersion.objects.filter(id=document.id).update(
            state="CHECKING", scan_result="NO_THREATS_FOUND"
        )
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "checking…" in body
    assert "Submit document to" not in body


def test_a_rejected_upload_says_what_to_do(client, agency_a, domain_a, user_a, membership_a):
    with tenant_scope(agency_a.id):
        document = register(agency_a.id, membership_a.id, kind="PASSPORT")
        DocumentVersion.objects.filter(id=document.id).update(state="REJECTED_ACTIVE_CONTENT")
    client.force_login(user_a)
    page = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "save it again as a plain PDF (Print → Save as PDF)" in page


def test_an_unread_message_can_be_told_which_document_it_asked_for(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT",
            address="a@o.test", tier="METADATA",
        )
        signal = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-1",
            sender_domain="tum.de", received_at=timezone.now(), application=application,
        )
    client.force_login(user_a)
    client.post(
        f"/student/documents/requests/{signal.id}/", {"kind": "TRANSCRIPT"},
        HTTP_HOST=domain_a.host,
    )
    signal.refresh_from_db()
    assert (signal.label, signal.document_name) == ("DOCUMENT_REQUEST", "Transcript")
```

Append `"/student/documents/"` to `STUDENT_PAGES` in `tests/dashboard/test_locks.py`.

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/documents/test_documents_page.py tests/dashboard/test_locks.py`
Expected: FAIL — 404 on `/student/documents/`.

- [ ] **Step 3: The views**

Append to `apps/documents/views.py` (imports: `import json`, `from datetime import date`, `from uuid import UUID`, `from django.contrib import messages`, `from django.http import Http404`, `from django.views.decorators.http import require_POST`, `from apps.concierge.models import UPLOAD_KINDS, DocumentVersion`, `from apps.mailbox.models import MailSignal`, `from apps.portals.applications import REFUSALS, ApplicationRefused, queue_upload`, `from apps.portals.models import Application`, `from .models import DocumentDraft`, `from .table import EXPIRING, ROWS, Cell, table_for`, `from .verification import unsuperseded_facts`):

```python
def page_context(student: Membership, *, counselor_view: bool) -> dict[str, object]:
    """The documents table and everything around it, from tenant rows only."""
    applications = list(
        Application.objects.filter(student=student)
        .select_related("portal_form", "candidate")
        .order_by("created_at")
    )
    signals = list(MailSignal.objects.filter(application__in=applications))
    table = table_for(student, applications, signals)
    grid = [
        {
            "row": row,
            "cells": [
                {
                    "column": column,
                    "state": cell,
                    "held": (
                        table.held_for(row.kind, column.application_id)
                        if cell not in (Cell.NOT_NEEDED, Cell.CHECKING)
                        else None
                    ),
                }
                for column, cell in zip(table.columns, row.cells, strict=True)
            ],
        }
        for row in table.rows
    ]
    facts = list(unsuperseded_facts(student).filter(confirmed_by__isnull=True))
    return {
        "table": table,
        "grid": grid,
        "uploads": DocumentVersion.objects.filter(student=student).order_by("-created_at"),
        "drafts": DocumentDraft.objects.filter(
            student=student, kind=DocumentDraft.Kind.CV
        ).order_by("-version"),
        "facts": facts,
        "confirm_body": json.dumps({"fact_ids": [str(fact.id) for fact in facts]}),
        "upload_kinds": UPLOAD_KINDS,
        "expiring": EXPIRING,
        "row_kinds": ROWS,
        "unnamed": [s for s in signals if s.label == "" and s.application_id is not None],
        "counselor_view": counselor_view,
        "upload_endpoint": (
            f"/counselor/students/{student.id}/uploads/" if counselor_view
            else "/api/documents/uploads"
        ),
    }


@login_required
def documents_page(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    return render(request, "student/documents.html", page_context(student, counselor_view=False))


def _uuid(raw: str | None) -> UUID:
    try:
        return UUID(str(raw))
    except ValueError:
        raise Http404 from None


@login_required
@require_POST
def submit_document(request: HttpRequest) -> HttpResponse:
    """Spec §6 step 1-3: the document goes to the application the cell names."""
    student = current_membership(request, Membership.Role.STUDENT)
    application = get_object_or_404(
        Application.objects.select_related("portal_form"),
        id=_uuid(request.POST.get("application_id")),
        student=student,
    )
    document_id = _uuid(request.POST.get("document_id"))
    source = request.POST.get("source", "")
    usable = (
        source == "upload"
        # AVAILABLE means checked and promoted (Task 14); CHECKING is not usable.
        and DocumentVersion.objects.filter(id=document_id, student=student, state="AVAILABLE")
        .exists()
    ) or (
        source == "draft"
        and DocumentDraft.objects.filter(
            id=document_id, student=student, status=DocumentDraft.Status.APPROVED
        ).exists()
    )
    if not usable:
        raise Http404
    try:
        queue_upload(application, document_id=document_id, source=source, actor=student)
    except ApplicationRefused as refused:
        messages.error(request, REFUSALS[refused.reason])
    else:
        messages.success(
            request, f"Your browser extension is opening {application.where} to attach it."
        )
    return redirect("student-documents")


@login_required
@require_POST
def document_expiry(request: HttpRequest, document_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    document = get_object_or_404(
        DocumentVersion, id=document_id, student=student, kind__in=EXPIRING
    )
    try:
        document.expires_on = date.fromisoformat(request.POST.get("expires_on", ""))
    except ValueError:
        messages.error(request, "Enter the date as shown on the document.")
    else:
        document.save(update_fields=["expires_on"])
        messages.success(request, "Saved.")
    return redirect("student-documents")


@login_required
@require_POST
def document_request(request: HttpRequest, signal_id: UUID) -> HttpResponse:
    """Spec §6: on the metadata tier nothing is read, so the student says which
    document a message asked for."""
    student = current_membership(request, Membership.Role.STUDENT)
    signal = get_object_or_404(
        MailSignal, id=signal_id, connection__membership=student, label=""
    )
    label = dict(ROWS).get(request.POST.get("kind", ""))
    if label is None:
        messages.error(request, "Choose a document from the list.")
    else:
        signal.label = MailSignal.Label.DOCUMENT_REQUEST
        signal.document_name = label
        signal.save(update_fields=["label", "document_name"])
    return redirect("student-documents")
```

(`get_object_or_404` and `render` join the existing `django.shortcuts` import.) Append to `apps/documents/urls.py`:

```python
    path("student/documents/", views.documents_page, name="student-documents"),
    path("student/documents/submit/", views.submit_document, name="student-document-submit"),
    path(
        "student/documents/<uuid:document_id>/expiry/",
        views.document_expiry,
        name="student-document-expiry",
    ),
    path(
        "student/documents/requests/<uuid:signal_id>/",
        views.document_request,
        name="student-document-request",
    ),
```

- [ ] **Step 4: The templates and the script**

`templates/student/documents.html`:

```html
{% extends "base.html" %}
{% load static %}
{% block title %}Documents{% endblock %}
{% block content %}
  <h1>Documents</h1>
  {% include "student/_documents.html" %}
  <script src="{% static 'dashboard/documents.js' %}" defer></script>
{% endblock %}
```

`templates/student/_documents.html` (shared with the counsellor board; student-only forms sit behind `counselor_view`):

```html
{% csrf_token %}
<section aria-labelledby="table-heading" id="documents">
  <h2 id="table-heading">What each application needs</h2>
  {% if table.columns %}
    <table>
      <thead>
        <tr>
          <th scope="col">Document</th>
          {% for column in table.columns %}<th scope="col" id="application-{{ column.application_id }}">{{ column.title }}</th>{% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for line in grid %}
          <tr>
            <th scope="row">{{ line.row.label }}{% if line.row.expires_on %} (expires {{ line.row.expires_on|date:"j M Y" }}){% endif %}</th>
            {% for cell in line.cells %}
              <td>
                {{ cell.state }}
                {% if cell.held and not counselor_view %}
                  <form method="post" action="{% url 'student-document-submit' %}">
                    {% csrf_token %}
                    <input type="hidden" name="application_id" value="{{ cell.column.application_id }}">
                    <input type="hidden" name="document_id" value="{{ cell.held.document_id }}">
                    <input type="hidden" name="source" value="{{ cell.held.source }}">
                    <button type="submit">Submit document to {{ cell.column.title }}</button>
                  </form>
                {% endif %}
              </td>
            {% endfor %}
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p>No applications yet, so nothing is required.</p>
  {% endif %}
</section>

{% if not read_only %}
<section aria-labelledby="upload-heading">
  <h2 id="upload-heading">Upload a document</h2>
  <form data-upload="{{ upload_endpoint }}">
    <p>
      <label for="upload-kind">Document</label>
      <select id="upload-kind" name="kind">{% for value, label in upload_kinds %}<option value="{{ value }}">{{ label }}</option>{% endfor %}</select>
    </p>
    <p><label for="upload-file">File</label> <input type="file" id="upload-file" name="file" accept=".pdf,.jpg,.jpeg,.png"></p>
    <button type="submit">Upload</button>
    <p role="status"></p>
  </form>
</section>
{% endif %}

<section aria-labelledby="uploads-heading">
  <h2 id="uploads-heading">Your uploads</h2>
  <ul>
    {% for upload in uploads %}
      <li>
        {{ upload.get_kind_display }} — {% if upload.rejection_message %}{{ upload.rejection_message }}{% elif upload.state == "CHECKING" %}checking…{% else %}{{ upload.state|lower }}{% endif %}{% if upload.expires_on %}, expires {{ upload.expires_on|date:"j M Y" }}{% endif %}
        {% if upload.kind in expiring and not counselor_view %}
          <form method="post" action="{% url 'student-document-expiry' upload.id %}">
            {% csrf_token %}
            <label for="expiry-{{ upload.id }}">Expires on</label>
            <input type="date" id="expiry-{{ upload.id }}" name="expires_on" value="{{ upload.expires_on|date:'Y-m-d' }}">
            <button type="submit">Save</button>
          </form>
        {% endif %}
      </li>
    {% empty %}
      <li>Nothing uploaded yet.</li>
    {% endfor %}
  </ul>
</section>

<section aria-labelledby="facts-heading" id="facts">
  <h2 id="facts-heading">Facts read from your CV</h2>
  {% if facts %}
    <ul>{% for fact in facts %}<li>{{ fact.category|lower }}: {% for key, value in fact.payload.items %}{{ key }} {{ value }}{% if not forloop.last %}; {% endif %}{% endfor %}</li>{% endfor %}</ul>
    {% if not counselor_view %}
      <p><button type="button" data-api-post="/api/documents/facts/confirm" data-body="{{ confirm_body }}">These are right — confirm them</button> <span role="status"></span></p>
    {% endif %}
  {% else %}
    <p>Nothing to confirm.</p>
  {% endif %}
</section>

<section aria-labelledby="drafts-heading" id="drafts">
  <h2 id="drafts-heading">Your CV</h2>
  {% if not counselor_view %}
    <p><button type="button" data-api-post="/api/documents/generate" data-body='{"kind": "CV"}'>Write my CV</button> <span role="status"></span></p>
  {% endif %}
  <ul>
    {% for draft in drafts %}
      <li>
        Version {{ draft.version }} — {{ draft.status|lower }}
        {% if draft.status == "DRAFT" and not counselor_view %}
          <button type="button" data-api-post="/api/documents/drafts/{{ draft.id }}/approve">Approve</button> <span role="status"></span>
        {% endif %}
        {% if draft.status == "APPROVED" and draft.rendered_filename %}<a href="{% url 'documents-download' draft.id draft.rendered_filename %}">Download</a>{% endif %}
      </li>
    {% empty %}
      <li>No CV yet.</li>
    {% endfor %}
  </ul>
</section>

{% if unnamed and not counselor_view %}
  <section aria-labelledby="unread-heading">
    <h2 id="unread-heading">Messages we could not read</h2>
    {% for signal in unnamed %}
      <form method="post" action="{% url 'student-document-request' signal.id %}">
        {% csrf_token %}
        <p>{{ signal.sender_domain }} wrote on {{ signal.received_at|date:"j M" }} about {{ signal.application.title }}. If it asked for a document, which one?</p>
        <label for="request-{{ signal.id }}">Document</label>
        <select id="request-{{ signal.id }}" name="kind">{% for kind, label in row_kinds %}<option value="{{ kind }}">{{ label }}</option>{% endfor %}</select>
        <button type="submit">Save</button>
      </form>
    {% endfor %}
  </section>
{% endif %}
```

`static/dashboard/documents.js`:

```js
// The documents page's one script (dashboard spec §6). It calls the existing
// JSON door (apps/documents/api.py) and reloads the page; no framework.
(function () {
  "use strict";
  var tokenInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
  var csrf = tokenInput ? tokenInput.value : "";

  function say(element, text) {
    var out = element.querySelector('[role="status"]') ||
      (element.parentElement && element.parentElement.querySelector('[role="status"]'));
    if (out) { out.textContent = text; }
  }

  function post(path, body) {
    return fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(body || {})
    }).then(function (response) {
      return response.json().then(function (data) { return { status: response.status, data: data }; });
    });
  }

  document.querySelectorAll("form[data-upload]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var file = form.querySelector('input[type="file"]').files[0];
      if (!file) { say(form, "Choose a file first."); return; }
      var kind = form.querySelector('select[name="kind"]').value;
      say(form, "Uploading…");
      post(form.dataset.upload, { kind: kind }).then(function (signed) {
        if (signed.status !== 201) { say(form, "Upload refused: " + (signed.data.error || signed.status)); return; }
        var data = new FormData();
        Object.keys(signed.data.fields).forEach(function (key) { data.append(key, signed.data.fields[key]); });
        data.append("file", file);
        return fetch(signed.data.url, { method: "POST", body: data }).then(function (put) {
          say(form, put.ok ? "Uploaded. We are checking the file; the page will refresh." : "Upload failed. Try again.");
          if (put.ok) { setTimeout(function () { window.location.reload(); }, 4000); }
        });
      }).catch(function () { say(form, "Upload failed. Try again."); });
    });
  });

  document.querySelectorAll("button[data-api-post]").forEach(function (button) {
    button.addEventListener("click", function () {
      var body = button.dataset.body ? JSON.parse(button.dataset.body) : {};
      post(button.dataset.apiPost, body).then(function (result) {
        if (result.status < 300) {
          say(button, "Done.");
          setTimeout(function () { window.location.reload(); }, 1500);
        } else {
          say(button, "Refused: " + (result.data.error || result.status));
        }
      }).catch(function () { say(button, "That did not work. Try again."); });
    });
  });
})();
```

- [ ] **Step 5: Run the tests (the static-reference test now guards the script)**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/documents tests/dashboard tests/test_static_references.py`
Expected: PASS.

- [ ] **Step 6: Lint, types, checks, collectstatic**

Run: `uv run ruff check . && uv run mypy apps config && uv run python manage.py check` and the Task 3 Step 5 `collectstatic` command.
Expected: no errors; `W004` for `static/` is gone; `dashboard/documents.js` is collected.

- [ ] **Step 7: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add -A apps/documents templates/student static tests && git commit -m "feat(documents): the documents page and Submit document

Documents x applications with missing, uploaded, approved and certified-copy
cells; uploads of every listed kind through the presigned form; CV facts,
generation and approval through the existing JSON door; Submit document queues
OPEN_UPLOAD_PAGE for the application the cell names after re-checking both are
the student's own; passport and certificate expiry; a metadata-tier message can
be told which document it asked for.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 16: Messages — recognised mail and counsellor messages, per application

Spec §2, §8 ("mail with no application shows under Messages and on no card"). Only facts and labels are shown — the platform keeps no message text (mailbox models' docstring). An untrusted reading is marked as a suggestion.

**Files:**
- Modify: `apps/concierge/views.py`, `apps/concierge/urls.py`, `tests/dashboard/test_locks.py`
- Create: `templates/student/messages.html`, `templates/student/_messages.html`, `tests/concierge/test_messages_page.py`

**Interfaces:**
- Produces: `apps.concierge.views.messages_context(student: Membership) -> dict[str, object]` (keys `mail_groups: list[tuple[str, list[MailSignal]]]`, `conversation`, `has_counselor`, `outcome_labels`) — reused by Task 20
- Produces URL name `student-messages` (`student/messages/`); `send_student_message` honours `return_to=messages`

- [ ] **Step 1: Write the failing tests**

`tests/concierge/test_messages_page.py`:

```python
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.concierge.models import ConversationMessage
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment, Membership
from tests.dashboard.conftest import add_card

pytestmark = pytest.mark.django_db
PAGE = "/student/messages/"


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


def _signal(agency, student, *, application=None, **fields):
    connection, _ = MailboxConnection.objects.get_or_create(
        tenant=agency, membership=student, provider="MICROSOFT",
        defaults={"address": f"{student.id}@outlook.test"},
    )
    return MailSignal.objects.create(
        tenant=agency, connection=connection, provider_message_id=f"m-{uuid4()}",
        sender_domain="tum.de", received_at=timezone.now(), application=application, **fields,
    )


def test_mail_is_grouped_by_application_and_unlinked_mail_has_its_own_group(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        _signal(agency_a, membership_a, application=application, label="DOCUMENT_REQUEST",
                document_name="Final transcript", trusted=True)
        _signal(agency_a, membership_a, label="DECISION", outcome="ADMITTED", trusted=False)
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "<h3>M.Sc. Informatics</h3>" in body
    assert "asks for: Final transcript" in body
    assert "<h3>Not about one application</h3>" in body
    assert "says: Admitted" in body
    assert "sender not verified" in body


def test_another_students_mail_is_never_listed(
    client, agency_a, domain_a, user_a, membership_a, user_b
) -> None:
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(tenant=agency_a, user=user_b, role=Membership.Role.STUDENT)
        _signal(agency_a, other, label="FEE")
    client.force_login(user_a)
    assert "A fee is due" not in client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()


def test_writing_from_the_messages_page_comes_back_to_it(
    client, agency_a, domain_a, user_a, membership_a, counselor_membership
) -> None:
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        ConversationMessage.objects.create(
            tenant=agency_a, student=membership_a, counselor=counselor_membership,
            sender=counselor_membership, body="Your transcript arrived.",
        )
    client.force_login(user_a)
    assert "Your transcript arrived." in client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()

    sent = client.post(
        "/student/messages/send/", {"body": "Thanks", "return_to": "messages"},
        HTTP_HOST=domain_a.host,
    )
    assert sent["Location"] == PAGE

    refused = client.post(
        "/student/messages/send/", {"body": "x" * 4001, "return_to": "messages"},
        HTTP_HOST=domain_a.host,
    )
    body = refused.content.decode()
    assert refused.status_code == 400
    assert "<h1>Messages</h1>" in body
    assert 'role="alert"' in body
    assert "x" * 4001 in body
```

Append `"/student/messages/"` to `STUDENT_PAGES` in `tests/dashboard/test_locks.py`.

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/concierge/test_messages_page.py`
Expected: FAIL — 404 on `/student/messages/`.

- [ ] **Step 3: The view**

`apps/concierge/views.py` (imports: `from apps.mailbox.models import MailSignal`, `from .models import ConversationMessage, Notification, RoadmapItem`):

```python
def messages_context(student: Membership) -> dict[str, object]:
    """Recognised mail per application, and the counsellor conversation."""
    groups: dict[str, list[MailSignal]] = {}
    for signal in (
        MailSignal.objects.filter(connection__membership=student)
        .select_related("application__candidate", "application__portal_form")
        .order_by("-received_at")
    ):
        title = signal.application.title if signal.application is not None else (
            "Not about one application"
        )
        groups.setdefault(title, []).append(signal)
    return {
        "mail_groups": list(groups.items()),
        "conversation": ConversationMessage.objects.filter(student=student).order_by("created_at"),
        "has_counselor": CounselorAssignment.objects.filter(student=student, active=True).exists(),
        "outcome_labels": dict(Application.Outcome.choices),
    }


def _messages_page(
    request: HttpRequest,
    student: Membership,
    *,
    status: int = 200,
    error: str | None = None,
    form_values: dict[str, str] | None = None,
) -> HttpResponse:
    context = messages_context(student)
    context.update(
        {"error": error, "error_form": "message" if error else None, "form_values": form_values or {}}
    )
    return render(request, "student/messages.html", context, status=status)


@login_required
def messages_page(request: HttpRequest) -> HttpResponse:
    return _messages_page(request, current_membership(request, Membership.Role.STUDENT))
```

In `send_student_message`, add after `body = ...`:

```python
    back_to_messages = request.POST.get("return_to") == "messages"
```

make `_message_error` return `_messages_page(request, student, status=status, error=message, form_values={"body": body})` when `back_to_messages`, and the existing `_student_dashboard_page(...)` call otherwise; and replace the final `return redirect("concierge-student-dashboard")` with:

```python
    return redirect("student-messages" if back_to_messages else "concierge-student-dashboard")
```

`apps/concierge/urls.py`: import `messages_page` and add `path("student/messages/", messages_page, name="student-messages"),`.

- [ ] **Step 4: The templates**

`templates/student/_messages.html`:

```html
{% load dashboard %}
<section aria-labelledby="mail-heading" id="messages">
  <h2 id="mail-heading">Mail from universities and funders</h2>
  {% for title, signals in mail_groups %}
    <section>
      <h3>{{ title }}</h3>
      <ul>
        {% for signal in signals %}
          <li>
            {{ signal.received_at|date:"j M Y H:i" }} — {{ signal.sender_domain }}:
            {% if signal.label %}{{ signal.get_label_display }}{% else %}wrote to you (open the email to read it){% endif %}
            {% if signal.document_name %} — asks for: {{ signal.document_name }}{% if signal.document_due %} by {{ signal.document_due|date:"j M Y" }}{% endif %}{% endif %}
            {% if signal.interview_at %} — interview on {{ signal.interview_at|date:"j M Y, H:i e" }}{% endif %}
            {% if signal.offered_programme %} — offers a place in: {{ signal.offered_programme }}{% endif %}
            {% if signal.outcome %} — says: {{ outcome_labels|lookup:signal.outcome }}{% endif %}
            {% if not signal.trusted %} (sender not verified: a suggestion only){% endif %}
          </li>
        {% endfor %}
      </ul>
    </section>
  {% empty %}
    <p>No mail recognised yet. Connect your inbox in Settings.</p>
  {% endfor %}
</section>
<section aria-labelledby="conversation-heading">
  <h2 id="conversation-heading">Your counsellor</h2>
  {% for message in conversation %}
    <p>{% if message.sender_id == message.student_id %}Student{% else %}Counsellor{% endif %}, {{ message.created_at|date:"j M H:i" }}: {{ message.body|linebreaksbr }}</p>
  {% empty %}
    <p>No messages yet.</p>
  {% endfor %}
</section>
```

`templates/student/messages.html`:

```html
{% extends "base.html" %}
{% block title %}Messages{% endblock %}
{% block content %}
  <h1>Messages</h1>
  {% include "student/_messages.html" %}
  {% if has_counselor %}
    <form method="post" action="{% url 'concierge-send-student-message' %}">
      {% csrf_token %}
      <input type="hidden" name="return_to" value="messages">
      {% if error and error_form == "message" %}<p role="alert" id="message-error">{{ error }}</p>{% endif %}
      <p>
        <label for="message-body">Write to your counsellor</label><br>
        <textarea id="message-body" name="body" rows="4" maxlength="4000">{{ form_values.body }}</textarea>
      </p>
      <button type="submit">Send</button>
    </form>
  {% endif %}
{% endblock %}
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/concierge tests/dashboard && uv run ruff check . && uv run mypy apps config`
Expected: PASS (the kept message-limit test still re-renders home: it sends no `return_to`).

- [ ] **Step 6: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add apps/concierge templates/student tests/concierge/test_messages_page.py tests/dashboard/test_locks.py && git commit -m "feat(concierge): the messages page

Recognised mail grouped per application (unlinked mail in its own group) with
the label, requested document and stated outcome -- never the text -- and the
counsellor conversation with a form that returns to the page.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 17: Settings — index, mailbox, extension, account, and the deletion waiting page

Spec §2. The mailbox views keep answering JSON to JSON callers and also accept a plain browser form post (recognised by `Accept: text/html`), which redirects back to the mailbox page with a message; the Outlook callback redirects there too. A not-yours id is still a 404 on both paths.

**Files:**
- Modify: `apps/concierge/views.py`, `apps/concierge/urls.py`, `apps/mailbox/views.py`, `apps/mailbox/urls.py`, `apps/portals/views.py`, `apps/portals/urls.py`, `apps/audit/views.py`, `apps/audit/urls.py`, `tests/dashboard/test_locks.py`
- Create: `templates/student/settings.html`, `templates/student/settings_mailbox.html`, `templates/student/settings_extension.html`, `templates/student/settings_account.html`, `templates/audit/deletion_pending.html`, `tests/mailbox/test_mailbox_page.py`, `tests/portals/test_extension_page.py`, `tests/audit/test_account_page.py`, `tests/concierge/test_settings_page.py`
- Delete: `tests/templates/audit/deletion_pending.html`

**Interfaces:**
- Produces URL names: `student-settings` (`student/settings/`), `student-settings-mailbox` (`student/settings/mailbox/`), `student-settings-extension` (`student/settings/extension/`), `student-settings-extension-disconnect` (`student/settings/extension/<uuid:pairing_id>/disconnect/`), `student-settings-account` (`student/settings/account/`)
- Produces: `apps.mailbox.views._wants_html(request: HttpRequest) -> bool`

- [ ] **Step 1: Write the failing tests**

`tests/concierge/test_settings_page.py`:

```python
import pytest

pytestmark = pytest.mark.django_db


def test_settings_links_every_settings_page(client, domain_a, user_a, membership_a) -> None:
    client.force_login(user_a)
    body = client.get("/student/settings/", HTTP_HOST=domain_a.host).content.decode()
    for href in (
        "/student/profile/", "/student/settings/mailbox/", "/student/settings/extension/",
        "/student/settings/account/",
    ):
        assert f'href="{href}"' in body
    assert "Not started" in body
```

`tests/mailbox/test_mailbox_page.py`:

```python
import pytest
from django.core import signing
from django.urls import reverse

from apps.mailbox.models import MailboxConnection
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db
PAGE = "/student/settings/mailbox/"


def test_the_page_lists_connections_and_offers_connect(student_client, connection_with_pack) -> None:
    client, _student = student_client
    body = client.get(PAGE).content.decode()
    assert connection_with_pack.address in body
    assert f'action="{reverse("mailbox-revoke", args=[connection_with_pack.id])}"' in body
    assert 'name="tier"' in body and 'name="kind"' in body
    assert '<label for="tier-' in body


def test_a_browser_revoke_comes_back_to_the_page(
    student_client, connection_with_pack, fake_secrets
) -> None:
    client, _student = student_client
    response = client.post(
        reverse("mailbox-revoke", args=[connection_with_pack.id]), HTTP_ACCEPT="text/html"
    )
    assert response.status_code == 302
    assert response["Location"] == PAGE
    connection_with_pack.refresh_from_db()
    assert connection_with_pack.status == MailboxConnection.Status.REVOKED


def test_a_browser_downgrade_reads_the_form(student_client, connection_with_pack) -> None:
    client, _student = student_client
    response = client.post(
        reverse("mailbox-tier", args=[connection_with_pack.id]), {"tier": "METADATA"},
        HTTP_ACCEPT="text/html",
    )
    assert response["Location"] == PAGE
    connection_with_pack.refresh_from_db()
    assert connection_with_pack.tier == MailboxConnection.Tier.METADATA


def test_a_browser_revoke_of_someone_else_s_connection_is_404(
    second_student_client, connection_with_pack
) -> None:
    response = second_student_client.post(
        reverse("mailbox-revoke", args=[connection_with_pack.id]), HTTP_ACCEPT="text/html"
    )
    assert response.status_code == 404


def test_the_callback_lands_on_the_mailbox_page(student_client, fake_exchange) -> None:
    client, student = student_client
    state = signing.dumps({"membership": str(student.id), "provider": "GOOGLE", "tier": "CONTENT"})
    response = client.get(reverse("mailbox-callback", args=["GOOGLE"]) + f"?code=c&state={state}")
    assert response["Location"] == PAGE
    with tenant_scope(student.tenant_id):
        assert MailboxConnection.objects.filter(membership=student).exists()
```

`tests/portals/test_extension_page.py`:

```python
import pytest

from apps.portals.pairing import issue_pairing_code, redeem_pairing_code
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db
PAGE = "/student/settings/extension/"


def _paired(agency, membership, installation="laptop-1"):
    with tenant_scope(agency.id):
        pairing, _token = redeem_pairing_code(issue_pairing_code(membership), installation)
    return pairing


def test_the_page_lists_paired_browsers_and_how_to_pair(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    pairing = _paired(agency_a, membership_a)
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "laptop-1" in body
    assert f'action="/student/settings/extension/{pairing.id}/disconnect/"' in body
    assert "How to pair" in body


def test_disconnect_revokes_the_pairing(client, agency_a, domain_a, user_a, membership_a) -> None:
    pairing = _paired(agency_a, membership_a)
    client.force_login(user_a)
    response = client.post(
        f"/student/settings/extension/{pairing.id}/disconnect/", HTTP_HOST=domain_a.host
    )
    assert response["Location"] == PAGE
    pairing.refresh_from_db()
    assert pairing.revoked_at is not None
    assert pairing.token_hash == ""


def test_another_students_pairing_is_404(client, agency_a, domain_a, user_a, membership_a, user_b) -> None:
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(tenant=agency_a, user=user_b, role=Membership.Role.STUDENT)
    pairing = _paired(agency_a, other)
    client.force_login(user_a)
    response = client.post(
        f"/student/settings/extension/{pairing.id}/disconnect/", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 404
```

`tests/audit/test_account_page.py`:

```python
import pytest
from django.utils import timezone

from apps.audit.models import DeletionRequest
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def test_the_account_page_asks_for_a_reason_from_the_list(client, domain_a, user_a, membership_a):
    client.force_login(user_a)
    body = client.get("/student/settings/account/", HTTP_HOST=domain_a.host).content.decode()
    assert 'action="/student/account/delete/"' in body
    assert '<label for="deletion-reason">' in body
    for value, _label in DeletionRequest.Reason.choices:
        assert f'value="{value}"' in body


def test_the_waiting_page_offers_restore(client, agency_a, domain_a, user_a, membership_a):
    with tenant_scope(agency_a.id):
        record = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="APPROVED", reason="OTHER",
            execute_after=timezone.now(),
        )
    client.force_login(user_a)
    body = client.get("/student/account/deletion/", HTTP_HOST=domain_a.host).content.decode()
    assert "Skip to content" in body
    assert f'action="/student/account/restore/{record.id}/"' in body
    assert 'action="/accounts/logout/"' in body
```

Append `"/student/settings/"`, `"/student/settings/mailbox/"`, `"/student/settings/extension/"`, `"/student/settings/account/"` to `STUDENT_PAGES` in `tests/dashboard/test_locks.py`.

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/concierge/test_settings_page.py tests/mailbox/test_mailbox_page.py tests/portals/test_extension_page.py tests/audit/test_account_page.py`
Expected: FAIL — 404 on every settings path; the callback still redirects to `/`.

- [ ] **Step 3: Settings index**

`apps/concierge/views.py` (import `from apps.accounts.models import StudentProfileVersion`):

```python
@login_required
def settings_page(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    profile_done = StudentProfileVersion.objects.filter(student=student).exists()
    return render(request, "student/settings.html", {"profile_done": profile_done})
```

`apps/concierge/urls.py`: import it and add `path("student/settings/", settings_page, name="student-settings"),`.

`templates/student/settings.html`:

```html
{% extends "base.html" %}
{% block title %}Settings{% endblock %}
{% block content %}
  <h1>Settings</h1>
  <ul>
    <li><a href="/student/profile/">Profile</a> — {% if profile_done %}complete; you can update it{% else %}Not started{% endif %}</li>
    <li><a href="/student/settings/mailbox/">Mailbox</a> — the inbox we watch for university replies</li>
    <li><a href="/student/settings/extension/">Browser extension</a> — the browsers that fill your applications</li>
    <li><a href="/student/settings/account/">Account</a> — leave and delete your data</li>
  </ul>
{% endblock %}
```

- [ ] **Step 4: Mailbox page and form posts**

`apps/mailbox/views.py` (imports: `from django.contrib import messages`, `from django.http import Http404`, `from django.shortcuts import redirect, render`, `from apps.mailbox.filter import allowed_senders`); update the module docstring's first paragraph to say the connect screen is `templates/student/settings_mailbox.html`. Add:

```python
def _wants_html(request: HttpRequest) -> bool:
    """A browser form post (Accept: text/html) gets a redirect and a message; a
    JSON caller keeps getting JSON. Django's test client sends no Accept header."""
    return "text/html" in request.headers.get("Accept", "")


def _answer(
    request: HttpRequest, payload: dict[str, object], *, status: int = 200, message: str = ""
) -> HttpResponse:
    if not _wants_html(request):
        return JsonResponse(payload, status=status)
    if status == 404:
        # The id of a connection that is not yours is not a fact you get to confirm.
        raise Http404
    if status >= 400:
        messages.error(request, message or "That did not work. Try again.")
    elif message:
        messages.success(request, message)
    return redirect("student-settings-mailbox")


@login_required
def mailbox_settings(request: HttpRequest) -> HttpResponse:
    """Connections, connect (tier and kind), revoke, downgrade, senders to confirm,
    and the live list of domains the pack justifies reading -- the privacy
    argument in one screen."""
    membership = current_membership(request, Membership.Role.STUDENT)
    return render(
        request,
        "student/settings_mailbox.html",
        {
            "connections": MailboxConnection.objects.filter(membership=membership).order_by(
                "-connected_at"
            ),
            "learned": LearnedSender.objects.filter(
                student=membership, confirmed_at__isnull=True
            ).exclude(domain=""),
            "domains": sorted(allowed_senders(membership)),
            "providers": settings.MAILBOX_PROVIDERS,
            "tiers": MailboxConnection.Tier.choices,
            "kinds": MailboxConnection.Kind.choices,
        },
    )
```

In `callback`, replace each `return JsonResponse({"reason": X}, status=S)` with `return _answer(request, {"reason": X}, status=S, message=...)` using the messages `"The connection link expired or was not yours. Start again."` (`bad_state`, `state_mismatch`), `"The provider did not send a code. Start again."` (`no_code`), `"The provider is busy. Try again in a minute."` (`try_again`) and `"The provider refused the connection."` (`grant_refused`); replace the final `return HttpResponseRedirect("/")` with:

```python
    messages.success(request, f"{grant.address} is connected.")
    return redirect("student-settings-mailbox")
```

In `revoke`: the not-found return becomes `return _answer(request, {"reason": "not_found"}, status=404)` and the last line `return _answer(request, {"revoked": True}, message="Disconnected.")`.

In `tier`, replace the body-reading block with:

```python
    if request.content_type == "application/json":
        try:
            wanted = json.loads(request.body or b"{}").get("tier", "")
        except json.JSONDecodeError:
            return JsonResponse({"reason": "bad_request"}, status=400)
    else:
        wanted = request.POST.get("tier", "")
    if wanted not in MailboxConnection.Tier.values:
        return _answer(request, {"reason": "unknown_tier"}, status=400)
```

and its other returns: not found → `_answer(request, {"reason": "not_found"}, status=404)`; widening → `_answer(request, {"reason": "reconnect_required"}, status=409, message="Reading more needs a new connection: disconnect and connect again.")`; success → `_answer(request, {"tier": wanted}, message="From now on only headers are read.")`.

In `confirm_sender`: not found → `_answer(request, {"reason": "not_found"}, status=404)`; success → `_answer(request, {"confirmed": True}, message="Confirmed.")`.

`apps/mailbox/urls.py`: add `path("student/settings/mailbox/", views.mailbox_settings, name="student-settings-mailbox"),`.

`templates/student/settings_mailbox.html`:

```html
{% extends "base.html" %}
{% block title %}Mailbox{% endblock %}
{% block content %}
  <h1>Mailbox</h1>
  <h2>Connected inboxes</h2>
  {% for connection in connections %}
    <article>
      <h3>{{ connection.address }}</h3>
      <p>{{ connection.get_provider_display }} · {{ connection.get_tier_display }} · {{ connection.get_kind_display }} · {{ connection.get_status_display }}{% if connection.last_sync_at %} · last checked {{ connection.last_sync_at|date:"j M H:i" }}{% endif %}</p>
      {% if connection.status == "ACTIVE" %}
        <form method="post" action="{% url 'mailbox-revoke' connection.id %}">{% csrf_token %}<button type="submit">Disconnect</button></form>
        {% if connection.tier == "CONTENT" %}
          <form method="post" action="{% url 'mailbox-tier' connection.id %}">
            {% csrf_token %}
            <input type="hidden" name="tier" value="METADATA">
            <button type="submit">Read headers only from now on</button>
          </form>
        {% endif %}
      {% endif %}
    </article>
  {% empty %}
    <p>No inbox connected.</p>
  {% endfor %}

  <h2>Connect an inbox</h2>
  <p>We read only mail from these senders: {{ domains|join:", "|default:"none yet — add an application first" }}.</p>
  {% for provider in providers %}
    <form method="get" action="{% url 'mailbox-connect' provider %}">
      <fieldset>
        <legend>{{ provider|title }}</legend>
        <p>
          <label for="tier-{{ provider }}">What we may read</label>
          <select id="tier-{{ provider }}" name="tier">{% for value, label in tiers %}<option value="{{ value }}">{{ label }}</option>{% endfor %}</select>
        </p>
        <p>
          <label for="kind-{{ provider }}">Which inbox</label>
          <select id="kind-{{ provider }}" name="kind">{% for value, label in kinds %}<option value="{{ value }}">{{ label }}</option>{% endfor %}</select>
        </p>
        <button type="submit">Connect</button>
      </fieldset>
    </form>
  {% endfor %}

  <h2>Senders to confirm</h2>
  {% for sender in learned %}
    <form method="post" action="{% url 'mailbox-confirm-sender' sender.id %}">
      {% csrf_token %}
      <p>{{ sender.domain }} wrote to the address you use on {{ sender.portal_host }}.</p>
      <button type="submit">Yes, this is {{ sender.portal_host }}</button>
    </form>
  {% empty %}
    <p>None.</p>
  {% endfor %}
{% endblock %}
```

- [ ] **Step 5: Extension page**

Append to `apps/portals/views.py` (imports: `from .models import ExtensionPairing`, `from .pairing import revoke_pairing`):

```python
@login_required
def extension_settings(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    pairings = ExtensionPairing.objects.filter(
        membership=student, redeemed_at__isnull=False, revoked_at__isnull=True
    ).order_by("-last_seen_at")
    return render(request, "student/settings_extension.html", {"pairings": pairings})


@login_required
@require_POST
def extension_disconnect(request: HttpRequest, pairing_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    pairing = get_object_or_404(
        ExtensionPairing, id=pairing_id, membership=student, revoked_at__isnull=True
    )
    revoke_pairing(pairing)
    messages.success(request, "That browser is disconnected.")
    return redirect("student-settings-extension")
```

`apps/portals/urls.py`:

```python
    path("student/settings/extension/", views.extension_settings, name="student-settings-extension"),
    path(
        "student/settings/extension/<uuid:pairing_id>/disconnect/",
        views.extension_disconnect,
        name="student-settings-extension-disconnect",
    ),
```

`templates/student/settings_extension.html`:

```html
{% extends "base.html" %}
{% block title %}Browser extension{% endblock %}
{% block content %}
  <h1>Browser extension</h1>
  <h2>Connected browsers</h2>
  {% for pairing in pairings %}
    <article>
      <p>{{ pairing.installation_id|default:"A browser" }} — connected {{ pairing.redeemed_at|date:"j M Y" }}{% if pairing.last_seen_at %}, last seen {{ pairing.last_seen_at|date:"j M Y H:i" }}{% endif %}</p>
      <form method="post" action="{% url 'student-settings-extension-disconnect' pairing.id %}">{% csrf_token %}<button type="submit">Disconnect</button></form>
    </article>
  {% empty %}
    <p>No browser is connected.</p>
  {% endfor %}
  <h2>How to pair</h2>
  <ol>
    <li>Use Chrome, Edge, Brave, Opera, Vivaldi or Arc on a computer.</li>
    <li>Install the Tehsil extension from the Chrome Web Store.</li>
    <li>Open this dashboard while logged in. The extension connects to your account by itself.</li>
  </ol>
  <p>Logging out keeps your browsers connected. Disconnect one here when you stop using it.</p>
{% endblock %}
```

- [ ] **Step 6: Account page and the waiting page**

Append to `apps/audit/views.py`:

```python
@login_required
def account_settings(request: HttpRequest) -> HttpResponse:
    """The deletion request form. An open request never reaches this: the
    deletion lock sends the student to the waiting page first."""
    current_membership(request, Membership.Role.STUDENT)
    return render(
        request, "student/settings_account.html", {"reasons": DeletionRequest.Reason.choices}
    )
```

`apps/audit/urls.py`: import it and add `path("student/settings/account/", account_settings, name="student-settings-account"),`.

`templates/student/settings_account.html`:

```html
{% extends "base.html" %}
{% block title %}Account{% endblock %}
{% block content %}
  <h1>Account</h1>
  <h2>Leave and delete my data</h2>
  <p>Your access closes as soon as you ask. Your data is erased after thirty days; until then you can restore your account.</p>
  <form method="post" action="{% url 'audit-request-account-deletion' %}">
    {% csrf_token %}
    <p>
      <label for="deletion-reason">Why are you leaving?</label>
      <select id="deletion-reason" name="reason" required>
        {% for value, label in reasons %}<option value="{{ value }}">{{ label }}</option>{% endfor %}
      </select>
    </p>
    <button type="submit">Delete my account</button>
  </form>
{% endblock %}
```

`templates/audit/deletion_pending.html`:

```html
{% extends "base.html" %}
{% block title %}Account closing{% endblock %}
{% block content %}
  <h1>Your account is closing</h1>
  {% if request_record.state == "APPROVED" %}
    <p>Your data will be erased on {{ request_record.execute_after|date:"j F Y" }}.</p>
  {% elif request_record.state == "RETENTION_REVIEW" %}
    <p>Your agency must keep some records for now; they will tell you what is kept and why.</p>
  {% else %}
    <p>Your request is being processed.</p>
  {% endif %}
  {% if in_flight %}<p>{{ in_flight }} of your applications are with a university. Closing your account does not withdraw them.</p>{% endif %}
  <form method="post" action="{% url 'audit-restore-account' request_record.id %}">
    {% csrf_token %}
    <button type="submit">Restore my account</button>
  </form>
{% endblock %}
```

```bash
cd /home/orkhan/Desktop/student-dashboard && git rm tests/templates/audit/deletion_pending.html
```

- [ ] **Step 7: Run the tests**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/concierge tests/mailbox tests/portals tests/audit tests/dashboard`
Expected: PASS (every existing mailbox view test keeps its JSON answers: none sends `Accept: text/html`).

- [ ] **Step 8: Lint, types, checks**

Run: `uv run ruff check . && uv run mypy apps config && uv run python manage.py check`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add -A apps templates tests && git commit -m "feat(settings): mailbox, extension and account pages

Settings index; the mailbox connect screen with tier, kind, the domains we read
and senders to confirm, its views answering JSON to JSON callers and redirecting
browser form posts back with a message (the callback lands there too); paired
browsers with disconnect; the deletion request form and the waiting page with
Restore.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 18: The profile wizard and the gap interview on `base.html`

Spec §2: the existing wizard and gap interview, now inside the page chrome. `base.html` holds no text input, so the gap interview's exact `<input type="text"` count still holds. `_page` in `apps/documents/views.py` becomes the public `render_gap_page` so the counsellor route (Task 20) renders the same page.

**Files:**
- Create: `templates/student/consultation.html`, `templates/student/_consultation_step.html`
- Modify: `apps/documents/templates/documents/gap_interview.html`, `apps/documents/views.py`, `apps/accounts/views.py`, `tests/accounts/test_consultation.py`, `tests/accounts/test_wizard_sequencing_errors.py` (remove `xfail` markers naming Task 18), `tests/dashboard/test_locks.py`
- Delete: `tests/templates/student/consultation.html`, `tests/templates/student/_consultation_step.html`

**Interfaces:**
- Produces: `apps.documents.views.render_gap_page(request: HttpRequest, student: Membership, *, error: str | None = None) -> HttpResponse`

- [ ] **Step 1: Write the failing tests**

Delete the four `xfail` markers naming Task 18. Append to `tests/documents/test_gap_interview_view.py`:

```python
def test_the_gap_interview_sits_inside_the_page_chrome(client, domain_a, user_a, membership_a):
    client.force_login(user_a)
    body = client.get(URL, HTTP_HOST=domain_a.host).content.decode()
    assert "Skip to content" in body
    assert 'href="/student/documents/"' in body
```

Append `"/student/profile/"` and `"/student/gap-interview/"` to `STUDENT_PAGES` in `tests/dashboard/test_locks.py`.

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/accounts tests/documents/test_gap_interview_view.py`
Expected: FAIL — the stub wizard templates render nothing; the gap page has no skip link.

- [ ] **Step 3: The wizard templates**

In `apps/accounts/views.py::_render_review`, add `"labels": QUESTION_LABELS` to the context (import `QUESTION_LABELS` from `.consultation`).

`templates/student/consultation.html`:

```html
{% extends "base.html" %}
{% block title %}Your profile{% endblock %}
{% block content %}
  <h1>Your profile</h1>
  <p>One question at a time. Your answers are kept as you go.</p>
  {% include "student/_consultation_step.html" %}
{% endblock %}
```

`templates/student/_consultation_step.html` (the fragment the htmx-headed posts still receive):

```html
{% load dashboard %}
<section id="consultation" aria-labelledby="consultation-heading">
  {% if review %}
    <h2 id="consultation-heading">Check your answers</h2>
    {% if error %}<p role="alert">{{ error }}</p>{% endif %}
    <dl>
      {% for key, value in draft.answers.items %}<dt>{{ labels|lookup:key|default:key }}</dt><dd>{{ value }}</dd>{% endfor %}
    </dl>
    <form method="post" action="{% url 'student-profile' %}">
      {% csrf_token %}
      <input type="hidden" name="action" value="confirm">
      <button type="submit">Confirm and start research</button>
    </form>
  {% else %}
    <h2 id="consultation-heading">Question {{ progress_answered|add:1 }} of {{ progress_total }}</h2>
    {% if error %}<p role="alert">{{ error }}</p>{% endif %}
    {% for message in form.value.errors %}<p role="alert">{{ message }}</p>{% endfor %}
    <form method="post" action="{% url 'student-profile' %}">
      {% csrf_token %}
      <input type="hidden" name="key" value="{{ question.key }}">
      <p>
        <label for="{{ form.value.id_for_label }}">{{ question.label }}</label><br>
        {{ form.value }}
      </p>
      <button type="submit">Next</button>
    </form>
  {% endif %}
</section>
```

```bash
cd /home/orkhan/Desktop/student-dashboard && git rm tests/templates/student/consultation.html tests/templates/student/_consultation_step.html
```

- [ ] **Step 4: The gap interview on `base.html`**

`apps/documents/templates/documents/gap_interview.html` — Django requires `{% extends %}` to be the first tag (a `{% comment %}` node before it is a `TemplateSyntaxError`), so the explanatory comment moves inside the content block. The whole file:

```html
{% extends "base.html" %}
{% block title %}A few questions about your CV{% endblock %}
{% block content %}
  {% comment %}
  Unstyled on purpose. Two things here are load-bearing rather than unfinished:

  No input carries `required`. Every question is skippable and a blank is an
  ordinary skip -- a browser-side requirement would refuse a submission the
  server considers entirely valid.

  Ids are positional (`q1`, `q2`) rather than the field name, which carries a
  colon: valid in an HTML id, but it breaks bare CSS and querySelector.

  base.html carries no text input, so the exact `<input type="text"` count in
  tests/documents/test_gap_interview_view.py still counts questions only.
  {% endcomment %}
  <h1>A few questions about your CV</h1>
  {% if error %}<p role="alert">{{ error }}</p>{% endif %}
  {% if notes %}
    <section>
      <h2>Worth knowing</h2>
      <p>Nothing to answer here -- these are for you and your counsellor.</p>
      <ul>
        {% for note in notes %}
          <li>{{ note.text }} <small>{{ note.evidence }}</small></li>
        {% endfor %}
      </ul>
    </section>
  {% endif %}
  {% if fields %}
    <p>Answer what you can. Anything you leave blank stays on the list.</p>
    <form method="post">
      {% csrf_token %}
      {% for name, question in fields %}
        <p>
          <label for="q{{ forloop.counter }}">{{ question.prompt }}</label>
          <small>{{ question.evidence }}</small>
          <input type="text" id="q{{ forloop.counter }}" name="{{ name }}">
        </p>
      {% endfor %}
      <button type="submit">Save answers</button>
    </form>
  {% endif %}
  {% if not fields and not notes %}<p>Nothing to ask right now.</p>{% endif %}
{% endblock %}
```

`apps/documents/views.py`: rename `_page` to `render_gap_page` (both call sites) and replace the docstring paragraph beginning "The template is an app template, not a root one." with: "The template is an app template that extends the root `base.html`; base.html carries no text input, which keeps tests/documents/test_gap_interview_view.py's exact count of `<input type=\"text\"` honest."

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/accounts tests/documents tests/dashboard`
Expected: PASS — the four wizard tests run without `xfail`; the gap-interview count test still passes.

- [ ] **Step 6: Lint, types**

Run: `uv run ruff check . && uv run mypy apps config`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add -A apps/accounts apps/documents templates/student tests && git commit -m "feat(profile): the wizard and the gap interview inside the page

The one-question-per-page wizard with its review step and inline errors, and
the gap interview moved onto base.html with no text input added to the chrome.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 19: The Application Kit page

Spec §2 and the glass-box kit: answers in the portal's order with missing ones marked, the programme's own REQUIRED statements, the steps only the applicant can take (their `source_url` is a model's read of a third-party page — `https_only`), approved documents with download links, why the extension cannot fill when it cannot, and Start application.

**Files:**
- Modify: `apps/portals/views.py` (`application_kit` context)
- Create: `templates/portals/kit.html`, `tests/portals/test_kit_page.py`
- Delete: `tests/templates/portals/kit.html`

**Interfaces:**
- Consumes: `build_kit(application) -> ApplicationKit`
- Template context: `kit`, `start_url: str`, `not_fillable_text: str`

- [ ] **Step 1: Write the failing tests**

`tests/portals/test_kit_page.py`:

```python
from uuid import uuid4

import pytest

from apps.audit.models import DeletionRequest
from apps.portals.models import Application, FieldMap, PortalForm
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _application(agency, student, **fields):
    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key=f"k-{uuid4()}",
        form_url="https://apply.example.edu/personal",
    )
    FieldMap.objects.create(
        portal_form=form, version=1,
        entries=[{"profile_field": "identity.full_name", "action": {
            "selector": "#name", "description": "Full name", "method": "fill",
            "arguments": ["%value%"]}}],
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form, **fields
    )


def test_the_kit_marks_missing_answers_and_offers_start(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        application = _application(
            agency_a, membership_a, kit_requirements=["A CV in English."]
        )
    client.force_login(user_a)
    body = client.get(f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host).content.decode()
    assert "Full name" in body
    assert "missing" in body
    assert "A CV in English." in body
    assert f'action="/student/applications/{application.id}/start/"' in body


def test_a_kit_action_with_an_http_url_is_text_not_a_link(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    actions = [
        {"text": "Sign the declaration by hand.", "source_url": "http://evil.example/x",
         "requirement": "REQUIRED", "status": "YOUR_ACTION", "statement_id": ""},
        {"text": "Upload the signed form.", "source_url": "https://apply.example.edu/rules",
         "requirement": "REQUIRED", "status": "YOUR_ACTION", "statement_id": ""},
    ]
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, kit_your_actions=actions)
    client.force_login(user_a)
    body = client.get(f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host).content.decode()
    assert "Sign the declaration by hand." in body
    assert 'href="http://evil.example/x"' not in body
    assert 'href="https://apply.example.edu/rules"' in body


def test_a_portal_less_kit_says_why_and_offers_no_start(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4()
        )
    client.force_login(user_a)
    body = client.get(f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host).content.decode()
    assert "application portal is not known yet" in body
    assert "/start/" not in body


def test_the_kit_is_behind_the_deletion_lock(client, agency_a, domain_a, user_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED", reason="OTHER"
        )
    client.force_login(user_a)
    response = client.get(f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host)
    assert response["Location"] == "/student/account/deletion/"
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/portals/test_kit_page.py`
Expected: FAIL — the stub renders nothing.

- [ ] **Step 3: The view's context**

In `apps/portals/views.py`:

```python
_NOT_FILLABLE = {
    "no_portal": "This programme's application portal is not known yet; your counsellor is finding it. Apply with this kit by hand meanwhile.",
    "automation_prohibited": "This portal does not allow filling tools. Apply with this kit by hand.",
    "no_field_map": "The extension has not seen this portal's form yet. It learns it the first time you start; this kit lists every answer we hold.",
}


@login_required
@require_GET
def application_kit(request: HttpRequest, application_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    application = get_object_or_404(Application, id=application_id, student=student)
    kit = build_kit(application)
    return render(
        request,
        "portals/kit.html",
        {
            "kit": kit,
            "not_fillable_text": _NOT_FILLABLE.get(kit.not_fillable_reason, ""),
            "start_url": (
                reverse("student-application-start", args=[application.id])
                if kit.not_fillable_reason in ("", "no_field_map")
                else ""
            ),
        },
    )
```

(import `from django.urls import reverse`). `no_field_map` still offers Start: the extension's first-encounter snapshot is what learns the map.

- [ ] **Step 4: The template**

`templates/portals/kit.html`:

```html
{% extends "base.html" %}
{% load dashboard %}
{% block title %}Application Kit{% endblock %}
{% block content %}
  <h1>Application Kit</h1>
  <p>Everything you need to apply{% if kit.portal_host %} on {{ kit.portal_host }}{% endif %}. You can copy each answer by hand on any device.</p>
  {% if kit.deadline %}<p>Deadline: {{ kit.deadline|date:"j M Y, H:i" }}{% if kit.deadline_timezone %} ({{ kit.deadline_timezone }}){% endif %}</p>{% endif %}
  {% if kit.apply_with_email %}<p>Register with this email address: {{ kit.apply_with_email }}</p>{% endif %}
  {% if not_fillable_text %}<p role="status">{{ not_fillable_text }}</p>{% endif %}
  {% if start_url %}
    <form method="post" action="{{ start_url }}">{% csrf_token %}<button type="submit">Start application</button></form>
  {% endif %}
  {% with url=kit.form_url|https_only %}{% if url %}<p><a href="{{ url }}">Open the portal</a></p>{% endif %}{% endwith %}

  <h2>Questions and your answers</h2>
  {% if kit.questions %}
    <dl>
      {% for question in kit.questions %}
        <dt>{{ question.label }}</dt>
        <dd>{% if question.missing %}missing — answer it in your profile or the gap interview{% else %}{{ question.answer }}{% endif %}</dd>
      {% endfor %}
    </dl>
  {% else %}
    <p>No answers yet. Finish your profile first.</p>
  {% endif %}

  <h2>What the programme requires</h2>
  {% if kit.requirements %}
    <ul>{% for requirement in kit.requirements %}<li>{{ requirement }}</li>{% endfor %}</ul>
  {% else %}
    <p>We have not read the programme's requirements yet.</p>
  {% endif %}

  {% if kit.your_actions %}
    <h2>Only you can do these</h2>
    {% if kit.letter_cycle %}<p>Read for the {{ kit.letter_cycle }} cycle.</p>{% endif %}
    <ul>
      {% for item in kit.your_actions %}
        <li>{{ item.text }}{% with url=item.source_url|https_only %}{% if url %} (<a href="{{ url }}">source</a>){% endif %}{% endwith %}</li>
      {% endfor %}
    </ul>
  {% endif %}

  <h2>Documents</h2>
  {% if kit.documents %}
    <ul>{% for document in kit.documents %}<li><a href="{{ document.download_path }}">{{ document.filename }}</a></li>{% endfor %}</ul>
  {% else %}
    <p>No approved document yet. See Documents.</p>
  {% endif %}
{% endblock %}
```

```bash
cd /home/orkhan/Desktop/student-dashboard && git rm tests/templates/portals/kit.html
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/portals && uv run ruff check . && uv run mypy apps config`
Expected: PASS (`tests/portals/test_kit_view.py` still reads `response.context["kit"]`).

- [ ] **Step 6: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add -A apps/portals/views.py templates/portals tests && git commit -m "feat(portals): the Application Kit page

Answers in the portal's order with missing ones marked, the programme's own
requirements, the steps only the applicant can take with https-only source
links, approved documents, why the extension cannot fill when it cannot, and
Start application where it can.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 20: The counsellor on a student's board

Spec §4a. An assigned counsellor (`CounselorAssignment`, active, same agency) opens `/counselor/students/<id>/` and sees the same home, board, documents and messages, with full rights: add and remove applications, record the portal and the outcome, upload documents for the student, answer missing items (the gap interview with `actor=counselor`), acknowledge items, write to the student. Each write leaves an `AuditEvent` with the counsellor as actor (the shared services in Tasks 8–9 already write them; acknowledge, message and upload write theirs here). Start application and the fill stay with the student: `routes._COUNSELOR` has no `start`, and no route here queues a device action. Staff MFA is enforced by `TenantMembershipMiddleware`; anyone but an active assignee gets a 404 (a non-counsellor's `PermissionDenied` is turned into 404 too, per the spec). **While the student has an open deletion request the board is read-only** (owner, 2026-10-04): `deletion_lock_target(student)` is not None, so every write route answers 409 with the board re-rendered read-only (the upload route answers JSON `409 deletion_requested`), and the page says "This student has asked to delete their account; changes are paused" and renders no forms (`read_only` in the context hides every form in the shared includes). The counsellor may also Accept or Ignore an offer of another programme on the student's behalf. The counsellor's entry page, the named-programme review page and MFA setup get their plain templates here, which un-`xfail`s the last seven kept tests.

**Files:**
- Create: `apps/dashboard/views.py`, `apps/dashboard/urls.py`, `templates/counselor/student_board.html`, `templates/counselor/dashboard.html`, `templates/counselor/review.html`, `templates/tenancy/mfa_setup.html`, `tests/dashboard/test_counselor_board.py`
- Modify: `config/urls.py`, `tests/concierge/test_roadmap.py`, `tests/funding/test_review_publication.py`, `tests/funding/test_student_controls.py`, `tests/tenancy/test_mfa.py` (remove `xfail` markers naming Task 20)
- Delete: `tests/templates/counselor/dashboard.html`, `tests/templates/counselor/review.html`, `tests/templates/tenancy/mfa_setup.html`

**Interfaces:**
- Produces URL names (prefix `counselor/students/<uuid:student_id>/`): `counselor-student-board` (``), `counselor-student-application-add` (`applications/add/<uuid:candidate_id>/`), `counselor-student-outcome` (`applications/<uuid:application_id>/outcome/`), `counselor-student-application-remove` (`.../remove/`), `counselor-student-application-portal` (`.../portal/`), `counselor-student-acknowledge` (`notifications/<uuid:notification_id>/acknowledge/`), `counselor-student-message` (`messages/send/`), `counselor-student-gap-interview` (`gap-interview/`), `counselor-student-upload` (`uploads/`, JSON), `counselor-student-offer-accept`, `counselor-student-offer-ignore` (`offers/<uuid:signal_id>/{accept,ignore}/`)
- Consumes: `apps.tenancy.middleware.deletion_lock_target(membership) -> str | None`, `offer_for`, `accept_offer`, `ignore_offer` (Task 9)
- Consumes: `board_for(..., counselor_view=True)`, `items_for(..., counselor_view=True)`, `page_context(..., counselor_view=True)`, `messages_context`, `render_gap_page`, the Task 9 services, `correct_outcome`

- [ ] **Step 1: Write the failing tests**

`tests/dashboard/test_counselor_board.py`:

```python
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.audit.models import DeletionRequest
from apps.concierge.models import ConversationMessage, DocumentVersion, Notification, RoadmapItem
from apps.funding.models import AuditEvent
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment
from tests.conftest import verify_mfa_session

from .conftest import add_card

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def counselor_client(client, agency_a, counselor_user, counselor_membership, membership_a):
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    return client


def _audited(agency, actor, event) -> bool:
    with tenant_scope(agency.id):
        return AuditEvent.objects.filter(actor=actor, event=event).exists()


def test_the_counselor_sees_the_students_board_without_start(
    counselor_client, agency_a, domain_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
    base = f"/counselor/students/{membership_a.id}/"
    body = counselor_client.get(base, HTTP_HOST=domain_a.host).content.decode()
    assert "M.Sc. Informatics" in body
    assert "Needs you now" in body
    assert "What each application needs" in body
    assert "/start/" not in body
    assert f'action="{base}applications/{application.id}/remove/"' in body
    assert counselor_client.get(f"{base}gap-interview/", HTTP_HOST=domain_a.host).status_code == 200


def test_counselor_writes_are_audited_with_the_counselor_as_actor(
    counselor_client, agency_a, domain_a, membership_a, counselor_membership, pack
) -> None:
    programme, award = pack
    base = f"/counselor/students/{membership_a.id}/"
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme, portal=False, state="SUBMITTED")
        item = RoadmapItem.objects.create(
            tenant=agency_a, student=membership_a, stage=RoadmapItem.Stage.MONITORING,
            owner_kind=RoadmapItem.OwnerKind.AGENT, deadline=timezone.now() + timedelta(days=3),
        )
        note = Notification.objects.create(
            tenant=agency_a, recipient=membership_a, roadmap_item=item, message="tum.de wrote."
        )
    host = {"HTTP_HOST": domain_a.host}
    counselor_client.post(f"{base}applications/{card.id}/outcome/", {"outcome": "ADMITTED"}, **host)
    counselor_client.post(
        f"{base}applications/{card.id}/portal/", {"form_url": "https://campus.tum.de/apply"}, **host
    )
    counselor_client.post(f"{base}applications/add/{award.id}/", **host)
    counselor_client.post(f"{base}notifications/{note.id}/acknowledge/", **host)
    counselor_client.post(f"{base}messages/send/", {"body": "Your transcript arrived."}, **host)
    with tenant_scope(agency_a.id):
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT", address="a@o.test"
        )
        offer = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-1",
            sender_domain="tum.de", received_at=timezone.now(), application=card,
            label="DECISION", offered_programme="M.Sc. Data Engineering",
        )
    counselor_client.post(f"{base}offers/{offer.id}/accept/", **host)

    with tenant_scope(agency_a.id):
        assert Application.objects.filter(program_id=offer.id).exists()
        card.refresh_from_db()
        note.refresh_from_db()
        assert (card.outcome, card.outcome_source) == ("ADMITTED", "PERSON")
        assert card.portal_form.portal_host == "campus.tum.de"
        assert Application.objects.filter(candidate=award).exists()
        assert note.acknowledged_at is not None
        message = ConversationMessage.objects.get(student=membership_a)
        assert message.sender_id == counselor_membership.id
    for event in (
        "application.outcome_recorded", "application.portal_recorded", "application.added",
        "notification.acknowledged", "message.sent", "application.offer_accepted",
    ):
        assert _audited(agency_a, counselor_membership, event), event


def test_the_counselor_registers_an_upload_for_the_student(
    counselor_client, agency_a, domain_a, membership_a, counselor_membership, monkeypatch
) -> None:
    import apps.dashboard.views as views

    monkeypatch.setattr(
        views, "presigned_upload", lambda document: {"url": "https://s3.test/", "fields": {}}
    )
    response = counselor_client.post(
        f"/counselor/students/{membership_a.id}/uploads/", json.dumps({"kind": "PASSPORT"}),
        content_type="application/json", HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 201
    with tenant_scope(agency_a.id):
        document = DocumentVersion.objects.get(id=response.json()["document_id"])
    assert (document.student_id, document.kind) == (membership_a.id, "PASSPORT")
    assert _audited(agency_a, counselor_membership, "document.upload_registered")


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("get", ""),
        ("get", "gap-interview/"),
        ("post", "messages/send/"),
        ("post", "uploads/"),
        ("post", f"applications/{uuid4()}/outcome/"),
        ("post", f"applications/add/{uuid4()}/"),
        ("post", f"notifications/{uuid4()}/acknowledge/"),
    ],
)
def test_an_unassigned_counselor_gets_404_everywhere(
    client, domain_a, counselor_user, counselor_membership, membership_a, method, suffix
) -> None:
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = getattr(client, method)(
        f"/counselor/students/{membership_a.id}/{suffix}", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 404


def test_a_student_cannot_open_a_counselor_board(client, domain_a, user_a, membership_a) -> None:
    client.force_login(user_a)
    response = client.get(f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_the_board_needs_staff_mfa(
    client, agency_a, domain_a, counselor_user, counselor_membership, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    response = client.get(f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host)
    assert response.status_code == 403


@pytest.fixture
def leaving(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED", reason="OTHER"
        )


def test_a_leaving_students_board_is_read_only(
    counselor_client, leaving, agency_a, domain_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme, state="SUBMITTED", outcome="ADMITTED")
    body = counselor_client.get(
        f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host
    ).content.decode()
    assert "This student has asked to delete their account; changes are paused" in body
    assert "M.Sc. Informatics" in body
    # The only form left is base.html's logout.
    assert body.count("<form") == 1


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("post", f"applications/{uuid4()}/outcome/"),
        ("post", f"applications/{uuid4()}/portal/"),
        ("post", f"applications/{uuid4()}/remove/"),
        ("post", f"applications/add/{uuid4()}/"),
        ("post", f"notifications/{uuid4()}/acknowledge/"),
        ("post", "messages/send/"),
        ("post", "uploads/"),
        ("post", "gap-interview/"),
        ("get", "gap-interview/"),
        ("post", f"offers/{uuid4()}/accept/"),
        ("post", f"offers/{uuid4()}/ignore/"),
    ],
)
def test_every_write_is_refused_while_the_student_is_leaving(
    counselor_client, leaving, agency_a, domain_a, membership_a, counselor_membership,
    method, suffix,
) -> None:
    response = getattr(counselor_client, method)(
        f"/counselor/students/{membership_a.id}/{suffix}", {"body": "hello"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 409
    with tenant_scope(agency_a.id):
        assert not AuditEvent.objects.filter(actor=counselor_membership).exists()
        assert not ConversationMessage.objects.filter(student=membership_a).exists()
```

Delete every `xfail` marker naming Task 20.

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/dashboard/test_counselor_board.py tests/concierge/test_roadmap.py tests/funding tests/tenancy/test_mfa.py`
Expected: FAIL — 404 on `/counselor/students/...` (no route) where 200 is expected; the counsellor stubs render nothing.

- [ ] **Step 3: The views**

`apps/dashboard/views.py`:

```python
"""The counsellor on one student's board (dashboard spec §4a).

Full rights, each write audited with the counsellor as actor. Starting an
application and the fill stay with the student -- their own browser, their own
extension -- so nothing here queues a device action. Staff MFA runs in
TenantMembershipMiddleware before any of this. Anyone but an active assignee of
this student in this agency gets a 404.
"""

from __future__ import annotations

import json
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.concierge.documents import presigned_upload, register
from apps.concierge.models import UPLOAD_KINDS, Notification
from apps.concierge.services import acknowledge_notification, send_message
from apps.concierge.views import messages_context
from apps.documents.gap_intake import submit_answers
from apps.documents.gaps import UnanswerableQuestion
from apps.documents.views import page_context, render_gap_page
from apps.funding.models import AuditEvent, PackCandidate, RecommendationCandidate
from apps.funding.services import current_pack
from apps.portals.applications import (
    REFUSALS,
    ApplicationRefused,
    accept_offer,
    add_application,
    ignore_offer,
    offer_for,
    record_portal,
    remove_application,
)
from apps.portals.models import Application
from apps.portals.outcome import correct_outcome
from apps.ratelimit import rate_limited
from apps.tenancy.middleware import deletion_lock_target
from apps.tenancy.models import CounselorAssignment, Membership
from apps.tenancy.services import current_membership

from .board import board_for
from .needs import items_for

_MESSAGE_LIMIT = 20
_MESSAGE_WINDOW_SECONDS = 60
_MESSAGE_MAX_LENGTH = 4000
_UPLOAD_LIMIT = 10
_UPLOAD_WINDOW_SECONDS = 3600


def _assigned(request: HttpRequest, student_id: UUID) -> tuple[Membership, Membership]:
    try:
        counselor = current_membership(request, Membership.Role.COUNSELOR)
    except PermissionDenied:
        raise Http404 from None
    assignment = get_object_or_404(
        CounselorAssignment.objects.select_related("student__user"),
        counselor=counselor,
        student_id=student_id,
        active=True,
    )
    return counselor, assignment.student


def _application(student: Membership, application_id: UUID) -> Application:
    return get_object_or_404(
        Application.objects.select_related("portal_form", "candidate"),
        id=application_id,
        student=student,
    )


def _back(student: Membership) -> HttpResponse:
    return redirect("counselor-student-board", student_id=student.id)


def _paused(student: Membership) -> bool:
    """The student asked to delete their account: the board is read-only until
    they restore it or are erased (owner, 2026-10-04)."""
    return deletion_lock_target(student) is not None


def _for_write(
    request: HttpRequest, student_id: UUID
) -> tuple[Membership, Membership, HttpResponse | None]:
    """_assigned, plus the pause: while the student is leaving, every write is
    refused 409 and the board comes back read-only. Checked before any object
    lookup, so a refused write learns nothing about the id it named."""
    counselor, student = _assigned(request, student_id)
    refusal = _board_page(request, student, status=409) if _paused(student) else None
    return counselor, student, refusal


def _board_page(
    request: HttpRequest,
    student: Membership,
    *,
    status: int = 200,
    error: str | None = None,
    form_values: dict[str, str] | None = None,
) -> HttpResponse:
    board = board_for(student, counselor_view=True)
    pack = current_pack(student)
    applied = set(
        Application.objects.filter(student=student, candidate__isnull=False).values_list(
            "candidate_id", flat=True
        )
    )
    addable = (
        [
            member.candidate
            for member in PackCandidate.objects.filter(pack_version=pack)
            .select_related("candidate")
            .order_by("candidate__program_name")
            if member.candidate_id not in applied
            and member.candidate.state == RecommendationCandidate.State.VISIBLE
            and (member.candidate.funding_card or {}).get("route") != "AUTOMATIC_ON_ADMISSION"
        ]
        if pack is not None
        else []
    )
    context: dict[str, object] = {
        **page_context(student, counselor_view=True),
        **messages_context(student),
        "student": student,
        "board": board,
        "needs": items_for(student, board=board, counselor_view=True),
        "outcome_choices": Application.Outcome.choices,
        "addable": addable,
        "error": error,
        "error_form": "message" if error else None,
        "form_values": form_values or {},
        "read_only": _paused(student),
    }
    return render(request, "counselor/student_board.html", context, status=status)


@login_required
def student_board(request: HttpRequest, student_id: UUID) -> HttpResponse:
    _counselor, student = _assigned(request, student_id)
    return _board_page(request, student)


@login_required
@require_POST
def add(request: HttpRequest, student_id: UUID, candidate_id: UUID) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    try:
        add_application(student=student, candidate_id=candidate_id, actor=counselor)
    except ApplicationRefused as refused:
        if refused.reason == "not_found":
            raise Http404 from refused
        messages.error(request, REFUSALS[refused.reason])
    return _back(student)


@login_required
@require_POST
def record_outcome(request: HttpRequest, student_id: UUID, application_id: UUID) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    try:
        correct_outcome(
            _application(student, application_id), request.POST.get("outcome", ""), actor=counselor
        )
    except ValueError:
        messages.error(request, "Choose an outcome from the list.")
    return _back(student)


@login_required
@require_POST
def remove(request: HttpRequest, student_id: UUID, application_id: UUID) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    remove_application(_application(student, application_id), actor=counselor)
    return _back(student)


@login_required
@require_POST
def portal(request: HttpRequest, student_id: UUID, application_id: UUID) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    try:
        record_portal(
            _application(student, application_id), request.POST.get("form_url", ""),
            actor=counselor,
        )
    except ApplicationRefused as refused:
        messages.error(request, REFUSALS[refused.reason])
    return _back(student)


@login_required
@require_POST
def acknowledge(request: HttpRequest, student_id: UUID, notification_id: UUID) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    note = get_object_or_404(Notification, id=notification_id, recipient=student)
    acknowledge_notification(note)
    AuditEvent.objects.create(actor=counselor, event="notification.acknowledged", object_id=note.id)
    return _back(student)


@login_required
@require_POST
def message(request: HttpRequest, student_id: UUID) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    body = request.POST.get("body", "").strip()
    refusal = None
    status = 400
    if rate_limited(
        "counselor-message", counselor.id, limit=_MESSAGE_LIMIT,
        window_seconds=_MESSAGE_WINDOW_SECONDS,
    ):
        refusal, status = "Too many messages. Try again shortly.", 429
    elif not body:
        refusal = "A message is required."
    elif len(body) > _MESSAGE_MAX_LENGTH:
        refusal = f"Messages must be {_MESSAGE_MAX_LENGTH} characters or fewer."
    if refusal is not None:
        return _board_page(request, student, status=status, error=refusal, form_values={"body": body})
    sent = send_message(student=student, counselor=counselor, sender=counselor, body=body)
    AuditEvent.objects.create(actor=counselor, event="message.sent", object_id=sent.id)
    return _back(student)


@login_required
def gap_interview(request: HttpRequest, student_id: UUID) -> HttpResponse:
    """The student's open questions, answered by the counsellor (spec §4a).
    gap_intake.submit_answers records the counsellor as the actor. Paused, like
    every write, while the student is leaving -- the page is a form."""
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    if request.method == "POST":
        try:
            submit_answers(request.POST, student=student, actor=counselor)
        except UnanswerableQuestion:
            return render_gap_page(
                request, student,
                error="The answers were not saved -- the questions below are current. Answer them again.",
            )
        return redirect("counselor-student-gap-interview", student_id=student.id)
    return render_gap_page(request, student)


@require_POST
def upload(request: HttpRequest, student_id: UUID) -> HttpResponse:
    """A presigned upload for the student's own document row, registered by the
    counsellor. JSON, like the student's door it mirrors (documents/api.py)."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "authentication_required"}, status=401)
    counselor, student = _assigned(request, student_id)
    if _paused(student):
        return JsonResponse({"error": "deletion_requested"}, status=409)
    if rate_limited(
        "counselor-upload", counselor.id, limit=_UPLOAD_LIMIT, window_seconds=_UPLOAD_WINDOW_SECONDS
    ):
        return JsonResponse({"error": "rate_limited"}, status=429)
    try:
        kind = json.loads(request.body or b"{}").get("kind", "")
    except (ValueError, AttributeError):
        return JsonResponse({"error": "invalid_json"}, status=400)
    if kind not in {value for value, _label in UPLOAD_KINDS}:
        return JsonResponse({"error": "invalid_kind"}, status=400)
    document = register(student.tenant_id, student.id, kind=kind)
    AuditEvent.objects.create(
        actor=counselor, event="document.upload_registered", object_id=document.id
    )
    presigned = presigned_upload(document)
    return JsonResponse(
        {"document_id": str(document.id), "url": presigned["url"], "fields": presigned["fields"]},
        status=201,
    )


@login_required
@require_POST
def offer_accept(request: HttpRequest, student_id: UUID, signal_id: UUID) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    signal = offer_for(student, signal_id)
    if signal is None:
        raise Http404
    accept_offer(signal, actor=counselor)
    return _back(student)


@login_required
@require_POST
def offer_ignore(request: HttpRequest, student_id: UUID, signal_id: UUID) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    signal = offer_for(student, signal_id)
    if signal is None:
        raise Http404
    ignore_offer(signal, actor=counselor)
    return _back(student)
```

`apps/dashboard/urls.py`:

```python
from django.urls import path

from . import views

_BASE = "counselor/students/<uuid:student_id>/"

urlpatterns = [
    path(_BASE, views.student_board, name="counselor-student-board"),
    path(
        _BASE + "applications/add/<uuid:candidate_id>/",
        views.add,
        name="counselor-student-application-add",
    ),
    path(
        _BASE + "applications/<uuid:application_id>/outcome/",
        views.record_outcome,
        name="counselor-student-outcome",
    ),
    path(
        _BASE + "applications/<uuid:application_id>/remove/",
        views.remove,
        name="counselor-student-application-remove",
    ),
    path(
        _BASE + "applications/<uuid:application_id>/portal/",
        views.portal,
        name="counselor-student-application-portal",
    ),
    path(
        _BASE + "notifications/<uuid:notification_id>/acknowledge/",
        views.acknowledge,
        name="counselor-student-acknowledge",
    ),
    path(_BASE + "messages/send/", views.message, name="counselor-student-message"),
    path(_BASE + "gap-interview/", views.gap_interview, name="counselor-student-gap-interview"),
    path(_BASE + "uploads/", views.upload, name="counselor-student-upload"),
    path(
        _BASE + "offers/<uuid:signal_id>/accept/",
        views.offer_accept,
        name="counselor-student-offer-accept",
    ),
    path(
        _BASE + "offers/<uuid:signal_id>/ignore/",
        views.offer_ignore,
        name="counselor-student-offer-ignore",
    ),
]
```

`config/urls.py`: add `path("", include("apps.dashboard.urls")),` after the `apps.concierge.urls` line.

- [ ] **Step 4: The templates**

`templates/counselor/student_board.html`:

```html
{% extends "base.html" %}
{% load static %}
{% block title %}{{ student.user.get_username }}{% endblock %}
{% block content %}
  <h1>{{ student.user.get_username }}</h1>
  {% if read_only %}
    <p role="status">This student has asked to delete their account; changes are paused.</p>
  {% else %}
    <p>You are working on this student's board. Every change you make is recorded with your name. Starting an application stays with the student.</p>
  {% endif %}
  {% include "student/_needs.html" %}
  {% include "student/_board.html" %}
  {% if not read_only %}
  <section aria-labelledby="add-heading">
    <h2 id="add-heading">Add an application</h2>
    {% for candidate in addable %}
      <form method="post" action="{% url 'counselor-student-application-add' student.id candidate.id %}">
        {% csrf_token %}
        <p>{{ candidate.program_name }}</p>
        <button type="submit">Add to applications</button>
      </form>
    {% empty %}
      <p>Every programme in the pack is already an application.</p>
    {% endfor %}
  </section>
  {% endif %}
  {% include "student/_documents.html" %}
  {% if not read_only %}<p><a href="{% url 'counselor-student-gap-interview' student.id %}">Answer missing items for this student</a></p>{% endif %}
  {% include "student/_messages.html" %}
  {% if not read_only %}
  <section aria-labelledby="write-heading">
    <h2 id="write-heading">Write to the student</h2>
    <form method="post" action="{% url 'counselor-student-message' student.id %}">
      {% csrf_token %}
      {% if error and error_form == "message" %}<p role="alert">{{ error }}</p>{% endif %}
      <p>
        <label for="message-body">Message</label><br>
        <textarea id="message-body" name="body" rows="4" maxlength="4000">{{ form_values.body }}</textarea>
      </p>
      <button type="submit">Send</button>
    </form>
  </section>
  {% endif %}
  <script src="{% static 'dashboard/documents.js' %}" defer></script>
{% endblock %}
```

`templates/counselor/dashboard.html` (context from `concierge.views._counselor_dashboard_page`: `assignments`, `items`, `error`, `error_form`):

```html
{% extends "base.html" %}
{% block title %}Your students{% endblock %}
{% block content %}
  <h1>Your students</h1>
  {% if error and not error_form %}<p role="alert">{{ error }}</p>{% endif %}
  <ul>
    {% for assignment in assignments %}
      <li><a href="{% url 'counselor-student-board' assignment.student_id %}">{{ assignment.student.user.get_username }}</a></li>
    {% empty %}
      <li>No students assigned.</li>
    {% endfor %}
  </ul>
  <h2>Tasks</h2>
  <ul>
    {% for item in items %}
      <li>
        {{ item.get_stage_display }} for {{ item.student.user.get_username }} — {{ item.get_state_display }}, due {{ item.deadline|date:"j M Y" }}
        {% if error and error_form == item.id|stringformat:"s" %}<p role="alert">{{ error }}</p>{% endif %}
        {% if item.owner_id == request.membership.id and item.state != "DONE" %}
          <form method="post" action="{% url 'concierge-mark-roadmap-item-done' item.id %}">
            {% csrf_token %}
            <label for="done-{{ item.id }}">What you did</label>
            <input type="text" id="done-{{ item.id }}" name="description">
            <button type="submit">Mark done</button>
          </form>
        {% endif %}
      </li>
    {% empty %}
      <li>No tasks.</li>
    {% endfor %}
  </ul>
{% endblock %}
```

`templates/counselor/review.html` (context from `funding.views._review_page`: `pack`, `pool`, `checking`, `named`, `error`, `error_form`, `error_field`, `form_values`; the resolve form sits on the candidates still being checked, which is what `resolve_named_program_view` resolves):

```html
{% extends "base.html" %}
{% block title %}Recommendations{% endblock %}
{% block content %}
  <h1>Recommendations, version {{ pack.version }}</h1>
  <h2>In the pack</h2>
  <ul>
    {% for member in pool %}<li>{{ member.candidate.program_name }} — {{ member.candidate.evidence.claim }}</li>{% empty %}<li>Empty.</li>{% endfor %}
  </ul>
  <h2>Being checked</h2>
  {% for candidate in checking %}
    <section>
      <h3>{{ candidate.program_name }}</h3>
      <form method="post" action="{% url 'counselor-resolve-named-program' pack.run_id candidate.id %}">
        {% csrf_token %}
        {% if error and error_form == candidate.id|stringformat:"s" %}<p role="alert">{{ error }}</p>{% endif %}
        <p>
          <label for="eligible-{{ candidate.id }}">Eligible?</label>
          <select id="eligible-{{ candidate.id }}" name="eligible"><option value="true">Yes</option><option value="false">No</option></select>
        </p>
        <p>
          <label for="reason-{{ candidate.id }}">Why</label>
          <input type="text" id="reason-{{ candidate.id }}" name="reason" value="{% if error_form == candidate.id|stringformat:'s' %}{{ form_values.reason }}{% endif %}">
        </p>
        <p>
          <label for="source-{{ candidate.id }}">Official source (https)</label>
          <input type="url" id="source-{{ candidate.id }}" name="source_url" value="{% if error_form == candidate.id|stringformat:'s' %}{{ form_values.source_url }}{% endif %}">
        </p>
        <button type="submit">Record</button>
      </form>
    </section>
  {% empty %}
    <p>Nothing is being checked.</p>
  {% endfor %}
  <h2>Programmes the student named</h2>
  <ul>
    {% for candidate, note in named %}<li>{{ candidate.program_name }} — {{ note }}</li>{% empty %}<li>None.</li>{% endfor %}
  </ul>
{% endblock %}
```

`templates/tenancy/mfa_setup.html` (context from `tenancy.views.mfa_setup`: `confirmed`, `error`, and while unconfirmed `qr_data_uri`, `secret`):

```html
{% extends "base.html" %}
{% block title %}Two-step verification{% endblock %}
{% block content %}
  <h1>Two-step verification</h1>
  {% if not confirmed %}
    <p>Scan this code with an authenticator app, or type the key into it.</p>
    <p><img src="{{ qr_data_uri }}" alt="QR code for your authenticator app"></p>
    <p>Key: <code>{{ secret }}</code></p>
  {% endif %}
  {% if error %}<p role="alert">{{ error }}</p>{% endif %}
  <form method="post" action="{% url 'tenancy-mfa-setup' %}">
    {% csrf_token %}
    <p>
      <label for="token">Six-digit code</label>
      <input type="text" id="token" name="token" inputmode="numeric" autocomplete="one-time-code" required>
    </p>
    <button type="submit">Verify</button>
  </form>
{% endblock %}
```

```bash
cd /home/orkhan/Desktop/student-dashboard && git rm tests/templates/counselor/dashboard.html tests/templates/counselor/review.html tests/templates/tenancy/mfa_setup.html
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q tests/dashboard tests/concierge tests/funding tests/tenancy tests/acceptance`
Expected: PASS, with no `xfail` left anywhere: `grep -rn "xfail(strict=True, reason=" tests` prints nothing.

- [ ] **Step 6: The whole gate**

Run: `POSTGRES_DB=tehsil_student_dashboard uv run pytest -q && uv run ruff check . && uv run mypy apps config && uv run python manage.py check && uv run python manage.py makemigrations --check --dry-run && uv run bandit -c pyproject.toml -r apps config`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add -A apps/dashboard config/urls.py templates tests && git commit -m "feat(dashboard): the counsellor on a student's board

An assigned counsellor sees the student's home, board, documents and messages
and may add and remove applications, record portals and outcomes, upload,
answer missing items, acknowledge, write and accept or ignore an offer of
another programme -- each write audited with the counsellor as actor; Start
application stays with the student. A student who asked to be deleted shows a
read-only board and every write answers 409. Everyone else gets a 404. Plain counsellor entry, review and MFA pages un-xfail the last
seven kept frontend tests.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 21: The live check runbook

Spec §11: "a test student, a real Outlook inbox, a document request mail, the card updating." No code. It also carries the first-deploy check of the upload path (spec §6, "Upload safety"): the GuardDuty Malware Protection plan has never run on real AWS, so nothing yet shows that a real infected upload is blocked rather than promoted.

**Files:**
- Create: `docs/runbooks/student-dashboard-live-check.md`

- [ ] **Step 1: Write the runbook**

`docs/runbooks/student-dashboard-live-check.md`:

```markdown
# Student dashboard: the live check

A manual end-to-end check that real mail reaches a student's board. Run it on a
local stack or a staging environment, never against a real student. About 30
minutes; it spends a handful of model calls.

## You need

- The app running with `MAILBOX_PROVIDERS=MICROSOFT`, the Microsoft OAuth client
  configured (`docs/runbooks/deploy.md`), `OPENAI_API_KEY` set
  (`source ~/.config/tehsil_agent/openai.env`), and an agency with a verified
  `TenantDomain` you can reach in a browser.
- A personal Outlook.com inbox created for this check.
- A second mailbox on a domain whose DMARC passes at Outlook (your own domain),
  to send from.

## Steps

1. Create the student:
   `uv run python manage.py create_student --agency <agency-uuid> --host <host> --username live-check`
   (type the password twice when asked).
2. Log in at `https://<host>/accounts/login/`; `/` lands on the board.
3. Complete the profile (Settings, Profile) and wait for Programmes & funding to
   stop reloading itself.
4. Press **Add to my applications** on one programme. The card appears in **To start**
   with **Open programme page** (no portal known yet).
5. As the counsellor (or with `record_portal` in a shell), record the card's portal as
   `https://<your-sending-domain>/apply`, so mail from that domain is vouched for
   this application.
6. Settings, Mailbox: connect the Outlook inbox, tier **Headers and body**, kind
   **Application inbox**. You land back on the mailbox page with "… is connected."
7. From your own domain, mail the Outlook address:
   subject "Missing document", body "Please upload a certified copy of your
   Bachelor's degree certificate by 15 June 2027."
8. Run `uv run python manage.py sync_mailboxes` (or wait for push, if enabled).
9. Check:
   - Messages lists the mail under the programme with "asks for: … degree certificate by 15 Jun 2027";
   - Documents shows **certified copy needed** in the Diploma row for that application;
   - Home: **Needs you now** has "Diploma — needed for …" with **Submit document**, and
     the card lists it under Missing.
10. Mail "We are pleased to inform you that you have been admitted to …" and sync
    again: the card moves to **Decision** and reads "Admitted — from <domain>'s email".
    Press **Not right?**, choose "No decision yet": the card leaves Decision and an
    `application.outcome_recorded` audit event names the student.
11. Clean up: Settings, Mailbox, **Disconnect**; Settings, Account, delete the account.

## First deploy: the upload checks

Run once on the first real AWS deployment, **before the first real student uploads
anything**, and again whenever `EvidenceBucket`, the GuardDuty plan, `OcrFunction` or the
scan-result queue changes. The GuardDuty Malware Protection plan has never run on real AWS:
until this passes, "GuardDuty blocks malware" is a design statement, not a measured one.
About 20 minutes.

You need the test student from step 1 above, logged in, and a device token for them:
in `uv run python manage.py shell`, inside `tenant_scope(<agency-uuid>)`,
`token = redeem_pairing_code(issue_pairing_code(membership), "live-check")[1]`
(`apps.portals.pairing`). Never keep the token past this check.

1. Download the standard EICAR anti-malware test file (`eicar.com.txt`, from
   https://www.eicar.org). It is harmless by design; every scanner reports it as malware.
   Never commit it, and never paste its text into a file in this repository.
2. Documents, **Upload**, kind **Passport**, choose `eicar.com.txt`. This goes through the
   real presigned form (`/api/documents/uploads`), straight to `quarantine/`.
3. Within a few minutes, check every one of these:
   - `aws s3api get-object-tagging --bucket <EvidenceBucketName> --key quarantine/<agency-uuid>/<document-uuid>`
     shows `GuardDutyMalwareScanStatus` = `THREATS_FOUND`;
   - `GET /api/documents/uploads/<document-uuid>` answers `"state": "BLOCKED"`,
     `"scan_result": "THREATS_FOUND"`, and the Documents page lists the upload as blocked;
   - nothing was promoted: `DocumentVersion.promoted_key` is empty and
     `aws s3 ls s3://<EvidenceBucketName>/tenants/<agency-uuid>/students/<student-uuid>/uploads/`
     lists nothing for that document;
   - `curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer <token>" https://<host>/ext/documents/<document-uuid>`
     prints `404`.
4. Controls for the upload check (the isolated function's `inspect`, also never run on
   real AWS). Write two files from a checkout:
   `uv run --project ocr python -c "import sys; sys.path.insert(0, 'ocr'); import pdf_fixtures as f; open('/tmp/plain.pdf','wb').write(f.written()); open('/tmp/launch.pdf','wb').write(f.written(f.launch))"`.
   Upload `/tmp/plain.pdf` as a Passport: it reads "checking…" briefly, then ends `AVAILABLE`
   with a `promoted_key`.
   Upload `/tmp/launch.pdf`: it ends `REJECTED_ACTIVE_CONTENT` and the Documents page shows
   "This PDF contains active content; save it again as a plain PDF (Print → Save as PDF) and
   upload that". Upload any `.txt` file renamed `passport.pdf`: `REJECTED_TYPE`, "Upload a
   PDF, JPEG or PNG".
5. Clean up: Settings, Account, delete the test account; revoke the pairing if it is not
   already revoked.

If the EICAR upload is promoted, reaches `AVAILABLE`, or `/ext/documents/<id>` returns
anything but 404: **stop — no student uploads until it is fixed.** Check, in order, that the
GuardDuty plan is enabled on `EvidenceBucket` with the `quarantine/` prefix, that the
scan-result EventBridge rule reaches the queue, and that the document worker is draining it.
If the upload stays `QUARANTINED`, the verdict never arrived (the same checks); if a control
in step 4 stays `CHECKING` and later becomes `REVIEW_REQUIRED`, the document worker could not
invoke `OcrFunction`.

## If a step fails

- No signal at step 8: the sender's domain is not vouched (step 5) or the sync
  refused the grant (`MailboxConnection.status`).
- A signal without a label: the connection is on the headers-only tier, or
  classification failed (`MailSignal.classify_attempts`).
- A label but no card change: the message was not trusted (`MailSignal.trusted`
  false: DMARC did not pass), which is the designed behaviour for an unverified sender.
```

- [ ] **Step 2: Commit**

```bash
cd /home/orkhan/Desktop/student-dashboard && git add docs/runbooks/student-dashboard-live-check.md && git commit -m "docs(runbooks): the student dashboard live check

A test student, a real Outlook inbox, a document request and a decision mail,
and what the board, documents and messages pages must show for each. Plus
the first-deploy check of the upload path: an EICAR upload through the real
presigned form must come back THREATS_FOUND, blocked, unpromoted and 404 at
/ext/documents/<id>, because the GuardDuty plan has never run on real AWS.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Controller amendment (2026-10-04)

T8's `_interview_time` was changed by the controller after drafting: an offset-less time is read
in `Application.deadline_timezone`, never UTC; with no offset and no zone it returns None and the
item says "see the email for the time". The T8 implementer adds these tests to
`tests/mailbox/test_decision_mail.py` (or the T8 test module the plan names):

```python
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apps.mailbox.actions import _interview_time


def test_an_interview_time_with_an_offset_is_kept_as_stated() -> None:
    assert _interview_time("2026-11-12T14:00:00+01:00", "") == datetime(
        2026, 11, 12, 13, 0, tzinfo=UTC
    )


def test_an_offset_less_time_is_read_in_the_portal_s_zone() -> None:
    assert _interview_time("2026-11-12T14:00:00", "Europe/Berlin") == datetime(
        2026, 11, 12, 14, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )


def test_an_offset_less_time_with_no_zone_is_not_guessed() -> None:
    assert _interview_time("2026-11-12T14:00:00", "") is None
    assert _interview_time("2026-11-12T14:00:00", "Not/AZone") is None
```

## Open points for the controller

1. **The frontend count is 40, not 42.** `grep -rc "^@pytest.mark.frontend" tests` and `tests/templates/README.md` both say 40; Task 1's table covers all 40 (12 retired, 28 kept).
2. **The consultation report vs. the kept test.** `phased requirements.md` P1-7.1 (2026-08-28) keeps official source URLs out of the student-facing report; the kept test asserted the opposite. Task 13 inverts that one assertion and the 2026-10-04 amendment it writes into P1-7 lifts the rule for the pages only. If the owner meant the report too, revert that edit and show the URL.
3. **Decided (owner, 2026-10-04): Accept on an offer creates a new card.** The Needs item reads "<University> offers you a place in <programme>" with Accept / Ignore; Accept makes the card through the add-to-applications path (the original portal when the same institution offers it, else portal-less with the counsellor task) and records the original card's REJECTED only if the letter said so; Ignore dismisses it (Tasks 8–12, 20).
4. **Decided (owner, 2026-10-04): logout keeps the extension paired.** Disconnect lives in Settings; erasure revokes (`request_deletion` already revokes every pairing) (Tasks 1, 17).
5. **A counsellor reaching `/`** is sent to `/counselor/` rather than the login page the spec names for "anyone else" — otherwise `LOGIN_REDIRECT_URL = "/"` would show a logged-in counsellor the login form again.
6. **`_DELETION_EXEMPT_PREFIXES` gains `/accounts/logout/`** (Task 1) so a deletion-locked student can log out. f7 edits the neighbouring lines of `apps/tenancy/middleware.py`; expect a merge conflict there.
7. **Decided (owner, 2026-10-04): a counsellor sees a read-only board while the student's deletion request is open**; every counsellor write answers 409 and the page renders no forms (Task 20).
8. **Decided (owner, 2026-10-04): uploads reach the extension** (Task 14). One correction to the brief: `DocumentScanRole` is GuardDuty's service role and runs none of our code, so it gets no `PutObject`; the document worker, which handles the scan result, already holds read on `quarantine/*` and write on `tenants/*`, so promotion needs no new grant (pinned by an infra test). **Security additions (owner, 2026-10-04):** a type allowlist by magic bytes (PDF, JPEG, PNG → else `REJECTED_TYPE`), active-content PDFs rejected and never rewritten (`REJECTED_ACTIVE_CONTENT`), both checked inside the isolated OCR function as a second operation (`inspect`); a clean verdict commits `CHECKING` and only the check moves it to `AVAILABLE` (promoted), a rejection, or `REVIEW_REQUIRED`, so `AVAILABLE` always means checked and promoted for every reader (coordinator, 2026-10-04); the served copy carries `attachment`, `nosniff` and `sandbox; default-src 'none'`; and the EICAR first-deploy check in the live-check runbook (Task 21). `docs/runbooks/deploy.md` is not edited: the plan does not otherwise touch it.
9. **Programme → portal at scale** (spec §9 dependency): the plan reuses a portal someone in the same agency recorded for the programme; a shared programme-to-portal table is not built.
10. **Structured eligibility fields** (P1-9 amendment) render from the evidence claim marked *unstructured*, the fallback that amendment allows; the catalogue has no such columns yet.
11. **Decided (owner, 2026-10-04): open awards list every eligible programme.** A HOLDER or COUNTRY award heads every pack and pool programme in its `country_code` (and degree level where both sides carry one; no award-side level exists in the catalogue yet), labelled "Eligible programmes in <country>"; a GLOBAL award heads every programme (Tasks 4–6, 13).
12. **Decided (owner, 2026-10-04): interview dates are extracted** into `MailVerdict.interview_at` / `MailSignal.interview_at` (REDACT); the interview item shows the date and sorts by it (Tasks 4, 8, 11).
13. **`outcome_source = PORTAL` has no writer yet.** Reading the portal's status page (`READ_PORTAL_STATUS`) and classifying it is spec B; this plan adds the value, shows it on the card ("from your portal"), and never writes it.
14. **Decided (owner, 2026-10-04): one Jev reading decides a mail and abstains** (Task 8); the two-readings fallback is gone. Two follow-ups this plan does not build: the **mailbox worker's task definition must carry `OPENROUTER_API_KEY`** (until it does, every reading is `not_configured` and abstains, so cards ask a person), and the TypeSafe DPA countersignature and sub-processor read stay open as follow-ups (`docs/legal/2026-09-provider-terms.md`).
15. **This branch must take `origin/master` before Task 8** (`engine_eval`, `GoldItem` from PR #171; f7 from PR #172). Task 8 Step 0 does it; after it, Task 12's acceptance-lock test runs instead of skipping.
16. **The bars start unlearned.** Until the owner labels the `decision_mail` gold rows and a `decision_eval score` run (without `--trust-corpus`) is written into `decision_bars.py`, no outcome is recorded automatically: the card shows the reading and asks. The shipped corpus is synthetic; published university templates are added through `decision_eval seed --extra`, and reaching the 1/500 target needs 1,497 clean rows per strict question.
17. **The upload check adds pypdf to the OCR image** (Task 14). pypdfium2 is already there, but pdfium's public API has no getter for a document's `/OpenAction` — only `FORM_DoDocumentOpenAction`, which runs it — and no general object walk for `/Launch` in an annotation's `/AA` or a `/RichMedia` annotation (checked against `pypdfium2_raw/bindings.py`). pypdf is pure Python, already the app's dependency on the same version line, added with `uv add --project ocr` (never a hand edit of `ocr/uv.lock`), and audited by CI's OCR `pip-audit` step. Its `inspect` and the fixtures were run on pypdf 6.19.0 before this plan was written; every expected name list in Task 14 is that run's output.
18. **No real TMİS e-diploma has been through the check.** The rule passes a `/Sig` field and a page-only `/OpenAction` (tested), but if a real e-diploma carries an embedded file (some signature schemes attach their XML) or a script, it is rejected — and the remedy the message gives (Print → Save as PDF) strips the signature. Run one real e-diploma through `ocr/read_pages.py --inspect` before launch; if it names anything, the owner decides between an exception for that signature profile and asking the student for the verification code instead.
19. **The GuardDuty Malware Protection plan and the OCR function have never run on real AWS.** The EICAR and control uploads in the live-check runbook (Task 21, "First deploy: the upload checks") are the first evidence either works; until they pass, no real student uploads.

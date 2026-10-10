# Phase 3 Portal Execution Implementation Plan (2a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a learned form fill end to end from a queue — recovering from selector drift, expired sessions and CAPTCHA on its own, escalating only the six cases a human must answer — and stop at `READY_TO_SUBMIT`.

**Architecture:** A portal SQS worker consumes one application at a time, opens a per-application Chrome profile, fills from the stored `FieldMap` (plan 1), reads the rendered page back, and stops. Everything added here is a recovery or escalation path around that spine: a scoped re-learn when a selector misses, a reauthentication when the session expires, a resolution service then a consultant when a challenge appears, and a `Notification` when the agent lacks a fact or an authority no software has. Recovery is recorded, never blocking; escalation blocks, and only for the six rows of §5.4's table.

**Tech Stack:** Django 5.2, Postgres with row-level security, Pydantic 2, `stagehand` 4.x (MIT), Chrome for Testing under Xvfb, boto3/SQS, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-phase3-portal-execution-design.md`

**Predecessor:** `docs/superpowers/plans/2026-08-27-phase3-portal-fill-core.md` (plan 1, merged: `apps/portals/{models,session,learn,fill,engine}.py`).

**Scope:** This is plan 2a of the two-part plan 2. It delivers the worker, autonomous recovery, challenge resolution, escalation, the browser profile lifecycle, and the CI and production wiring for a headful browser. **It cannot submit an application.** Submission, the two authority modes, the read-back submission gate and the 48-hour rule are plan 2b, gated on the portal-terms blocker in §10 of `phased requirements.md`.

## Global Constraints

- **Nothing in this plan may submit.** The terminal success state is `Application.State.READY_TO_SUBMIT`. No click, submit, or form-activation primitive is added to `PortalSession` except `press_enter()`, which exists solely for the login form and is unreachable from a stored `FieldMap` (asserted in Task 7).
- Chrome is pinned to the Playwright-installed Chrome for Testing. System Chrome fails with `Extensions.loadUnpacked: Method not available` and has no working configuration.
- Chrome runs headful. Extensions do not load in `headless_shell`; CI and production need Xvfb.
- Chrome runs with the renderer sandbox on. `apps/portals/engine.py` refuses to open a session when `CI` is set, because stagehand appends `--no-sandbox` whenever it sees that variable. Do not remove that guard, do not set `chromium_sandbox=False`, and do not "fix" a sandbox failure by disabling it.
- Stagehand's `self_heal` is always `False`. Silent re-inference leaves no artifact; our re-learn writes a `RecoveryEvent`.
- A `FieldMap` must never contain a student profile value. Student data reaches the browser only through `Variables` at `act()` time.
- Page content passed to an LLM is labelled as data, never instructions; output is schema-constrained; `max_output_tokens` is capped. Follow `apps/research/extraction.py`.
- Every LLM-calling path is wrapped in `apps.ratelimit.rate_limited`.
- No fingerprint evasion, stealth, spoofed navigator properties, or rotating/residential proxies. Enforced by `tests/portals/test_boundary.py`.
- Cost model assumes **no prompt caching** — settled by measurement, see the spec's Cost section. The learn pass is `N x observe`: ~141,800 prompt tokens and $0.76 per 36-field form version, $0.00 per replay.
- `line-length = 100`, `target-version = "py312"`. Run `uv run ruff check`, never `ruff format` — it churns 26 unrelated files.
- Tests run under `DJANGO_SETTINGS_MODULE=config.settings.test`.
- **Isolate the test database.** Nine worktrees share one `test_tehsil` and `config/settings/database.py` reads `POSTGRES_DB` with no per-worktree suffix, which has produced 292- and 108-error cascades. Run every suite as `POSTGRES_DB=tehsil_plan2a uv run pytest ...`. Before diagnosing any suite failure, check for a parallel run with `ps -eo args --no-headers | grep '/pytest ' | grep -v 'bash -c'` — do **not** use `pgrep -f '...pytest'`, it matches its own command line and hangs.
- Work happens in the worktree. Every git command uses `git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2` on branch `claude/phase3-plan2` — a bare `git commit` lands on the wrong branch.

## File structure

| File | Responsibility |
| --- | --- |
| `apps/queue.py` | **new.** The one SQS transport, generic over the message model. Replaces the duplicated implementations in `apps/research/queue.py` and `apps/documents/europass_queue.py`. |
| `apps/portals/schemas.py` | **new.** `PortalMessage` — identifiers only, never content. |
| `apps/portals/queue.py` | **new.** `enqueue_portal_work` — the portal-side wrapper over the shared transport. |
| `apps/portals/escalation.py` | **new.** The six triggers of §5.4 and nothing else: state transition, roadmap item, notification, audit step. |
| `apps/portals/profiles.py` | **new.** Per-application Chrome profile: tenant-isolated path, 0700, TTL sweep, `open_portal_session`. |
| `apps/portals/profile.py` | **new.** `verified_values` — flattens `VerifiedFact` rows to the `"category.key"` names a `FieldMap` entry uses. |
| `apps/portals/services.py` | **new.** `prepare_application`: the spine. goto → reauth if needed → fill with recovery → read back → `READY_TO_SUBMIT`. |
| `apps/portals/recovery.py` | **new.** Scoped re-learn on a selector miss, and the `RecoveryEvent` it writes. |
| `apps/portals/auth.py` | **new.** Session-expiry detection, platform-managed credentials, reauthentication. |
| `apps/portals/challenge.py` | **new.** Deterministic challenge detection: markers, then a stall heuristic. Never guesses. |
| `apps/portals/resolve.py` | **new.** `CaptchaResolver` protocol, `ServiceResolver` + one provider adapter, `ConsultantResolver`. |
| `apps/portals/dispatch.py` | **new.** Poll-based resume: enqueue a resume for every blocked application whose consultant task is done. |
| `apps/portals/reporting.py` | **new.** Per-portal intervention rate, so an expensive portal is visible. |
| `apps/portals/worker.py` | **new.** Tenant-scoped message handling, mirroring `apps/research/worker.py`. |
| `apps/portals/models.py` | modified. `RecoveryEvent`, `Application.exception_item`, `PortalForm.form_url` / `login_marker` / `mfa_marker` / `review_required`. |
| `apps/portals/session.py` | modified. `exists`, `query_attribute`, `press_enter` on the protocol. |
| `apps/portals/engine.py` | modified. Those three against real Chrome, plus `chrome_binary()` resolution. |
| `apps/portals/fill.py` | modified. `FillInterrupted` carries what was already filled; `fill_form(skip=...)`. |
| `Dockerfile` | modified. A `portal` stage: Chrome for Testing, Xvfb, `run_portal_worker`. |
| `infra/template.yaml` | modified. Portal queue, EC2 capacity for the sandboxed browser, task definition, alarms. |

---

### Task 1: Spike — can `extract` yield an actionable selector?

The spec's one open cost question. `1 x extract` mapped 36/36 fields for $0.054 against `N x observe`'s
$0.761 — a measured 14x — but `extract` returns accessibility node references (`[0-147]`) and `act()`
needs a selector. This task answers whether a resolution path exists in `stagehand==4.0.2`. **It changes
no production code either way.** The learn pass keeps `N x observe`, the shape that ships and works.

**Files:**
- Create: `scripts/spike_extract_node_refs.py`
- Modify: `docs/superpowers/specs/2026-08-27-phase3-portal-execution-design.md` (the "one open question" section, replaced with the answer)

**Interfaces:**
- Consumes: `apps.portals.engine.portal_session`, `apps.portals.session.FieldAction`
- Produces: nothing importable. The deliverable is a recorded finding.

- [ ] **Step 1: Write the spike script**

```python
# scripts/spike_extract_node_refs.py
"""Does a node reference from extract() resolve to something act() accepts?

Time-boxed spike, not a test: it needs a live LLM credential and real Chrome,
and its output is a paragraph in the spec, not an assertion. See the spec's
Cost section for why the answer is worth $0.70 per form version.

    xvfb-run -a --server-args="-screen 0 1280x1024x24" \
        uv run python scripts/spike_extract_node_refs.py

Exit 0 whatever the answer is -- "no path exists" is a successful spike.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.portals.engine import PORTAL_SYSTEM_PROMPT, chrome_binary  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "portals" / "fixtures" / "form36.html"


async def probe() -> None:
    from stagehand import Stagehand, local_browser

    with tempfile.TemporaryDirectory() as profile:
        browser = await local_browser.launch(
            headless=False,
            executable_path=str(chrome_binary()),
            chromium_sandbox=True,
            user_data_dir=profile,
            preserve_user_data_dir=False,
        )
        try:
            stagehand = await Stagehand.create(
                browser=browser,
                model="anthropic/claude-opus-4-8",
                model_api_key=os.environ["ANTHROPIC_API_KEY"],
                system_prompt=PORTAL_SYSTEM_PROMPT,
                self_heal=False,
            )
            page = await browser.context.new_page(FIXTURE.as_uri())
            # Flat schema, one string property per field: a dict[str, str]
            # schema silently returns nothing and logs "Extraction incomplete"
            # rather than erroring (measured, spec Cost section).
            result = await stagehand.extract(
                "the form control for the applicant's given name",
                page=page,
                schema={
                    "type": "object",
                    "properties": {"given_name": {"type": "string"}},
                    "required": ["given_name"],
                },
            )
            print("extract returned:", json.dumps(result.data, default=str))

            # The question: is there any public call that turns what came back
            # into a selector act() will take? Three candidates, in order of
            # how much they would prove.
            for name in ("ref", "locator", "tools"):
                print(f"page.{name}:", getattr(type(page), name, None))
            print("backend_node_id plumbing:", [
                attribute
                for attribute in dir(page)
                if "node" in attribute.lower() or "ref" in attribute.lower()
            ])
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(probe())
```

- [ ] **Step 2: Build the 36-field fixture the measurement used**

The fixture is the one described in the spec's Cost section: 36 inputs with realistic page furniture
(cookie banner, header nav, breadcrumb, fieldsets, mixed input types, footer), so the accessibility
tree is ~12,100 characters rather than a toy.

Run: `ls tests/portals/fixtures/form36.html`
Expected: if it is missing, write it — 36 labelled inputs across four `<fieldset>` blocks, a
`<nav>`, a cookie `<div role="dialog">` and a `<footer>`. Its exact content does not matter beyond
size and shape; it is spike input, not an assertion.

- [ ] **Step 3: Run the spike**

Run:
```bash
xvfb-run -a --server-args="-screen 0 1280x1024x24" \
    ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY uv run python scripts/spike_extract_node_refs.py
```
Expected: either a printed call that yields a selector, or evidence that none is public in 4.0.2.
**Time-box: one hour.** If it is not answered by then, the answer is "not without SDK work", which is
a valid finding.

- [ ] **Step 4: Record the finding in the spec**

Replace the spec's "The one open question before `extract` can replace `observe`" section with what
was measured. Both outcomes are one paragraph:

- *Resolution works*: name the exact call, note that switching the learn pass is a follow-up plan
  (it changes `learn.py`'s per-field loop into one call and needs its own accuracy test against a
  second fixture), and leave `N x observe` shipping.
- *No path exists*: close the question, state that `1 x extract` is unavailable in 4.0.2, and note
  the escape hatch that remains — `Stagehand.create(model=...)` accepts a
  `Callable[[LLMGenerateInput], Awaitable[LLMGenerateOutput]]`, which hands over the whole Anthropic
  request.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 add scripts/spike_extract_node_refs.py tests/portals/fixtures/form36.html docs/superpowers/specs/2026-08-27-phase3-portal-execution-design.md
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 commit -m "spike(portals): answer whether extract node refs resolve to selectors"
```

---

### Task 2: One SQS transport, parameterised over the message type

The spec calls for `apps/research/queue.py` to be parameterised rather than duplicated. It is already
duplicated once — `apps/documents/europass_queue.py` is the same sixty lines with a different model —
so this collapses both and gives the portal worker the third caller for free.

**Files:**
- Create: `apps/queue.py`
- Modify: `apps/research/queue.py` (reduced to the research-specific wrapper), `apps/documents/europass_queue.py` (reduced to its message model and wrapper), `apps/research/management/commands/run_research_worker.py`, `apps/documents/management/commands/run_europass_worker.py`
- Test: `tests/test_queue_transport.py`, `tests/research/test_queue.py` (two call sites gain a kwarg), `tests/documents/test_europass_queue.py` (import moves)

**Interfaces:**
- Produces: `apps.queue.SQSClient`, `apps.queue.enqueue(message, *, client=None, queue_url, group_id=None) -> None`, `apps.queue.consume_once(*, client, queue_url, message_type, handler) -> int`
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_queue_transport.py
"""The shared transport. Per-app behaviour stays in each app's own test module."""

from typing import Literal
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from apps.queue import consume_once, enqueue


class Fixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    tenant_id: UUID


def test_enqueue_omits_the_group_id_for_a_standard_queue():
    """A MessageGroupId on a standard queue is an InvalidParameterValue from
    SQS, so the parameter is absent rather than empty."""
    client = Mock()

    enqueue(Fixture(tenant_id=uuid4()), client=client, queue_url="q")

    assert "MessageGroupId" not in client.send_message.call_args.kwargs


def test_enqueue_sets_the_group_id_when_one_is_given():
    client = Mock()
    tenant_id = uuid4()

    enqueue(Fixture(tenant_id=tenant_id), client=client, queue_url="q", group_id=str(tenant_id))

    assert client.send_message.call_args.kwargs["MessageGroupId"] == str(tenant_id)


def test_consume_validates_against_the_type_the_caller_named():
    """The whole point of the parameter: a portal message arriving on the
    research queue must fail validation, not be handed to a research handler
    that reads attributes it does not have."""
    client = Mock()
    client.receive_message.return_value = {
        "Messages": [{"Body": '{"schema_version": 1, "unexpected": true}', "ReceiptHandle": "r"}]
    }

    with pytest.raises(ValidationError):
        consume_once(client=client, queue_url="q", message_type=Fixture, handler=Mock())
    client.delete_message.assert_not_called()


def test_consume_counts_what_it_processed_not_what_it_received():
    """A malformed envelope is skipped, not counted -- a caller that logs the
    return value as throughput would otherwise report work never done."""
    message = Fixture(tenant_id=uuid4())
    client = Mock()
    client.receive_message.return_value = {
        "Messages": [
            {"Body": message.model_dump_json(), "ReceiptHandle": "r"},
            {"NoBody": True},
        ]
    }
    seen = []

    assert consume_once(client=client, queue_url="q", message_type=Fixture, handler=seen.append) == 1
    assert seen == [message]
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/test_queue_transport.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.queue'`.

- [ ] **Step 3: Write the shared transport**

```python
# apps/queue.py
"""One SQS transport, parameterised over the message model.

apps/research/queue.py and apps/documents/europass_queue.py were the same
sixty lines twice, differing only in the model they validated and whether the
queue was FIFO. Both now import from here. Each app keeps its own message model
and its own enqueue wrapper, because the group-id policy is the only thing that
genuinely differs between them: research groups by tenant, Europass has no
groups at all, and portals group by application.
"""

from collections.abc import Callable
from typing import Any, Protocol, TypeVar

import boto3  # type: ignore[import-untyped]
from pydantic import BaseModel

MessageT = TypeVar("MessageT", bound=BaseModel)


class SQSClient(Protocol):
    def send_message(self, **kwargs: str) -> object: ...

    def receive_message(self, **kwargs: object) -> dict[str, object]: ...

    def delete_message(self, **kwargs: str) -> object: ...


def enqueue(
    message: BaseModel,
    *,
    client: SQSClient | None = None,
    queue_url: str,
    group_id: str | None = None,
) -> None:
    sqs = client or boto3.client("sqs")
    kwargs: dict[str, Any] = {"QueueUrl": queue_url, "MessageBody": message.model_dump_json()}
    # Omitted rather than sent empty. MessageGroupId is a FIFO-queue
    # parameter; enqueue_research passes one today against a queue the
    # template defines as standard (infra/template.yaml::ResearchQueue), which
    # is a pre-existing question this refactor deliberately preserves rather
    # than changes -- behaviour parity is what makes the research tests a valid
    # guard on it.
    if group_id is not None:
        kwargs["MessageGroupId"] = group_id
    sqs.send_message(**kwargs)


def consume_once(
    *,
    client: SQSClient,
    queue_url: str,
    message_type: type[MessageT],
    handler: Callable[[MessageT], None],
) -> int:
    """Receive at most one message, hand it to ``handler``, delete on success.

    Deletion happens only after the handler returns. A handler that raises
    leaves the message on the queue, so SQS redelivers it and the DLQ
    eventually catches what never succeeds -- that is the entire retry story.
    """
    response = client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=20,
        AttributeNames=["ApproximateReceiveCount"],
    )
    messages = response.get("Messages", [])
    if not isinstance(messages, list):
        return 0
    processed = 0
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        body = raw.get("Body")
        receipt = raw.get("ReceiptHandle")
        if not isinstance(body, str) or not isinstance(receipt, str):
            continue
        handler(message_type.model_validate_json(body))
        client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
        processed += 1
    return processed
```

- [ ] **Step 4: Reduce both duplicates to their wrappers**

```python
# apps/research/queue.py
"""Research-side queue policy. The transport itself is apps/queue.py."""

from apps.queue import SQSClient, enqueue

from .schemas import ResearchMessage

__all__ = ["SQSClient", "enqueue_research"]


def enqueue_research(
    message: ResearchMessage, *, client: SQSClient | None = None, queue_url: str
) -> None:
    """FIFO, grouped by tenant: one tenant's runs never overtake each other,
    and one tenant's backlog never blocks another's."""
    enqueue(message, client=client, queue_url=queue_url, group_id=str(message.tenant_id))
```

In `apps/documents/europass_queue.py`, delete the `SQSClient` protocol and the whole `consume_once`
body, keep `EuropassRenderMessage` and `enqueue_europass_render`, and replace the imports:

```python
from apps.queue import SQSClient, enqueue

# ... EuropassRenderMessage unchanged ...


def enqueue_europass_render(
    message: EuropassRenderMessage, *, client: SQSClient | None = None, queue_url: str
) -> None:
    """Standard queue, so no group: there is exactly one worker and ordering is
    meaningless."""
    enqueue(message, client=client, queue_url=queue_url)
```

- [ ] **Step 5: Update the three call sites**

In `apps/research/management/commands/run_research_worker.py`, import `consume_once` from
`apps.queue` and add `message_type=ResearchMessage` to the call. In
`apps/documents/management/commands/run_europass_worker.py`, import `consume_once` from `apps.queue`
(keep it a module-level name — `tests/documents/test_run_europass_worker.py` monkeypatches it there)
and add `message_type=EuropassRenderMessage`. In `tests/research/test_queue.py` and
`tests/documents/test_europass_queue.py`, add the same kwarg to each `consume_once` call and move the
`consume_once` import to `apps.queue`. No assertion in either file changes.

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/test_queue_transport.py tests/research tests/documents -q`
Expected: PASS. The research and Europass suites are the guard on this refactor; a behaviour change
shows up there, not in the new file.

- [ ] **Step 7: Gates and commit**

```bash
uv run ruff check apps tests
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps config
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 add apps/queue.py apps/research/queue.py apps/documents/europass_queue.py apps/research/management apps/documents/management tests/test_queue_transport.py tests/research/test_queue.py tests/documents/test_europass_queue.py
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 commit -m "refactor(queue): one SQS transport parameterised over the message type"
```

---

### Task 3: The escalation surface — six triggers and nothing else

**Files:**
- Create: `apps/portals/escalation.py`
- Modify: `apps/tenancy/db.py` (add `tenant_transaction`), `apps/portals/models.py` (add `Application.exception_item`, `Application.next_step_sequence`), `apps/portals/migrations/0004_escalation.py` (generated, then hand-edited to add the composite tenant FK)
- Test: `tests/portals/test_escalation.py`, `tests/tenancy/test_db.py` (append)

**Interfaces:**
- Consumes: `apps.concierge.models.{Notification, RoadmapItem}`, `apps.tenancy.models.CounselorAssignment`, `apps.portals.models.{Application, ApplicationStep}`
- Produces: `apps.tenancy.db.tenant_transaction(tenant_id) -> ContextManager[None]`, `apps.portals.escalation.Trigger` (StrEnum: `MISSING_FACT`, `PERSONAL_ATTESTATION`, `APPLICANT_MFA`, `UNSOLVED_CHALLENGE`, `AMBIGUOUS_DECISION`, `PORTAL_ERROR`), `escalate(application: Application, trigger: Trigger, *, detail: str) -> RoadmapItem`, `request_first_portal_review(application: Application) -> RoadmapItem | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/portals/test_escalation.py
"""Section 5.4's table is the whole escalation surface. These tests pin both
halves of that claim: every row escalates, and the table has no seventh row."""

from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _application(agency, student):
    from apps.portals.models import Application, PortalForm

    # form_key varies: PortalForm has a unique (portal_host, form_key)
    # constraint and these helpers are called more than once per test.
    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key=f"personal-details-{uuid4()}"
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_every_trigger_blocks_the_application_and_notifies_someone(agency_a, membership_a):
    from apps.concierge.models import Notification
    from apps.portals.escalation import BLOCKED_STATE, Trigger, escalate

    with tenant_scope(agency_a.id):
        for trigger in Trigger:
            application = _application(agency_a, membership_a)

            item = escalate(application, trigger, detail="because")

            application.refresh_from_db()
            assert application.state == BLOCKED_STATE[trigger], trigger
            assert application.exception_item_id == item.id
            assert Notification.objects.filter(recipient=item.owner).exists()
            step = application.steps.order_by("-sequence").first()
            assert step.kind == "ESCALATION"
            assert step.detail["trigger"] == trigger.value
            assert step.detail["detail"] == "because"


def test_the_trigger_table_is_exactly_section_54s_six_rows():
    """A seventh trigger is a product decision, not a refactor. If this fails,
    the requirements changed or something that recovers autonomously has been
    turned into a blocking escalation by accident."""
    from apps.portals.escalation import BLOCKED_STATE, Trigger

    assert [trigger.value for trigger in Trigger] == [
        "MISSING_FACT",
        "PERSONAL_ATTESTATION",
        "APPLICANT_MFA",
        "UNSOLVED_CHALLENGE",
        "AMBIGUOUS_DECISION",
        "PORTAL_ERROR",
    ]
    assert set(BLOCKED_STATE) == set(Trigger)


def test_only_the_two_personal_rows_reach_the_student(
    agency_a, membership_a, counselor_membership
):
    """§5.4 assigns everything else to the consultant desk. Sending a portal
    error to the student is not a smaller mistake than the reverse."""
    from apps.concierge.models import RoadmapItem
    from apps.portals.escalation import Trigger, escalate
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )

        personal = escalate(
            _application(agency_a, membership_a), Trigger.APPLICANT_MFA, detail="sms code"
        )
        portal = escalate(
            _application(agency_a, membership_a), Trigger.PORTAL_ERROR, detail="duplicate"
        )

        assert personal.owner_id == membership_a.id
        assert personal.stage == RoadmapItem.Stage.PERSONAL_ACTION
        assert portal.owner_id == counselor_membership.id
        assert portal.stage == RoadmapItem.Stage.APPLICATION_PREP


def test_a_challenge_escalation_uses_the_portal_exception_stage(
    agency_a, membership_a, counselor_membership
):
    """Spec design point 8: the dashboard requirement in §5.2 is already
    satisfied by the existing stages, so no new pause concept is introduced."""
    from apps.concierge.models import RoadmapItem
    from apps.portals.escalation import Trigger, escalate
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        item = escalate(
            _application(agency_a, membership_a), Trigger.UNSOLVED_CHALLENGE, detail="hcaptcha"
        )

        assert item.stage == RoadmapItem.Stage.PORTAL_EXCEPTION


def test_an_unassigned_student_still_reaches_a_human(agency_a, membership_a):
    """A missing CounselorAssignment is a tenancy configuration error. It must
    not silently swallow an escalation, and there is no third principal to
    fall back to, so the student is told."""
    from apps.portals.escalation import Trigger, escalate

    with tenant_scope(agency_a.id):
        item = escalate(_application(agency_a, membership_a), Trigger.PORTAL_ERROR, detail="x")

        assert item.owner_id == membership_a.id


def test_the_first_application_on_a_new_portal_asks_for_review_without_blocking(
    agency_a, membership_a, counselor_membership
):
    """§5.2 requires consultant review of the first prepared application on
    each portal. That is a review task, not an escalation: the application is
    ready, so its state must not move to a BLOCKED_* value."""
    from apps.concierge.models import RoadmapItem
    from apps.portals.escalation import request_first_portal_review
    from apps.portals.models import Application
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        application = _application(agency_a, membership_a)
        application.state = Application.State.READY_TO_SUBMIT
        application.save(update_fields=["state"])

        first = request_first_portal_review(application)
        application.refresh_from_db()

        assert first is not None
        assert first.stage == RoadmapItem.Stage.APPLICATION_PREP
        assert application.state == Application.State.READY_TO_SUBMIT
        assert application.portal_form.review_required is False

        # Second application on the same portal: the portal is no longer new.
        assert request_first_portal_review(_application(agency_a, membership_a)) is None
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_escalation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.portals.escalation'`.

- [ ] **Step 3: Add the transaction helper every writer below this line uses**

`set_local_tenant` sets `app.tenant_id` with `set_config(..., true)` — transaction-local — and raises
outside an atomic block. The research worker satisfies that by wrapping one whole message in one
transaction, which is right for a fetch and wrong for a browser session that runs for minutes. Every
portal writer therefore opens its own short transaction and re-establishes the scope inside it.

```python
# tests/tenancy/test_db.py -- append
def test_tenant_transaction_sets_the_guc_inside_its_own_block(agency_a):
    from django.db import connection

    from apps.tenancy.db import tenant_transaction

    with tenant_transaction(agency_a.id):
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('app.tenant_id', true)")
            assert cursor.fetchone()[0] == str(agency_a.id)
```

```python
# apps/tenancy/db.py -- append
from collections.abc import Iterator
from contextlib import contextmanager

from django.db import transaction


@contextmanager
def tenant_transaction(tenant_id: UUID) -> Iterator[None]:
    """One short transaction with ``app.tenant_id`` set inside it.

    The GUC is transaction-local, so scope and transaction are the same object
    and there is no way to hold one without the other. Callers that must not
    hold a transaction open -- anything driving a browser or an LLM -- wrap each
    database interaction in this instead of wrapping the whole operation.

    Nesting is a savepoint and re-runs set_config harmlessly, so a caller does
    not have to know whether it is already inside one.
    """
    with transaction.atomic():
        set_local_tenant(tenant_id)
        yield
```

- [ ] **Step 4: Add the model fields**

```python
# apps/portals/models.py -- inside PortalForm, after form_key
    #: The page a fill starts on. Held here rather than passed per application
    #: because it is a property of the form version, not of the student.
    form_url = models.URLField(max_length=500, blank=True)
    #: §5.2: consultant review of the first prepared application on each new
    #: portal. Cleared by request_first_portal_review once that task exists.
    review_required = models.BooleanField(default=True)

# apps/portals/models.py -- inside Application, after state
    #: The roadmap item a human must close before this application moves
    #: again. Nullable and cleared on resume, so "blocked on a person" is one
    #: indexed query rather than a scan of ApplicationStep rows.
    exception_item = models.ForeignKey(
        "concierge.RoadmapItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    def next_step_sequence(self) -> int:
        """Next audit-trail sequence number.

        # ponytail: read-then-write. It takes two workers on one application
        # to race, and there is one portal task by construction
        # (PortalDesiredCount maxes at 1). Revisit if that ever changes.
        """
        last = self.steps.order_by("-sequence").values_list("sequence", flat=True).first()
        return (last or 0) + 1
```

Run: `POSTGRES_DB=tehsil_plan2a uv run python manage.py makemigrations portals --name escalation`
Expected: `0004_escalation.py` adding three fields.

Then hand-edit that migration to add the composite tenant guard, the same shape
`0003_tenant_guards.py` uses for `student_id` and `application_id`. `RoadmapItem` carries a
`roadmap_tenant_id_uniq` constraint, so the reference is available — without this an application row
could name another tenant's roadmap item, which RLS would hide but not prevent from being written:

```python
    operations = [
        # ... the generated AddField operations ...
        migrations.RunSQL(
            """
            ALTER TABLE portals_application
                ADD CONSTRAINT portal_app_exception_tenant_fk
                FOREIGN KEY (tenant_id, exception_item_id)
                REFERENCES concierge_roadmapitem (tenant_id, id);
            """,
            "ALTER TABLE portals_application DROP CONSTRAINT portal_app_exception_tenant_fk;",
        ),
    ]
```

Add `("concierge", "0002_tenant_guards")` to the migration's `dependencies`.

- [ ] **Step 5: Write the escalation module**

```python
# apps/portals/escalation.py
"""The whole escalation surface: six triggers, and nothing else escalates.

Everything not in this table recovers on its own and is recorded as a
RecoveryEvent instead (apps/portals/recovery.py). The distinction is the
spec's, and it is the difference between a platform that notifies a human when
only a human can answer and one that queues work behind every hiccup.
"""

import logging
from datetime import timedelta
from enum import StrEnum

from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import CounselorAssignment, Membership

from .models import Application, ApplicationStep

logger = logging.getLogger(__name__)


class Trigger(StrEnum):
    """One member per row of §5.4's table. Adding a member is a product
    decision that changes what the platform asks people to do."""

    MISSING_FACT = "MISSING_FACT"
    PERSONAL_ATTESTATION = "PERSONAL_ATTESTATION"
    APPLICANT_MFA = "APPLICANT_MFA"
    UNSOLVED_CHALLENGE = "UNSOLVED_CHALLENGE"
    AMBIGUOUS_DECISION = "AMBIGUOUS_DECISION"
    PORTAL_ERROR = "PORTAL_ERROR"


BLOCKED_STATE = {
    Trigger.MISSING_FACT: Application.State.BLOCKED_MISSING_FACT,
    Trigger.PERSONAL_ATTESTATION: Application.State.BLOCKED_PERSONAL_ACTION,
    Trigger.APPLICANT_MFA: Application.State.BLOCKED_PERSONAL_ACTION,
    Trigger.UNSOLVED_CHALLENGE: Application.State.BLOCKED_CHALLENGE,
    # Ambiguity is a missing fact seen from the agent's side: the answer is not
    # determined by anything verified. It is deliberately NOT a portal error --
    # nothing is broken, and routing it there would hide real portal failures
    # in a bucket full of judgement calls.
    Trigger.AMBIGUOUS_DECISION: Application.State.BLOCKED_MISSING_FACT,
    Trigger.PORTAL_ERROR: Application.State.BLOCKED_PORTAL_ERROR,
}

#: The two rows that require one specific human. §5.4 gives the rest to the
#: consultant desk, and a student asked to resolve a portal error has been
#: handed work the platform sold them out of.
STUDENT_TRIGGERS = frozenset({Trigger.PERSONAL_ATTESTATION, Trigger.APPLICANT_MFA})

STAGE = {
    Trigger.UNSOLVED_CHALLENGE: RoadmapItem.Stage.PORTAL_EXCEPTION,
    Trigger.PERSONAL_ATTESTATION: RoadmapItem.Stage.PERSONAL_ACTION,
    Trigger.APPLICANT_MFA: RoadmapItem.Stage.PERSONAL_ACTION,
}
DEFAULT_STAGE = RoadmapItem.Stage.APPLICATION_PREP

#: A roadmap item needs a deadline and an application does not carry one here
#: (the program deadline lives in apps/funding). Three days is the desk SLA,
#: not a guess at the portal's deadline; deadline_urgency will show it as
#: DUE_SOON immediately, which is correct -- a blocked application is urgent.
ESCALATION_SLA = timedelta(days=3)


def _recipient(application: Application, trigger: Trigger) -> Membership:
    if trigger in STUDENT_TRIGGERS:
        return application.student
    assignment = (
        # active=True, not merely assigned: the model allows one *active*
        # counselor per student and keeps the inactive rows, so dropping the
        # filter can route an escalation to someone who has left the agency.
        CounselorAssignment.objects.filter(student=application.student, active=True)
        .select_related("counselor")
        .first()
    )
    # No assignment is a tenancy configuration error, not a reason to drop the
    # escalation. The student is the only other principal we know exists.
    return assignment.counselor if assignment else application.student


def escalate(application: Application, trigger: Trigger, *, detail: str) -> RoadmapItem:
    """Block the application, create the human's task, and tell them.

    ``detail`` is the specific missing fact or required action -- §5.4 requires
    the notification to carry it, because "the application is blocked" is not
    something anyone can act on.
    """
    with tenant_transaction(application.tenant_id):
        return _escalate(application, trigger, detail=detail)


def _escalate(application: Application, trigger: Trigger, *, detail: str) -> RoadmapItem:
    recipient = _recipient(application, trigger)
    item = RoadmapItem.objects.create(
        tenant=application.tenant,
        student=application.student,
        stage=STAGE.get(trigger, DEFAULT_STAGE),
        owner=recipient,
        owner_kind=RoadmapItem.OwnerKind.HUMAN,
        deadline=timezone.now() + ESCALATION_SLA,
    )
    ApplicationStep.objects.create(
        tenant=application.tenant,
        application=application,
        sequence=application.next_step_sequence(),
        kind="ESCALATION",
        detail={"trigger": trigger.value, "detail": detail, "roadmap_item": str(item.id)},
    )
    application.state = BLOCKED_STATE[trigger]
    application.exception_item = item
    application.save(update_fields=["state", "exception_item"])
    Notification.objects.create(
        tenant=application.tenant,
        recipient=recipient,
        message=f"{application.portal_form.portal_host}: {trigger.value} -- {detail}",
    )
    # Watched by PortalEscalationFilter (infra/template.yaml). The alarm is on
    # the rate: escalations are expected, a spike in them is not.
    logger.info(
        "PortalEscalation trigger=%s application=%s portal=%s",
        trigger.value,
        application.id,
        application.portal_form.portal_host,
    )
    return item


def request_first_portal_review(application: Application) -> RoadmapItem | None:
    """§5.2's first-application review. Returns None once the portal is known.

    Not an escalation: the application is prepared and stays prepared. The
    consultant is asked to look at it, not to unblock it, so no state moves and
    exception_item is left alone.
    """
    portal_form = application.portal_form
    if not portal_form.review_required:
        return None
    with tenant_transaction(application.tenant_id):
        return _request_first_portal_review(application)


def _request_first_portal_review(application: Application) -> RoadmapItem:
    portal_form = application.portal_form
    item = RoadmapItem.objects.create(
        tenant=application.tenant,
        student=application.student,
        stage=DEFAULT_STAGE,
        owner=_recipient(application, Trigger.AMBIGUOUS_DECISION),
        owner_kind=RoadmapItem.OwnerKind.HUMAN,
        deadline=timezone.now() + ESCALATION_SLA,
    )
    Notification.objects.create(
        tenant=application.tenant,
        recipient=item.owner,
        message=(
            f"First prepared application on {portal_form.portal_host} -- "
            "review before it is submitted."
        ),
    )
    # PortalForm is platform-shared, so the first review covers every tenant.
    # That is the same amortisation argument as FieldMap: the form is public
    # and nothing about the review is tenant-specific.
    portal_form.review_required = False
    portal_form.save(update_fields=["review_required"])
    return item
```

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals tests/tenancy -q`
Expected: PASS, including plan 1's existing portal tests.

- [ ] **Step 7: Gates and commit**

```bash
uv run ruff check apps tests
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps
POSTGRES_DB=tehsil_plan2a uv run python manage.py makemigrations --check --dry-run
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 add apps/tenancy/db.py apps/portals/escalation.py apps/portals/models.py apps/portals/migrations/0004_escalation.py tests/portals/test_escalation.py tests/tenancy/test_db.py
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 commit -m "feat(portals): the six-trigger escalation surface"
```

---

### Task 4: Per-application browser profiles, with a TTL

The `user_data_dir` holds live portal session cookies for one student's portal account. Plan 1 wrote
it to a `tmp_path` in tests only; this is where it gets a real home.

**Files:**
- Create: `apps/portals/profiles.py`
- Modify: `config/settings/base.py` (three settings)
- Test: `tests/portals/test_profiles.py`

**Interfaces:**
- Consumes: `apps.portals.engine.portal_session`, `apps.portals.models.Application`
- Produces: `profile_dir(application) -> Path`, `sweep_expired(*, root=None, ttl=None, now=None) -> int`, `open_portal_session(application) -> ContextManager[StagehandPortalSession]`

- [ ] **Step 1: Write the failing test**

```python
# tests/portals/test_profiles.py
"""What protects a directory full of live portal session cookies."""

import os
from datetime import timedelta
from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _application(agency, student):
    from apps.portals.models import Application, PortalForm

    # form_key varies: PortalForm has a unique (portal_host, form_key)
    # constraint and these helpers are called more than once per test.
    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key=f"personal-details-{uuid4()}"
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_the_profile_path_is_tenant_isolated(settings, tmp_path, agency_a, membership_a):
    from apps.portals.profiles import profile_dir

    settings.PORTAL_PROFILE_ROOT = tmp_path
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        path = profile_dir(application)

    assert path.parent.name == str(agency_a.id)
    assert path.name == str(application.id)
    assert path.is_relative_to(tmp_path)


def test_the_profile_and_its_tenant_directory_are_private(
    settings, tmp_path, agency_a, membership_a
):
    """0700 on both levels. One tenant's cookie jar must not be listable
    through another tenant's directory, and the process running this is not
    the only account on a shared host."""
    from apps.portals.profiles import profile_dir

    settings.PORTAL_PROFILE_ROOT = tmp_path
    with tenant_scope(agency_a.id):
        path = profile_dir(_application(agency_a, membership_a))

    assert os.stat(path).st_mode & 0o777 == 0o700
    assert os.stat(path.parent).st_mode & 0o777 == 0o700


def test_sweep_removes_profiles_past_their_ttl_and_keeps_fresh_ones(
    settings, tmp_path, agency_a, membership_a
):
    from apps.portals.profiles import LAST_USED, profile_dir, sweep_expired

    settings.PORTAL_PROFILE_ROOT = tmp_path
    with tenant_scope(agency_a.id):
        stale = profile_dir(_application(agency_a, membership_a))
        fresh = profile_dir(_application(agency_a, membership_a))

    for path in (stale, fresh):
        (path / LAST_USED).touch()
    old = (stale / LAST_USED).stat().st_mtime - timedelta(days=3).total_seconds()
    os.utime(stale / LAST_USED, (old, old))

    assert sweep_expired(root=tmp_path, ttl=timedelta(days=1)) == 1
    assert not stale.exists()
    assert fresh.exists()


def test_sweep_removes_a_profile_that_never_recorded_a_use(settings, tmp_path):
    """A directory with no marker is either a crashed session or something
    that does not belong here. Both are cookies nobody is tracking."""
    from apps.portals.profiles import sweep_expired

    orphan = tmp_path / str(uuid4()) / str(uuid4())
    orphan.mkdir(parents=True)

    assert sweep_expired(root=tmp_path, ttl=timedelta(days=1)) == 1
    assert not orphan.exists()


def test_sweep_never_follows_a_symlink_out_of_the_root(settings, tmp_path):
    """This function calls rmtree. The shape check is the whole safety
    argument, so it gets a test that fails loudly if it is ever loosened."""
    from apps.portals.profiles import sweep_expired

    outside = tmp_path.parent / "not-a-profile"
    outside.mkdir()
    (outside / "keepme").touch()
    tenant = tmp_path / str(uuid4())
    tenant.mkdir()
    (tenant / str(uuid4())).symlink_to(outside, target_is_directory=True)

    assert sweep_expired(root=tmp_path, ttl=timedelta(days=1)) == 0
    assert (outside / "keepme").exists()


def test_sweep_ignores_anything_not_shaped_like_a_profile(settings, tmp_path):
    from apps.portals.profiles import sweep_expired

    (tmp_path / "README").write_text("not a tenant directory", encoding="utf-8")
    (tmp_path / "loose").mkdir()

    assert sweep_expired(root=tmp_path, ttl=timedelta(days=1)) == 0
    assert (tmp_path / "loose").exists()
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_profiles.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.portals.profiles'`.

- [ ] **Step 3: Add the settings**

```python
# config/settings/base.py -- after EVIDENCE_BUCKET_NAME
PORTAL_QUEUE_URL = os.getenv("PORTAL_QUEUE_URL", "test-portal-queue")
#: Where Chrome profiles for portal sessions live. A path on the portal task's
#: own encrypted volume -- never a shared filesystem, see apps/portals/profiles.py.
PORTAL_PROFILE_ROOT = Path(os.getenv("PORTAL_PROFILE_ROOT", "/tmp/tehsil-portal-profiles"))  # noqa: S108
PORTAL_PROFILE_TTL_HOURS = int(os.getenv("PORTAL_PROFILE_TTL_HOURS", "24"))
```

```python
# config/settings/production.py -- after EUROPASS_QUEUE_URL
PORTAL_QUEUE_URL = os.environ["PORTAL_QUEUE_URL"]
```

If bandit flags the `/tmp` default (B108), the `# noqa` above is the wrong tool — remove it and add a
`# nosec B108` with this reason: the default is a development fallback, production sets
`PORTAL_PROFILE_ROOT` explicitly from the task definition, and the directory is created 0700 by
`profile_dir` rather than reused.

- [ ] **Step 4: Write the profile module**

```python
# apps/portals/profiles.py
"""Per-application Chrome profiles: where live portal session cookies live.

Three controls, in the order of what they actually protect against.

- A tenant-isolated path, 0700 at both levels, so one tenant's cookie jar is
  not reachable through another's and no other account on the host can read it.
- A TTL sweep, so an abandoned session's cookies stop existing rather than
  sitting on disk until the task is replaced.
- Encryption at rest is the volume's, not this module's. The profile is a live
  Chrome directory (SQLite and LevelDB files) held open for the session's whole
  life, so an application-level tar-and-encrypt would have to decrypt it back
  to disk to be usable and would protect nothing during the window that
  matters. The portal task's EBS volume is created with Encrypted: true
  (infra/template.yaml, Task 14), which is what "encrypted at rest" means for a
  directory something is writing to.
  # ponytail: volume-level encryption. If a profile ever has to outlive its
  # task -- EFS, S3, a second host -- it leaves that volume and needs real
  # envelope encryption before it does.

There is deliberately no shared storage: an interrupted session resumes only on
the task that owns it, and a task that dies takes its profile with it. That is
not a gap, it is why reauthentication exists (apps/portals/auth.py).
"""

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from .engine import StagehandPortalSession, portal_session
from .models import Application

#: Touched on entry and exit of every session. The directory's own mtime is not
#: enough: Chrome writes to files inside it without changing the parent.
LAST_USED = ".last_used"
PROFILE_MODE = 0o700


def _root() -> Path:
    return Path(settings.PORTAL_PROFILE_ROOT)


def profile_dir(application: Application) -> Path:
    path = _root() / str(application.tenant_id) / str(application.id)
    path.mkdir(mode=PROFILE_MODE, parents=True, exist_ok=True)
    # mkdir's mode is masked by umask and skipped entirely when the directory
    # already exists, so both levels are set explicitly.
    path.chmod(PROFILE_MODE)
    path.parent.chmod(PROFILE_MODE)
    return path


def _is_profile(path: Path) -> bool:
    """A tenant/application pair of real directories, and nothing else.

    This is the guard on an rmtree. Symlinks are rejected rather than resolved:
    a symlink here is either a mistake or an attempt to have us delete
    something outside the root, and neither deserves a follow.
    """
    if path.is_symlink() or not path.is_dir():
        return False
    if path.parent.is_symlink():
        return False
    try:
        UUID(path.name)
        UUID(path.parent.name)
    except ValueError:
        return False
    return True


def sweep_expired(
    *, root: Path | None = None, ttl: timedelta | None = None, now: datetime | None = None
) -> int:
    """Delete every profile untouched for longer than the TTL. Returns the count."""
    root = root or _root()
    ttl = ttl or timedelta(hours=settings.PORTAL_PROFILE_TTL_HOURS)
    now = now or timezone.now()
    if not root.exists():
        return 0
    removed = 0
    for tenant_dir in root.iterdir():
        if tenant_dir.is_symlink() or not tenant_dir.is_dir():
            continue
        for candidate in tenant_dir.iterdir():
            if not _is_profile(candidate):
                continue
            marker = candidate / LAST_USED
            # No marker means a crashed session or a directory nobody is
            # tracking. Both are cookies with no owner, so both go.
            if marker.exists():
                last_used = datetime.fromtimestamp(marker.stat().st_mtime, tz=now.tzinfo)
                if now - last_used <= ttl:
                    continue
            shutil.rmtree(candidate)
            removed += 1
    return removed


@contextmanager
def open_portal_session(application: Application) -> Iterator[StagehandPortalSession]:
    """A browser pinned to this application's portal and this application's profile."""
    path = profile_dir(application)
    (path / LAST_USED).touch()
    try:
        with portal_session(
            user_data_dir=path, allowed_host=application.portal_form.portal_host
        ) as session:
            yield session
    finally:
        # Touched again on the way out so the TTL measures time since the last
        # use, not time since the session started -- a six-hour fill would
        # otherwise be swept while it was still running.
        (path / LAST_USED).touch()
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_profiles.py -q`
Expected: PASS.

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check apps config tests
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps config
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 add apps/portals/profiles.py config/settings/base.py config/settings/production.py tests/portals/test_profiles.py
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 commit -m "feat(portals): tenant-isolated browser profiles with a TTL sweep"
```

---

### Task 5: The prepare spine, the portal queue, and the worker

The end-to-end path with no recovery in it yet: verified values, fill, read back, stop at
`READY_TO_SUBMIT`. Later tasks wrap recovery around the same function.

**Files:**
- Create: `apps/portals/profile.py`, `apps/portals/schemas.py`, `apps/portals/queue.py`, `apps/portals/services.py`, `apps/portals/worker.py`, `apps/portals/management/__init__.py`, `apps/portals/management/commands/__init__.py`, `apps/portals/management/commands/run_portal_worker.py`
- Test: `tests/portals/test_profile_values.py`, `tests/portals/test_services.py`, `tests/portals/test_portal_queue.py`

**Interfaces:**
- Consumes: `apps.queue.{enqueue, consume_once}`, `apps.portals.fill.{fill_form, read_back, MissingFact, ReadBackMismatch}`, `apps.portals.escalation.{Trigger, escalate, request_first_portal_review}`, `apps.portals.profiles.open_portal_session`, `apps.documents.models.VerifiedFact`
- Produces:
  - `apps.portals.profile.verified_values(student: Membership) -> dict[str, str]`
  - `apps.portals.schemas.PortalMessage` (`schema_version`, `kind: Literal["prepare_application", "resume_application"]`, `tenant_id`, `application_id`)
  - `apps.portals.queue.enqueue_portal_work(message, *, client=None, queue_url) -> None`
  - `apps.portals.services.prepare_application(application, session) -> Application`
  - `apps.portals.worker.{process_portal_message, handle_portal_message}`

- [ ] **Step 1: Write the failing test for the value bridge**

```python
# tests/portals/test_profile_values.py
"""FieldMap entries name "category.key". VerifiedFact stores a category and a
payload. This is the one place those two vocabularies meet."""

import pytest
from django.utils import timezone

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _fact(agency, student, category, payload, *, confirmed=True, supersedes=None):
    from apps.documents.models import VerifiedFact

    return VerifiedFact.objects.create(
        tenant=agency,
        student=student,
        category=category,
        payload=payload,
        source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
        source_ref="passport.pdf",
        confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None,
        created_by=student,
        supersedes=supersedes,
    )


def test_confirmed_facts_flatten_to_dotted_names(agency_a, membership_a):
    from apps.documents.models import VerifiedFact
    from apps.portals.profile import verified_values

    with tenant_scope(agency_a.id):
        _fact(agency_a, membership_a, VerifiedFact.Category.IDENTITY, {"full_name": "Ada Byron"})

        assert verified_values(membership_a)["identity.full_name"] == "Ada Byron"


def test_an_unconfirmed_fact_is_not_a_verified_value(agency_a, membership_a):
    """P1-14 and §5.2 both turn on "verified". An unconfirmed row is a claim,
    and typing it into an attested form is exactly what escalation prevents."""
    from apps.documents.models import VerifiedFact
    from apps.portals.profile import verified_values

    with tenant_scope(agency_a.id):
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.PERSONAL,
            {"city": "London"},
            confirmed=False,
        )

        assert "personal.city" not in verified_values(membership_a)


def test_a_correction_wins_over_what_it_supersedes(agency_a, membership_a):
    from apps.documents.models import VerifiedFact
    from apps.portals.profile import verified_values

    with tenant_scope(agency_a.id):
        original = _fact(
            agency_a, membership_a, VerifiedFact.Category.PERSONAL, {"city": "Londn"}
        )
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.PERSONAL,
            {"city": "London"},
            supersedes=original,
        )

        assert verified_values(membership_a)["personal.city"] == "London"


def test_non_string_payload_members_are_left_out(agency_a, membership_a):
    """A form field takes text. A list of publications is a document-generation
    input, not something to type into an input element, and silently
    str()-ing it would fill a portal with a Python repr."""
    from apps.documents.models import VerifiedFact
    from apps.portals.profile import verified_values

    with tenant_scope(agency_a.id):
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.PUBLICATION,
            {"titles": ["a", "b"], "count": 2, "venue": "Nature"},
        )

        values = verified_values(membership_a)
        assert values["publication.venue"] == "Nature"
        assert "publication.titles" not in values
        assert "publication.count" not in values
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_profile_values.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.portals.profile'`.

- [ ] **Step 3: Write the value bridge**

```python
# apps/portals/profile.py
"""Verified facts, in the vocabulary a FieldMap entry uses.

A FieldMap entry names "personal.given_name". A VerifiedFact holds a category
and a payload dict. Nothing else in the codebase needs that translation, so it
lives here rather than in apps/documents, and it is deliberately one-way:
nothing writes facts from a portal page.
"""

from apps.documents.models import VerifiedFact
from apps.tenancy.models import Membership


def verified_values(student: Membership) -> dict[str, str]:
    """Confirmed, current facts flattened to ``"category.key" -> value``.

    # ponytail: last row wins for a repeated category. A form that needs the
    # second degree rather than the most recent one needs indexed keys
    # ("education.1.institution"), which no field map asks for yet.
    """
    superseded = set(
        VerifiedFact.objects.filter(student=student, supersedes__isnull=False).values_list(
            "supersedes_id", flat=True
        )
    )
    values: dict[str, str] = {}
    for fact in (
        VerifiedFact.objects.filter(student=student, confirmed_at__isnull=False)
        .exclude(id__in=superseded)
        .order_by("created_at")
    ):
        for key, value in fact.payload.items():
            # Text only. A list or a number here belongs to document
            # generation; typing its repr into a portal field is worse than
            # escalating the field as missing.
            if isinstance(value, str) and value.strip():
                values[f"{fact.category.lower()}.{key}"] = value
    return values
```

- [ ] **Step 4: Write the failing test for the spine**

```python
# tests/portals/test_services.py
"""prepare_application: fill, verify, stop. It must never submit."""

from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope
from tests.portals.fakes import FakePortalSession

pytestmark = pytest.mark.django_db

ENTRIES = [
    {
        "profile_field": "identity.full_name",
        "action": {"selector": "#name", "method": "fill", "arguments": ["%value%"]},
    },
    {
        "profile_field": "personal.city",
        "action": {"selector": "#city", "method": "fill", "arguments": ["%value%"]},
    },
]


def _application_with_map(agency, student, *, entries=None):
    from apps.portals.models import Application, FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key=f"personal-details-{uuid4()}",
        form_url="https://apply.example.edu/personal",
        review_required=False,
    )
    FieldMap.objects.create(portal_form=form, version=1, entries=entries or ENTRIES)
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_a_complete_application_reaches_ready_to_submit(
    agency_a, membership_a, monkeypatch
):
    from apps.portals import services
    from apps.portals.models import Application

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    session = FakePortalSession()
    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)

        services.prepare_application(application, session)

        application.refresh_from_db()
        assert application.state == Application.State.READY_TO_SUBMIT
        assert session.values == {"#name": "Ada Byron", "#city": "London"}
        assert session.visited == ["https://apply.example.edu/personal"]


def test_preparing_makes_no_llm_call(agency_a, membership_a, monkeypatch):
    """The cost thesis, asserted where it is spent. A prepare that observes is
    a prepare that costs $0.76 per student instead of per form version."""
    from apps.portals import services

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    session = FakePortalSession()
    with tenant_scope(agency_a.id):
        services.prepare_application(_application_with_map(agency_a, membership_a), session)

    assert session.observe_calls == 0


def test_a_missing_verified_fact_escalates_and_names_the_field(
    agency_a, membership_a, monkeypatch
):
    from apps.concierge.models import Notification
    from apps.portals import services
    from apps.portals.models import Application

    monkeypatch.setattr(
        services, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    session = FakePortalSession()
    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)

        services.prepare_application(application, session)

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_MISSING_FACT
        assert "personal.city" in Notification.objects.get().message
        # Nothing was typed: a half-filled form on a real portal is worse than
        # one never started.
        assert session.values == {}


def test_a_read_back_mismatch_escalates_as_a_portal_error(
    agency_a, membership_a, monkeypatch
):
    """The page holding something other than what we typed is not something to
    retry -- it means a selector resolved somewhere unexpected."""
    from apps.portals import services
    from apps.portals.models import Application

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )

    class Diverging(FakePortalSession):
        def read_value(self, selector):
            return "something else" if selector == "#city" else super().read_value(selector)

    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)

        services.prepare_application(application, Diverging())

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_PORTAL_ERROR


def test_the_first_application_on_a_portal_gets_a_review_task(
    agency_a, membership_a, counselor_membership, monkeypatch
):
    from apps.concierge.models import RoadmapItem
    from apps.portals import services
    from apps.portals.models import Application
    from apps.tenancy.models import CounselorAssignment

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        application = _application_with_map(agency_a, membership_a)
        application.portal_form.review_required = True
        application.portal_form.save(update_fields=["review_required"])

        services.prepare_application(application, FakePortalSession())

        application.refresh_from_db()
        assert application.state == Application.State.READY_TO_SUBMIT
        assert RoadmapItem.objects.filter(owner=counselor_membership).exists()


def test_the_audit_trail_records_the_versions_used(agency_a, membership_a, monkeypatch):
    """§5.5: profile and document versions used, form answers, agent actions."""
    from apps.portals import services

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)

        services.prepare_application(application, FakePortalSession())

        kinds = list(application.steps.order_by("sequence").values_list("kind", flat=True))
        assert kinds == ["FILL", "READ_BACK"]
        fill_step = application.steps.get(kind="FILL")
        assert fill_step.detail["field_map_version"] == 1
        assert fill_step.detail["filled"] == ["identity.full_name", "personal.city"]
        # The answers themselves are audit evidence and belong here; the
        # student's values never reach FieldMap, which is the shared table.
        assert fill_step.detail["values"]["personal.city"] == "London"
```

- [ ] **Step 5: Run it to make sure it fails**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_services.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.portals.services'`.

- [ ] **Step 6: Write the spine**

```python
# apps/portals/services.py
"""Prepare one application: fill it, verify it against the page, and stop.

READY_TO_SUBMIT is the terminal success state of plan 2a. Submission, the two
authority modes and the 48-hour rule are plan 2b and are gated on the
portal-terms blocker in §10 of `phased requirements.md` -- there is deliberately
no code path here that could submit if a flag were flipped.
"""

import logging

from apps.tenancy.db import tenant_transaction

from .escalation import Trigger, escalate, request_first_portal_review
from .fill import MissingFact, ReadBackMismatch, fill_form, read_back
from .models import Application, ApplicationStep, FieldMap
from .profile import verified_values
from .session import PortalSession

logger = logging.getLogger(__name__)


class NoFieldMap(Exception):
    """The portal form has never been learned. A caller must run the learn pass."""


def _record(application: Application, kind: str, detail: dict[str, object]) -> None:
    """Its own short transaction. The audit trail records what was really typed
    into a real portal, so each step is committed before the next one can
    fail -- one transaction around the whole fill would roll away the evidence
    that the fill happened."""
    with tenant_transaction(application.tenant_id):
        ApplicationStep.objects.create(
            tenant=application.tenant,
            application=application,
            sequence=application.next_step_sequence(),
            kind=kind,
            detail=detail,
        )


def prepare_application(application: Application, session: PortalSession) -> Application:
    """Fill and verify. Escalates rather than raising for the cases §5.4 names."""
    field_map = FieldMap.current_for(application.portal_form)
    if field_map is None:
        raise NoFieldMap(f"{application.portal_form.portal_host} has no current field map")

    values = verified_values(application.student)
    missing = [
        entry["profile_field"]
        for entry in field_map.entries
        if not (values.get(entry["profile_field"]) or "").strip()
    ]
    if missing:
        # Before goto, deliberately: there is no reason to open a browser
        # against a portal for an application that cannot be completed.
        escalate(application, Trigger.MISSING_FACT, detail=", ".join(sorted(missing)))
        return application

    session.goto(application.portal_form.form_url)

    try:
        filled = fill_form(session, field_map, values)
    except MissingFact as error:
        escalate(application, Trigger.MISSING_FACT, detail=str(error))
        return application

    _record(
        application,
        "FILL",
        {
            "field_map_version": field_map.version,
            "filled": filled,
            "values": {name: values[name] for name in filled},
        },
    )

    try:
        read_back(session, field_map, values)
    except ReadBackMismatch as mismatch:
        # Not a retry: the page holding something else means a selector
        # resolved somewhere we did not intend, and typing again would do it
        # a second time.
        escalate(
            application,
            Trigger.PORTAL_ERROR,
            detail=f"read-back mismatch on {mismatch.field}",
        )
        return application

    _record(application, "READ_BACK", {"field_map_version": field_map.version, "ok": True})
    with tenant_transaction(application.tenant_id):
        application.state = Application.State.READY_TO_SUBMIT
        application.save(update_fields=["state"])
    request_first_portal_review(application)
    return application
```

- [ ] **Step 7: Write the failing test for the message and worker**

```python
# tests/portals/test_portal_queue.py
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.django_db


def test_the_message_carries_identifiers_only():
    """A queue is a durable store with its own retention policy. Student values
    in a message body would be a second copy of their personal data governed by
    different rules from the first."""
    from apps.portals.schemas import PortalMessage

    message = PortalMessage(
        kind="prepare_application", tenant_id=uuid4(), application_id=uuid4()
    )

    assert set(message.model_dump()) == {
        "schema_version",
        "kind",
        "tenant_id",
        "application_id",
    }
    with pytest.raises(ValidationError):
        PortalMessage(
            kind="prepare_application",
            tenant_id=uuid4(),
            application_id=uuid4(),
            given_name="Ada",
        )


def test_portal_work_goes_to_a_standard_queue():
    """No group id: the portal queue is standard, like every other queue in
    infra/template.yaml. One task consumes it one message at a time."""
    from apps.portals.queue import enqueue_portal_work
    from apps.portals.schemas import PortalMessage

    client = Mock()
    application_id = uuid4()

    enqueue_portal_work(
        PortalMessage(
            kind="prepare_application", tenant_id=uuid4(), application_id=application_id
        ),
        client=client,
        queue_url="q",
    )

    kwargs = client.send_message.call_args.kwargs
    assert "MessageGroupId" not in kwargs
    assert str(application_id) in kwargs["MessageBody"]


def test_a_redelivered_message_does_not_prepare_twice(agency_a, membership_a):
    """SQS redelivers whenever a visibility timeout expires under a slow fill.
    Re-running the whole prepare would type into a real portal a second time."""
    from apps.portals import worker
    from apps.portals.models import Application, PortalForm
    from apps.portals.schemas import PortalMessage
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        form = PortalForm.objects.create(portal_host="apply.example.edu", form_key=f"k-{uuid4()}")
        application = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid4(),
            portal_form=form,
            state=Application.State.READY_TO_SUBMIT,
        )

        def never(_application):  # pragma: no cover -- must not be called
            raise AssertionError("a prepared application must not be prepared again")

        worker.handle_portal_message(
            PortalMessage(
                kind="prepare_application",
                tenant_id=agency_a.id,
                application_id=application.id,
            ),
            session_factory=never,
        )


def test_the_handler_runs_inside_the_message_tenant(agency_a, membership_a):
    """The scope comes from the message. Note what is deliberately NOT asserted:
    that a transaction is open around the handler. app.tenant_id is
    transaction-local, so it is established per write by tenant_transaction
    rather than once around a browser session -- see process_portal_message."""
    from apps.portals import worker
    from apps.portals.schemas import PortalMessage
    from apps.tenancy.context import current_tenant_id

    seen = {}
    message = PortalMessage(
        kind="prepare_application", tenant_id=agency_a.id, application_id=uuid4()
    )

    worker.process_portal_message(message, lambda _: seen.update(tenant=current_tenant_id()))

    assert seen["tenant"] == agency_a.id
```

- [ ] **Step 8: Write the message, queue wrapper, worker and command**

```python
# apps/portals/schemas.py
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PortalMessage(BaseModel):
    """Identifiers only -- never content. The worker reads everything else from
    the database under tenant scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    kind: Literal["prepare_application", "resume_application"]
    tenant_id: UUID
    application_id: UUID
```

```python
# apps/portals/queue.py
"""Portal-side queue policy. The transport itself is apps/queue.py."""

from apps.queue import SQSClient, enqueue

from .schemas import PortalMessage

__all__ = ["SQSClient", "enqueue_portal_work"]


def enqueue_portal_work(
    message: PortalMessage, *, client: SQSClient | None = None, queue_url: str
) -> None:
    """Standard queue, no group id -- like every other queue in this template.

    Ordering needs no queue feature here: there is one portal task
    (PortalDesiredCount maxes at 1) consuming one message at a time, so two
    workers never hold one application's browser profile at once. What guards
    an SQS redelivery is the state check in handle_portal_message, not a
    group id.
    """
    enqueue(message, client=client, queue_url=queue_url)
```

```python
# apps/portals/worker.py
"""Tenant-scoped portal work. Mirrors apps/research/worker.py deliberately."""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

from .models import Application
from .profiles import open_portal_session
from .schemas import PortalMessage
from .services import prepare_application
from .session import PortalSession

logger = logging.getLogger(__name__)


def process_portal_message(
    message: PortalMessage, handler: Callable[[PortalMessage], None]
) -> None:
    """Tenant scope for the message; transactions belong to each write.

    Deliberately NOT one atomic block around the handler, which is where
    apps/research/worker.py puts it. That handler makes one fetch; this one
    drives a browser for minutes, and a transaction held open that long keeps a
    Postgres connection idle-in-transaction and -- worse -- rolls back the
    ApplicationStep rows describing what was actually typed into a real portal
    if anything later fails. Every writer below opens its own short
    tenant_transaction instead.
    """
    with tenant_scope(message.tenant_id):
        handler(message)


def handle_portal_message(
    message: PortalMessage,
    *,
    session_factory: Callable[
        [Application], AbstractContextManager[PortalSession]
    ] = open_portal_session,
) -> None:
    """Open a browser for one application and prepare it.

    ``session_factory`` is injected so every test above this line runs against
    FakePortalSession; production passes the real one.
    """
    with tenant_transaction(message.tenant_id):
        application = Application.objects.get(id=message.application_id)

    # SQS redelivers whenever a visibility timeout expires under a slow fill,
    # so the state is the idempotence guard: an application already prepared or
    # blocked is not typed into a second time. There is no row lock, because
    # holding one for the whole browser session is the long transaction this
    # worker exists to avoid, and there is only one consumer.
    if application.state != Application.State.PREPARING:
        logger.info("PortalSkip application=%s state=%s", application.id, application.state)
        return

    with session_factory(application) as session:
        prepare_application(application, session)
```

```python
# apps/portals/management/commands/run_portal_worker.py
import boto3  # type: ignore[import-untyped]
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from apps.portals.profiles import sweep_expired
from apps.portals.schemas import PortalMessage
from apps.portals.worker import handle_portal_message, process_portal_message
from apps.queue import consume_once


class Command(BaseCommand):
    help = "Consume tenant-scoped portal work from SQS"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true")

    def handle(self, *_args: object, **options: object) -> None:
        client = boto3.client("sqs")

        while True:
            # Before receiving, not after: a worker that dies mid-loop has
            # still swept, and a profile past its TTL should not survive
            # because the queue happened to be busy.
            sweep_expired()
            consume_once(
                client=client,
                queue_url=settings.PORTAL_QUEUE_URL,
                message_type=PortalMessage,
                handler=lambda message: process_portal_message(message, handle_portal_message),
            )
            if options["once"]:
                return
```

Create the two empty `__init__.py` files under `apps/portals/management/` and
`apps/portals/management/commands/`.

- [ ] **Step 9: Run the tests**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals -q`
Expected: PASS.

- [ ] **Step 10: Gates and commit**

```bash
uv run ruff check apps tests
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 add apps/portals tests/portals
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 commit -m "feat(portals): prepare-application spine, portal queue and worker"
```

---

### Task 6: Three more session primitives, and the boundary that keeps them narrow

Recovery, reauthentication and challenge detection all need to ask the page questions plan 1's
protocol cannot ask. Each addition widens what a compromised page could reach, so each is justified
here and pinned by the boundary test.

**Files:**
- Modify: `apps/portals/session.py`, `apps/portals/engine.py`, `tests/portals/fakes.py`
- Test: `tests/portals/test_session_protocol.py` (append), `tests/portals/test_boundary.py` (append)

**Interfaces:**
- Produces on `PortalSession`: `exists(selector: str) -> bool`, `query_attribute(selector: str, attribute: str) -> str | None`, `press_enter() -> None`
- Produces on `FakePortalSession`: an `elements: dict[str, dict[str, str]]` map (selector → attributes) and an `enter_presses: int` counter

- [ ] **Step 1: Write the failing tests**

```python
# tests/portals/test_session_protocol.py -- append
def test_the_fake_answers_the_three_query_primitives():
    from tests.portals.fakes import FakePortalSession

    session = FakePortalSession(elements={".g-recaptcha": {"data-sitekey": "abc"}})

    assert session.exists(".g-recaptcha") is True
    assert session.exists("#nothing") is False
    assert session.query_attribute(".g-recaptcha", "data-sitekey") == "abc"
    assert session.query_attribute(".g-recaptcha", "data-missing") is None
    assert session.query_attribute("#nothing", "data-sitekey") is None

    session.press_enter()
    assert session.enter_presses == 1
```

```python
# tests/portals/test_boundary.py -- append
def test_press_enter_is_unreachable_from_a_stored_field_map():
    """press_enter is the only control-activation primitive in the app, and it
    exists for one caller: the login form, where the password field already has
    focus. A replay path that could reach it could submit an application, which
    is plan 2b's decision and gated on portal terms."""
    import pathlib

    portals = pathlib.Path(__file__).resolve().parents[2] / "apps" / "portals"
    for module in ("fill.py", "learn.py", "recovery.py"):
        source = (portals / module).read_text(encoding="utf-8")
        assert "press_enter" not in source, module

    auth = (portals / "auth.py").read_text(encoding="utf-8")
    assert "press_enter" in auth


def test_no_module_reaches_past_the_session_protocol_to_click():
    """The engine exposes a Stagehand Page, which has click(), type() and
    key_press() on it. Only engine.py may touch that object; everything else
    goes through PortalSession, whose surface is the allowlist."""
    import pathlib

    portals = pathlib.Path(__file__).resolve().parents[2] / "apps" / "portals"
    for path in portals.rglob("*.py"):
        if path.name in {"engine.py"} or "migrations" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for reach in (".page.", "page.click(", "page.key_press("):
            assert reach not in source, f"{path.name}: {reach}"


def test_nothing_in_the_app_can_submit():
    """Plan 2a's hard boundary. Submission is plan 2b and gated on the
    portal-terms blocker in §10 of `phased requirements.md`."""
    import pathlib

    portals = pathlib.Path(__file__).resolve().parents[2] / "apps" / "portals"
    for path in portals.rglob("*.py"):
        # models.py declares the state (plan 2b sets it) and every migration
        # replays the choices list, so both name it without being able to use
        # it. Everything else must not mention it at all.
        if path.name == "models.py" or "migrations" in path.parts:
            continue
        assert "SUBMITTED" not in path.read_text(encoding="utf-8"), path.name
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_session_protocol.py tests/portals/test_boundary.py -q`
Expected: FAIL — `TypeError: FakePortalSession.__init__() got an unexpected keyword argument 'elements'`
and a missing `apps/portals/auth.py`. The auth assertions pass once Task 8 lands; until then, keep
that half of `test_press_enter_is_unreachable_from_a_stored_field_map` commented with the task number,
and uncomment it in Task 8.

- [ ] **Step 3: Extend the protocol**

```python
# apps/portals/session.py -- inside PortalSession, after read_value
    def exists(self, selector: str) -> bool:
        ...

    def query_attribute(self, selector: str, attribute: str) -> str | None:
        ...

    def press_enter(self) -> None:
        ...
```

- [ ] **Step 4: Implement them against real Chrome**

```python
# apps/portals/engine.py -- add `import json` at the top, then inside
# StagehandPortalSession after read_value

    def exists(self, selector: str) -> bool:
        """Is there such an element? Used for challenge markers and login
        markers -- both deterministic DOM questions, never a judgement."""
        self._assert_on_portal()
        return self._loop.run(self.page.locator(selector).count()) > 0

    def query_attribute(self, selector: str, attribute: str) -> str | None:
        """One attribute value, or None.

        Both arguments go through json.dumps: they are ours, not the page's,
        but an expression built by string interpolation is one refactor away
        from taking a page-derived selector, and the quoting is free.
        """
        self._assert_on_portal()
        expression = (
            f"document.querySelector({json.dumps(selector)})"
            f"?.getAttribute({json.dumps(attribute)}) ?? null"
        )
        value = self._loop.run(self.page.evaluate(expression))
        return value if isinstance(value, str) else None

    def press_enter(self) -> None:
        """Submit the login form from the field we just typed into.

        No selector, deliberately. The only caller (auth.reauthenticate) has
        just filled the password field, so focus is already where it must be.
        A press(selector) would be a general-purpose control-activation
        primitive, and a stored FieldMap could then name any control on the
        page -- including a submit button, for every student of every tenant.
        """
        self._assert_on_portal()
        self._loop.run(self.page.key_press("Enter"))
```

`Locator.count`, `Page.evaluate` and `Page.key_press` were confirmed present on `stagehand==4.0.2` by
introspection. They go through `self._loop.run` like every other call: the CDP connection is bound to
the loop that opened it.

- [ ] **Step 5: Extend the fake**

```python
# tests/portals/fakes.py
class FakePortalSession:
    def __init__(
        self,
        observed: list[FieldAction] | None = None,
        elements: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self._observed = observed or []
        #: selector -> attributes. Present keys exist; absent keys do not.
        self.elements = elements or {}
        self.observe_calls = 0
        self.observe_variables: list[dict[str, str] | None] = []
        self.values: dict[str, str] = {}
        self.visited: list[str] = []
        self.enter_presses = 0

    # ... existing methods unchanged ...

    def exists(self, selector: str) -> bool:
        return selector in self.elements or selector in self.values

    def query_attribute(self, selector: str, attribute: str) -> str | None:
        return self.elements.get(selector, {}).get(attribute)

    def press_enter(self) -> None:
        self.enter_presses += 1
```

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals -q`
Expected: PASS.

- [ ] **Step 7: Verify the three primitives against real Chrome**

Add to `tests/portals/test_engine_browser.py`, inside the existing `portal_browser`-marked module:

```python
@pytest.mark.portal_browser
def test_the_query_primitives_answer_against_real_chrome(tmp_path):
    """exists/query_attribute/press_enter are the only three methods whose
    implementation is a guess about the SDK rather than a call plan 1 already
    made. One run against a file:// fixture settles all three."""
    fixture = pathlib.Path(__file__).parent / "fixtures" / "login.html"
    with portal_session(user_data_dir=tmp_path, allowed_host=None) as session:
        session.goto(fixture.as_uri())

        assert session.exists("#password") is True
        assert session.exists("#not-here") is False
        assert session.query_attribute("#password", "type") == "password"
        assert session.query_attribute("#password", "data-absent") is None
        session.press_enter()  # must not raise
```

Write `tests/portals/fixtures/login.html` as a minimal login form: a `#username` text input, a
`#password` password input inside a `<form>`, and nothing else.

Run: `xvfb-run -a --server-args="-screen 0 1280x1024x24" env -u CI POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_engine_browser.py -m portal_browser -q`
Expected: PASS. If `Locator.count` or `Page.evaluate` turns out not to be awaitable in this SDK
version, drop the `self._loop.run(...)` wrapper for that one call — do not change the sandbox, the
model, or the domain policy to make it pass.

- [ ] **Step 8: Gates and commit**

```bash
uv run ruff check apps tests
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 add apps/portals/session.py apps/portals/engine.py tests/portals
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 commit -m "feat(portals): exists, query_attribute and press_enter on the session protocol"
```

---

### Task 7: Scoped re-learn on a selector miss

Spec design points 5 and 6: a changed form leaves evidence and keeps going. Stagehand's `self_heal`
stays off because it re-infers silently; our re-learn writes a new `FieldMap` version that is
diffable against the one it replaced.

**Files:**
- Create: `apps/portals/recovery.py`
- Modify: `apps/portals/models.py` (`RecoveryEvent`), `apps/portals/migrations/0005_recovery_event.py` (generated), `apps/portals/fill.py` (`FillInterrupted`, `skip=`), `apps/portals/services.py` (call through recovery)
- Test: `tests/portals/test_recovery.py`, `tests/portals/test_fill.py` (append)

**Interfaces:**
- Consumes: `apps.portals.learn.learn_form`, `apps.portals.fill.{fill_form, FillInterrupted}`
- Produces:
  - `apps.portals.models.RecoveryEvent` (platform-scoped: `portal_form`, `kind`, `page_url`, `replaced_field_map`, `replacement_field_map`, `detail`, `created_at`)
  - `apps.portals.fill.FillInterrupted(filled: list[str], profile_field: str)` and `fill_form(session, field_map, values, *, skip: Collection[str] = ()) -> list[str]`
  - `apps.portals.fill.already_correct(session, field_map, values) -> set[str]`
  - `apps.portals.recovery.fill_with_recovery(session, application, field_map, values, *, relearn) -> FieldMap`

- [ ] **Step 1: Write the failing test**

```python
# tests/portals/test_recovery.py
"""A form that has drifted must not stop an application, and must not be
invisible afterwards."""

from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope
from tests.portals.fakes import FakePortalSession

pytestmark = pytest.mark.django_db

ENTRIES = [
    {
        "profile_field": "identity.full_name",
        "action": {"selector": "#name", "method": "fill", "arguments": ["%value%"]},
    },
    {
        "profile_field": "personal.city",
        "action": {"selector": "#city", "method": "fill", "arguments": ["%value%"]},
    },
]
MOVED = [
    ENTRIES[0],
    {
        "profile_field": "personal.city",
        "action": {"selector": "#town", "method": "fill", "arguments": ["%value%"]},
    },
]
VALUES = {"identity.full_name": "Ada Byron", "personal.city": "London"}


class DriftingSession(FakePortalSession):
    """Every selector works except #city, which no longer resolves."""

    def act(self, action, variables):
        from apps.portals.engine import ActFailed

        if action.selector == "#city":
            raise ActFailed("#city: no element matched")
        super().act(action, variables)


def _fixtures(agency, student):
    from apps.portals.models import Application, FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key="personal-details",
        form_url="https://apply.example.edu/personal",
        review_required=False,
    )
    field_map = FieldMap.objects.create(portal_form=form, version=1, entries=ENTRIES)
    application = Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )
    return form, field_map, application


def test_a_selector_miss_relearns_and_finishes(agency_a, membership_a):
    from apps.portals.models import FieldMap
    from apps.portals.recovery import fill_with_recovery

    session = DriftingSession()
    with tenant_scope(agency_a.id):
        form, field_map, application = _fixtures(agency_a, membership_a)

        def relearn():
            return FieldMap.objects.create(portal_form=form, version=2, entries=MOVED)

        replacement = fill_with_recovery(
            session, application, field_map, VALUES, relearn=relearn
        )

        assert replacement.version == 2
        # Both fields end up filled, and the one that worked first time was
        # not typed twice.
        assert session.values == {"#name": "Ada Byron", "#town": "London"}


def test_the_recovery_names_both_field_map_versions(agency_a, membership_a):
    """§5.2 wants site changes to create review tasks rather than guesses. The
    spec satisfies that by recording, so the record has to be enough to review
    from: which portal, which page, what was replaced and by what."""
    from apps.portals.models import FieldMap, RecoveryEvent
    from apps.portals.recovery import fill_with_recovery

    with tenant_scope(agency_a.id):
        form, field_map, application = _fixtures(agency_a, membership_a)
        fill_with_recovery(
            DriftingSession(),
            application,
            field_map,
            VALUES,
            relearn=lambda: FieldMap.objects.create(
                portal_form=form, version=2, entries=MOVED
            ),
        )

        event = RecoveryEvent.objects.get()
        assert event.kind == RecoveryEvent.Kind.SELECTOR_MISS
        assert event.portal_form_id == form.id
        assert event.replaced_field_map_id == field_map.id
        assert event.replacement_field_map.version == 2
        assert event.detail["profile_field"] == "personal.city"


def test_recovery_never_escalates_and_never_blocks(agency_a, membership_a):
    """The whole point of design point 5: a changed form is not a human's
    problem until re-learning it has also failed."""
    from apps.concierge.models import Notification
    from apps.portals.models import Application, FieldMap
    from apps.portals.recovery import fill_with_recovery

    with tenant_scope(agency_a.id):
        form, field_map, application = _fixtures(agency_a, membership_a)
        fill_with_recovery(
            DriftingSession(),
            application,
            field_map,
            VALUES,
            relearn=lambda: FieldMap.objects.create(
                portal_form=form, version=2, entries=MOVED
            ),
        )

        application.refresh_from_db()
        assert application.state == Application.State.PREPARING
        assert not Notification.objects.exists()
        assert application.steps.filter(kind="RECOVERY").count() == 1


def test_a_second_miss_after_relearning_gives_up(agency_a, membership_a):
    """One re-learn, not a loop. A form we cannot map twice in a row is a
    portal error, and each attempt costs a full learn pass."""
    from apps.portals.fill import FillInterrupted
    from apps.portals.models import FieldMap
    from apps.portals.recovery import fill_with_recovery

    with tenant_scope(agency_a.id):
        form, field_map, application = _fixtures(agency_a, membership_a)

        with pytest.raises(FillInterrupted):
            fill_with_recovery(
                DriftingSession(),
                application,
                field_map,
                VALUES,
                relearn=lambda: FieldMap.objects.create(
                    portal_form=form, version=2, entries=ENTRIES
                ),
            )


def test_the_relearn_supersedes_the_old_map_for_every_later_student(
    agency_a, membership_a
):
    """The cost thesis: a re-learn is paid once per form version, not once per
    application. If the old map stayed current, the next student would pay for
    the same drift again."""
    from apps.portals.models import FieldMap
    from apps.portals.recovery import fill_with_recovery

    with tenant_scope(agency_a.id):
        form, field_map, application = _fixtures(agency_a, membership_a)
        fill_with_recovery(
            DriftingSession(),
            application,
            field_map,
            VALUES,
            relearn=lambda: FieldMap.current_for(form)
            and FieldMap.objects.create(portal_form=form, version=2, entries=MOVED),
        )

        assert FieldMap.current_for(form).version == 2
```

```python
# tests/portals/test_fill.py -- append
def test_a_failed_act_reports_what_was_already_filled():
    """Recovery has to know where it got to. Without this the choice is
    retyping every field (two values in one input on a portal that appends) or
    skipping fields that were never filled."""
    from apps.portals.engine import ActFailed
    from apps.portals.fill import FillInterrupted, fill_form

    class Failing(FakePortalSession):
        def act(self, action, variables):
            if action.selector == "#city":
                raise ActFailed("boom")
            super().act(action, variables)

    field_map = SimpleNamespace(entries=ENTRIES)  # reuse this module's helper
    with pytest.raises(FillInterrupted) as raised:
        fill_form(Failing(), field_map, VALUES)

    assert raised.value.filled == ["identity.full_name"]
    assert raised.value.profile_field == "personal.city"


def test_skip_leaves_a_field_untouched():
    from apps.portals.fill import fill_form

    session = FakePortalSession()
    fill_form(session, SimpleNamespace(entries=ENTRIES), VALUES, skip={"identity.full_name"})

    assert session.values == {"#city": "London"}


def test_already_correct_is_what_the_page_holds_not_what_we_believe():
    """Used on resume: skip only fields the portal's own draft still holds.
    A portal that lost the draft is then refilled rather than half-skipped."""
    from apps.portals.fill import already_correct

    session = FakePortalSession()
    session.values["#name"] = "Ada Byron"

    assert already_correct(session, SimpleNamespace(entries=ENTRIES), VALUES) == {
        "identity.full_name"
    }
```

Match the existing helpers in `tests/portals/test_fill.py` rather than the `SimpleNamespace` sketch
above if that module already builds a real `FieldMap`; the assertions are what matter.

- [ ] **Step 2: Run to make sure they fail**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_recovery.py tests/portals/test_fill.py -q`
Expected: FAIL — no `apps.portals.recovery`, no `FillInterrupted`.

- [ ] **Step 3: Add the RecoveryEvent model**

```python
# apps/portals/models.py -- after FieldMap
class RecoveryEvent(models.Model):
    """What recovered, on which portal, and between which two field maps.

    Platform-scoped like PortalForm and FieldMap, and for the same reason: it
    names a public form and two of its versions and carries no student data.
    The tenant-side record is the ApplicationStep row written beside it. Keeping
    this table platform-wide is what makes "which portals are drifting" one
    query instead of a loop over every tenant.
    """

    class Kind(models.TextChoices):
        SELECTOR_MISS = "SELECTOR_MISS", "Selector miss, re-learned"
        SESSION_EXPIRED = "SESSION_EXPIRED", "Session expired, reauthenticated"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    portal_form = models.ForeignKey(
        PortalForm, on_delete=models.CASCADE, related_name="recovery_events"
    )
    kind = models.CharField(max_length=30, choices=Kind.choices)
    page_url = models.URLField(max_length=500, blank=True)
    replaced_field_map = models.ForeignKey(
        FieldMap, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    replacement_field_map = models.ForeignKey(
        FieldMap, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    #: The field that missed, never a value. This table is shared across
    #: tenants, so a student value here would be the leak FieldMap is
    #: carefully designed to avoid.
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
```

Run: `POSTGRES_DB=tehsil_plan2a uv run python manage.py makemigrations portals --name recovery_event`
Expected: `0005_recovery_event.py`.

- [ ] **Step 4: Teach fill.py to report where it got to**

```python
# apps/portals/fill.py -- add to the imports, plus a module-level
# `logger = logging.getLogger(__name__)` beside them
import logging
from collections.abc import Collection

from .engine import ActFailed


class FillInterrupted(Exception):
    """An act() failed partway. Carries what was already typed so a recovery
    can finish the form instead of starting it again."""

    def __init__(self, filled: list[str], profile_field: str) -> None:
        super().__init__(f"{profile_field}: fill interrupted after {len(filled)} field(s)")
        self.filled = filled
        self.profile_field = profile_field


def already_correct(
    session: PortalSession, field_map: FieldMap, values: dict[str, str]
) -> set[str]:
    """Fields the rendered page already holds correctly.

    The only fields safe to skip on a resume. A portal that persisted its own
    draft returns most of them; one that did not returns none and the form is
    filled from scratch, which is the behaviour we want in both cases.
    """
    correct = set()
    for entry in field_map.entries:
        action = FieldAction.model_validate(entry["action"])
        try:
            rendered = session.read_value(action.selector)
        except Exception:
            # A selector that no longer resolves raises rather than returning
            # "". That is drift, and drift is the re-learn path's business --
            # this function's only job is to answer "safe to skip?", and the
            # answer for a field it cannot read is no. The log line is not
            # decoration: bandit's B112 fires on a bare except/continue, which
            # is verified against this repo's own bandit config.
            logger.debug("cannot read %s, not skipping it", action.selector)
            continue
        if rendered == values.get(entry["profile_field"]):
            correct.add(entry["profile_field"])
    return correct
```

Then change `fill_form`'s signature and loop:

```python
def fill_form(
    session: PortalSession,
    field_map: FieldMap,
    values: dict[str, str],
    *,
    skip: Collection[str] = (),
) -> list[str]:
    _require_values(field_map, values)
    _require_fillable(field_map)

    filled: list[str] = []
    for entry in field_map.entries:
        profile_field = entry["profile_field"]
        if profile_field in skip:
            continue
        action = FieldAction.model_validate(entry["action"])
        try:
            session.act(action, {"value": values[profile_field]})
        except ActFailed as error:
            # Not swallowed and not retried here: the caller decides whether a
            # re-learn is warranted, and it needs to know how far we got.
            raise FillInterrupted(filled, profile_field) from error
        filled.append(profile_field)
    return filled
```

`fill.py` importing `ActFailed` from `engine.py` pulls stagehand into fill's import graph. If that
proves unwanted (it makes `tests/portals/test_fill.py` depend on the SDK being installed), move
`ActFailed` and `OffDomain` into `session.py` and re-export them from `engine.py` — that is the
smaller change of the two, and `session.py` is already the module both sides import.

- [ ] **Step 5: Write the recovery module**

```python
# apps/portals/recovery.py
"""Autonomous recovery: a changed form is re-learned, not escalated.

Design point 5 of the spec. Section 5.2's "create review tasks rather than
guessing" is satisfied by recording -- a RecoveryEvent naming both field map
versions is reviewable after the fact -- rather than by stopping, because a
portal that renamed an input should not queue every student behind a human.
"""

import logging
from collections.abc import Callable

from apps.tenancy.db import tenant_transaction

from .fill import FillInterrupted, fill_form
from .models import Application, ApplicationStep, FieldMap, RecoveryEvent

logger = logging.getLogger(__name__)


def fill_with_recovery(
    session,  # PortalSession
    application: Application,
    field_map: FieldMap,
    values: dict[str, str],
    *,
    relearn: Callable[[], FieldMap],
    skip: frozenset[str] = frozenset(),
) -> FieldMap:
    """Fill; on a selector miss, re-learn this form once and finish it.

    Returns the field map that actually completed the form -- the caller reads
    back against that one, not against the map it started with.

    One re-learn, never a loop: each attempt is a full learn pass (~$0.76 for a
    36-field form), and a form we cannot map twice in a row is a portal error
    rather than drift.
    """
    try:
        fill_form(session, field_map, values, skip=skip)
        return field_map
    except FillInterrupted as interrupted:
        replacement = relearn()
        with tenant_transaction(application.tenant_id):
            RecoveryEvent.objects.create(
                portal_form=application.portal_form,
                kind=RecoveryEvent.Kind.SELECTOR_MISS,
                page_url=application.portal_form.form_url,
                replaced_field_map=field_map,
                replacement_field_map=replacement,
                detail={"profile_field": interrupted.profile_field},
            )
            ApplicationStep.objects.create(
                tenant=application.tenant,
                application=application,
                sequence=application.next_step_sequence(),
                kind="RECOVERY",
                detail={
                    "kind": RecoveryEvent.Kind.SELECTOR_MISS.value,
                    "from_version": field_map.version,
                    "to_version": replacement.version,
                    "profile_field": interrupted.profile_field,
                },
            )
        logger.info(
            "PortalRecovery kind=SELECTOR_MISS portal=%s from=%s to=%s",
            application.portal_form.portal_host,
            field_map.version,
            replacement.version,
        )
        # Fields already typed are not typed again. If the re-learn happened
        # because the page navigated rather than because one input moved, the
        # skipped fields are stale -- and prepare_application's read-back over
        # the replacement map is what catches that.
        fill_form(session, replacement, values, skip=set(interrupted.filled) | set(skip))
        return replacement
```

- [ ] **Step 6: Route the spine through it**

In `apps/portals/services.py`, replace the bare `fill_form` call with:

```python
    from .fill import already_correct
    from .learn import RateLimited, UnmappedField, learn_form
    from .recovery import fill_with_recovery

    def relearn() -> FieldMap:
        """A learn pass scoped to this form, with the student's own values as
        the forbidden list -- a re-learn is the widest path for a page value to
        end up in a shared FieldMap, so it is checked hardest."""
        return learn_form(
            session,
            application.portal_form,
            profile_fields=[entry["profile_field"] for entry in field_map.entries],
            tenant_id=application.tenant_id,
            forbidden_values=list(values.values()),
        )

    try:
        field_map = fill_with_recovery(
            session,
            application,
            field_map,
            values,
            relearn=relearn,
            skip=frozenset(already_correct(session, field_map, values)),
        )
        filled = [entry["profile_field"] for entry in field_map.entries]
    except MissingFact as error:
        escalate(application, Trigger.MISSING_FACT, detail=str(error))
        return application
    except (FillInterrupted, RateLimited) as error:
        escalate(application, Trigger.PORTAL_ERROR, detail=str(error))
        return application
```

`RateLimited` is `apps.portals.learn.RateLimited` — a tenant that has exhausted its learn budget is a
portal error to a human, not a silent stall. `UnmappedField` from the same module is left to
propagate: it means the re-learn could not map a field at all, which the `FillInterrupted` handler
above does not cover, so add it to the same `except` tuple.

- [ ] **Step 7: Run the tests**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals -q`
Expected: PASS.

- [ ] **Step 8: Gates and commit**

```bash
uv run ruff check apps tests
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps
POSTGRES_DB=tehsil_plan2a uv run python manage.py makemigrations --check --dry-run
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 add apps/portals tests/portals
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 commit -m "feat(portals): scoped re-learn with a recorded RecoveryEvent"
```

---

### Task 8: Session expiry and reauthentication

§5.2: "If a portal session expires, first attempt normal reauthentication with platform-managed
credentials... requesting student action only for personal authentication such as applicant-specific
MFA."

**Files:**
- Create: `apps/portals/auth.py`
- Modify: `apps/portals/models.py` (`PortalForm.login_marker`, `PortalForm.mfa_marker`), `apps/portals/migrations/0006_login_markers.py` (generated), `apps/portals/services.py`, `apps/audit/deletion.py`
- Test: `tests/portals/test_auth.py`, `tests/audit/test_deletion_purges_credentials.py`

**Binding project rule (`CLAUDE.md`, "Application automation (Phase 3)"):** portal credentials never
live in the database; they are keyed **per student-portal** in Secrets Manager, the IAM grant is
per-secret-prefix and belongs to the portal role, and **erasure ships with storage** — a student's
secrets are destroyed on the same path that deletes their documents. The last clause is why this task
touches `apps/audit/deletion.py`: shipping the storage without the erasure is the failure that rule
exists to prevent.

**Interfaces:**
- Consumes: `apps.portals.fill.fill_form`, `apps.portals.escalation.{Trigger, escalate}`, `apps.portals.models.RecoveryEvent`
- Produces:
  - `PortalCredentials(NamedTuple)` with `username: str`, `password: str`
  - `CredentialProvider` protocol: `credentials_for(*, tenant_id: UUID, student_id: UUID, portal_host: str) -> PortalCredentials | None`
  - `secret_id(tenant_id, student_id, portal_host) -> str`
  - `delete_student_portal_credentials(*, tenant_id, student_id, client=None) -> int`
  - `SecretsManagerCredentials` (the production implementation)
  - `LOGIN_FORM_KEY = "login"`, `LOGIN_USERNAME_FIELD = "portal.username"`, `LOGIN_PASSWORD_FIELD = "portal.password"`
  - `session_expired(session, portal_form) -> bool`
  - `reauthenticate(session, application, *, provider) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/portals/test_auth.py
"""Reauthentication is a recovery, not an escalation -- except for the one
thing that reaches the student's own device."""

from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope
from tests.portals.fakes import FakePortalSession

pytestmark = pytest.mark.django_db

LOGIN_ENTRIES = [
    {
        "profile_field": "portal.username",
        "action": {"selector": "#user", "method": "fill", "arguments": ["%value%"]},
    },
    {
        "profile_field": "portal.password",
        "action": {"selector": "#pass", "method": "fill", "arguments": ["%value%"]},
    },
]


def _portal(agency, student, **form_kwargs):
    from apps.portals.models import Application, FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key="personal-details",
        form_url="https://apply.example.edu/personal",
        review_required=False,
        **form_kwargs,
    )
    login = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key="login", form_url="https://apply.example.edu/login"
    )
    FieldMap.objects.create(portal_form=login, version=1, entries=LOGIN_ENTRIES)
    application = Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )
    return form, application


class StaticProvider:
    def __init__(self, credentials=None):
        self._credentials = credentials
        self.asked = []

    def credentials_for(self, *, tenant_id, student_id, portal_host):
        self.asked.append((tenant_id, student_id, portal_host))
        return self._credentials


def test_the_login_marker_is_how_expiry_is_detected(agency_a, membership_a):
    """Deterministic, like challenge detection: a known element on the page,
    never an inference from how the page 'feels'."""
    from apps.portals.auth import session_expired

    with tenant_scope(agency_a.id):
        form, _ = _portal(agency_a, membership_a, login_marker="#login-form")

        assert session_expired(FakePortalSession(elements={"#login-form": {}}), form) is True
        assert session_expired(FakePortalSession(), form) is False


def test_a_portal_with_no_marker_is_never_treated_as_expired(agency_a, membership_a):
    """An unconfigured marker must not mean "always expired" -- that would
    reauthenticate on every single step."""
    from apps.portals.auth import session_expired

    with tenant_scope(agency_a.id):
        form, _ = _portal(agency_a, membership_a, login_marker="")

        assert session_expired(FakePortalSession(elements={"#login-form": {}}), form) is False


def test_reauthentication_types_the_credential_and_submits(agency_a, membership_a):
    from apps.portals.auth import PortalCredentials, reauthenticate

    session = FakePortalSession(elements={"#login-form": {}})
    with tenant_scope(agency_a.id):
        _, application = _portal(agency_a, membership_a, login_marker="#login-form")

        # The marker disappears once the form is submitted.
        def press_enter():
            session.elements.pop("#login-form", None)
            session.enter_presses += 1

        session.press_enter = press_enter

        assert (
            reauthenticate(
                session,
                application,
                provider=StaticProvider(PortalCredentials("ada", "s3cret")),
            )
            is True
        )
        assert session.values == {"#user": "ada", "#pass": "s3cret"}
        assert session.enter_presses == 1


def test_reauthentication_is_recorded_as_a_recovery_without_the_credential(
    agency_a, membership_a
):
    """§5.5 wants the action recorded. The password is not part of the action."""
    from apps.portals.auth import PortalCredentials, reauthenticate
    from apps.portals.models import RecoveryEvent

    session = FakePortalSession(elements={"#login-form": {}})
    with tenant_scope(agency_a.id):
        _, application = _portal(agency_a, membership_a, login_marker="#login-form")
        session.press_enter = lambda: session.elements.pop("#login-form", None)

        reauthenticate(
            session, application, provider=StaticProvider(PortalCredentials("ada", "s3cret"))
        )

        event = RecoveryEvent.objects.get()
        assert event.kind == RecoveryEvent.Kind.SESSION_EXPIRED
        serialised = f"{event.detail}{list(application.steps.values_list('detail', flat=True))}"
        assert "s3cret" not in serialised
        assert "ada" not in serialised


def test_an_mfa_prompt_escalates_to_the_student(agency_a, membership_a):
    """The credential reaches the student's own device. No amount of platform
    credential management resolves that, which is why it is in §5.4's table."""
    from apps.portals.auth import PortalCredentials, reauthenticate
    from apps.portals.models import Application

    session = FakePortalSession(elements={"#login-form": {}, "#mfa": {}})
    with tenant_scope(agency_a.id):
        _, application = _portal(
            agency_a, membership_a, login_marker="#login-form", mfa_marker="#mfa"
        )
        session.press_enter = lambda: session.elements.pop("#login-form", None)

        assert (
            reauthenticate(
                session,
                application,
                provider=StaticProvider(PortalCredentials("ada", "s3cret")),
            )
            is False
        )

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_PERSONAL_ACTION


def test_a_missing_platform_credential_reaches_the_consultant_desk(agency_a, membership_a):
    """Not a crash and not a student task: §5.2 routes reauthentication to a
    consultant, and only personal authentication to the student."""
    from apps.portals.auth import reauthenticate
    from apps.portals.models import Application

    with tenant_scope(agency_a.id):
        _, application = _portal(agency_a, membership_a, login_marker="#login-form")

        assert (
            reauthenticate(
                FakePortalSession(elements={"#login-form": {}}),
                application,
                provider=StaticProvider(None),
            )
            is False
        )

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_PORTAL_ERROR


def test_a_login_that_does_not_take_is_a_portal_error(agency_a, membership_a):
    """The marker is still there after submitting: wrong password, locked
    account, changed login page. All three need a human, none need the student."""
    from apps.portals.auth import PortalCredentials, reauthenticate
    from apps.portals.models import Application

    with tenant_scope(agency_a.id):
        _, application = _portal(agency_a, membership_a, login_marker="#login-form")

        assert (
            reauthenticate(
                FakePortalSession(elements={"#login-form": {}}),
                application,
                provider=StaticProvider(PortalCredentials("ada", "wrong")),
            )
            is False
        )

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_PORTAL_ERROR
```

- [ ] **Step 2: Run to make sure they fail**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_auth.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.portals.auth'`.

- [ ] **Step 3: Add the marker fields**

```python
# apps/portals/models.py -- inside PortalForm, after review_required
    #: A selector present only when the portal is showing its login page.
    #: Empty means "this portal's expiry signal has not been configured", which
    #: is treated as never-expired -- the opposite default would reauthenticate
    #: on every step of every portal.
    login_marker = models.CharField(max_length=200, blank=True)
    #: A selector present only when the portal is asking for a second factor.
    mfa_marker = models.CharField(max_length=200, blank=True)
```

Run: `POSTGRES_DB=tehsil_plan2a uv run python manage.py makemigrations portals --name login_markers`

- [ ] **Step 4: Write the auth module**

```python
# apps/portals/auth.py
"""Platform-managed portal credentials, and the one case that is not.

§5.2 routes an expired session to reauthentication first, a consultant second,
and the student only for authentication that reaches their own device.

Credentials are never stored in Postgres. The provider resolves them at use
time from AWS Secrets Manager, so a database dump is not a set of live portal
logins and the credential's whole lifecycle (rotation, access audit, deletion)
belongs to the secret store rather than to this app.
"""

import json
import logging
from typing import NamedTuple, Protocol
from uuid import UUID

import boto3  # type: ignore[import-untyped]

from .escalation import Trigger, escalate
from .fill import fill_form
from .models import Application, FieldMap, PortalForm, RecoveryEvent
from .session import PortalSession

logger = logging.getLogger(__name__)

LOGIN_FORM_KEY = "login"
LOGIN_USERNAME_FIELD = "portal.username"
LOGIN_PASSWORD_FIELD = "portal.password"


class PortalCredentials(NamedTuple):
    username: str
    password: str


class CredentialProvider(Protocol):
    def credentials_for(
        self, *, tenant_id: UUID, portal_host: str
    ) -> PortalCredentials | None: ...


def secret_id(tenant_id: UUID, student_id: UUID, portal_host: str) -> str:
    """One secret per student per portal.

    Per *student*, not per tenant: a portal account belongs to the applicant,
    so a tenant-wide credential would log every student into one person's
    account. The path shape is also what makes erasure possible without
    ListSecrets -- see delete_student_portal_credentials.
    """
    return f"tehsil/portal/{tenant_id}/{student_id}/{portal_host}"


class SecretsManagerCredentials:
    """Resolved at use time, never stored in Postgres (CLAUDE.md, Phase 3 rules).

    A missing or unreadable secret returns None rather than raising: an
    unconfigured portal is a consultant task, not a worker crash that
    redelivers the message until the DLQ catches it.
    """

    def __init__(self, client: object | None = None) -> None:
        self._client = client or boto3.client("secretsmanager")

    def credentials_for(
        self, *, tenant_id: UUID, student_id: UUID, portal_host: str
    ) -> PortalCredentials | None:
        try:
            response = self._client.get_secret_value(  # type: ignore[attr-defined]
                SecretId=secret_id(tenant_id, student_id, portal_host)
            )
            payload = json.loads(response["SecretString"])
            return PortalCredentials(payload["username"], payload["password"])
        except Exception:
            # Deliberately broad and deliberately not logging the exception:
            # botocore puts the SecretId in the message, and a ResourceNotFound
            # for a name we constructed is not information a log reader needs.
            # Nothing here may reach a log or an exception message with a
            # credential in it.
            logger.warning("no portal credential for %s", portal_host)
            return None


def delete_student_portal_credentials(
    *, tenant_id: UUID, student_id: UUID, client: object | None = None
) -> int:
    """Destroy every portal credential belonging to one student. Returns the count.

    Called from apps/audit/deletion.py on the EXECUTED transition, beside
    delete_student_documents: GDPR erasure that leaves live portal logins behind
    is the failure CLAUDE.md's Phase 3 rules name explicitly.

    The portal list comes from PortalForm rather than from ListSecrets, so the
    IAM grant stays scoped to the secret prefix -- ListSecrets cannot be
    resource-scoped, and widening a deletion path to account-wide enumeration
    to save a query is the wrong trade.

    # ponytail: iterates known portals. A credential stored for a portal that
    # has no PortalForm row would be missed; nothing can create one today,
    # because a portal with no form is a portal nothing can apply to.
    """
    secrets = client or boto3.client("secretsmanager")
    deleted = 0
    hosts = PortalForm.objects.values_list("portal_host", flat=True).distinct()
    for portal_host in hosts:
        try:
            secrets.delete_secret(  # type: ignore[attr-defined]
                SecretId=secret_id(tenant_id, student_id, portal_host),
                ForceDeleteWithoutRecovery=True,
            )
            deleted += 1
        except Exception:
            # Already absent is the common case and is success. The log line
            # also keeps bandit's B112 (try/except/continue) quiet, and a
            # portal host is not a credential.
            logger.debug("no credential to delete for %s", portal_host)
            continue
    return deleted


def session_expired(session: PortalSession, portal_form: PortalForm) -> bool:
    return bool(portal_form.login_marker) and session.exists(portal_form.login_marker)


def reauthenticate(
    session: PortalSession, application: Application, *, provider: CredentialProvider
) -> bool:
    """Log back in. Returns True when the session is usable again.

    Every False path has already escalated, so the caller stops rather than
    deciding what a failure means.
    """
    portal_form = application.portal_form
    credentials = provider.credentials_for(
        tenant_id=application.tenant_id,
        student_id=application.student_id,
        portal_host=portal_form.portal_host,
    )
    if credentials is None:
        escalate(
            application,
            Trigger.PORTAL_ERROR,
            detail=f"no platform credential configured for {portal_form.portal_host}",
        )
        return False

    login_form = PortalForm.objects.filter(
        portal_host=portal_form.portal_host, form_key=LOGIN_FORM_KEY
    ).first()
    login_map = FieldMap.current_for(login_form) if login_form else None
    if login_map is None:
        escalate(
            application,
            Trigger.PORTAL_ERROR,
            detail=f"login form for {portal_form.portal_host} has not been learned",
        )
        return False

    session.goto(login_form.form_url)
    # The credential travels the same path a student value does -- as a
    # Stagehand variable at act() time -- so it is never written to a FieldMap
    # and never reaches a model prompt.
    fill_form(
        session,
        login_map,
        {
            LOGIN_USERNAME_FIELD: credentials.username,
            LOGIN_PASSWORD_FIELD: credentials.password,
        },
    )
    session.press_enter()

    if portal_form.mfa_marker and session.exists(portal_form.mfa_marker):
        escalate(
            application,
            Trigger.APPLICANT_MFA,
            detail=f"{portal_form.portal_host} is asking for a second factor",
        )
        return False

    if session.exists(portal_form.login_marker):
        # Wrong password, locked account, or a login page that changed shape.
        # All three need a human and none of them need the student.
        escalate(
            application,
            Trigger.PORTAL_ERROR,
            detail=f"reauthentication to {portal_form.portal_host} did not take",
        )
        return False

    RecoveryEvent.objects.create(
        portal_form=portal_form,
        kind=RecoveryEvent.Kind.SESSION_EXPIRED,
        page_url=login_form.form_url,
        detail={"portal_host": portal_form.portal_host},
    )
    logger.info("PortalRecovery kind=SESSION_EXPIRED portal=%s", portal_form.portal_host)
    return True
```

- [ ] **Step 5: Destroy credentials on the erasure path**

```python
# tests/audit/test_deletion_purges_credentials.py
"""CLAUDE.md's Phase 3 rule: erasure ships with storage. This is the test that
makes "we will remember to delete the secrets" into something enforced."""

from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def test_executing_a_deletion_destroys_the_students_portal_credentials(
    agency_a, membership_a, monkeypatch
):
    from apps.audit import deletion
    from apps.portals.models import PortalForm
    from apps.tenancy.context import tenant_scope

    PortalForm.objects.create(portal_host="apply.example.edu", form_key=f"k-{uuid4()}")
    destroyed = []
    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kwargs: 0)
    monkeypatch.setattr(
        deletion,
        "delete_student_portal_credentials",
        lambda **kwargs: destroyed.append(kwargs) or 1,
    )

    with tenant_scope(agency_a.id):
        request = _approved_deletion_request(agency_a, membership_a)  # this module's helper
        deletion.advance_deletion(request, "EXECUTED")

    assert destroyed == [{"tenant_id": agency_a.id, "student_id": membership_a.id}]


def test_a_credential_deletion_failure_leaves_the_request_unexecuted(
    agency_a, membership_a, monkeypatch
):
    """Same rule the document purge already follows: a storage failure must not
    record an erasure that did not happen."""
    from apps.audit import deletion
    from apps.tenancy.context import tenant_scope

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kwargs: 0)
    monkeypatch.setattr(
        deletion,
        "delete_student_portal_credentials",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("secretsmanager down")),
    )

    with tenant_scope(agency_a.id):
        request = _approved_deletion_request(agency_a, membership_a)
        with pytest.raises(RuntimeError):
            deletion.advance_deletion(request, "EXECUTED")
        request.refresh_from_db()
        assert request.state == "APPROVED"
```

Copy `_approved_deletion_request` from `tests/audit/test_deletion_purges_documents.py`, which already
builds a `DeletionRequest` with a `RetentionPolicy` in place.

```python
# apps/audit/deletion.py -- add the import and one call
from apps.portals.auth import delete_student_portal_credentials

        if target_state == "EXECUTED":
            # Before the state write: a storage failure must leave the request
            # in APPROVED rather than recording an erasure that did not happen.
            delete_student_documents(tenant_id=request.tenant_id, student_id=request.student_id)
            # Same path, same rule. A student's portal logins outliving their
            # erasure is the failure CLAUDE.md's Phase 3 rules name by hand.
            delete_student_portal_credentials(
                tenant_id=request.tenant_id, student_id=request.student_id
            )
```

Add `secretsmanager:DeleteSecret` on `arn:aws:secretsmanager:...:secret:tehsil/portal/*` to
`WorkerTaskRole` in Task 14 — that is the role `test_only_worker_task_role_may_erase_tenant_objects`
already pins as the one that erases tenant data. `advance_deletion` has no in-app caller yet, so if a
view calls it later, the grant follows the caller.

- [ ] **Step 6: Wire it into the spine**

In `apps/portals/services.py`, immediately after `session.goto(...)`:

```python
    if session_expired(session, application.portal_form):
        if not reauthenticate(session, application, provider=provider):
            return application  # already escalated
        # Back on the form, and back on the same profile: the fill below skips
        # whatever the portal's own draft still holds (already_correct), so no
        # completed step is repeated.
        session.goto(application.portal_form.form_url)
```

`prepare_application` gains one keyword-only parameter, defaulted so every existing test keeps
working: `provider: CredentialProvider | None = None`, resolved to `SecretsManagerCredentials()`
lazily inside the function — constructing a boto3 client at import time would make every portal test
need AWS credentials.

- [ ] **Step 7: Uncomment the auth half of the boundary test from Task 6**

- [ ] **Step 8: Run the tests and gates, then commit**

```bash
POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals tests/audit -q
uv run ruff check apps tests
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 add apps/portals apps/audit/deletion.py tests/portals tests/audit
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 commit -m "feat(portals): reauthenticate an expired session, and erase credentials with the student"
```

Expected: PASS on all four. Bandit will flag the broad `except Exception` in
`SecretsManagerCredentials` only if it is bare (`B110 try_except_pass`); it logs, so it is not — if it
is flagged anyway, that is a real finding to narrow to `botocore.exceptions.ClientError` plus
`KeyError`, not to silence.

---

### Task 9: Deterministic challenge detection

"Detection is explicit and deterministic: known challenge containers and scripts are matched by DOM
query, plus a stall heuristic. Detection never guesses."

**Files:**
- Create: `apps/portals/challenge.py`
- Test: `tests/portals/test_challenge.py`

**Interfaces:**
- Consumes: `PortalSession.exists`, `PortalSession.query_attribute`
- Produces: `Challenge` dataclass (`kind: str`, `site_key: str`, `page_url: str`, `response_selector: str`), `MARKERS`, `STALL_THRESHOLD`, `UNKNOWN_KIND`, `detect_challenge(session, *, page_url, act_failures=0) -> Challenge | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/portals/test_challenge.py
"""Detection is a DOM query, never a judgement. Both directions matter: a
missed challenge stalls an application, and a false positive sends an ordinary
form to a consultant."""

from tests.portals.fakes import FakePortalSession

PAGE = "https://apply.example.edu/personal"


def test_each_known_challenge_is_matched_with_its_site_key():
    from apps.portals.challenge import detect_challenge

    for selector, kind in (
        (".g-recaptcha", "recaptcha"),
        (".h-captcha", "hcaptcha"),
        (".cf-turnstile", "turnstile"),
    ):
        session = FakePortalSession(elements={selector: {"data-sitekey": "site-key-1"}})

        challenge = detect_challenge(session, page_url=PAGE)

        assert challenge is not None
        assert challenge.kind == kind
        assert challenge.site_key == "site-key-1"
        assert challenge.page_url == PAGE


def test_an_ordinary_form_is_not_a_challenge():
    from apps.portals.challenge import detect_challenge

    session = FakePortalSession(elements={"#name": {}, "form": {}, ".g-recaptcha-help": {}})

    assert detect_challenge(session, page_url=PAGE) is None


def test_a_marker_without_a_site_key_is_still_a_challenge():
    """An invisible reCAPTCHA renders its site key elsewhere. Reporting no
    challenge because we could not read the key would strand the application
    at the one moment a resolver is needed."""
    from apps.portals.challenge import detect_challenge

    session = FakePortalSession(elements={".g-recaptcha": {}})

    challenge = detect_challenge(session, page_url=PAGE)
    assert challenge is not None
    assert challenge.site_key == ""


def test_repeated_failures_with_no_marker_are_an_unknown_challenge():
    """The stall heuristic. It has no site key by construction, so it can only
    ever reach a consultant -- a resolution service has nothing to be given."""
    from apps.portals.challenge import STALL_THRESHOLD, UNKNOWN_KIND, detect_challenge

    session = FakePortalSession()

    assert detect_challenge(session, page_url=PAGE, act_failures=STALL_THRESHOLD - 1) is None
    stalled = detect_challenge(session, page_url=PAGE, act_failures=STALL_THRESHOLD)
    assert stalled is not None
    assert stalled.kind == UNKNOWN_KIND
    assert stalled.site_key == ""
```

- [ ] **Step 2: Run to make sure it fails**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_challenge.py -q`
Expected: FAIL — no `apps.portals.challenge`.

- [ ] **Step 3: Write the module**

```python
# apps/portals/challenge.py
"""Is this page asking a human to prove they are one?

Deterministic by design. Every entry in MARKERS is a container class the
provider's own script renders, and the site key is read from the attribute that
script reads. Nothing here infers a challenge from page text, timing alone, or
a model's opinion, because a false positive sends an ordinary application to a
consultant and a false negative strands it.
"""

from dataclasses import dataclass

from .session import PortalSession

UNKNOWN_KIND = "unknown"

#: (kind, container selector, site-key attribute, response field selector).
#: The response selector is where a solved token is written back -- always a
#: form field the provider's own script fills, never a control.
MARKERS: tuple[tuple[str, str, str, str], ...] = (
    ("recaptcha", ".g-recaptcha", "data-sitekey", "textarea[name='g-recaptcha-response']"),
    ("hcaptcha", ".h-captcha", "data-sitekey", "textarea[name='h-captcha-response']"),
    ("turnstile", ".cf-turnstile", "data-sitekey", "input[name='cf-turnstile-response']"),
)

#: Consecutive failed actions on a page that previously worked. Three, not one:
#: a single miss is ordinary drift and belongs to the re-learn path.
STALL_THRESHOLD = 3


@dataclass(frozen=True)
class Challenge:
    kind: str
    site_key: str
    page_url: str
    response_selector: str


def detect_challenge(
    session: PortalSession, *, page_url: str, act_failures: int = 0
) -> Challenge | None:
    for kind, container, site_key_attribute, response_selector in MARKERS:
        if not session.exists(container):
            continue
        return Challenge(
            kind=kind,
            # An invisible widget renders its key elsewhere. No key is a
            # resolvable state (the consultant path needs none), so it is an
            # empty string rather than a reason to report nothing.
            site_key=session.query_attribute(container, site_key_attribute) or "",
            page_url=page_url,
            response_selector=response_selector,
        )
    if act_failures >= STALL_THRESHOLD:
        # No marker and nothing working. This cannot be handed to a resolution
        # service -- there is no site key and no kind to send -- so it exists
        # purely to reach a consultant with the session preserved.
        return Challenge(
            kind=UNKNOWN_KIND, site_key="", page_url=page_url, response_selector=""
        )
    return None
```

- [ ] **Step 4: Run the tests, gates, commit**

```bash
POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals -q
uv run ruff check apps tests && uv run mypy apps config && uv run bandit -c pyproject.toml -r apps
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 add apps/portals/challenge.py tests/portals/test_challenge.py
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 commit -m "feat(portals): deterministic challenge detection with a stall heuristic"
```

---

### Task 10: `ServiceResolver`, one provider adapter, and the per-portal gate

**A conflict to resolve before writing this, not during.** The spec says the resolution service is
"enabled by default" and that the per-portal approval record "does not block execution". `CLAUDE.md`'s
Phase 3 rules say the opposite: a resolution service "may be integrated only per-approved-portal,
after the portal-terms and legal gates, with consultant fallback." `CLAUDE.md` is the binding project
instruction, so this task implements the narrower reading — `PortalForm.resolution_approved`, default
**False**, checked before the service is called — and the consultant path handles every unapproved
portal, which is the MVP behaviour §5.1 already describes. The wider reading remains one field flip
per portal away. **If the intent was genuinely the spec's, say so and drop the field: it is one
boolean and one branch.** Either way §10's portal-terms blocker still gates running any of this
against a real portal.

**Files:**
- Create: `apps/portals/resolve.py`
- Modify: `config/settings/base.py` (three settings), `apps/portals/models.py` (`PortalForm.resolution_approved`), `apps/portals/migrations/0007_resolution_approval.py` (generated)
- Test: `tests/portals/test_resolve_service.py`

**Interfaces:**
- Consumes: `apps.portals.challenge.{Challenge, UNKNOWN_KIND}`, `apps.portals.session.{FieldAction, PortalSession}`
- Produces:
  - `ProviderAdapter` protocol: `solve(*, kind: str, site_key: str, page_url: str) -> str | None`
  - `HttpCaptchaProvider(endpoint: str, api_key: str)` — the one concrete adapter
  - `configured_adapter() -> ProviderAdapter | None`
  - `CaptchaResolver` protocol: `solve(challenge: Challenge, *, application: Application) -> str | None`
  - `ServiceResolver(adapter=None, *, attempts=None, sleep=time.sleep)`
  - `apply_token(session, challenge, token) -> None`
  - `PortalForm.resolution_approved: bool` (default False)

- [ ] **Step 1: Write the failing test**

```python
# tests/portals/test_resolve_service.py
"""The service tier: bounded, credential-optional, and unable to do anything
except write a token into the field the provider's own script writes to."""

from uuid import uuid4

import pytest

from apps.portals.challenge import UNKNOWN_KIND, Challenge
from apps.tenancy.context import tenant_scope
from tests.portals.fakes import FakePortalSession

pytestmark = pytest.mark.django_db

CHALLENGE = Challenge(
    kind="recaptcha",
    site_key="site-key-1",
    page_url="https://apply.example.edu/personal",
    response_selector="textarea[name='g-recaptcha-response']",
)


def _application(agency, student):
    from apps.portals.models import Application, PortalForm

    # form_key varies: PortalForm has a unique (portal_host, form_key)
    # constraint and these helpers are called more than once per test.
    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key=f"personal-details-{uuid4()}"
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_a_solved_challenge_returns_the_token(agency_a, membership_a):
    from apps.portals.resolve import ServiceResolver

    class Adapter:
        def solve(self, *, kind, site_key, page_url):
            assert (kind, site_key) == ("recaptcha", "site-key-1")
            return "token-1"

    with tenant_scope(agency_a.id):
        resolver = ServiceResolver(Adapter())
        assert resolver.solve(CHALLENGE, application=_application(agency_a, membership_a)) == "token-1"


def test_attempts_are_bounded_and_backed_off(agency_a, membership_a):
    """A resolution service that is down must not become an unbounded spend."""
    from apps.portals.resolve import ServiceResolver

    calls = []
    slept = []

    class Failing:
        def solve(self, *, kind, site_key, page_url):
            calls.append(1)
            return None

    with tenant_scope(agency_a.id):
        resolver = ServiceResolver(Failing(), attempts=3, sleep=slept.append)
        assert resolver.solve(CHALLENGE, application=_application(agency_a, membership_a)) is None

    assert len(calls) == 3
    assert slept == [1.0, 2.0]  # no sleep after the last attempt


def test_an_unapproved_portal_never_reaches_the_service(agency_a, membership_a):
    """CLAUDE.md: a resolution service may be integrated only per-approved
    portal, after the portal-terms and legal gates. The default is False, so a
    portal nobody has cleared falls through to a consultant."""
    from apps.portals.resolve import ServiceResolver

    class Adapter:
        def solve(self, *, kind, site_key, page_url):  # pragma: no cover -- must not run
            raise AssertionError("an unapproved portal must not reach the provider")

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        assert application.portal_form.resolution_approved is False

        assert ServiceResolver(Adapter()).solve(CHALLENGE, application=application) is None


def test_no_configured_provider_is_a_fallback_not_a_crash(agency_a, membership_a):
    """§ Challenge resolution: 'an absent or rejected credential is a
    ConsultantResolver fallback, not a crash'."""
    from apps.portals.resolve import ServiceResolver

    with tenant_scope(agency_a.id):
        assert ServiceResolver(None).solve(
            CHALLENGE, application=_application(agency_a, membership_a)
        ) is None


def test_an_unknown_challenge_is_never_sent_to_the_service(agency_a, membership_a):
    """The stall heuristic produces no kind and no site key. Sending that to a
    paid API is spend with no possible result."""
    from apps.portals.resolve import ServiceResolver

    class Adapter:
        def solve(self, *, kind, site_key, page_url):  # pragma: no cover -- must not run
            raise AssertionError("unknown challenges never reach the provider")

    unknown = Challenge(kind=UNKNOWN_KIND, site_key="", page_url="p", response_selector="")
    with tenant_scope(agency_a.id):
        assert ServiceResolver(Adapter()).solve(
            unknown, application=_application(agency_a, membership_a)
        ) is None


def test_a_provider_that_raises_is_a_failed_attempt_not_a_crash():
    from apps.portals.resolve import ServiceResolver

    class Exploding:
        def solve(self, *, kind, site_key, page_url):
            raise RuntimeError("provider 503")

    assert ServiceResolver(Exploding(), attempts=2, sleep=lambda _: None)._attempt(CHALLENGE) is None


def test_the_token_is_written_through_the_ordinary_fill_path():
    """apply_token builds a FieldAction that is_fillable accepts, so a token
    goes in exactly the way a student value does -- no new primitive, and
    nothing that could activate a control."""
    from apps.portals.resolve import apply_token

    session = FakePortalSession()
    apply_token(session, CHALLENGE, "token-1")

    assert session.values == {"textarea[name='g-recaptcha-response']": "token-1"}


def test_configured_adapter_is_none_without_a_credential(settings, monkeypatch):
    from apps.portals.resolve import configured_adapter

    settings.PORTAL_CAPTCHA_ENDPOINT = "https://provider.example/solve"
    monkeypatch.delenv("PORTAL_CAPTCHA_API_KEY", raising=False)

    assert configured_adapter() is None
```

- [ ] **Step 2: Run to make sure it fails**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_resolve_service.py -q`
Expected: FAIL — no `apps.portals.resolve`.

- [ ] **Step 3: The per-portal approval field**

```python
# apps/portals/models.py -- inside PortalForm, after mfa_marker
    #: Whether automated challenge resolution is approved for THIS portal.
    #: Default False and deliberately not a global setting: CLAUDE.md's Phase 3
    #: rules make the resolution service a per-portal decision taken after the
    #: portal-terms and legal gates, and the record of that decision is an
    #: audit artifact under §5.5. An unapproved portal gets the consultant
    #: path, which is the MVP behaviour §5.1 describes.
    resolution_approved = models.BooleanField(default=False)
```

Run: `POSTGRES_DB=tehsil_plan2a uv run python manage.py makemigrations portals --name resolution_approval`

- [ ] **Step 4: Settings**

```python
# config/settings/base.py -- after PORTAL_PROFILE_TTL_HOURS
#: The resolution provider is named in configuration, not in code. Empty means
#: no service tier, which is a supported deployment: every challenge then goes
#: to a consultant. The credential is read from the environment at use time and
#: is deliberately not a setting -- it must not appear in a settings dump.
PORTAL_CAPTCHA_ENDPOINT = os.getenv("PORTAL_CAPTCHA_ENDPOINT", "")
PORTAL_CAPTCHA_ATTEMPTS = int(os.getenv("PORTAL_CAPTCHA_ATTEMPTS", "3"))
PORTAL_CAPTCHA_TIMEOUT_SECONDS = float(os.getenv("PORTAL_CAPTCHA_TIMEOUT_SECONDS", "120"))
```

- [ ] **Step 5: Write the resolver**

```python
# apps/portals/resolve.py
"""Challenge resolution: the service first, a consultant second.

§2 makes CAPTCHA delegable application work and §5.1 requires both paths. The
provider is named in configuration rather than in code so that swapping one is
a deployment change; the adapter interface is three arguments wide on purpose,
because anything wider starts to encode one provider's API.

Shipping the service enabled by default is a deliberate operator decision
recorded in the spec, and §10's portal-terms blocker still applies before any
of this runs against a real portal.
"""

import json
import logging
import os
import time
from collections.abc import Callable
from typing import Protocol

import urllib3
from django.conf import settings

from .challenge import UNKNOWN_KIND, Challenge
from .models import Application
from .session import FieldAction, PortalSession, VALUE_PLACEHOLDER

logger = logging.getLogger(__name__)


class ProviderAdapter(Protocol):
    def solve(self, *, kind: str, site_key: str, page_url: str) -> str | None: ...


class CaptchaResolver(Protocol):
    def solve(self, challenge: Challenge, *, application: Application) -> str | None: ...


class HttpCaptchaProvider:
    """One concrete adapter, shaped like every hosted resolution API: post the
    challenge, get a token back. A provider whose API differs gets its own
    class implementing ProviderAdapter -- not a branch in this one."""

    def __init__(self, endpoint: str, api_key: str) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._http = urllib3.PoolManager()

    def solve(self, *, kind: str, site_key: str, page_url: str) -> str | None:
        response = self._http.request(
            "POST",
            self._endpoint,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            body=json.dumps({"type": kind, "site_key": site_key, "url": page_url}),
            timeout=urllib3.Timeout(total=settings.PORTAL_CAPTCHA_TIMEOUT_SECONDS),
            retries=False,
        )
        if response.status != 200:
            return None
        token = json.loads(response.data).get("token")
        return token if isinstance(token, str) and token else None


def configured_adapter() -> ProviderAdapter | None:
    """None whenever the deployment has no service tier. Both halves are
    required: an endpoint with no credential is a misconfiguration, and
    treating it as configured would spend every attempt on a 401."""
    endpoint = settings.PORTAL_CAPTCHA_ENDPOINT
    api_key = os.environ.get("PORTAL_CAPTCHA_API_KEY", "")
    if not endpoint or not api_key:
        return None
    return HttpCaptchaProvider(endpoint, api_key)


class ServiceResolver:
    """Bounded attempts against the configured provider. Never raises."""

    def __init__(
        self,
        adapter: ProviderAdapter | None = None,
        *,
        attempts: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._adapter = adapter
        self._attempts = attempts or settings.PORTAL_CAPTCHA_ATTEMPTS
        self._sleep = sleep

    def _attempt(self, challenge: Challenge) -> str | None:
        assert self._adapter is not None
        try:
            return self._adapter.solve(
                kind=challenge.kind, site_key=challenge.site_key, page_url=challenge.page_url
            )
        except Exception:
            # A provider outage is a failed attempt, not a failed application:
            # the consultant path is right there.
            logger.warning("captcha provider attempt failed", exc_info=True)
            return None

    def solve(self, challenge: Challenge, *, application: Application) -> str | None:
        # Three ways to not call the provider, and all three are ordinary
        # states rather than errors: no service tier configured, a portal
        # nobody has approved for automated resolution (CLAUDE.md's Phase 3
        # rule, default False), and a stall-heuristic challenge that carries
        # no site key to send.
        if (
            self._adapter is None
            or not application.portal_form.resolution_approved
            or challenge.kind == UNKNOWN_KIND
        ):
            return None
        for attempt in range(self._attempts):
            token = self._attempt(challenge)
            if token:
                return token
            if attempt < self._attempts - 1:
                self._sleep(2.0**attempt)
        logger.info(
            "PortalChallengeUnsolved portal=%s kind=%s",
            application.portal_form.portal_host,
            challenge.kind,
        )
        return None


def apply_token(session: PortalSession, challenge: Challenge, token: str) -> None:
    """Write the token into the provider's own response field.

    Through FieldAction and act(), not a new primitive: the response field is a
    textarea or hidden input, so filling it is exactly the operation the replay
    allowlist already permits.
    """
    session.act(
        FieldAction(
            selector=challenge.response_selector,
            method="fill",
            arguments=[VALUE_PLACEHOLDER],
        ),
        {"value": token},
    )
```

- [ ] **Step 6: Run tests, gates, commit**

```bash
POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals -q
uv run ruff check apps config tests && uv run mypy apps config && uv run bandit -c pyproject.toml -r apps config
POSTGRES_DB=tehsil_plan2a uv run python manage.py makemigrations --check --dry-run
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 add apps/portals config/settings/base.py tests/portals/test_resolve_service.py
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 commit -m "feat(portals): bounded challenge resolution behind one provider adapter"
```

Bandit will look at the broad `except Exception` in `_attempt` (B110 only fires on `pass`; this logs)
and at `urllib3` usage. Both are the same shapes `apps/research/egress.py` already ships. If
`pip-audit` flags nothing new, no dependency was added — `urllib3` is already pinned.

---

### Task 11: `ConsultantResolver`, and resuming when the consultant is done

"Preserves the session, creates a scoped `RoadmapItem(PORTAL_EXCEPTION)`, detects completion and
resumes at the paused step without repeating completed work."

**Files:**
- Create: `apps/portals/dispatch.py`
- Modify: `apps/portals/resolve.py` (append `ConsultantResolver`, `resolve_challenge`), `apps/portals/services.py` (detect and resolve), `apps/portals/management/commands/run_portal_worker.py` (poll for completions)
- Test: `tests/portals/test_resolve_consultant.py`, `tests/portals/test_dispatch.py`

**Interfaces:**
- Produces:
  - `ConsultantResolver.solve(challenge, *, application) -> None` (always None — it hands over to a human)
  - `resolve_challenge(session, challenge, *, application, service=None, consultant=None) -> bool`
  - `apps.portals.dispatch.resume_completed_exceptions(*, client=None, queue_url=None) -> int`

- [ ] **Step 1: Write the failing tests**

```python
# tests/portals/test_resolve_consultant.py
from uuid import uuid4

import pytest

from apps.portals.challenge import Challenge
from apps.tenancy.context import tenant_scope
from tests.portals.fakes import FakePortalSession

pytestmark = pytest.mark.django_db

CHALLENGE = Challenge(
    kind="hcaptcha",
    site_key="k",
    page_url="https://apply.example.edu/personal",
    response_selector="textarea[name='h-captcha-response']",
)


def _application(agency, student):
    from apps.portals.models import Application, PortalForm

    # form_key varies: PortalForm has a unique (portal_host, form_key)
    # constraint and these helpers are called more than once per test.
    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key=f"personal-details-{uuid4()}"
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_the_service_is_tried_before_the_consultant(agency_a, membership_a):
    from apps.concierge.models import RoadmapItem
    from apps.portals.resolve import resolve_challenge

    class Solving:
        def solve(self, challenge, *, application):
            return "token-1"

    session = FakePortalSession()
    with tenant_scope(agency_a.id):
        # ServiceResolver is stubbed here, so the per-portal approval flag is
        # not in play -- that gate has its own test in test_resolve_service.py.
        assert resolve_challenge(
            session, CHALLENGE, application=_application(agency_a, membership_a), service=Solving()
        ) is True

    assert session.values[CHALLENGE.response_selector] == "token-1"
    assert not RoadmapItem.objects.exists()


def test_a_failed_service_falls_back_to_a_scoped_consultant_task(agency_a, membership_a):
    from apps.concierge.models import RoadmapItem
    from apps.portals.models import Application
    from apps.portals.resolve import ConsultantResolver, resolve_challenge

    class Failing:
        def solve(self, challenge, *, application):
            return None

    session = FakePortalSession()
    session.values["#name"] = "Ada Byron"
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        assert resolve_challenge(
            session,
            CHALLENGE,
            application=application,
            service=Failing(),
            consultant=ConsultantResolver(),
        ) is False

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_CHALLENGE
        assert application.exception_item.stage == RoadmapItem.Stage.PORTAL_EXCEPTION
        # Completed form state is preserved: nothing cleared the page and
        # nothing reset the application's steps.
        assert session.values["#name"] == "Ada Byron"
```

```python
# tests/portals/test_dispatch.py
"""Completion detection without a hook inside the concierge app.

Mirrors apps/research/dispatch.py::recover_undispatched_runs: the worker loop
polls for work a human has finished, so marking a roadmap item done stays an
ordinary concierge action with no automation reaching into it.
"""

from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _blocked_application(agency, student, *, item_state):
    from apps.concierge.models import RoadmapItem
    from apps.portals.models import Application, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key=f"personal-details-{uuid4()}"
    )
    item = RoadmapItem.objects.create(
        tenant=agency,
        student=student,
        stage=RoadmapItem.Stage.PORTAL_EXCEPTION,
        owner=student,
        deadline=timezone.now() + timedelta(days=1),
        state=item_state,
    )
    return Application.objects.create(
        tenant=agency,
        student=student,
        program_id=uuid4(),
        portal_form=form,
        state=Application.State.BLOCKED_CHALLENGE,
        exception_item=item,
    )


def test_a_finished_consultant_task_enqueues_a_resume(agency_a, membership_a):
    from apps.concierge.models import RoadmapItem
    from apps.portals.dispatch import resume_completed_exceptions
    from apps.portals.models import Application

    client = Mock()
    with tenant_scope(agency_a.id):
        application = _blocked_application(
            agency_a, membership_a, item_state=RoadmapItem.State.DONE
        )

    assert resume_completed_exceptions(client=client, queue_url="q") == 1

    body = client.send_message.call_args.kwargs["MessageBody"]
    assert str(application.id) in body
    assert "resume_application" in body
    with tenant_scope(agency_a.id):
        application.refresh_from_db()
        assert application.state == Application.State.PREPARING
        assert application.exception_item_id is None


def test_an_open_consultant_task_is_left_alone(agency_a, membership_a):
    from apps.concierge.models import RoadmapItem
    from apps.portals.dispatch import resume_completed_exceptions

    client = Mock()
    with tenant_scope(agency_a.id):
        _blocked_application(agency_a, membership_a, item_state=RoadmapItem.State.PENDING)

    assert resume_completed_exceptions(client=client, queue_url="q") == 0
    client.send_message.assert_not_called()
```

- [ ] **Step 2: Run to make sure they fail**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_resolve_consultant.py tests/portals/test_dispatch.py -q`
Expected: FAIL — no `ConsultantResolver`, no `apps.portals.dispatch`.

- [ ] **Step 3: Append the consultant path to `resolve.py`**

```python
# apps/portals/resolve.py -- append
from .escalation import Trigger, escalate


class ConsultantResolver:
    """Hands the preserved session to a human. Always returns None.

    It cannot return a token by construction, which is the point: the fallback
    is a person doing the challenge in the session we kept open, not a second
    automated guess. The session survives because the browser profile is
    per-application and outlives the worker's message
    (apps/portals/profiles.py).
    """

    def solve(self, challenge: Challenge, *, application: Application) -> str | None:
        escalate(
            application,
            Trigger.UNSOLVED_CHALLENGE,
            detail=f"{challenge.kind} on {challenge.page_url}",
        )
        return None


def resolve_challenge(
    session: PortalSession,
    challenge: Challenge,
    *,
    application: Application,
    service: CaptchaResolver | None = None,
    consultant: CaptchaResolver | None = None,
) -> bool:
    """True when the page is clear to continue.

    Order is fixed by §5.1: the service is tried first and only its exhaustion
    reaches a consultant. Nothing here clears the form -- the fields already
    filled stay filled, which is what "without losing completed form state"
    means in practice.
    """
    service = service or ServiceResolver(configured_adapter())
    token = service.solve(challenge, application=application)
    if token:
        apply_token(session, challenge, token)
        return True
    (consultant or ConsultantResolver()).solve(challenge, application=application)
    return False
```

- [ ] **Step 4: Write the resume dispatcher**

```python
# apps/portals/dispatch.py
"""Resume applications whose human has finished.

Polled from the worker loop rather than triggered from the concierge app: a
callback there would put portal automation inside the module that
tests/concierge/test_roadmap.py pins as human-recorded facts only. This is the
same shape as apps/research/dispatch.py::recover_undispatched_runs.
"""

import logging

from django.conf import settings
from django.db import transaction

from apps.concierge.models import RoadmapItem
from apps.queue import SQSClient
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Agency

from .models import Application
from .queue import enqueue_portal_work
from .schemas import PortalMessage

logger = logging.getLogger(__name__)

#: The states a human closing their task can release. A missing fact and a
#: personal action release the same way a challenge does -- the fact was added
#: or the action was performed, and the item being DONE is the signal.
RESUMABLE = (
    Application.State.BLOCKED_CHALLENGE,
    Application.State.BLOCKED_MISSING_FACT,
    Application.State.BLOCKED_PERSONAL_ACTION,
    Application.State.BLOCKED_PORTAL_ERROR,
)


def resume_completed_exceptions(
    *, client: SQSClient | None = None, queue_url: str | None = None
) -> int:
    resumed = 0
    for tenant_id in Agency.objects.values_list("id", flat=True):
        with transaction.atomic(), tenant_scope(tenant_id):
            set_local_tenant(tenant_id)
            applications = list(
                Application.objects.select_for_update().filter(
                    state__in=RESUMABLE, exception_item__state=RoadmapItem.State.DONE
                )
            )
            for application in applications:
                application.state = Application.State.PREPARING
                application.exception_item = None
                application.save(update_fields=["state", "exception_item"])
                enqueue_portal_work(
                    PortalMessage(
                        kind="resume_application",
                        tenant_id=tenant_id,
                        application_id=application.id,
                    ),
                    client=client,
                    queue_url=queue_url or settings.PORTAL_QUEUE_URL,
                )
                resumed += 1
                logger.info("PortalResume application=%s", application.id)
    return resumed
```

Add `resume_completed_exceptions()` to the worker loop in `run_portal_worker.py`, beside
`sweep_expired()`, passing `client=client`.

- [ ] **Step 5: Detect and resolve inside the spine**

In `apps/portals/services.py`, after the `goto`/reauth block and before the fill:

```python
    challenge = detect_challenge(session, page_url=application.portal_form.form_url)
    if challenge and not resolve_challenge(session, challenge, application=application):
        return application  # ConsultantResolver has already escalated
```

Resume needs no separate code path: `prepare_application` skips whatever the page already holds
(`already_correct`), so an application resumed after a consultant solved its CAPTCHA continues from
where it stopped and repeats no completed step.

- [ ] **Step 6: Prove the pause and resume against a real browser**

`CLAUDE.md` names this the untested, load-bearing assumption of the whole phase: "that a browser
session can be paused, handed to a consultant and resumed without repeating completed steps". Two
`portal_session` opens on one `user_data_dir` is the cheap version of that proof.

```python
# tests/portals/test_engine_browser.py -- append
@pytest.mark.portal_browser
def test_a_profile_survives_the_session_that_created_it(tmp_path):
    """The pause/resume premise, minimally. A cookie set in the first session
    must be readable in the second: that is what lets a consultant solve a
    challenge in a preserved session and the worker pick it back up.

    On EC2 capacity with one task the directory outlives the message, which is
    the deployment shape Task 14 chooses. It does NOT survive the instance --
    and that is what apps/portals/auth.py::reauthenticate is for.
    """
    fixture = pathlib.Path(__file__).parent / "fixtures" / "login.html"

    with portal_session(user_data_dir=tmp_path, allowed_host=None) as session:
        session.goto(fixture.as_uri())
        session._loop.run(session.page.evaluate("document.cookie = 'resumed=yes; path=/'"))

    with portal_session(user_data_dir=tmp_path, allowed_host=None) as session:
        session.goto(fixture.as_uri())
        assert "resumed=yes" in str(session._loop.run(session.page.evaluate("document.cookie")))
```

Run: `xvfb-run -a --server-args="-screen 0 1280x1024x24" env -u CI POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_engine_browser.py -m portal_browser -q`
Expected: PASS. A `file://` page may refuse `document.cookie`; if it does, serve the fixture from a
`http.server` on localhost inside the test rather than weakening the assertion. **If the profile does
not survive, stop and report it** — the resume design in this task rests on it, and the fallback
(re-fill everything after reauthentication) is a different plan.

- [ ] **Step 7: Run tests, gates, commit**

```bash
POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals tests/concierge -q
uv run ruff check apps tests && uv run mypy apps config && uv run bandit -c pyproject.toml -r apps
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 add apps/portals tests/portals
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 commit -m "feat(portals): consultant fallback and poll-based resume"
```

`tests/concierge` is in the run deliberately: this task's design claim is that nothing in the
concierge app changed.

---

### Task 12: Per-portal intervention rate

"Intervention rate is recorded per portal and reported, so an expensive portal is visible and can be
improved or dropped on evidence." §5.4's 90/10/2 targets are targets, not measurements — this is what
turns them into measurements.

**Files:**
- Create: `apps/portals/reporting.py`, `apps/portals/management/commands/report_portal_interventions.py`
- Test: `tests/portals/test_reporting.py`

**Interfaces:**
- Produces: `PortalIntervention` dataclass (`portal_host`, `applications`, `escalations`, `recoveries`, `intervention_rate`), `intervention_rates() -> list[PortalIntervention]`

- [ ] **Step 1: Write the failing test**

```python
# tests/portals/test_reporting.py
from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope
from tests.portals.fakes import FakePortalSession  # noqa: F401 -- keeps the import shape uniform

pytestmark = pytest.mark.django_db


def test_the_rate_counts_escalated_applications_per_portal(
    agency_a, membership_a, counselor_membership
):
    from apps.portals.escalation import Trigger, escalate
    from apps.portals.models import Application, PortalForm
    from apps.portals.reporting import intervention_rates

    with tenant_scope(agency_a.id):
        form = PortalForm.objects.create(portal_host="slow.example.edu", form_key="f")
        applications = [
            Application.objects.create(
                tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
            )
            for _ in range(4)
        ]
        escalate(applications[0], Trigger.PORTAL_ERROR, detail="x")

    rates = {row.portal_host: row for row in intervention_rates()}

    assert rates["slow.example.edu"].applications == 4
    assert rates["slow.example.edu"].escalations == 1
    assert rates["slow.example.edu"].intervention_rate == 0.25


def test_recoveries_are_reported_but_are_not_interventions(agency_a, membership_a):
    """A recovery is the system working. Counting it as an intervention would
    make the autonomous path look like the expensive one."""
    from apps.portals.models import Application, PortalForm, RecoveryEvent
    from apps.portals.reporting import intervention_rates

    with tenant_scope(agency_a.id):
        form = PortalForm.objects.create(portal_host="drifty.example.edu", form_key="f")
        Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )
        RecoveryEvent.objects.create(
            portal_form=form, kind=RecoveryEvent.Kind.SELECTOR_MISS, detail={}
        )

    row = {r.portal_host: r for r in intervention_rates()}["drifty.example.edu"]
    assert (row.recoveries, row.escalations, row.intervention_rate) == (1, 0, 0.0)


def test_a_portal_with_no_applications_reports_a_zero_rate_not_a_crash(agency_a):
    from apps.portals.models import PortalForm
    from apps.portals.reporting import intervention_rates

    PortalForm.objects.create(portal_host="unused.example.edu", form_key="f")

    assert {r.portal_host: r.intervention_rate for r in intervention_rates()}[
        "unused.example.edu"
    ] == 0.0
```

- [ ] **Step 2: Run to make sure it fails**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_reporting.py -q`
Expected: FAIL — no `apps.portals.reporting`.

- [ ] **Step 3: Write the report**

```python
# apps/portals/reporting.py
"""Which portals cost a human, per portal, across every tenant.

Applications are tenant-scoped and RLS keeps them that way, so the count is
gathered by looping tenants under tenant_scope rather than by one unscoped
query -- the same shape as apps/research/dispatch.py. PortalForm and
RecoveryEvent are platform-scoped and are read once, outside the loop.
"""

from dataclasses import dataclass

from django.db.models import Count

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Agency

from .models import Application, ApplicationStep, PortalForm, RecoveryEvent


@dataclass(frozen=True)
class PortalIntervention:
    portal_host: str
    applications: int
    escalations: int
    recoveries: int

    @property
    def intervention_rate(self) -> float:
        """Escalations per application. Recoveries are excluded deliberately:
        §5.4's target is about work reaching a human, and a recovery is the
        system not needing one."""
        return round(self.escalations / self.applications, 4) if self.applications else 0.0


def intervention_rates() -> list[PortalIntervention]:
    """Call this outside any tenant scope.

    tenant_scope refuses to *switch* an active scope (TenantContextConflict),
    so a caller already inside one tenant would raise on the second. The
    management command runs unscoped; a per-tenant dashboard view wants a
    single-tenant query rather than this function.
    """
    hosts = {
        form.id: form.portal_host for form in PortalForm.objects.only("id", "portal_host")
    }
    applications: dict[str, int] = {host: 0 for host in hosts.values()}
    escalations: dict[str, int] = {host: 0 for host in hosts.values()}

    for tenant_id in Agency.objects.values_list("id", flat=True):
        with tenant_scope(tenant_id):
            set_local_tenant(tenant_id)
            for row in Application.objects.values("portal_form_id").annotate(n=Count("id")):
                applications[hosts[row["portal_form_id"]]] += row["n"]
            for row in (
                ApplicationStep.objects.filter(kind="ESCALATION")
                .values("application__portal_form_id")
                .annotate(n=Count("id", distinct=True))
            ):
                escalations[hosts[row["application__portal_form_id"]]] += row["n"]

    recoveries: dict[str, int] = {host: 0 for host in hosts.values()}
    for row in RecoveryEvent.objects.values("portal_form_id").annotate(n=Count("id")):
        recoveries[hosts[row["portal_form_id"]]] += row["n"]

    return [
        PortalIntervention(
            portal_host=host,
            applications=applications[host],
            escalations=escalations[host],
            recoveries=recoveries[host],
        )
        for host in sorted(applications)
    ]
```

```python
# apps/portals/management/commands/report_portal_interventions.py
from django.core.management.base import BaseCommand

from apps.portals.reporting import intervention_rates


class Command(BaseCommand):
    help = "Print the per-portal intervention rate (§5.4's 90/10/2 targets, measured)"

    def handle(self, *_args: object, **_options: object) -> None:
        self.stdout.write(f"{'portal':40} {'apps':>6} {'escal':>6} {'recov':>6} {'rate':>7}")
        for row in intervention_rates():
            self.stdout.write(
                f"{row.portal_host:40} {row.applications:6} {row.escalations:6} "
                f"{row.recoveries:6} {row.intervention_rate:7.2%}"
            )
```

- [ ] **Step 4: Run tests, gates, commit**

```bash
POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals -q
uv run ruff check apps tests && uv run mypy apps config && uv run bandit -c pyproject.toml -r apps
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 add apps/portals tests/portals
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 commit -m "feat(portals): per-portal intervention rate report"
```

---

### Task 13: A portal image, and a CI job that proves the sandbox survives it

Plan 1 pinned Chrome to a hardcoded path under `$HOME`. A container installs it somewhere else and
runs as a non-root user, so resolution has to move. The CI half is the interesting part: the sandbox
check cannot run in a GitHub Actions job directly — stagehand strips the renderer sandbox whenever
`CI` is set, and `scripts/validate_portal_sandbox.py` correctly refuses to measure the wrong thing —
but it *can* run inside the container, because `docker run` does not pass the runner's environment in.

**Files:**
- Modify: `apps/portals/engine.py` (`chrome_binary()`), `scripts/validate_portal_sandbox.py`, `Dockerfile`, `.github/workflows/ci.yml`
- Test: `tests/portals/test_boundary.py` (append)

**Interfaces:**
- Produces: `apps.portals.engine.chrome_binary() -> Path` (replaces the `CHROME_BINARY` constant)

- [ ] **Step 1: Write the failing test**

```python
# tests/portals/test_boundary.py -- append
def test_chrome_is_resolved_from_the_playwright_cache_wherever_it_is(monkeypatch, tmp_path):
    """The container installs Chrome under PLAYWRIGHT_BROWSERS_PATH and runs as
    a non-root user, so a path under $HOME resolves to a directory that does not
    exist there. Same binary, different root."""
    from apps.portals.engine import chrome_binary

    for revision in ("chromium-1140", "chromium-1234"):
        binary = tmp_path / revision / "chrome-linux64" / "chrome"
        binary.parent.mkdir(parents=True)
        binary.touch()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))

    # Highest revision, numerically -- "chromium-999" sorts above
    # "chromium-1234" as a string, which would pin an older Chrome silently.
    assert chrome_binary().parts[-3] == "chromium-1234"


def test_a_missing_chrome_is_a_loud_failure(monkeypatch, tmp_path):
    """Not a fallback to system Chrome: that combination has no working
    configuration (Extensions.loadUnpacked is unavailable on it)."""
    import pytest

    from apps.portals.engine import chrome_binary

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    with pytest.raises(RuntimeError, match="Chrome for Testing"):
        chrome_binary()
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals/test_boundary.py -q`
Expected: FAIL — `ImportError: cannot import name 'chrome_binary'`.

- [ ] **Step 3: Replace the constant with a resolver**

```python
# apps/portals/engine.py -- replace CHROME_BINARY
def chrome_binary() -> Path:
    """Chrome for Testing, wherever playwright put it.

    PLAYWRIGHT_BROWSERS_PATH moves the whole cache; the container sets it so
    one copy serves a non-root user, exactly as the `browser` stage already
    does. The revision directory is whatever the pinned playwright installed,
    so it is discovered rather than hardcoded -- but numerically, because
    sorted() puts "chromium-999" above "chromium-1234" and would silently pin
    an older Chrome.

    System Chrome is never a fallback: it fails with
    `Extensions.loadUnpacked: Method not available` and has no working
    configuration, so an absent cache is an error rather than a downgrade.
    """
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or Path.home() / ".cache/ms-playwright")
    candidates = sorted(
        root.glob("chromium-*/chrome-linux64/chrome"),
        key=lambda path: int(path.parts[-3].removeprefix("chromium-") or 0),
    )
    if not candidates:
        raise RuntimeError(f"Chrome for Testing is not installed under {root}")
    return candidates[-1]
```

Update the two references in `portal_session` (`executable_path=str(chrome_binary())`) and the three
in `scripts/validate_portal_sandbox.py`: import `chrome_binary` instead of the constant, resolve it
once at the top of `main()` and pass the resulting path into `seccomp_modes()` and `probe()` — the
script compares `/proc/<pid>/exe` against it, so it must resolve the same way the launcher did, and
resolving it at import time would raise before the "SKIP: Chrome is not installed" branch can run.

A revision directory that is not `chromium-<int>` raises `ValueError` inside the key function. If
patchright's directory naming differs, filter to `path.parts[-3].removeprefix("chromium-").isdigit()`
before sorting rather than swallowing the error.

- [ ] **Step 4: Add the portal image stage**

```dockerfile
# Dockerfile -- append after the browser stage
FROM runtime AS portal
# Unlike `browser`, this stage DOES carry credentials: it holds the database
# password, the LLM key and a profile of live portal session cookies, because a
# fill has to read a FieldMap and write an audit trail while it types. What
# makes that acceptable is the renderer sandbox -- see apps/portals/engine.py,
# which refuses to open a session when it would be stripped. That is also why
# the portal service runs on EC2 capacity and not Fargate: Fargate refuses the
# unprivileged user namespaces the sandbox needs (measured, us-east-1,
# 2026-08-26), so Chrome would fail to launch there rather than run unprotected.
#
# playwright, not patchright: apps/portals/engine.py needs Chrome for Testing,
# which is the revision playwright installs. The `browser` stage's patchright
# copy is a different revision serving a different tier.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# xvfb because extensions do not load in headless_shell, so Chrome runs headful
# and headful Chrome needs a display. dbus-x11 and the font package keep the
# rendered page close to what a portal expects to be filled in.
RUN apt-get update && apt-get install --no-install-recommends -y \
    xvfb fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN playwright install --with-deps chromium && chmod -R a+rX /ms-playwright
ENV PORTAL_PROFILE_ROOT=/var/lib/tehsil/portal-profiles
RUN mkdir -p /var/lib/tehsil/portal-profiles && chown app /var/lib/tehsil/portal-profiles
USER app
CMD ["xvfb-run", "-a", "--server-args=-screen 0 1280x1024x24", \
     "python", "manage.py", "run_portal_worker"]
```

- [ ] **Step 5: Build it and run the sandbox validation inside it**

Run:
```bash
docker build --target portal -t tehsil-portal:local .
docker run --rm tehsil-portal:local \
    xvfb-run -a --server-args="-screen 0 1280x1024x24" \
    python scripts/validate_portal_sandbox.py
```
Expected: `OK: headful and sandboxed on a fake display`.

If it prints `FAIL: no child is seccomp-filtered`, Chrome's namespace sandbox could not start inside
Docker's default seccomp profile. **Do not add `--no-sandbox`.** In order of preference: run the
container with `--security-opt seccomp=unconfined` (which does not stop Chrome applying its own
seccomp-bpf filter to renderers — that is what the script measures), then `--cap-add=SYS_ADMIN`, and
if neither works, drop the CI job and document that this check runs on the deployment host only. The
one outcome that is not acceptable is a green check that measured an unsandboxed browser.

- [ ] **Step 6: Add the CI job**

```yaml
# .github/workflows/ci.yml -- new top-level job
  portal-sandbox:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - run: docker build --target portal -t tehsil-portal:ci .
      # The runner sets CI=true, and stagehand appends --no-sandbox whenever it
      # sees that (browser.py:589,682) -- which is the opposite of what this
      # job measures. docker run does not pass the runner's environment into
      # the container, so the check runs against a real sandbox. Never add
      # `-e CI` here: the script would SKIP and the job would go green having
      # measured nothing.
      - run: |
          docker run --rm --security-opt seccomp=unconfined tehsil-portal:ci \
            xvfb-run -a --server-args="-screen 0 1280x1024x24" \
            python scripts/validate_portal_sandbox.py
```

- [ ] **Step 7: Run the tests, gates and commit**

```bash
POSTGRES_DB=tehsil_plan2a uv run pytest tests/portals -q
uv run ruff check apps scripts tests && uv run mypy apps config && uv run bandit -c pyproject.toml -r apps
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 add apps/portals/engine.py scripts/validate_portal_sandbox.py Dockerfile .github/workflows/ci.yml tests/portals/test_boundary.py
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 commit -m "build(portals): portal image with Xvfb, and a CI job that proves the sandbox"
```

---

### Task 14: The production task definition

The portal worker is the one service that holds credentials *and* renders hostile pages. Two
consequences shape everything in this task: it runs on EC2 capacity (Fargate cannot give Chrome the
user namespaces its sandbox needs), and its security group must be admitted to the database, which
means deliberately editing a test that currently pins that list to two members.

**Files:**
- Modify: `infra/template.yaml`, `tests/infra/test_template.py`, `infra/parameters/production.json`, `infra/parameters/test.json`
- Test: `tests/infra/test_template.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/infra/test_template.py -- append
def test_the_portal_service_runs_on_ec2_not_fargate(template: Template) -> None:
    """Fargate refuses unprivileged user namespaces (measured, us-east-1,
    2026-08-26), so Chrome's renderer sandbox cannot engage there. The sandbox
    is the only boundary between a hostile portal page and a process holding
    the database password, the LLM key and live student cookies, so the launch
    type follows the sandbox rather than the other way around."""
    task = template.resource("PortalTaskDefinition")["Properties"]
    service = template.resource("PortalService")["Properties"]

    assert task["RequiresCompatibilities"] == ["EC2"]
    assert "FARGATE" not in task["RequiresCompatibilities"]
    assert service["LaunchType"] == "EC2"


def test_the_portal_volume_is_encrypted(template: Template) -> None:
    """The browser profile holding live portal session cookies lives on this
    volume, and volume-level encryption is what "encrypted at rest" means for a
    directory Chrome holds open (apps/portals/profiles.py)."""
    mappings = template.resource("PortalLaunchTemplate")["Properties"]["LaunchTemplateData"][
        "BlockDeviceMappings"
    ]

    assert all(mapping["Ebs"]["Encrypted"] is True for mapping in mappings)


def test_the_portal_service_ships_stopped(template: Template) -> None:
    """Portal terms (§10) gate running this against a real portal at all, and
    an idle EC2 instance is not free."""
    assert template.parameter("PortalDesiredCount")["Default"] == 0
    assert template.resource("PortalService")["Properties"]["DesiredCount"] == {
        "Ref": "PortalDesiredCount"
    }
    assert template.resource("PortalAutoScalingGroup")["Properties"]["MinSize"] == "0"


def test_the_database_admits_web_worker_and_portal_only(template: Template) -> None:
    """Replaces the two-member assertion. The portal task is admitted because it
    reads field maps and writes the audit trail while it types; the browser task
    is still absent, and that absence is still the second lock behind its absent
    credential."""
    assert _admitted_groups(template.resource("DatabaseSecurityGroup")["Properties"]) == [
        {"Ref": "WebSecurityGroup"},
        {"Ref": "WorkerSecurityGroup"},
        {"Ref": "PortalSecurityGroup"},
    ]


def test_the_portal_task_role_consumes_only_the_portal_queue(template: Template) -> None:
    actions = _policy_actions(template.resource("PortalTaskRole"))

    assert any("sqs:ReceiveMessage" in action for action in actions)
    # _policy_actions exists in this module; there is no _policy_resources, so
    # the resource side is read directly rather than adding a helper for one use.
    statements = [
        statement
        for policy in template.resource("PortalTaskRole")["Properties"]["Policies"]
        for statement in policy["PolicyDocument"]["Statement"]
    ]
    resources = [statement["Resource"] for statement in statements]
    assert {"Fn::GetAtt": ["PortalQueue", "Arn"]} in resources
    assert {"Fn::GetAtt": ["ResearchQueue", "Arn"]} not in resources
    assert {"Fn::GetAtt": ["EuropassQueue", "Arn"]} not in resources


def test_the_portal_escalation_filter_matches_what_escalate_actually_logs(
    template: Template,
) -> None:
    """Same failure this codebase has already had once: a metric filter whose
    pattern never matches is an alarm that never fires."""
    pattern = template.resource("PortalEscalationFilter")["Properties"]["FilterPattern"]

    assert "PortalEscalation" in pattern
    source = (
        Path(__file__).resolve().parents[2] / "apps" / "portals" / "escalation.py"
    ).read_text(encoding="utf-8")
    assert "PortalEscalation" in source
```

Extend the existing `task_definition_id` parametrization with `"PortalTaskDefinition"`, and add
`"PORTAL_QUEUE_URL"` to `_PRODUCTION_REQUIRED_ENV_VARS`. Both will fail until Step 3.

- [ ] **Step 2: Run to make sure they fail**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/infra -q`
Expected: FAIL — `PortalTaskDefinition is not defined in infra/template.yaml`, plus the four existing
task definitions failing the env-var assertion once `PORTAL_QUEUE_URL` is in the required set.

- [ ] **Step 3: Add the resources**

Parameters:

```yaml
  PortalImage:
    Type: String
    Description: >
      Immutable URI of the Dockerfile `portal` stage. Separate from AppImage: that stage
      carries Chrome for Testing and Xvfb, which no other service needs.
    AllowedPattern: "^.+@sha256:[0-9a-f]{64}$"

  PortalDesiredCount:
    Type: Number
    Default: 0
    MinValue: 0
    MaxValue: 1
    Description: >
      Ships STOPPED. §10's portal-terms blocker gates pointing this at a real portal at all,
      and the EC2 capacity behind it is not free. MaxValue is 1 and load-bearing: browser
      profiles are local to the instance that owns them, so a second task cannot resume an
      application the first one paused.

  LlmApiKeySecretArn:
    Type: String
    Description: >
      Secrets Manager ARN holding the Anthropic API key the learn pass uses. Supplied rather
      than created here so the key's lifecycle (rotation, access audit) is not this stack's.
```

Queue, mirroring `ResearchQueue` exactly — **standard, not FIFO**. `PortalDeadLetterQueue` and
`PortalQueue`, both with `KmsMasterKeyId: alias/aws/sqs`, a `RedrivePolicy` with
`maxReceiveCount: 3`, and `VisibilityTimeout: 1800` on `PortalQueue` because a learn pass plus a fill
is minutes rather than seconds. A FIFO queue would need either `ContentBasedDeduplication: true` or a
`MessageDeduplicationId` that `apps/queue.py::enqueue` does not send, so every publish would fail —
and it buys nothing here, because there is one consumer. Add `PortalQueueAgeAlarm` and
`PortalDeadLetterDepthAlarm` copied from the research pair.

Security group and role:

```yaml
  PortalSecurityGroup:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: Portal browser tasks; egress only, admitted to the database
      VpcId: !Ref ValidationVpc
      SecurityGroupEgress:
        - IpProtocol: -1
          CidrIp: 0.0.0.0/0

  PortalTaskRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Action: sts:AssumeRole
            Principal: {Service: ecs-tasks.amazonaws.com}
      Policies:
        - PolicyName: ConsumePortalQueueAndReadPortalCredentials
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: Allow
                Action:
                  - sqs:ReceiveMessage
                  - sqs:DeleteMessage
                  - sqs:SendMessage
                  - sqs:GetQueueAttributes
                Resource: !GetAtt PortalQueue.Arn
              # Portal logins, one secret per tenant per portal
              # (apps/portals/auth.py::SecretsManagerCredentials). Scoped by
              # path prefix so this role cannot read the database or Django
              # secrets that live beside it.
              - Effect: Allow
                Action: secretsmanager:GetSecretValue
                Resource: !Sub "arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:tehsil/portal/*"
```

And add the erasure half to `WorkerTaskRole`'s existing policy — the role
`test_only_worker_task_role_may_erase_tenant_objects` already pins as the one that deletes tenant
data, now that `advance_deletion` destroys portal credentials (Task 8):

```yaml
              - Effect: Allow
                Action: secretsmanager:DeleteSecret
                Resource: !Sub "arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:tehsil/portal/*"
```

EC2 capacity, and the instance role the ECS agent needs:

```yaml
  PortalInstanceRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Action: sts:AssumeRole
            Principal: {Service: ec2.amazonaws.com}
      Policies:
        # Written out rather than the AmazonEC2ContainerServiceforEC2Role
        # managed policy: nothing else in this template uses a managed policy,
        # and this list is what the agent actually calls.
        - PolicyName: EcsAgentRegistrationAndTelemetry
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: Allow
                Action:
                  - ecs:DeregisterContainerInstance
                  - ecs:DiscoverPollEndpoint
                  - ecs:Poll
                  - ecs:RegisterContainerInstance
                  - ecs:StartTelemetrySession
                  - ecs:UpdateContainerInstancesState
                  - ecs:Submit*
                  - ecr:GetAuthorizationToken
                  - ecr:BatchCheckLayerAvailability
                  - ecr:GetDownloadUrlForLayer
                  - ecr:BatchGetImage
                  - logs:CreateLogStream
                  - logs:PutLogEvents
                Resource: "*"

  PortalInstanceProfile:
    Type: AWS::IAM::InstanceProfile
    Properties:
      Roles: [!Ref PortalInstanceRole]

  PortalLaunchTemplate:
    Type: AWS::EC2::LaunchTemplate
    Properties:
      LaunchTemplateData:
        ImageId: "{{resolve:ssm:/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id}}"
        InstanceType: t3.large
        IamInstanceProfile: {Arn: !GetAtt PortalInstanceProfile.Arn}
        SecurityGroupIds: [!Ref PortalSecurityGroup]
        BlockDeviceMappings:
          - DeviceName: /dev/xvda
            Ebs:
              VolumeSize: 40
              VolumeType: gp3
              # The browser profiles live here. This is the whole of
              # "encrypted at rest" for a directory Chrome holds open --
              # see apps/portals/profiles.py's module docstring.
              Encrypted: true
              DeleteOnTermination: true
        MetadataOptions:
          # IMDSv2 required: a hostile page that achieves SSRF through the
          # browser must not be able to read the instance role from
          # 169.254.169.254 with a plain GET.
          HttpTokens: required
          HttpPutResponseHopLimit: 1
        UserData:
          Fn::Base64: !Sub |
            #!/bin/bash
            echo "ECS_CLUSTER=${ValidationCluster}" >> /etc/ecs/ecs.config

  PortalAutoScalingGroup:
    Type: AWS::AutoScaling::AutoScalingGroup
    Properties:
      MinSize: "0"
      MaxSize: "1"
      DesiredCapacity: !Ref PortalDesiredCount
      VPCZoneIdentifier: [!Ref WorkerPrivateSubnetA, !Ref WorkerPrivateSubnetB]
      LaunchTemplate:
        LaunchTemplateId: !Ref PortalLaunchTemplate
        Version: !GetAtt PortalLaunchTemplate.LatestVersionNumber

  PortalCapacityProvider:
    Type: AWS::ECS::CapacityProvider
    Properties:
      AutoScalingGroupProvider:
        AutoScalingGroupArn: !Ref PortalAutoScalingGroup
        ManagedScaling: {Status: ENABLED, TargetCapacity: 100}
        ManagedTerminationProtection: DISABLED

  PortalCapacityProviderAssociation:
    Type: AWS::ECS::ClusterCapacityProviderAssociations
    Properties:
      Cluster: !Ref ValidationCluster
      CapacityProviders: [!Ref PortalCapacityProvider, FARGATE]
      DefaultCapacityProviderStrategy:
        - CapacityProvider: FARGATE
          Weight: 1
```

Log group, task definition, service:

```yaml
  PortalLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub "/tehsil/app/${AWS::StackName}/portal"
      RetentionInDays: 30

  PortalTaskDefinition:
    Type: AWS::ECS::TaskDefinition
    Properties:
      RequiresCompatibilities: [EC2]
      NetworkMode: awsvpc
      Cpu: "1024"
      Memory: "3072"
      ExecutionRoleArn: !GetAtt AppExecutionRole.Arn
      TaskRoleArn: !GetAtt PortalTaskRole.Arn
      ContainerDefinitions:
        - Name: portal
          Image: !Ref PortalImage
          Essential: true
          LinuxParameters:
            # Chrome forks liberally and orphans processes; without an init to
            # reap them a long-running task accumulates zombies. Same reason as
            # the browser task.
            InitProcessEnabled: true
          Environment:
            - Name: DJANGO_SETTINGS_MODULE
              Value: config.settings.production
            - Name: DJANGO_ALLOWED_HOSTS
              Value: !Ref DjangoAllowedHosts
            - Name: PORTAL_QUEUE_URL
              Value: !Ref PortalQueue
            - Name: RESEARCH_QUEUE_URL
              Value: !Ref ResearchQueue
            - Name: EUROPASS_QUEUE_URL
              Value: !Ref EuropassQueue
            - Name: POSTGRES_HOST
              Value: !GetAtt Database.Endpoint.Address
            - Name: POSTGRES_PORT
              Value: !GetAtt Database.Endpoint.Port
            - Name: POSTGRES_DB
              Value: !Ref DBName
            - Name: DATABASE_ROLE
              Value: runtime
            - Name: POSTGRES_RUNTIME_USER
              Value: tehsil_runtime
          Secrets:
            - Name: POSTGRES_RUNTIME_PASSWORD
              ValueFrom: !Ref RuntimeDatabaseSecret
            - Name: DJANGO_SECRET_KEY
              ValueFrom: !Ref ValidationSecret
            # The learn pass calls the model from inside the browser extension,
            # so this key is in the browser's process whatever we do. It is one
            # more reason the renderer sandbox is non-negotiable here.
            - Name: ANTHROPIC_API_KEY
              ValueFrom: !Ref LlmApiKeySecretArn
          LogConfiguration:
            LogDriver: awslogs
            Options:
              awslogs-group: !Ref PortalLogGroup
              awslogs-region: !Ref AWS::Region
              awslogs-stream-prefix: portal

  PortalService:
    Type: AWS::ECS::Service
    Properties:
      ServiceName: portal
      Cluster: !Ref ValidationCluster
      LaunchType: EC2
      DesiredCount: !Ref PortalDesiredCount
      TaskDefinition: !Ref PortalTaskDefinition
      NetworkConfiguration:
        AwsvpcConfiguration:
          AssignPublicIp: DISABLED
          Subnets: [!Ref WorkerPrivateSubnetA, !Ref WorkerPrivateSubnetB]
          SecurityGroups: [!Ref PortalSecurityGroup]

  PortalEscalationFilter:
    Type: AWS::Logs::MetricFilter
    Properties:
      LogGroupName: !Ref PortalLogGroup
      FilterPattern: '"PortalEscalation"'
      MetricTransformations:
        - MetricNamespace: Tehsil/Portals
          MetricName: PortalEscalations
          MetricValue: "1"

  PortalEscalationRateAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      # A rate, not a count: escalations are expected -- §5.4 budgets under 10%
      # consultant intervention -- and an alarm on any escalation would page on
      # the system working. A spike means a portal changed shape.
      Namespace: Tehsil/Portals
      MetricName: PortalEscalations
      Statistic: Sum
      Period: 3600
      EvaluationPeriods: 1
      Threshold: 20
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
```

Add `PortalSecurityGroup` to `DatabaseSecurityGroup`'s ingress with this comment:

```yaml
        # The portal task reads field maps and writes the §5.5 audit trail
        # while it types, so unlike the browser task it cannot be
        # credential-free. What makes that acceptable is the renderer sandbox
        # (apps/portals/engine.py refuses to run without it) and the EC2
        # launch type that makes the sandbox possible. Adding
        # BrowserSecurityGroup here is still wrong for the original reason.
```

Add `PORTAL_QUEUE_URL` to the `Environment` block of `WebTaskDefinition`, `WorkerTaskDefinition`,
`MigrationTaskDefinition` and `EuropassWorkerTaskDefinition` — `config/settings/production.py` now
requires it in every process that loads production settings, which is the structural rule
`test_app_task_definitions_supply_every_production_required_env_var` exists to enforce.

Add `PortalImage`, `PortalDesiredCount` and `LlmApiKeySecretArn` to both files under
`infra/parameters/`, and a `PortalQueueUrl` output beside `ResearchQueueUrl`.

- [ ] **Step 4: Run the infra tests**

Run: `POSTGRES_DB=tehsil_plan2a uv run pytest tests/infra -q`
Expected: PASS.

- [ ] **Step 5: Validate the template against CloudFormation's own parser**

Run: `aws cloudformation validate-template --template-body file://infra/template.yaml --region eu-central-1`
Expected: a parameter listing and no error. If no AWS credential is available in this environment,
say so in the task report rather than skipping silently — the static tests do not catch a malformed
`!Sub` or an unknown resource property.

- [ ] **Step 6: Commit**

```bash
uv run ruff check tests
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 add infra tests/infra
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 commit -m "infra(portals): sandboxed portal worker on EC2 capacity, shipped stopped"
```

---

### Task 15: Whole-suite verification and the PR

- [ ] **Step 1: Run everything**

```bash
POSTGRES_DB=tehsil_plan2a uv run pytest -q
```
Expected: the plan-1 baseline (1238 passed, 3 skipped) plus this plan's tests, no failures. If a
suite unrelated to portals fails, first check for a parallel run — `ps -eo args --no-headers | grep
'/pytest ' | grep -v 'bash -c'` — because nine worktrees share one database. Note that
`tests/test_aws_boundary_run_controller.py` is independently flaky at roughly one run in two; it
shells out to bash and races on a pipe, and it is pre-existing.

- [ ] **Step 2: Run every gate**

```bash
uv run ruff check .
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps config
uv run pip-audit --ignore-vuln PYSEC-2026-2034 --ignore-vuln PYSEC-2026-3412
POSTGRES_DB=tehsil_plan2a uv run python manage.py check
POSTGRES_DB=tehsil_plan2a uv run python manage.py makemigrations --check --dry-run
```
Expected: clean on all six. No new dependency was added by this plan, so `pip-audit` should report
exactly what it reported before it.

- [ ] **Step 3: Run the browser-marked tests and the sandbox validation**

```bash
xvfb-run -a --server-args="-screen 0 1280x1024x24" env -u CI \
    POSTGRES_DB=tehsil_plan2a uv run pytest -m portal_browser -q
xvfb-run -a --server-args="-screen 0 1280x1024x24" env -u CI \
    uv run python scripts/validate_portal_sandbox.py
```
Expected: PASS, and `OK: headful and sandboxed on a fake display`. These need Chrome for Testing and
an LLM credential; if either is absent, report that rather than reporting a pass.

- [ ] **Step 4: Open the PR**

```bash
git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/phase3-plan2 push -u origin claude/phase3-plan2
gh pr create --base master --head claude/phase3-plan2 \
  --title "Phase 3 portal execution (plan 2a): worker, recovery, escalation" \
  --body "Implements docs/superpowers/plans/2026-08-27-phase3-portal-execution-2a.md. Nothing here can submit an application; submission is plan 2b and gated on the portal-terms blocker in §10."
```

---

## What plan 2a deliberately leaves for plan 2b

All of it is gated on the portal-terms blocker in §10 of `phased requirements.md` — automated access,
delegated form completion and submission.

- Submission itself, and the `SUBMITTED` / `CONFIRMED` transitions.
- The two authority modes (`counselor-submit`, `student-submit`) and the submission gate: authority
  mode, counselor approval of every document version under P1-14, and a rendered-page read-back
  assertion at submit time.
- The §5.1 rule that an application still unsubmitted 48 hours before its deadline is submitted under
  the same one-time authority, recorded as an approval event and notified.
- Repopulating a lost portal draft from the verified snapshot, with the duplicate-application check
  §5.2 requires. Plan 2a's resume relies on `already_correct`, which refills a lost draft in place;
  the duplicate check only matters next to submission.
- Document uploads to portals (§5.2's "form answers and uploaded documents" — answers are covered
  here, uploads are not), and §5.6 monitoring.
- Application-fee payment (§5.3), which is excluded from the whole phase by §10.
- Browser-level domain pinning if `set_domain_policy` proves unsuitable, carried forward from plan 1.
- Switching the learn pass to `1 x extract` if Task 1's spike found a resolution path — a measured 14x
  reduction per form version, but a change to the one code path whose accuracy governs every fill.

## Spec coverage

| Spec requirement | Task |
| --- | --- |
| `apps/research/queue.py` parameterised over its message type | 2 |
| Escalation is a notification, never a blocking queue; §5.4's six rows | 3 |
| `user_data_dir` encrypted at rest, tenant-isolated, TTL | 4 |
| Replay pass makes no LLM call (asserted end to end) | 5 |
| Validate every prepared form against the verified profile | 5 |
| Consultant review of the first prepared application per portal (§5.2) | 5 |
| Read-back against the rendered page | 5 (plan 1 built `read_back`; 5 wires it) |
| Scoped re-learn on selector miss; `RecoveryEvent` names both versions | 7 |
| `self_heal` stays off; a changed form leaves evidence | 6, 7 |
| Session reauthentication with platform-managed credentials | 8 |
| Applicant-specific MFA escalates to the student | 8 |
| Challenge detection is explicit and deterministic | 9 |
| Stall heuristic: a second interrupted fill on a freshly re-learned map reaches a consultant as UNSOLVED_CHALLENGE | 9 (detection), fix wave (wiring) |
| `ServiceResolver`, provider named in configuration, bounded attempts | 10 |
| Absent or rejected credential falls back rather than crashing | 10 |
| `ConsultantResolver` preserves the session and completed form state | 11 |
| Completion detected, resumed without repeating completed work | 11 |
| Every `Application` state transition, blocked and resume, round-trips | 3 (in), 11 (out) |
| Portal credentials never in the database, per student-portal (`CLAUDE.md`) | 8 |
| Erasure destroys a student's portal credentials (`CLAUDE.md`) | 8 |
| Resolution service only per approved portal (`CLAUDE.md`) | 10 |
| Pause and resume without repeating completed steps -- asserted against a real browser profile, NOT yet executed (portal_browser marker, needs ANTHROPIC_API_KEY) | 11 |
| Intervention rate recorded per portal and reported | 12 |
| Xvfb for CI and production; pinned Chrome; sandbox preserved | 13, 14 |
| No fingerprint evasion or proxy rotation (capability boundary) | 6 (test), plan 1 (test) |
| Nothing in this phase can submit | 6 (test), and by omission throughout |

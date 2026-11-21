"""The snapshot the content script sends, and what the server refuses to read.

A FieldMap is shared by every tenant. A snapshot taken in one student's browser
that carries that student's typed answers would put them in a shared table, so
the guard runs before the model call, not after.
"""

import pytest


def _snapshot(**overrides):
    from apps.portals.snapshot import FormSnapshot

    return FormSnapshot(
        page_url="https://apply.example.edu/personal",
        controls=[
            {
                "selector": "#name",
                "tag": "input",
                "type": "text",
                "name": "applicant_name",
                "id": "name",
                "label": "Full name",
                "placeholder": "As in your passport",
                "options": [],
                "required": True,
            },
            {
                "selector": "#country",
                "tag": "select",
                "type": "",
                "name": "country",
                "id": "country",
                "label": "Country of residence",
                "placeholder": "",
                "options": ["United Kingdom", "Germany"],
                "required": True,
            },
        ],
        **overrides,
    )


def test_a_snapshot_carries_no_value_field() -> None:
    from apps.portals.snapshot import SnapshotControl

    assert "value" not in SnapshotControl.model_fields


def test_an_unknown_key_is_refused() -> None:
    from pydantic import ValidationError

    from apps.portals.snapshot import SnapshotControl

    with pytest.raises(ValidationError):
        SnapshotControl(selector="#a", tag="input", value="Ada Byron")


def test_a_snapshot_carrying_a_student_value_is_refused() -> None:
    from apps.portals.snapshot import SnapshotPIILeak, assert_no_student_values

    snapshot = _snapshot()
    with pytest.raises(SnapshotPIILeak):
        assert_no_student_values(snapshot, ["As in your passport"])


def test_an_empty_forbidden_value_matches_nothing() -> None:
    """A student with a blank field would otherwise make every snapshot a leak."""
    from apps.portals.snapshot import assert_no_student_values

    assert_no_student_values(_snapshot(), ["", "   "])


def test_a_clean_snapshot_passes() -> None:
    from apps.portals.snapshot import assert_no_student_values

    assert_no_student_values(_snapshot(), ["Ada Byron", "London"])


def _snapshot_at(page_url: str):
    from apps.portals.snapshot import FormSnapshot

    return FormSnapshot(page_url=page_url, controls=_snapshot().controls)


def test_a_page_url_path_carrying_a_student_value_is_refused() -> None:
    """Not just a query string: probed through the real view with an address
    in page_url's query, and a path is exactly as reachable by the model."""
    from apps.portals.snapshot import SnapshotPIILeak, assert_no_student_values

    snapshot = _snapshot_at("https://apply.example.edu/leyla.apply@outlook.com/personal")
    with pytest.raises(SnapshotPIILeak):
        assert_no_student_values(snapshot, ["leyla.apply@outlook.com"])


def test_a_percent_encoded_page_url_value_is_refused() -> None:
    from apps.portals.snapshot import SnapshotPIILeak, assert_no_student_values

    snapshot = _snapshot_at(
        "https://apply.example.edu/personal?email=leyla.apply%2Btag%40outlook.com"
    )
    with pytest.raises(SnapshotPIILeak):
        assert_no_student_values(snapshot, ["leyla.apply+tag@outlook.com"])


def test_the_snapshot_pii_guard_is_case_insensitive() -> None:
    from apps.portals.snapshot import SnapshotPIILeak, assert_no_student_values

    with pytest.raises(SnapshotPIILeak):
        assert_no_student_values(_snapshot(), ["AS IN YOUR PASSPORT"])


class _FakeResponses:
    """Stands in for OpenAI().responses. Returns whatever mapping it was built
    with, so every test below is about what the server does with the answer --
    never about the model."""

    def __init__(self, mapping):
        self._mapping = mapping
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return type("Response", (), {"output_parsed": self._mapping})()


def _client(pairs, slots=()):
    from apps.portals.learn import SnapshotMapping, SnapshotMappingEntry

    mapping = SnapshotMapping(
        mappings=[
            SnapshotMappingEntry(
                profile_field=p[0], selector=p[1], sure=p[2] if len(p) > 2 else True
            )
            for p in pairs
        ],
        documents=list(slots),
    )
    return type("Client", (), {"responses": _FakeResponses(mapping)})()


@pytest.mark.django_db
def test_the_server_derives_the_method_the_model_never_chooses_it(agency_a) -> None:
    """The safety property of this whole path. The model returns a selector;
    the method comes from the control's own tag. A prompt-injected page cannot
    produce a click because there is no field in the model's output that could
    carry one."""
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-1")
    field_map = learn_from_snapshot(
        form,
        _snapshot(),
        profile_fields=["identity.full_name", "personal.country"],
        tenant_id=agency_a.id,
        forbidden_values=[],
        client=_client([("identity.full_name", "#name"), ("personal.country", "#country")]),
    )

    assert field_map.entries == [
        {
            "profile_field": "identity.full_name",
            "sure": True,
            "action": {"selector": "#name", "method": "fill", "arguments": ["%value%"]},
        },
        {
            "profile_field": "personal.country",
            "sure": True,
            "action": {
                "selector": "#country",
                "method": "selectOption",
                "arguments": ["%value%"],
            },
        },
    ]


@pytest.mark.django_db
def test_a_selector_that_is_not_on_the_page_is_refused(agency_a) -> None:
    """The model's only output is constrained to the snapshot's own selectors.
    Anything else is an invented control, which is what an injected page would
    ask for."""
    from apps.portals.learn import UnmappedField, learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-2")
    with pytest.raises(UnmappedField):
        learn_from_snapshot(
            form,
            _snapshot(),
            profile_fields=["identity.full_name"],
            tenant_id=agency_a.id,
            forbidden_values=[],
            client=_client([("identity.full_name", "#somewhere-else")]),
        )


@pytest.mark.django_db
def test_a_field_the_model_did_not_map_is_skipped_and_the_rest_is_stored(agency_a) -> None:
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-3")
    field_map = learn_from_snapshot(
        form, _snapshot(), profile_fields=["identity.full_name", "personal.country"],
        tenant_id=agency_a.id, forbidden_values=[],
        client=_client([("identity.full_name", "#name")]),
    )
    assert [e["profile_field"] for e in field_map.entries] == ["identity.full_name"]


@pytest.mark.django_db
def test_an_unsure_mapping_is_stored_as_unsure(agency_a) -> None:
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-4")
    field_map = learn_from_snapshot(
        form, _snapshot(), profile_fields=["identity.full_name", "personal.country"],
        tenant_id=agency_a.id, forbidden_values=[],
        client=_client(
            [("identity.full_name", "#name", True), ("personal.country", "#country", False)]
        ),
    )
    assert {e["profile_field"]: e["sure"] for e in field_map.entries} == {
        "identity.full_name": True, "personal.country": False,
    }


@pytest.mark.django_db
def test_a_map_with_nothing_usable_is_still_refused(agency_a) -> None:
    from apps.portals.learn import UnmappedField, learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-5")
    with pytest.raises(UnmappedField):
        learn_from_snapshot(
            form, _snapshot(), profile_fields=["identity.full_name"], tenant_id=agency_a.id,
            forbidden_values=[], client=_client([]),
        )


@pytest.mark.django_db
def test_a_snapshot_with_a_student_value_never_reaches_the_model(agency_a) -> None:
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm
    from apps.portals.snapshot import SnapshotPIILeak

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-4")
    client = _client([("identity.full_name", "#name")])
    with pytest.raises(SnapshotPIILeak):
        learn_from_snapshot(
            form,
            _snapshot(),
            profile_fields=["identity.full_name"],
            tenant_id=agency_a.id,
            forbidden_values=["As in your passport"],
            client=client,
        )
    assert client.responses.calls == []


def test_the_learn_pii_guard_is_case_insensitive() -> None:
    from apps.portals.learn import PIILeak, _assert_no_pii
    from apps.portals.session import FieldAction

    action = FieldAction(selector="#Leyla.Apply@Outlook.com", method="fill", arguments=[])
    with pytest.raises(PIILeak):
        _assert_no_pii(action, ["leyla.apply@outlook.com"])


@pytest.mark.django_db
def test_a_query_string_address_is_stripped_before_the_prompt_is_built(agency_a) -> None:
    """Probed through the real view: page_url with a tagged address in its query
    string reached the model verbatim. Stripped once, where the prompt is
    built, so the map still learns -- the address just never travels."""
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-url-1")
    client = _client([("identity.full_name", "#name")])
    address = "leyla.apply+ab12cd@outlook.com"
    snapshot = _snapshot_at(f"https://apply.example.edu/personal?email={address}")

    field_map = learn_from_snapshot(
        form,
        snapshot,
        profile_fields=["identity.full_name"],
        tenant_id=agency_a.id,
        forbidden_values=[address],
        client=client,
    )

    assert field_map.entries
    prompt = client.responses.calls[0]["input"][1]["content"]
    assert address not in prompt


@pytest.mark.django_db
def test_an_address_in_the_page_url_path_is_stripped_before_the_prompt_is_built(
    agency_a,
) -> None:
    """Round 2: the model is given only scheme+hostname, so a path-carried
    address is dropped before the prompt is built rather than caught by the
    guard -- structurally excluded instead of pattern-matched."""
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-url-2")
    client = _client([("identity.full_name", "#name")])
    address = "leyla.apply+ab12cd@outlook.com"
    snapshot = _snapshot_at(f"https://apply.example.edu/{address}/personal")

    field_map = learn_from_snapshot(
        form,
        snapshot,
        profile_fields=["identity.full_name"],
        tenant_id=agency_a.id,
        forbidden_values=[address],
        client=client,
    )

    assert field_map.entries
    prompt = client.responses.calls[0]["input"][1]["content"]
    assert address not in prompt


@pytest.mark.django_db
def test_a_double_encoded_page_url_path_value_is_stripped_before_the_prompt_is_built(
    agency_a,
) -> None:
    """The finding this round exists for: a double-encoded address in the path
    survived the single unquote in assert_no_student_values. Dropping the path
    from what the model sees closes it without a decode loop."""
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-url-3")
    client = _client([("identity.full_name", "#name")])
    address = "leyla.apply+ab12cd@outlook.com"
    encoded = "leyla.apply%252Bab12cd%2540outlook.com"
    snapshot = _snapshot_at(f"https://apply.example.edu/{encoded}/personal")

    field_map = learn_from_snapshot(
        form,
        snapshot,
        profile_fields=["identity.full_name"],
        tenant_id=agency_a.id,
        forbidden_values=[address],
        client=client,
    )

    assert field_map.entries
    prompt = client.responses.calls[0]["input"][1]["content"]
    assert address not in prompt
    assert encoded not in prompt


@pytest.mark.django_db
def test_a_userinfo_carrying_page_url_value_is_stripped_before_the_prompt_is_built(
    agency_a,
) -> None:
    """A page_url can carry a value as userinfo (user:pass@host) as readily as
    in the path or query -- also dropped, since only scheme+hostname reaches
    the model."""
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-url-4")
    client = _client([("identity.full_name", "#name")])
    address = "leyla.apply+ab12cd@outlook.com"
    snapshot = _snapshot_at(f"https://{address}:secret@apply.example.edu/personal")

    field_map = learn_from_snapshot(
        form,
        snapshot,
        profile_fields=["identity.full_name"],
        tenant_id=agency_a.id,
        forbidden_values=[address],
        client=client,
    )

    assert field_map.entries
    prompt = client.responses.calls[0]["input"][1]["content"]
    assert address not in prompt
    assert "secret" not in prompt


@pytest.mark.django_db
def test_a_malformed_page_url_is_refused_not_with_a_500(agency_a) -> None:
    """urlsplit raises ValueError on a bad IPv6 host; that must become the same
    refusal the PII guard gives, never an unhandled exception."""
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm
    from apps.portals.snapshot import SnapshotPIILeak

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-url-5")
    snapshot = _snapshot_at("https://[bad-ipv6/path")

    with pytest.raises(SnapshotPIILeak):
        learn_from_snapshot(
            form,
            snapshot,
            profile_fields=["identity.full_name"],
            tenant_id=agency_a.id,
            forbidden_values=[],
            client=_client([("identity.full_name", "#name")]),
        )


@pytest.mark.django_db
def test_a_page_url_with_no_hostname_is_refused(agency_a) -> None:
    """A relative page_url has nothing to reduce to -- refused rather than
    silently mapped against an empty origin."""
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm
    from apps.portals.snapshot import SnapshotPIILeak

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-url-6")
    snapshot = _snapshot_at("/personal")

    with pytest.raises(SnapshotPIILeak):
        learn_from_snapshot(
            form,
            snapshot,
            profile_fields=["identity.full_name"],
            tenant_id=agency_a.id,
            forbidden_values=[],
            client=_client([("identity.full_name", "#name")]),
        )


@pytest.mark.django_db
def test_learning_twice_supersedes_the_previous_map(agency_a) -> None:
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import FieldMap, PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-5")
    kwargs = dict(
        profile_fields=["identity.full_name"],
        tenant_id=agency_a.id,
        forbidden_values=[],
    )
    first = learn_from_snapshot(
        form, _snapshot(), client=_client([("identity.full_name", "#name")]), **kwargs
    )
    second = learn_from_snapshot(
        form, _snapshot(), client=_client([("identity.full_name", "#name")]), **kwargs
    )

    first.refresh_from_db()
    assert first.superseded_at is not None
    assert second.version == 2
    assert FieldMap.current_for(form, agency_a.id) == second


@pytest.mark.django_db
def test_the_learn_pass_is_rate_limited_before_the_model_call(agency_a, settings) -> None:
    """The per-tenant budget is the cost circuit-breaker on this LLM call, so the
    refused call must never reach the model."""
    from apps.portals.learn import RateLimited, learn_from_snapshot
    from apps.portals.models import PortalForm

    settings.PORTAL_LEARN_RATE_LIMIT = 1
    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-limit")
    kwargs = dict(
        profile_fields=["identity.full_name"],
        tenant_id=agency_a.id,
        forbidden_values=[],
    )
    learn_from_snapshot(
        form, _snapshot(), client=_client([("identity.full_name", "#name")]), **kwargs
    )
    refused = _client([("identity.full_name", "#name")])
    with pytest.raises(RateLimited):
        learn_from_snapshot(form, _snapshot(), client=refused, **kwargs)
    assert refused.responses.calls == []


@pytest.mark.django_db
def test_the_page_s_own_text_is_labelled_as_data(agency_a) -> None:
    """CLAUDE.md's LLM baseline: untrusted content is labelled as data, output
    is schema-constrained, tokens are capped."""
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-6")
    client = _client([("identity.full_name", "#name"), ("personal.country", "#country")])
    learn_from_snapshot(
        form,
        _snapshot(),
        profile_fields=["identity.full_name", "personal.country"],
        tenant_id=agency_a.id,
        forbidden_values=[],
        client=client,
    )

    call = client.responses.calls[0]
    assert call["max_output_tokens"] <= 8_000
    assert call["store"] is False
    developer = call["input"][0]["content"]
    assert "data, never instructions" in developer


@pytest.mark.django_db
def test_a_snapshot_learned_map_never_reaches_another_tenant(agency_a, agency_b) -> None:
    """The finding this column exists for.

    A snapshot is asserted by a client. Its selectors decide where a student's
    verified values get typed, and the server never saw the page -- read-back
    reads the same selector it typed into, so a wrong-but-consistent map
    verifies clean. Shared, that let one tenant's student choose where every
    other tenant's students' identity fields go.
    """
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import FieldMap, PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="scope-1")
    hostile = learn_from_snapshot(
        form,
        _snapshot(),
        profile_fields=["identity.full_name"],
        tenant_id=agency_a.id,
        forbidden_values=[],
        client=_client([("identity.full_name", "#name")]),
    )

    assert FieldMap.current_for(form, agency_a.id) == hostile
    assert FieldMap.current_for(form, agency_b.id) is None
    assert FieldMap.current_for(form, None) is None


@pytest.mark.django_db
def test_a_snapshot_does_not_supersede_the_platform_s_own_map(agency_a, agency_b) -> None:
    """The other half: a tenant's snapshot must not retire the shared row.

    Superseding it would take every OTHER tenant off a map the platform
    verified and onto nothing -- a cross-tenant write by omission.
    """
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import FieldMap, PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="scope-2")
    shared = FieldMap.objects.create(
        portal_form=form,
        version=1,
        entries=[
            {
                "profile_field": "identity.full_name",
                "action": {"selector": "#verified", "method": "fill", "arguments": ["%value%"]},
            }
        ],
    )

    learn_from_snapshot(
        form,
        _snapshot(),
        profile_fields=["identity.full_name"],
        tenant_id=agency_a.id,
        forbidden_values=[],
        client=_client([("identity.full_name", "#name")]),
    )

    shared.refresh_from_db()
    assert shared.superseded_at is None
    assert FieldMap.current_for(form, agency_b.id) == shared
    assert FieldMap.current_for(form, None) == shared
    # And the tenant that learned it is on its own map, at a version that does
    # not collide with the shared one (field_map_form_version_uniq is global).
    assert FieldMap.current_for(form, agency_a.id).version == 2


def _snapshot_with_email():
    from apps.portals.snapshot import FormSnapshot

    base = _snapshot()
    return FormSnapshot(
        page_url=base.page_url,
        controls=[
            *base.controls,
            {
                "selector": "#email",
                "tag": "input",
                "type": "email",
                "name": "email",
                "id": "email",
                "label": "Email address",
                "placeholder": "",
                "options": [],
                "required": True,
            },
        ],
    )


@pytest.mark.django_db
def test_the_portal_address_is_learned_when_the_page_asks_for_it(agency_a) -> None:
    """contact.email is not a verified fact, so it was never offered to the
    learn pass, and a learned map could never fill it (plan 2's deferred item)."""
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-email-1")
    client = _client([("identity.full_name", "#name"), ("contact.email", "#email")])
    field_map = learn_from_snapshot(
        form,
        _snapshot_with_email(),
        profile_fields=["identity.full_name"],
        optional_fields=("contact.email",),
        tenant_id=agency_a.id,
        forbidden_values=[],
        client=client,
    )

    assert [entry["profile_field"] for entry in field_map.entries] == [
        "identity.full_name",
        "contact.email",
    ]
    assert "contact.email" in client.responses.calls[0]["input"][1]["content"]


@pytest.mark.django_db
def test_a_page_with_no_email_control_still_learns(agency_a) -> None:
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-email-2")
    field_map = learn_from_snapshot(
        form,
        _snapshot(),
        profile_fields=["identity.full_name"],
        optional_fields=("contact.email",),
        tenant_id=agency_a.id,
        forbidden_values=[],
        client=_client([("identity.full_name", "#name")]),
    )

    assert [entry["profile_field"] for entry in field_map.entries] == ["identity.full_name"]


def _free_text(context: str, heading: str = ""):
    from apps.portals.snapshot import FormSnapshot

    return FormSnapshot.model_validate({
        "page_url": "https://apply.example.edu/docs",
        "controls": [{"selector": "#t2", "tag": "input", "type": "file",
                      "heading": heading, "context": context}],
    })


def test_a_student_value_in_heading_or_context_is_redacted_not_refused() -> None:
    from apps.portals.snapshot import redact_student_values

    snapshot = _free_text("Welcome, Leyla Aliyeva. Upload transcript", heading="Degree 2")
    redacted = redact_student_values(snapshot, ["Leyla Aliyeva", ""])
    assert redacted.controls[0].context == "Welcome, ■. Upload transcript"
    assert redacted.controls[0].heading == "Degree 2"


def test_redaction_is_whole_words_and_skips_values_shorter_than_three() -> None:
    from apps.portals.snapshot import redact_student_values

    redacted = redact_student_values(_free_text("Ali, Aliyeva Ltd, Al, ALI"), ["Ali", "Al"])
    assert redacted.controls[0].context == "■, Aliyeva Ltd, Al, ■"


def test_a_label_leak_is_still_refused_after_redaction() -> None:
    from apps.portals.snapshot import (
        FormSnapshot,
        SnapshotPIILeak,
        assert_no_student_values,
        redact_student_values,
    )

    snapshot = FormSnapshot.model_validate({
        "page_url": "https://apply.example.edu/docs",
        "controls": [{"selector": "#n", "tag": "input", "label": "Name (LEYLA)",
                      "context": "leyla"}],
    })
    redacted = redact_student_values(snapshot, ["Leyla"])
    assert redacted.controls[0].context == "■"
    with pytest.raises(SnapshotPIILeak):
        assert_no_student_values(redacted, ["Leyla"])


@pytest.mark.django_db
def test_the_prompt_never_carries_a_redacted_value(agency_a) -> None:
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm
    from apps.portals.snapshot import FormSnapshot

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="ctx-1")
    snapshot = FormSnapshot.model_validate({
        "page_url": "https://apply.example.edu/p",
        "controls": [{"selector": "#name", "tag": "input", "label": "Full name",
                      "context": "Signed in as Leyla Aliyeva"}],
    })
    client = _client([("identity.full_name", "#name")])
    learn_from_snapshot(
        form, snapshot, profile_fields=["identity.full_name"], tenant_id=agency_a.id,
        forbidden_values=["Leyla Aliyeva"], client=client,
    )
    # The raw user message, not json.dumps of it: json.dumps escapes "■" to ■.
    sent = client.responses.calls[0]["input"][1]["content"]
    assert "Leyla" not in sent and "■" in sent


@pytest.mark.django_db
def test_one_entry_per_selector_indexed_beats_unindexed_then_sure_beats_unsure(agency_a) -> None:
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-dedupe")
    field_map = learn_from_snapshot(
        form, _snapshot(),
        profile_fields=[
            "education.institution_original", "education.1.institution_original",
            "identity.full_name", "personal.full_name",
        ],
        tenant_id=agency_a.id, forbidden_values=[],
        client=_client([
            ("education.institution_original", "#name", True),
            ("education.1.institution_original", "#name", False),
            ("identity.full_name", "#country", False),
            ("personal.full_name", "#country", True),
        ]),
    )
    assert {e["profile_field"]: e["sure"] for e in field_map.entries} == {
        "education.1.institution_original": False, "personal.full_name": True,
    }


@pytest.mark.django_db
def test_a_file_slot_is_stored_and_a_slot_on_a_text_box_is_dropped(agency_a) -> None:
    from apps.portals.learn import DocumentSlot, learn_from_snapshot
    from apps.portals.models import PortalForm
    from apps.portals.snapshot import FormSnapshot

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="slots-1")
    snapshot = FormSnapshot.model_validate({
        "page_url": "https://apply.example.edu/docs",
        "controls": [
            {"selector": "#cv", "tag": "input", "type": "file", "label": "CV"},
            {"selector": "#name", "tag": "input", "type": "text", "label": "Full name"},
        ],
    })
    slots = [
        DocumentSlot(selector="#cv", kind="CV", variant="ANY", degree=None, sure=True),
        DocumentSlot(selector="#name", kind="PASSPORT", variant="ANY", degree=None, sure=True),
    ]
    field_map = learn_from_snapshot(
        form, snapshot, profile_fields=["identity.full_name"], tenant_id=agency_a.id,
        forbidden_values=[], client=_client([], slots=slots),
    )
    assert field_map.entries == []
    assert [s["selector"] for s in field_map.slots] == ["#cv"]


@pytest.mark.django_db
def test_two_slots_on_one_box_keep_one_sure_beats_unsure_then_the_first(agency_a) -> None:
    from apps.portals.learn import DocumentSlot, learn_from_snapshot
    from apps.portals.models import PortalForm
    from apps.portals.snapshot import FormSnapshot

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="slots-2")
    snapshot = FormSnapshot.model_validate({
        "page_url": "https://apply.example.edu/docs",
        "controls": [
            {"selector": "#a", "tag": "input", "type": "file", "label": "Upload"},
            {"selector": "#b", "tag": "input", "type": "file", "label": "Upload"},
        ],
    })
    slots = [
        DocumentSlot(selector="#a", kind="CV", variant="ANY", degree=None, sure=False),
        DocumentSlot(selector="#a", kind="PASSPORT", variant="ANY", degree=None, sure=True),
        DocumentSlot(selector="#b", kind="DIPLOMA", variant="ANY", degree=None, sure=True),
        DocumentSlot(selector="#b", kind="OTHER", variant="ANY", degree=None, sure=True),
    ]
    field_map = learn_from_snapshot(
        form, snapshot, profile_fields=["identity.full_name"], tenant_id=agency_a.id,
        forbidden_values=[], client=_client([], slots=slots),
    )
    assert [(s["selector"], s["kind"]) for s in field_map.slots] == [
        ("#a", "PASSPORT"), ("#b", "DIPLOMA"),
    ]


def test_redaction_survives_the_clients_whitespace_collapsing() -> None:
    from apps.portals.snapshot import redact_student_values

    snapshot = _free_text("At 12 Nizami St\nBaku, for Leyla  Aliyeva.")
    redacted = redact_student_values(snapshot, ["12 Nizami St Baku", "Leyla Aliyeva"])
    assert redacted.controls[0].context == "At ■, for ■."


@pytest.mark.django_db
def test_an_earlier_answer_echoed_by_the_page_never_reaches_the_model(agency_a) -> None:
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm
    from apps.portals.snapshot import FormSnapshot

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="echo-1")
    snapshot = FormSnapshot.model_validate({
        "page_url": "https://apply.example.edu/p",
        "controls": [{"selector": "#name", "tag": "input", "label": "Full name",
                      "context": "Previously you entered Ganja Sports Lyceum"}],
    })
    client = _client([("identity.full_name", "#name")])
    learn_from_snapshot(
        form, snapshot, profile_fields=["identity.full_name"], tenant_id=agency_a.id,
        forbidden_values=[], redact_values=["Ganja Sports Lyceum"], client=client,
    )
    sent = client.responses.calls[0]["input"][1]["content"]
    assert "Ganja" not in sent and "entered ■" in sent


@pytest.mark.django_db
def test_learning_a_second_wizard_step_preserves_earlier_steps_and_records_max_length(
    agency_a,
) -> None:
    from apps.portals.learn import DocumentSlot, learn_from_snapshot
    from apps.portals.models import PortalForm
    from apps.portals.snapshot import FormSnapshot

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="wizard-1")
    step_1 = FormSnapshot.model_validate({
        "page_url": "https://apply.example.edu/step-1",
        "controls": [
            {"selector": "#name", "tag": "input", "type": "text", "label": "Full name"},
            {"selector": "#cv", "tag": "input", "type": "file", "label": "Upload CV"},
        ],
    })
    learn_from_snapshot(
        form,
        step_1,
        profile_fields=["identity.full_name", "narrative.motivation_letter"],
        tenant_id=agency_a.id,
        forbidden_values=[],
        client=_client(
            [("identity.full_name", "#name")],
            slots=[DocumentSlot(selector="#cv", kind="CV", variant="ANY", degree=None, sure=True)],
        ),
    )

    step_2 = FormSnapshot.model_validate({
        "page_url": "https://apply.example.edu/step-2",
        "controls": [
            {
                "selector": "#motivation",
                "tag": "textarea",
                "label": "Motivation letter",
                "max_length": 1500,
            },
            {
                "selector": "#letter-file",
                "tag": "input",
                "type": "file",
                "label": "Motivation letter PDF",
            },
        ],
    })
    merged = learn_from_snapshot(
        form,
        step_2,
        profile_fields=["identity.full_name", "narrative.motivation_letter"],
        tenant_id=agency_a.id,
        forbidden_values=[],
        client=_client(
            [("narrative.motivation_letter", "#motivation")],
            slots=[
                DocumentSlot(
                    selector="#letter-file",
                    kind="MOTIVATION_LETTER",
                    variant="ANY",
                    degree=None,
                    sure=True,
                )
            ],
        ),
    )
    assert [(e["profile_field"], e.get("max_length")) for e in merged.entries] == [
        ("identity.full_name", None),
        ("narrative.motivation_letter", 1500),
    ]
    assert [(s["selector"], s["kind"]) for s in merged.slots] == [
        ("#cv", "CV"),
        ("#letter-file", "MOTIVATION_LETTER"),
    ]

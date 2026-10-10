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


def _client(pairs):
    from apps.portals.learn import SnapshotMapping, SnapshotMappingEntry

    mapping = SnapshotMapping(
        mappings=[
            SnapshotMappingEntry(profile_field=field, selector=selector)
            for field, selector in pairs
        ]
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
            "action": {"selector": "#name", "method": "fill", "arguments": ["%value%"]},
        },
        {
            "profile_field": "personal.country",
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
def test_a_field_the_model_did_not_map_refuses_the_whole_map(agency_a) -> None:
    """Storing the rest produces a map that fills a form only partly while every
    downstream check passes clean -- learn.py's own UnmappedField docstring."""
    from apps.portals.learn import UnmappedField, learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-3")
    with pytest.raises(UnmappedField):
        learn_from_snapshot(
            form,
            _snapshot(),
            profile_fields=["identity.full_name", "personal.country"],
            tenant_id=agency_a.id,
            forbidden_values=[],
            client=_client([("identity.full_name", "#name")]),
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
    assert call["max_output_tokens"] <= 4_000
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

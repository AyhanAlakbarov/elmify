import uuid

import pytest
from django.db import IntegrityError, transaction

from apps.documents.constraints import ConstraintRule, Enforcement, resolve_rules
from apps.documents.drafts import create_draft
from apps.documents.models import DocumentDraft
from apps.documents.render import (
    _EUROPASS_RENDER_LIMIT,
    _EUROPASS_RENDER_WINDOW_SECONDS,
    PreflightBlocked,
    RenderRateLimited,
    render_cv,
    render_cv_with_warnings,
    render_draft,
)
from apps.documents.requirement_list import build_requirements
from apps.funding.models import CatalogRule, FundingOpportunity, Institution, Program
from apps.ratelimit import rate_limited
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _approved_draft(agency_a, django_user_model, *, programme, content=None, render_variant=""):
    """An APPROVED CV draft, tenant-scoped, optionally linked to a programme.

    Only render_draft accepts an unapproved draft as an error case -- every
    other test here needs one already past that gate, same pattern as
    tests/documents/test_render.py:379-395.
    """
    from tests.documents.test_render import _content

    user = django_user_model.objects.create(username=f"u{uuid.uuid4().hex[:12]}")
    student = Membership.objects.create(
        tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
    )
    draft = create_draft(
        student=student,
        kind=DocumentDraft.Kind.CV,
        content=content if content is not None else _content(),
        programme=programme,
        render_variant=render_variant,
    )
    DocumentDraft.objects.filter(id=draft.id).update(status=DocumentDraft.Status.APPROVED)
    draft.refresh_from_db()
    return draft


def _long_content():
    from tests.documents.test_render import _content, _many_experience

    return _content(experience=_many_experience(20))


def _rule(**overrides):
    base = dict(
        rule_id="R-080",
        scope_kind=CatalogRule.ScopeKind.FUNDER,
        scope_values=["rhodes"],
        key="max_pages",
        value=2,
        enforcement="BINDING",
        rule_text="Rhodes: CV should not exceed 2 pages.",
        source_url="https://www.rhodeshouse.ox.ac.uk/",
        verified_for_cycle="current template",
        confidence="high",
    )
    base.update(overrides)
    return CatalogRule.objects.create(**base)


def test_a_catalog_rule_round_trips_its_scope_and_value():
    rule = _rule()
    stored = CatalogRule.objects.get(rule_id="R-080")
    assert stored.scope_values == ["rhodes"]
    assert stored.value == 2
    assert stored.id == rule.id


def test_the_same_rule_id_may_set_two_different_keys():
    """R-032 is one researched rule and two constraints: no photo AND no date
    of birth. Uniqueness is on (rule_id, key), not rule_id alone."""
    _rule(rule_id="R-032", key="photo_allowed", value=False)
    _rule(rule_id="R-032", key="date_of_birth_allowed", value=False)
    assert CatalogRule.objects.filter(rule_id="R-032").count() == 2


def test_the_same_rule_id_may_not_set_the_same_key_twice():
    _rule(rule_id="R-032", key="photo_allowed", value=False)
    with pytest.raises(IntegrityError):
        _rule(rule_id="R-032", key="photo_allowed", value=True)


def test_a_universal_rule_carries_no_scope_values():
    rule = _rule(rule_id="S-009", scope_kind=CatalogRule.ScopeKind.UNIVERSAL, scope_values=[])
    assert rule.scope_values == []


def test_a_non_universal_rule_must_carry_scope_values():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _rule(rule_id="R-081", scope_kind=CatalogRule.ScopeKind.FUNDER, scope_values=[])


def test_a_universal_rule_may_not_carry_scope_values():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _rule(
                rule_id="S-010",
                scope_kind=CatalogRule.ScopeKind.UNIVERSAL,
                scope_values=["rhodes"],
            )


def test_an_invalid_scope_kind_is_rejected():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _rule(rule_id="R-082", scope_kind="PLANET", scope_values=["earth"])


def _programme(country_code="GB", constraints=None):
    institution = Institution.objects.create(
        canonical_key=f"inst:{country_code}",
        name="Test University",
        country_code=country_code,
        official_website="https://university.example.test",
    )
    return Program.objects.create(
        institution=institution,
        canonical_key=f"prog:{country_code}",
        name="MSc Test",
        campus_name="Main",
        city="Town",
        country_code=country_code,
        location_key=f"{country_code.lower()}:town",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=12,
        cv_constraints=constraints or [],
    )


def _opportunity(key="sisgp"):
    return FundingOpportunity.objects.create(
        canonical_key=key, name=key.upper(), family="GOVERNMENT_SCHOLARSHIP",
        scope_type="COUNTRY", country_code="SE",
    )


def _award(*, route="CONSIDERED_WITH_ADMISSION", cv_format_requirement=""):
    """An Erasmus Mundus-style scholarship applied for in the programme's own
    application (Task 2's `together`), not a separate funder opportunity."""
    key = f"emjm-{uuid.uuid4().hex[:12]}"
    return FundingOpportunity.objects.create(
        canonical_key=key, name=key.upper(), family="MULTILATERAL",
        scope_type="GLOBAL", route=route, cv_format_requirement=cv_format_requirement,
    )


def _funder_rule(award, rule_id, key, value, **overrides):
    """A FUNDER-scoped CatalogRule that matches `award` (_scope_matches checks
    `opportunity.canonical_key in rule.scope_values`)."""
    return _rule(
        rule_id=rule_id, scope_kind=CatalogRule.ScopeKind.FUNDER,
        scope_values=[award.canonical_key], key=key, value=value, **overrides,
    )


def _taught_content():
    from tests.documents.test_render import _content
    return _content()


def test_a_universal_rule_applies_with_no_programme_and_no_funder():
    _rule(rule_id="S-009", scope_kind=CatalogRule.ScopeKind.UNIVERSAL,
          scope_values=[], key="max_pages", value=2)
    resolved = resolve_rules(None, None, content=_taught_content())
    assert [rule.rule_id for rule in resolved] == ["S-009"]


def test_a_country_rule_matches_by_membership_not_equality():
    _rule(rule_id="R-032", scope_kind=CatalogRule.ScopeKind.COUNTRY,
          scope_values=["US", "CA", "GB", "AU"], key="photo_allowed", value=False)
    resolved = resolve_rules(_programme("GB"), None, content=_taught_content())
    assert [r.rule_id for r in resolved] == ["R-032"]
    assert resolve_rules(_programme("DE"), None, content=_taught_content()) == ()


def test_a_funder_rule_only_applies_when_that_funder_is_named():
    _rule(rule_id="R-078", scope_kind=CatalogRule.ScopeKind.FUNDER,
          scope_values=["sisgp"], key="max_entries_per_section", value={"experience": 3})
    programme = _programme("SE")
    assert resolve_rules(programme, None, content=_taught_content()) == ()
    resolved = resolve_rules(programme, _opportunity("sisgp"), content=_taught_content())
    assert [rule.rule_id for rule in resolved] == ["R-078"]


def test_the_funder_wins_over_the_country_on_the_same_key():
    """R-079 (SISGP mandates date of birth) over R-032 (US/CA/UK/AU forbid it).
    The research states this outcome directly: personal-data inclusion is a
    per-destination render decision, never a global content decision."""
    _rule(rule_id="R-032", scope_kind=CatalogRule.ScopeKind.COUNTRY,
          scope_values=["GB"], key="date_of_birth_allowed", value=False)
    _rule(rule_id="R-079", scope_kind=CatalogRule.ScopeKind.FUNDER,
          scope_values=["sisgp"], key="date_of_birth_allowed", value=True)
    resolved = resolve_rules(_programme("GB"), _opportunity("sisgp"), content=_taught_content())
    assert [rule.rule_id for rule in resolved] == ["R-079"]


def test_specificity_wins_even_when_it_is_looser():
    """DAAD allows 3 pages where the taught default is 2. The funder's own
    published rule is the operative one, not the tightest one available."""
    _rule(rule_id="R-023", scope_kind=CatalogRule.ScopeKind.TRACK,
          scope_values=["taught"], key="max_pages", value=2)
    _rule(rule_id="R-012", scope_kind=CatalogRule.ScopeKind.FUNDER,
          scope_values=["daad"], key="max_pages", value=3)
    resolved = resolve_rules(_programme("DE"), _opportunity("daad"), content=_taught_content())
    assert [(r.rule_id, r.value) for r in resolved] == [("R-012", 3)]


def test_programme_constraints_win_over_every_catalog_scope():
    _rule(rule_id="R-012", scope_kind=CatalogRule.ScopeKind.FUNDER,
          scope_values=["daad"], key="max_pages", value=3)
    programme = _programme("DE", constraints=[{
        "rule_id": "P-001", "key": "max_pages", "value": 1,
        "enforcement": "BINDING", "rule_text": "This programme caps at 1 page.",
    }])
    resolved = resolve_rules(programme, _opportunity("daad"), content=_taught_content())
    assert [(r.rule_id, r.value) for r in resolved] == [("P-001", 1)]


def test_a_resolved_rule_says_which_tier_answered():
    """The rank that decided the merge was computed and thrown away, so a
    warning could not say whether a page limit came from the funder, the
    country or a programme page a model read."""
    _rule(rule_id="R-012", scope_kind=CatalogRule.ScopeKind.FUNDER,
          scope_values=["daad"], key="max_pages", value=3)
    _rule(rule_id="R-013", scope_kind=CatalogRule.ScopeKind.COUNTRY,
          scope_values=["DE"], key="photo_allowed", value=True)
    resolved = resolve_rules(_programme("DE"), _opportunity("daad"), content=_taught_content())
    assert {r.rule_id: r.scope for r in resolved} == {"R-012": "FUNDER", "R-013": "COUNTRY"}


def test_a_rule_off_a_programme_page_says_so():
    programme = _programme("DE", constraints=[{
        "rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 1,
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "Your CV may be one page.",
        "scope": "PROGRAMME",
    }])
    resolved = resolve_rules(programme, None, content=_taught_content())
    assert [(r.rule_id, r.scope) for r in resolved] == [("PAGE-0-max_pages", "PROGRAMME")]


def test_a_stored_rule_written_before_the_field_existed_still_loads():
    """extra="forbid" plus rules_from_program's deliberate raise means a
    missing key is fatal, not skipped -- so the field needs its default and ""
    must stay a legal value."""
    programme = _programme("DE", constraints=[{
        "rule_id": "P-001", "key": "max_pages", "value": 1,
        "enforcement": "BINDING", "rule_text": "This programme caps at 1 page.",
    }])
    resolved = resolve_rules(programme, None, content=_taught_content())
    assert [(r.rule_id, r.scope) for r in resolved] == [("P-001", "")]


def test_scope_matches_raises_on_an_unrecognised_scope_kind():
    from apps.documents.constraints import _scope_matches

    class _Rule:
        scope_kind = "PLANET"
        scope_values = []

    with pytest.raises(ValueError):
        _scope_matches(_Rule(), program=None, opportunity=None, track="taught")


def _every_seed_funder():
    """The seed refuses to run against funders that do not exist, so tests that
    exercise it must load them first -- the same precondition a deployment has."""
    from apps.documents.catalog_seed import SEED_FUNDERS

    for canonical_key, name, _requirement in SEED_FUNDERS:
        FundingOpportunity.objects.create(
            canonical_key=canonical_key,
            name=name,
            family="GOVERNMENT_SCHOLARSHIP",
            scope_type="GLOBAL",
        )


def test_seeding_twice_changes_nothing_the_second_time():
    from apps.documents.catalog_seed import seed_cv_rules

    _every_seed_funder()
    created, updated, deleted = seed_cv_rules()
    assert created > 0
    again = seed_cv_rules()
    assert again == (0, 0, 0)


def test_seeding_removes_a_rule_no_longer_in_the_module():
    from apps.documents.catalog_seed import seed_cv_rules

    _every_seed_funder()
    seed_cv_rules()
    _rule(rule_id="R-999", key="max_pages", value=9)
    _created, _updated, deleted = seed_cv_rules()
    assert deleted == 1
    assert not CatalogRule.objects.filter(rule_id="R-999").exists()


def test_seeding_removes_a_stale_key_even_when_its_rule_id_is_still_seeded():
    """R-032 is seeded twice (photo_allowed, date_of_birth_allowed). A third,
    stray row under the same rule_id but a key SEED_RULES no longer sets must
    be swept -- the delete sweep is keyed on (rule_id, key), not rule_id
    alone, and this is the case an rule_id-only exclude would spare."""
    from apps.documents.catalog_seed import seed_cv_rules

    _every_seed_funder()
    seed_cv_rules()
    _rule(rule_id="R-032", key="signature_required", value=True)
    _created, _updated, deleted = seed_cv_rules()
    assert deleted == 1
    assert not CatalogRule.objects.filter(rule_id="R-032", key="signature_required").exists()
    assert CatalogRule.objects.filter(rule_id="R-032", key="photo_allowed").exists()
    assert CatalogRule.objects.filter(rule_id="R-032", key="date_of_birth_allowed").exists()


def test_every_seeded_key_is_a_key_the_engine_can_check():
    from typing import get_args

    from apps.documents.catalog_seed import SEED_RULES
    from apps.documents.constraints import _CONSTRAINT_KEYS
    from apps.documents.render import _CHECKERS

    allowed = set(get_args(_CONSTRAINT_KEYS))
    for row in SEED_RULES:
        assert row["key"] in allowed, row["rule_id"]
        if row["enforcement"] == "BINDING":
            assert row["key"] in _CHECKERS, (
                f"{row['rule_id']} is BINDING with no checker -- it would block "
                "every render for that funder"
            )


def test_seeding_annotates_an_existing_funder_and_never_invents_one():
    """The seed sets cv_format_requirement on funders the discovery pipeline
    loaded. It does not create them: FundingOpportunity needs `family`, and
    this research establishes none -- Rhodes is a private trust, so every
    value in that taxonomy would be a false claim."""
    from apps.documents.catalog_seed import seed_cv_rules

    _every_seed_funder()
    seed_cv_rules()
    assert (
        FundingOpportunity.objects.get(canonical_key="rhodes").cv_format_requirement
        == "funder_template"
    )


def test_seeding_refuses_when_a_rule_names_a_funder_that_does_not_exist():
    from apps.documents.catalog_seed import seed_cv_rules

    with pytest.raises(ValueError, match="not in the catalog"):
        seed_cv_rules()


def test_two_rules_of_the_same_scope_and_key_are_a_data_error():
    from apps.documents.catalog_seed import _assert_no_same_scope_conflict

    rows = (
        {"rule_id": "A", "scope_kind": "COUNTRY", "scope_values": ["DE"], "key": "max_pages"},
        {"rule_id": "B", "scope_kind": "COUNTRY", "scope_values": ["DE"], "key": "max_pages"},
    )
    with pytest.raises(ValueError, match="max_pages"):
        _assert_no_same_scope_conflict(rows)


def test_a_draft_renders_with_its_programmes_rules(agency_a, django_user_model):
    """render_draft resolved nothing before this: every caller had to pass
    constraints, and the one caller in the app passed none."""
    with tenant_scope(agency_a.id):
        programme = _programme("GB")
        _rule(rule_id="R-032", scope_kind=CatalogRule.ScopeKind.COUNTRY,
              scope_values=["GB"], key="max_pages", value=1,
              enforcement="BINDING")
        draft = _approved_draft(agency_a, django_user_model, programme=programme,
                                content=_long_content())
        with pytest.raises(PreflightBlocked):
            render_draft(draft=draft)


def test_a_draft_with_no_programme_renders_exactly_as_before(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, programme=None)
        assert render_draft(draft=draft).variant == "STANDARD"


def test_a_funder_scoped_rule_blocks_a_draft_via_its_funding_opportunity(
    agency_a, django_user_model
):
    """_scope_matches's FUNDER branch carries 13 of the 20 seeded rows and
    every BINDING rule, but nothing in apps/ ever assigns
    DocumentDraft.funding_opportunity -- this closes that end-to-end gap."""
    with tenant_scope(agency_a.id):
        opportunity = _opportunity(key="rhodes")
        _rule(value=1)  # R-080: FUNDER/rhodes, max_pages=1, BINDING
        draft = _approved_draft(
            agency_a, django_user_model, programme=None, content=_long_content()
        )
        DocumentDraft.objects.filter(id=draft.id).update(funding_opportunity=opportunity)
        draft.refresh_from_db()
        with pytest.raises(PreflightBlocked, match="R-080"):
            render_draft(draft=draft)


def test_a_resolved_europass_variant_is_still_rate_limited(agency_a, django_user_model):
    """The guard must read the resolved variant, not draft.render_variant.
    A draft that stores no variant but resolves to EUROPASS_API is exactly the
    case this task creates, and it is the case an unmoved guard misses."""
    with tenant_scope(agency_a.id):
        institution = Institution.objects.create(
            canonical_key="inst:europass", name="Test University", country_code="SE",
            official_website="https://university.example.test",
        )
        programme = Program.objects.create(
            institution=institution, canonical_key="prog:europass", name="MSc Test",
            campus_name="Main", city="Town", country_code="SE", location_key="se:town",
            degree_level="MASTER", teaching_languages=["English"], duration_months=12,
            cv_format_requirement=Program.CVFormatRequirement.EUROPASS_REQUIRED,
        )
        draft = _approved_draft(agency_a, django_user_model, programme=programme)
        assert draft.render_variant == ""
        for _ in range(_EUROPASS_RENDER_LIMIT):
            rate_limited(
                "europass-render", draft.student_id,
                limit=_EUROPASS_RENDER_LIMIT,
                window_seconds=_EUROPASS_RENDER_WINDOW_SECONDS,
            )
        with pytest.raises(RenderRateLimited):
            render_draft(draft=draft)


def test_an_institution_scoped_rule_resolves_for_that_institution_only():
    """The one published rule that names the CV outright -- Cambridge's AI
    prohibition -- is a university's, and no scope could hold it before."""
    _rule(
        rule_id="L-041",
        scope_kind=CatalogRule.ScopeKind.INSTITUTION,
        scope_values=["gb:university of cambridge"],
        key="ai_use_policy",
        value="PROHIBITS",
        enforcement="ADVISORY_HIGH_RISK",
        rule_text="Cambridge: AI must not be used when writing personal statements and CVs.",
    )
    cambridge = _programme(country_code="GB")
    cambridge.institution.canonical_key = "gb:university of cambridge"
    cambridge.institution.save(update_fields=["canonical_key"])
    elsewhere = _programme(country_code="FR")

    from tests.documents.test_render import _content

    content = _content()
    assert [r.rule_id for r in resolve_rules(cambridge, None, content=content)] == ["L-041"]
    assert resolve_rules(elsewhere, None, content=content) == ()


def test_an_ai_use_policy_is_always_reported_and_never_blocks():
    """Nothing in a rendered PDF shows how it was written, so this is a fact
    about the reader rather than a defect in the artefact: surfaced to the
    human approving the draft, and never a gate (the letter engine's rule)."""
    rule = ConstraintRule(
        rule_id="L-041",
        key="ai_use_policy",
        value="PROHIBITS",
        enforcement=Enforcement.ADVISORY_HIGH_RISK,
        rule_text="Cambridge: AI must not be used when writing personal statements and CVs.",
    )
    from tests.documents.test_render import _content

    artifact, violations = render_cv_with_warnings(
        _content(), variant="STANDARD", constraints=(rule,)
    )
    assert artifact.pdf_bytes is not None
    assert [v.rule.rule_id for v in violations] == ["L-041"]
    assert "PROHIBITS" in violations[0].detail
    # render_cv raises only on BINDING, so the advisory tier cannot block.
    render_cv(_content(), variant="STANDARD", constraints=(rule,))


# --- a hint must not be able to delete a requirement -------------------------
#
# cv_constraints got its first automated writer on 2026-09-12
# (derive.py::derive_page_rules). Every derived rule is ADVISORY_HIGH_RISK
# and four of the seven derivable keys have BINDING seeds, so without the guard
# in resolve_rules a sentence a model read off a third-party programme page
# silently downgraded a funder's published requirement for every tenant.


def _derived(key, value, rule_text="The CV must carry a date of issue."):
    """A rule shaped exactly as derive_page_rules writes one."""
    return {
        "rule_id": "PAGE-0",
        "key": key,
        "value": value,
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": rule_text,
        "source_url": "https://university.example.test/msc",
    }


def test_an_advisory_programme_rule_cannot_displace_a_binding_one():
    """Rewritten on purpose 2026-10-14 (spec §6.4). R-010 is a FUNDER rule, as
    seeded, so it is theirs and "required beats not stated" keeps it. The old
    version used a UNIVERSAL R-010; under "theirs beat ours" a page rule now
    beats that one by design -- see the next test."""
    _rule(
        rule_id="R-010",
        scope_kind=CatalogRule.ScopeKind.FUNDER,
        scope_values=["daad"],
        key="date_of_issue_required",
        value=True,
        enforcement="BINDING",
    )
    programme = _programme("DE", constraints=[_derived("date_of_issue_required", False)])

    resolved = resolve_rules(programme, _opportunity("daad"), content=_taught_content())

    kept = [r for r in resolved if r.key == "date_of_issue_required"]
    assert [r.rule_id for r in kept] == ["R-010"]
    assert kept[0].enforcement == Enforcement.BINDING
    assert kept[0].value is True


def test_a_page_rule_beats_a_binding_universal_one_and_keeps_its_force():
    """Theirs beat ours (spec §6.4 step 3), and the merged rule keeps the
    strongest enforcement of the rules it came from (step 7)."""
    _rule(rule_id="R-010", scope_kind=CatalogRule.ScopeKind.UNIVERSAL, scope_values=[],
          key="date_of_issue_required", value=True, enforcement="BINDING")
    programme = _programme("DE", constraints=[_derived("date_of_issue_required", False)])

    resolved = resolve_rules(programme, None, content=_taught_content())

    assert [(r.rule_id, r.value, r.enforcement) for r in resolved] == [
        ("PAGE-0", False, Enforcement.BINDING),
    ]


def test_an_advisory_programme_rule_still_wins_where_nothing_binding_covers_the_key():
    """Spec §6.4 step 3: the page's own rule is theirs and beats our universal
    one outright, whatever their forces -- the one-page cap applies."""
    _rule(
        rule_id="S-009",
        scope_kind=CatalogRule.ScopeKind.UNIVERSAL,
        scope_values=[],
        key="max_pages",
        value=2,
        enforcement="ADVISORY_STYLE",
    )
    programme = _programme(
        "DE", constraints=[_derived("max_pages", 1, "Your CV must not exceed one page.")]
    )

    resolved = resolve_rules(programme, None, content=_taught_content())

    assert [(r.rule_id, r.value) for r in resolved if r.key == "max_pages"] == [("PAGE-0", 1)]


def test_a_binding_programme_rule_no_longer_replaces_a_stricter_binding_funder_one():
    """Rewritten on purpose 2026-10-14; it was
    test_a_binding_programme_rule_still_replaces_a_binding_catalog_one. Between
    theirs the stricter value wins (spec §6.4 step 4), not the more specific
    source: a programme saying no date of issue is needed cannot remove the
    funder's requirement for one."""
    _rule(
        rule_id="R-010",
        scope_kind=CatalogRule.ScopeKind.FUNDER,
        scope_values=["daad"],
        key="date_of_issue_required",
        value=True,
        enforcement="BINDING",
    )
    curated = _derived("date_of_issue_required", False)
    curated |= {"rule_id": "R-999", "enforcement": "BINDING"}
    programme = _programme("DE", constraints=[curated])

    resolved = resolve_rules(programme, _opportunity("daad"), content=_taught_content())

    assert [(r.rule_id, r.value) for r in resolved if r.key == "date_of_issue_required"] == [
        ("R-010", True),
    ]


def test_a_derived_rule_cannot_unlock_the_europass_pii_egress():
    """The whole reason the guard exists, checked where it actually bites.

    date_of_issue_required is a content-only key precisely because EUROPASS_API
    can never satisfy it, and _blocked_by_content_only_rules inspects BINDING
    rules only. Downgrade that rule and the pre-render gate stops firing, so a
    student's name, date of birth, education and employment history reach
    europa.eu on a render that had been refused before any egress.
    """
    from apps.documents.render import RenderedArtifact, _blocked_by_content_only_rules

    _rule(
        rule_id="R-010",
        scope_kind=CatalogRule.ScopeKind.UNIVERSAL,
        scope_values=[],
        key="date_of_issue_required",
        value=True,
        enforcement="BINDING",
    )
    programme = _programme("DE", constraints=[_derived("date_of_issue_required", True)])
    content = _taught_content()
    placeholder = RenderedArtifact(
        variant="EUROPASS_API", pdf_bytes=None, field_mapped=None, page_count=None, byte_size=0
    )

    resolved = resolve_rules(programme, None, content=content)

    assert _blocked_by_content_only_rules(content, resolved, placeholder) is True


def test_two_surfaced_rules_on_one_programme_both_survive_resolution():
    """resolve_rules merges by key. `unapplied` and `undecided` carry a quote
    each, and two quotes on one page are two rules -- merging would keep the
    last one and lose the other, which is the silent drop this design ends."""
    programme = _programme(constraints=[
        {"rule_id": "PAGE-0-unapplied", "key": "unapplied", "value": "cv",
         "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "Include your cumulative GPA.",
         "source_url": ""},
        {"rule_id": "PAGE-4-unapplied", "key": "unapplied", "value": "cv",
         "enforcement": "ADVISORY_HIGH_RISK",
         "rule_text": "Include details on the recognition of the awarding institution.",
         "source_url": ""},
    ])
    resolved = resolve_rules(programme, None, content=_taught_content())
    assert sorted(r.rule_id for r in resolved if r.key == "unapplied") == [
        "PAGE-0-unapplied", "PAGE-4-unapplied",
    ]


# --- spec 2026-10-12 §6.4: who wins ------------------------------------------


def test_every_key_and_directive_action_has_a_row_in_the_stricter_table():
    """Spec §6.4: a key the system can read with no row is a rule nobody
    decided how to merge. Adding a key to CONSTRAINT_KEYS fails here first."""
    from apps.documents.constraints import CONSTRAINT_KEYS
    from apps.documents.requirement_list import (
        _COMBINE,
        _OTHER_ROWS,
        DIRECTIVE_ACTIONS,
        MERGE,
        REQUIREMENT_KEYS,
    )

    assert set(CONSTRAINT_KEYS) | set(DIRECTIVE_ACTIONS) <= set(MERGE)
    assert set(MERGE) == REQUIREMENT_KEYS
    assert set(MERGE.values()) <= set(_COMBINE) | _OTHER_ROWS


def test_no_language_in_common_cannot_be_combined():
    from apps.documents.requirement_list import _COMBINE, Irreconcilable

    with pytest.raises(Irreconcilable):
        _COMBINE["common_language"](["de", ["fr", "en"]])
    assert _COMBINE["common_language"]([["fr", "en"], "en"]) == "en"


def _page_rule(rule_id, key, value, enforcement="ADVISORY_HIGH_RISK", **extra):
    return ConstraintRule.model_validate({
        "rule_id": rule_id, "key": key, "value": value, "enforcement": enforcement,
        "rule_text": f"{rule_id}: the page's sentence.", **extra,
    })


def _merged(*pairs, directives=()):
    """merge() over (rule, origin) pairs; ours carry their scope's rank."""
    from apps.documents.constraints import _SCOPE_ORDER
    from apps.documents.requirement_list import Contribution, merge

    contributions = [
        Contribution(rule=rule, origin=origin,
                     rank=_SCOPE_ORDER.index(rule.scope) if origin == "ours" else 0)
        for rule, origin in pairs
    ]
    return merge(contributions, directives)


@pytest.mark.parametrize(
    ("key", "programme", "scholarship", "stricter"),
    [
        ("max_pages", 3, 2, 2),
        ("max_bytes", 2_000_000, 10_000_000, 2_000_000),
        ("no_unexplained_gaps", 3, 1, 1),
        ("min_final_page_fill", 0.2, 0.5, 0.5),
        # max_entries_per_section merges per section: its own tests below.
        ("required_fields", ["sex"], ["sex", "citizenship"], ["sex", "citizenship"]),
        ("prohibited_content", [], ["hyperlinks"], ["hyperlinks"]),
        ("photo_allowed", True, False, False),
        ("photo_required", True, False, True),
        ("date_of_birth_allowed", True, False, False),
        ("signature_required", False, True, True),
        ("date_of_issue_required", True, False, True),
        ("language", ["en", "fr"], "fr", "fr"),
        ("cv_scope", "relevant_only", "complete", "complete"),
        ("cv_start", {"milestone": "first_degree", "years": None},
         {"milestone": "upper_secondary", "years": 10},
         {"milestone": "upper_secondary", "years": 10}),
        ("font", "Arial 11", "Times New Roman", "Arial 11"),
        ("max_words", 1000, 800, 800),
        ("max_chars_incl_spaces", 4000, 5000, 4000),
        ("max_chars_excl_spaces", 3000, 3500, 3000),
        ("min_words", 300, 500, 500),
        ("min_chars_excl_spaces", 2000, 1500, 2000),
    ],
)
def test_between_programme_and_scholarship_the_stricter_value_wins(
    key, programme, scholarship, stricter
):
    """One case per value row of the §6.4 table. The info, directive and
    format rows have their own tests below."""
    items = _merged(
        (_page_rule("P-1", key, programme), "programme"),
        (_page_rule("F-1", key, scholarship, "BINDING"), "scholarship"),
    )
    winners = [i for i in items if i.key == key and i.force != "info"]
    assert [i.value for i in winners] == [stricter]


@pytest.mark.parametrize("key", ["ai_use_policy", "undecided", "unapplied"])
def test_a_for_information_key_keeps_every_rule_and_never_refuses(key):
    items = _merged(
        (_page_rule("P-1", key, "PROHIBITS", "BINDING"), "programme"),
        (_page_rule("F-1", key, "REQUIRES_DISCLOSURE"), "scholarship"),
    )
    assert [(i.force, i.rule.enforcement) for i in items] == [
        ("info", Enforcement.ADVISORY_HIGH_RISK), ("info", Enforcement.ADVISORY_HIGH_RISK),
    ]


def test_a_second_font_from_theirs_is_for_information():
    items = _merged(
        (_page_rule("P-1", "font", "Arial 11"), "programme"),
        (_page_rule("F-1", "font", "Times New Roman"), "scholarship"),
    )
    assert [(i.value, i.force) for i in items] == [("Arial 11", "soft"),
                                                   ("Times New Roman", "info")]


def test_no_language_in_common_is_a_conflict_with_both_sides_kept():
    items = _merged(
        (_page_rule("P-1", "language", "de"), "programme"),
        (_page_rule("F-1", "language", "fr"), "scholarship"),
    )
    assert [(i.value, i.conflict) for i in items] == [("de", "language"), ("fr", "language")]


def _directive(action, target, value=None):
    from apps.documents.constraints import PageDirective

    return PageDirective(action=action, target=target, value=value,
                         rule_text=f"{action} {target}", source_url="")


def test_include_and_emphasise_directives_are_all_kept_theirs_first():
    items = _merged(directives=(
        (_directive("emphasise", "research"), "scholarship"),
        (_directive("include", "education.ects_credits"), "programme"),
        (_directive("emphasise", "experience"), "programme"),
        (_directive("include", "education.ects_credits"), "scholarship"),
    ))
    assert [(i.key, i.value, i.origin) for i in items] == [
        ("include", "education.ects_credits", "programme"),
        ("emphasise", "experience", "programme"),
        ("emphasise", "research", "scholarship"),
    ]


def test_two_orders_for_one_section_are_a_conflict():
    items = _merged(directives=(
        (_directive("order", "cv", "chronological"), "programme"),
        (_directive("order", "cv", "reverse_chronological"), "scholarship"),
    ))
    assert len(items) == 2
    assert {i.conflict for i in items} == {"order:cv"}


def test_theirs_beat_ours_even_when_theirs_is_soft():
    items = _merged(
        (_page_rule("C-1", "max_pages", 1, "ADVISORY_STYLE", scope="COUNTRY"), "ours"),
        (_page_rule("P-1", "max_pages", 3), "programme"),
    )
    assert [(i.value, i.rule.rule_id) for i in items] == [(3, "P-1")]


def test_among_ours_the_more_specific_scope_still_wins():
    items = _merged(
        (_page_rule("C-1", "max_pages", 3, "ADVISORY_STYLE", scope="COUNTRY"), "ours"),
        (_page_rule("U-1", "max_pages", 1, "ADVISORY_STYLE", scope="UNIVERSAL"), "ours"),
    )
    assert [(i.value, i.rule.rule_id) for i in items] == [(3, "C-1")]


def test_a_merged_rule_carries_the_strongest_force_of_its_contributors():
    """Step 7: whichever rule supplied the value. The scholarship's BINDING
    three pages lose to the page's advisory two, and the two stay BINDING."""
    items = _merged(
        (_page_rule("P-1", "max_pages", 2), "programme"),
        (_page_rule("F-1", "max_pages", 3, "BINDING"), "scholarship"),
    )
    assert [(i.value, i.rule.rule_id, i.force, i.rule.enforcement) for i in items] == [
        (2, "P-1", "strict", Enforcement.BINDING),
    ]
    assert items[0].contributors == ("P-1", "F-1")


def test_a_scholarship_requiring_a_date_of_birth_against_a_page_ban_is_a_conflict():
    """Step 5: SISGP's R-079 against a programme page forbidding it."""
    items = _merged(
        (_page_rule("R-079", "required_fields", ["sex", "date_of_birth"], "BINDING"),
         "scholarship"),
        (_page_rule("P-1", "date_of_birth_allowed", False), "programme"),
    )
    assert {i.conflict for i in items} == {"required_fields+date_of_birth_allowed"}


def test_an_include_directive_against_a_page_ban_is_a_conflict():
    items = _merged(
        (_page_rule("F-1", "date_of_birth_allowed", False), "scholarship"),
        directives=((_directive("include", "personal.date_of_birth"), "programme"),),
    )
    assert {i.conflict for i in items} == {"include+date_of_birth_allowed"}


def test_a_country_ban_loses_to_a_scholarship_requirement_on_another_key():
    """Step 5's ours case: R-032 (no date of birth in GB) is ours, so SISGP's
    required date of birth stands and no conflict is raised."""
    items = _merged(
        (_page_rule("R-079", "required_fields", ["date_of_birth"], "BINDING"), "scholarship"),
        (_page_rule("R-032", "date_of_birth_allowed", False, scope="COUNTRY"), "ours"),
    )
    assert [(i.key, i.conflict) for i in items] == [("required_fields", "")]


def test_a_required_photo_against_a_forbidden_one_is_a_conflict():
    items = _merged(
        (_page_rule("P-1", "photo_required", True), "programme"),
        (_page_rule("F-1", "photo_allowed", False), "scholarship"),
    )
    assert all(i.conflict == "photo_required+photo_allowed" for i in items)


def test_a_letter_floor_above_its_cap_is_a_conflict():
    from apps.documents.requirement_list import Contribution, merge

    items = merge([
        Contribution(rule=_page_rule("S-1", "min_words", 900), origin="programme",
                     document="letter"),
        Contribution(rule=_page_rule("S-2", "max_words", 800), origin="scholarship",
                     document="letter"),
    ])
    assert all(i.conflict == "min_words+max_words" for i in items)


def _undecided(rule_id, value, readings=None):
    return _page_rule(rule_id, "undecided", value,
                      **({"readings": readings} if readings else {}))


def test_an_unclear_limit_takes_the_stricter_reading():
    items = _merged((_undecided("PAGE-0-max_pages", "max_pages",
                                {"key": "max_pages", "values": [3, 2]}), "programme"))
    assert [(i.key, i.value, i.force) for i in items] == [("max_pages", 2, "soft")]


def test_two_section_caps_merge_per_section_each_with_its_own_force():
    """Final review I3 (spec §6.4 step 7, controller ruling): a merged rule
    carries the strongest force of the rules its VALUE came from. The
    scholarship's BINDING experience cap must not make the page's soft
    awards cap BINDING."""
    items = _merged(
        (_page_rule("P-1", "max_entries_per_section", {"experience": 3, "awards": 5}),
         "programme"),
        (_page_rule("F-1", "max_entries_per_section", {"experience": 2}, "BINDING"),
         "scholarship"),
    )
    assert [(i.value, i.force, i.rule.rule_id, i.contributors) for i in items] == [
        ({"experience": 2}, "strict", "F-1", ("F-1", "P-1")),
        ({"awards": 5}, "soft", "P-1", ("P-1",)),
    ]


def test_one_supplier_of_two_section_caps_keeps_its_rule_ids_unique():
    items = _merged(
        (_page_rule("P-1", "max_entries_per_section", {"experience": 2, "awards": 2}),
         "programme"),
        (_page_rule("F-1", "max_entries_per_section", {"experience": 3}, "BINDING"),
         "scholarship"),
    )
    assert [(i.value, i.force, i.rule.rule_id) for i in items] == [
        ({"experience": 2}, "strict", "P-1"), ({"awards": 2}, "soft", "P-1-2"),
    ]
    assert [i.contributors for i in items] == [("P-1", "F-1"), ("P-1",)]


@pytest.mark.parametrize(("readings", "expected"), [
    ([2, "3"], [("max_pages", 2, "soft")]),
    ([2, 3, True], [("max_pages", 2, "soft")]),
    (["2"], [("undecided", "max_pages", "info")]),
    ([True, 0], [("undecided", "max_pages", "info")]),
])
def test_an_unclear_limit_reads_only_the_readings_that_are_a_limit(readings, expected):
    """Final review I2: (2, "3") raised TypeError out of min() -- every render
    of the programme -- and (2, 3, True) merged to max_pages=True, a one-page
    cap. A reading that is no positive number is not a reading of a limit."""
    items = _merged((_undecided("PAGE-0-max_pages", "max_pages",
                                {"key": "max_pages", "values": readings}), "programme"))
    assert [(i.key, i.value, i.force) for i in items] == expected


def test_a_fractional_cap_is_not_a_limit_reading():
    items = _merged((_undecided("PAGE-0-max_pages", "max_pages",
                                {"key": "max_pages", "values": [0.5]}), "programme"))
    assert [(i.key, i.force) for i in items] == [("undecided", "info")]


@pytest.mark.parametrize(("key", "readings", "expected"), [
    ("max_entries_per_section", [{"publications": 3}, [3], {"awards": "x"}],
     {"publications": 3}),
    ("prohibited_content", [["hyperlinks"], "photos", [3]], ["hyperlinks"]),
])
def test_an_unclear_shaped_limit_reads_only_readings_of_its_shape(key, readings, expected):
    items = _merged((_undecided("PAGE-0-x", key, {"key": key, "values": readings}),
                     "programme"))
    assert [(i.key, i.value) for i in items] == [(key, expected)]


def test_a_wrong_typed_page_limit_beside_a_funder_one_keeps_each_with_its_own_force():
    """Final review I2, probe 3: three readings agreed on the string "2", and
    against R-008's BINDING 2 min() raised TypeError. Each of theirs stands
    alone instead, so render reports the bad one as it always did."""
    from apps.documents.derive import Candidate, Derivations, Derived, decide

    pages = Candidate(text="The CV must not exceed two pages.", heading="", europass=False)
    sample = Derivations(rules=(Derived(statement_index=0, key="max_pages", value="2"),))
    [page] = decide((pages,), [sample] * 3, source_url="https://x.example.org/").rules
    funder = _page_rule("R-008", "max_pages", 2, "BINDING", scope="FUNDER")
    items = _merged((funder, "scholarship"), (page, "programme"))
    assert [(i.value, i.force, i.rule.enforcement) for i in items] == [
        ("2", "soft", Enforcement.ADVISORY_HIGH_RISK), (2, "strict", Enforcement.BINDING),
    ]


@pytest.mark.parametrize(("votes", "expected"), [
    ((2, 2, "3"), 2), ((2, 3, True), 2), ((True, 1, 1), 1),
])
def test_disputed_readings_from_the_judge_merge_without_crashing(votes, expected):
    """Final review I2, probe 2, through decide: what the judge saves is what
    the merge reads."""
    from apps.documents.derive import Candidate, Derivations, Derived, decide

    pages = Candidate(text="The CV must not exceed two pages.", heading="", europass=False)
    samples = [Derivations(rules=(Derived(statement_index=0, key="max_pages", value=v),))
               for v in votes]
    rules = decide((pages,), samples, source_url="https://x.example.org/").rules
    items = _merged(*((rule, "programme") for rule in rules))
    # repr, because True == 1: a merged True is the bug, not a pass.
    assert [(i.key, repr(i.value)) for i in items] == [("max_pages", repr(expected))]


def test_a_bare_string_beside_a_listed_field_is_not_unioned_letter_by_letter():
    items = _merged(
        (_page_rule("P-1", "required_fields", "phone"), "programme"),
        (_page_rule("F-1", "required_fields", ["sex"], "BINDING"), "scholarship"),
    )
    assert [(i.value, i.force) for i in items] == [("phone", "soft"), (["sex"], "strict")]


def test_a_language_code_matches_whatever_its_case():
    """Final review M5: "EN" against ["fr", "en"] is one language, not a clash."""
    items = _merged(
        (_page_rule("P-1", "language", "EN"), "programme"),
        (_page_rule("F-1", "language", ["fr", "en"], "BINDING"), "scholarship"),
    )
    assert [(i.value, i.force, i.conflict) for i in items] == [("en", "strict", "")]


def test_an_unclear_personal_item_is_asked_not_guessed():
    items = _merged((_undecided("PAGE-1-photo_allo", "photo_allowed",
                                {"key": "photo_allowed", "values": [True, False]}),
                     "programme"))
    assert [(i.key, i.ask, i.value) for i in items] == [("photo_allowed", True, None)]
    # Render still reports the quote, never a decided photo rule.
    assert items[0].rule.key == "undecided"


def test_an_unclear_rule_without_saved_readings_is_for_information():
    items = _merged((_undecided("PAGE-2-max_pages", "max_pages"), "programme"))
    assert [(i.key, i.force) for i in items] == [("undecided", "info")]


def test_an_unclear_format_stays_for_information():
    items = _merged((_undecided("PAGE-3-cv_format", "cv_format"), "programme"))
    assert [(i.key, i.force) for i in items] == [("undecided", "info")]


def test_a_third_party_reading_never_becomes_an_item():
    """Step 1, with readings on the same line (review focus 1): the
    supervisor's two pages must not become the student's. The sentence itself
    is still shown, for information (owner, 2026-10-14: a skipped sentence is
    silent, so it is never dropped)."""
    items = _merged(
        (_undecided("PAGE-4-max_pages", "max_pages",
                    {"key": "max_pages", "values": [2, 3]}), "programme"),
        (_undecided("PAGE-4-third_par", "third_party"), "programme"),
        (_undecided("PAGE-5-unjudged", "unjudged"), "programme"),
    )
    assert [(i.key, i.value, i.force) for i in items] == [
        ("undecided", "third_party", "info"),
        ("undecided", "unjudged", "info"),
    ]


def test_a_third_party_line_on_one_page_does_not_discard_the_same_line_of_another():
    """Review focus 5: line numbers restart on every page."""
    items = _merged(
        (_undecided("PAGE-4-third_par", "third_party"), "scholarship"),
        (_undecided("PAGE-4-max_pages", "max_pages",
                    {"key": "max_pages", "values": [2]}), "programme"),
    )
    assert [(i.key, i.value) for i in items] == [
        ("undecided", "third_party"),
        ("max_pages", 2),
    ]

# Ruling P8: real producer output, not hand-built rules.

_SUPERVISOR_LINE = "Short CV (max. 2 pages) from this academic supervisor."


def test_a_supervisors_disputed_page_limit_from_the_judge_ends_as_one_info_item():
    """derive.decide on the supervisor's line: unanimous readings write the
    `third_party` marker; disagreeing ones write an unclear `max_pages` rule
    with no readings. Either way merge shows the sentence once, for
    information, and never makes it the student's page limit."""
    from apps.documents.derive import _SAMPLES, Candidate, Derivations, Derived, decide

    supervisor = Candidate(text=_SUPERVISOR_LINE, heading="Documents", europass=False,
                           third_party=True)

    def sample(pages):
        return Derivations(formats=(), directives=(), rules=(
            Derived(statement_index=0, key="max_pages", value=pages),))

    unanimous = decide((supervisor,), [sample(2)] * _SAMPLES, source_url="").rules
    disputed = decide((supervisor,), [sample(2), sample(3), sample(2)], source_url="").rules
    assert [r.rule_id for r in unanimous] == ["PAGE-0-third_par"]
    for rules in (unanimous, disputed):
        items = _merged(*((rule, "programme") for rule in rules))
        assert [(i.key, i.force, i.sentence) for i in items] == [
            ("undecided", "info", _SUPERVISOR_LINE)]


def test_a_grammar_third_party_note_keeps_its_line_out_of_the_rules():
    """rule_sinks.to_notes: the `-third_par` tail is recognised by id (its
    value is "cv:limit"), and an unsure reading on the same line is dropped
    with it, so two pages never become a `max_pages` item."""
    from apps.documents.grammar import Rule
    from apps.documents.rule_sinks import to_notes

    notes = to_notes((
        Rule(index=0, document="cv", operation="limit", value=2, unit="pages",
             sentence=_SUPERVISOR_LINE, confidence=0.95, note="third_party"),
        Rule(index=0, document="cv", operation="limit", value=2, unit="pages",
             bound="maximum", sentence=_SUPERVISOR_LINE, confidence=0.6, note="unsure"),
    ), source_url="")
    assert [(n.rule_id, n.value, n.readings is not None) for n in notes] == [
        ("PAGE-0-third_par", "cv:limit", False), ("PAGE-0-unsure", "cv:limit", True)]
    items = _merged(*((note, "programme") for note in notes))
    assert [(i.key, i.value, i.force) for i in items] == [("undecided", "cv:limit", "info")]
    assert not any(i.key == "max_pages" for i in items)


def test_an_unjudged_line_from_the_judge_is_one_info_item():
    from apps.documents.derive import Candidate, decide

    pages = Candidate(text="Your CV must not exceed two pages.", heading="", europass=False)
    rules = decide((pages,), [], source_url="").rules
    assert [(r.rule_id, r.value) for r in rules] == [("PAGE-0-unjudged", "unjudged")]
    items = _merged(*((rule, "programme") for rule in rules))
    assert [(i.key, i.value, i.force) for i in items] == [("undecided", "unjudged", "info")]


def test_overlapping_clashes_are_one_conflict_holding_every_side():
    """Fix round 1: photo_required and required_fields both clash with one
    photo ban. Step 6 must see all three in one choice, not two partial ones."""
    from apps.documents.requirement_list import RequirementList

    items = _merged(
        (_page_rule("P-1", "photo_required", True), "programme"),
        (_page_rule("P-2", "required_fields", ["photo_url"]), "programme"),
        (_page_rule("F-1", "photo_allowed", False, "BINDING"), "scholarship"),
    )
    groups = RequirementList(items=items).conflicts()
    assert len(groups) == 1
    [sides] = groups.values()
    assert sorted(i.key for i in sides) == ["photo_allowed", "photo_required", "required_fields"]


def test_the_first_font_carries_a_binding_losers_force():
    """Fix round 1, spec §6.4 step 7: the losers' force counts too."""
    items = _merged(
        (_page_rule("P-1", "font", "Arial"), "programme"),
        (_page_rule("F-1", "font", "Times", "BINDING"), "scholarship"),
    )
    assert [(i.value, i.force, i.rule.enforcement) for i in items] == [
        ("Arial", "strict", Enforcement.BINDING),
        ("Times", "info", Enforcement.ADVISORY_HIGH_RISK),
    ]
    assert items[0].contributors == ("P-1", "F-1")


def test_theirs_beat_ours_through_resolve_rules_even_when_theirs_is_soft():
    _rule(rule_id="R-023", scope_kind=CatalogRule.ScopeKind.TRACK, scope_values=["taught"],
          key="max_pages", value=2, enforcement="ADVISORY_STYLE")
    programme = _programme("DE", constraints=[_derived("max_pages", 3, "Up to three pages.")])
    resolved = resolve_rules(programme, None, content=_taught_content())
    assert [(r.rule_id, r.value) for r in resolved if r.key == "max_pages"] == [("PAGE-0", 3)]


def test_a_soft_page_limit_under_a_binding_funder_one_is_enforced_as_binding():
    _rule(rule_id="R-012", scope_kind=CatalogRule.ScopeKind.FUNDER, scope_values=["daad"],
          key="max_pages", value=3)
    programme = _programme("DE", constraints=[_derived("max_pages", 2, "Two pages.")])
    resolved = resolve_rules(programme, _opportunity("daad"), content=_taught_content())
    assert [(r.rule_id, r.value, r.enforcement) for r in resolved] == [
        ("PAGE-0", 2, Enforcement.BINDING),
    ]


def test_an_unclear_programme_limit_reaches_render_as_its_stricter_reading():
    programme = _programme("DE", constraints=[{
        "rule_id": "PAGE-0-max_pages", "key": "undecided", "value": "max_pages",
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "Two or three pages.",
        "readings": {"key": "max_pages", "values": [3, 2]},
    }])
    resolved = resolve_rules(programme, None, content=_taught_content())
    assert [(r.rule_id, r.key, r.value, r.enforcement, r.readings) for r in resolved] == [
        ("PAGE-0-max_pages", "max_pages", 2, Enforcement.ADVISORY_HIGH_RISK, None),
    ]


def test_a_third_party_sentence_reaches_render_only_as_information():
    programme = _programme("DE", constraints=[
        {"rule_id": "PAGE-4-max_pages", "key": "undecided", "value": "max_pages",
         "enforcement": "ADVISORY_HIGH_RISK",
         "rule_text": "Short CV (max. 2 pages) from this academic supervisor.",
         "readings": {"key": "max_pages", "values": [2, 3]}},
        {"rule_id": "PAGE-4-third_par", "key": "undecided", "value": "third_party",
         "enforcement": "ADVISORY_HIGH_RISK",
         "rule_text": "Short CV (max. 2 pages) from this academic supervisor."},
    ])
    resolved = resolve_rules(programme, None, content=_taught_content())
    assert [(r.key, r.value, r.enforcement) for r in resolved] == [
        ("undecided", "third_party", Enforcement.ADVISORY_HIGH_RISK)
    ]


def test_a_for_information_rule_never_refuses_a_cv():
    """An ai_use_policy row seeded BINDING by mistake still cannot block."""
    _rule(rule_id="L-041", scope_kind=CatalogRule.ScopeKind.INSTITUTION,
          scope_values=["gb:university of cambridge"], key="ai_use_policy",
          value="PROHIBITS", enforcement="BINDING")
    cambridge = _programme(country_code="GB")
    cambridge.institution.canonical_key = "gb:university of cambridge"
    cambridge.institution.save(update_fields=["canonical_key"])

    resolved = resolve_rules(cambridge, None, content=_taught_content())

    assert [r.enforcement for r in resolved] == [Enforcement.ADVISORY_HIGH_RISK]
    render_cv(_taught_content(), variant="STANDARD", constraints=resolved)


def test_no_seed_rule_of_ours_is_binding_on_a_content_only_key():
    """Pins the one gap "theirs beat ours, even when soft" (spec §6.4) leaves.

    A page rule beats ours outright and only inherits our force, so a page
    `date_of_issue_required=False` over a BINDING rule of ours would merge to
    a BINDING False, which _blocked_by_content_only_rules lets through -- and
    EUROPASS_API would send the student's data to europa.eu. Among theirs the
    stricter value wins, so only theirs are protected by the merge itself.
    """
    from apps.documents.catalog_seed import SEED_RULES
    from apps.documents.render import _CONTENT_ONLY_KEYS

    ours_binding = [
        (row["rule_id"], row["scope_kind"], row["key"])
        for row in SEED_RULES
        if row["scope_kind"] in {"UNIVERSAL", "TRACK", "COUNTRY"}
        and row["enforcement"] == "BINDING"
        and row["key"] in _CONTENT_ONLY_KEYS
    ]
    assert ours_binding == [], (
        f"{ours_binding}: a BINDING UNIVERSAL/TRACK/COUNTRY rule on a content-only key "
        "needs its own guard first -- page rules beat ours (spec §6.4 step 3), so a "
        "soft page value can relax it and unblock the Europass PII egress."
    )


def test_a_binding_funder_section_cap_does_not_make_a_page_cap_on_another_section_binding():
    """Final review I3, end to end: SISGP's R-078 (experience, BINDING) and a
    page's soft "at most 3 publications". Before, both sections merged into
    one BINDING rule, and a student with four publications was refused by the
    pre-render gate on a sentence that was only ever advisory."""
    from apps.documents.render import RenderedArtifact, _blocked_by_content_only_rules
    from apps.documents.schemas import PublicationEntry

    _rule(rule_id="R-078", scope_kind=CatalogRule.ScopeKind.FUNDER, scope_values=["sisgp"],
          key="max_entries_per_section", value={"experience": 3})
    programme = _programme("SE", constraints=[
        _derived("max_entries_per_section", {"publications": 3}, "List at most 3 publications."),
    ])
    content = _taught_content().model_copy(update={"publications": tuple(
        PublicationEntry(authors=("Jane Doe",), title=f"Paper {n}") for n in range(4)
    )})
    placeholder = RenderedArtifact(
        variant="EUROPASS_API", pdf_bytes=None, field_mapped=None, page_count=None, byte_size=0
    )

    resolved = resolve_rules(programme, _opportunity("sisgp"), content=content)

    assert [(r.value, r.enforcement) for r in resolved if r.key == "max_entries_per_section"] == [
        ({"publications": 3}, Enforcement.ADVISORY_HIGH_RISK),
        ({"experience": 3}, Enforcement.BINDING),
    ]
    assert _blocked_by_content_only_rules(content, resolved, placeholder) is False


def test_a_page_rule_cannot_relax_a_binding_funder_date_of_issue_and_unlock_europass():
    """Among theirs the stricter value wins (spec §6.4 step 4), so a page saying
    no date of issue is needed leaves the funder's BINDING requirement, and the
    pre-render gate still refuses the EUROPASS_API egress."""
    from apps.documents.render import RenderedArtifact, _blocked_by_content_only_rules

    _rule(
        rule_id="R-010",
        scope_kind=CatalogRule.ScopeKind.FUNDER,
        scope_values=["daad"],
        key="date_of_issue_required",
        value=True,
        enforcement="BINDING",
    )
    programme = _programme("DE", constraints=[_derived("date_of_issue_required", False)])
    content = _taught_content()
    placeholder = RenderedArtifact(
        variant="EUROPASS_API", pdf_bytes=None, field_mapped=None, page_count=None, byte_size=0
    )

    resolved = resolve_rules(programme, _opportunity("daad"), content=content)

    assert _blocked_by_content_only_rules(content, resolved, placeholder) is True


def test_a_binding_funder_date_of_issue_stored_as_one_still_blocks_europass_beside_a_page_false():
    """render._check_date_of_issue tests truthiness, the merge tested `is True`:
    a BINDING `1` merged to False and opened the Europass egress. A non-bool
    value now stands alone with its own force, so the gate still fires."""
    from apps.documents.render import RenderedArtifact, _blocked_by_content_only_rules

    _rule(
        rule_id="R-010",
        scope_kind=CatalogRule.ScopeKind.FUNDER,
        scope_values=["daad"],
        key="date_of_issue_required",
        value=1,
        enforcement="BINDING",
    )
    programme = _programme("DE", constraints=[_derived("date_of_issue_required", False)])
    content = _taught_content()
    placeholder = RenderedArtifact(
        variant="EUROPASS_API", pdf_bytes=None, field_mapped=None, page_count=None, byte_size=0
    )

    resolved = resolve_rules(programme, _opportunity("daad"), content=content)

    assert _blocked_by_content_only_rules(content, resolved, placeholder) is True


def test_a_together_awards_funder_rule_reaches_the_programmes_list(program_factory):
    programme = program_factory()
    emjm = _award(route="JOINT_SELECTION", cv_format_requirement="europass_required")
    _funder_rule(emjm, "R-900", "max_pages", 3, enforcement="BINDING")
    built = build_requirements(
        programme, together=[emjm], catalog=CatalogRule.objects.order_by("rule_id")
    )
    item = next(i for i in built.items if i.key == "max_pages")
    assert (item.value, item.origin, item.force) == (3, "scholarship", "strict")


def test_a_together_award_brings_its_format_when_the_card_has_none(program_factory):
    built = build_requirements(
        program_factory(), together=[_award(cv_format_requirement="europass_required")]
    )
    fmt = next(i for i in built.items if i.key == "cv_format")
    assert (fmt.value, fmt.origin) == ("europass_required", "scholarship")


def test_a_together_award_adds_no_non_funder_catalog_rule_twice(program_factory):
    programme = program_factory()  # country DE
    award = _award()
    _rule(rule_id="S-900", scope_kind=CatalogRule.ScopeKind.UNIVERSAL, scope_values=[],
          key="max_bytes", value=1000, enforcement="ADVISORY_STYLE")
    _rule(rule_id="C-900", scope_kind=CatalogRule.ScopeKind.COUNTRY, scope_values=["DE"],
          key="photo_allowed", value=False, enforcement="ADVISORY_STYLE")
    _funder_rule(award, "R-901", "max_pages", 3, enforcement="BINDING")
    catalog = CatalogRule.objects.order_by("rule_id")
    alone = build_requirements(programme, catalog=catalog)
    joined = build_requirements(programme, together=[award], catalog=catalog)
    # A rule added twice shows up as a repeated contributor on its item.
    assert [i.contributors for i in alone.items] == [
        i.contributors for i in joined.items if i.key != "max_pages"
    ]
    assert {"max_bytes", "photo_allowed"} <= {i.key for i in alone.items}
    funder = [i for i in joined.items if i.key == "max_pages"]
    assert [(i.value, i.origin) for i in funder] == [(3, "scholarship")]
    assert not [i for i in alone.items if i.key == "max_pages"]


def test_seeded_sisgp_max_pages_and_cambridge_max_bytes_resolve():
    from apps.documents.catalog_seed import seed_cv_rules

    _every_seed_funder()
    seed_cv_rules()

    sisgp = FundingOpportunity.objects.get(canonical_key="sisgp")
    se_prog = _programme("SE")
    sisgp_rules = {
        r.key: (r.rule_id, r.value, r.enforcement)
        for r in resolve_rules(se_prog, sisgp, content=_taught_content())
    }
    assert sisgp_rules["max_pages"] == ("R-078", 3, Enforcement.BINDING)
    assert sisgp_rules["max_entries_per_section"] == (
        "R-078",
        {"experience": 3},
        Enforcement.BINDING,
    )

    cambridge = _programme("GB")
    cambridge.institution.canonical_key = "gb:university of cambridge"
    cambridge.institution.save(update_fields=["canonical_key"])
    cam_rules = {
        r.key: (r.rule_id, r.value, r.enforcement)
        for r in resolve_rules(cambridge, None, content=_taught_content())
    }
    assert cam_rules["max_bytes"] == ("R-082", 2097152, Enforcement.BINDING)
    assert cam_rules["ai_use_policy"] == ("L-041", "PROHIBITS", Enforcement.ADVISORY_HIGH_RISK)

    aus_awards = FundingOpportunity.objects.get(canonical_key="australia-awards")
    assert aus_awards.cv_format_requirement == ""

    nawa_pmfc = FundingOpportunity.objects.get(canonical_key="nawa-pmfc")
    assert nawa_pmfc.cv_format_requirement == "structured_fields_only"


def test_seeded_eth_zurich_and_tum_institution_rules_resolve_and_ask_for_upper_secondary(
    agency_a, membership_a
):
    from apps.documents.catalog_seed import seed_cv_rules
    from apps.documents.gaps import upper_secondary_required

    _every_seed_funder()
    seed_cv_rules()

    eth = _programme("CH")
    eth.institution.canonical_key = "ch:eth zurich"
    eth.institution.save(update_fields=["canonical_key"])
    eth_rules = {
        r.key: (r.rule_id, r.value, r.enforcement)
        for r in resolve_rules(eth, None, content=_taught_content())
    }
    assert eth_rules["no_unexplained_gaps"] == ("S-047", 3, Enforcement.BINDING)
    assert eth_rules["cv_scope"] == ("S-047", "complete", Enforcement.BINDING)
    assert eth_rules["cv_start"] == (
        "S-047",
        {"start": "upper_secondary"},
        Enforcement.ADVISORY_HIGH_RISK,
    )

    with tenant_scope(agency_a.id):
        questions = upper_secondary_required(membership_a, eth)
    assert [q.payload_key for q in questions] == ["institution_original", "degree_as_awarded"]

    tum = _programme("DE")
    tum.institution.canonical_key = "de:technical university of munich"
    tum.institution.save(update_fields=["canonical_key"])
    tum_rules = {
        r.key: (r.rule_id, r.value, r.enforcement)
        for r in resolve_rules(tum, None, content=_taught_content())
    }
    assert tum_rules["no_unexplained_gaps"] == ("S-047", 3, Enforcement.BINDING)
    assert tum_rules["font"] == (
        "S-047",
        "Times New Roman or Arial, 12 point",
        Enforcement.ADVISORY_HIGH_RISK,
    )
    assert tum_rules["date_of_birth_allowed"] == ("S-047", True, Enforcement.ADVISORY_STYLE)



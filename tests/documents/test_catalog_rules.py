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
    _rule(
        rule_id="R-010",
        scope_kind=CatalogRule.ScopeKind.UNIVERSAL,
        scope_values=[],
        key="date_of_issue_required",
        value=True,
        enforcement="BINDING",
    )
    programme = _programme("DE", constraints=[_derived("date_of_issue_required", False)])

    resolved = resolve_rules(programme, None, content=_taught_content())

    kept = [r for r in resolved if r.key == "date_of_issue_required"]
    assert [r.rule_id for r in kept] == ["R-010"]
    assert kept[0].enforcement == Enforcement.BINDING
    assert kept[0].value is True


def test_an_advisory_programme_rule_still_wins_where_nothing_binding_covers_the_key():
    """Specificity is preserved everywhere it is safe -- the guard is narrow."""
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


def test_a_binding_programme_rule_still_replaces_a_binding_catalog_one():
    """A hand-curated programme rule is the most specific there is; the guard
    is about enforcement level, never about where the rule came from."""
    _rule(
        rule_id="R-010",
        scope_kind=CatalogRule.ScopeKind.UNIVERSAL,
        scope_values=[],
        key="date_of_issue_required",
        value=True,
        enforcement="BINDING",
    )
    curated = _derived("date_of_issue_required", False)
    curated |= {"rule_id": "R-999", "enforcement": "BINDING"}
    programme = _programme("DE", constraints=[curated])

    resolved = resolve_rules(programme, None, content=_taught_content())

    assert [r.rule_id for r in resolved if r.key == "date_of_issue_required"] == ["R-999"]


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

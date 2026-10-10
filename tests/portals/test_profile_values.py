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


def test_a_gap_statement_is_a_portal_value(agency_a, membership_a):
    """A gap statement is printed on the CV and nowhere else -- typed into a
    portal field it would leave the one document it was written for."""
    from apps.documents.models import VerifiedFact
    from apps.portals.profile import verified_values

    with tenant_scope(agency_a.id):
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.TIMELINE,
            {
                "start_date": "2023-06-30",
                "end_date": "2023-11-01",
                "statement": "Full-time carer for a family member.",
            },
        )
        _fact(agency_a, membership_a, VerifiedFact.Category.IDENTITY, {"full_name": "Ada Byron"})

        values = verified_values(membership_a)
        assert values["identity.full_name"] == "Ada Byron"
        assert values["timeline.statement"] == "Full-time carer for a family member."

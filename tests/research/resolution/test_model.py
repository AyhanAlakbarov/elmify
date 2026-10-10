"""Spec 11: "The item carries nothing about a person, and that is a rule."

A platform table sits outside tenant RLS and outside advance_deletion's sweep.
A person pointer here is the documents.EuropassRenderCache shape: a personal
datum nothing erases.
"""

import pytest
from django.apps import apps
from django.db import IntegrityError
from django.utils import timezone

from apps.research.models import PlatformAgency, ResolutionItem
from apps.tenancy.models import TenantScopedModel

pytestmark = pytest.mark.django_db

_PERSON_MODELS = {"tenancy.membership", "audit.pseudonym", "auth.user", "accounts.user"}


def _new(**fields):
    now = timezone.now()
    defaults = {"evidence": {}, "ask": "?", "options": [], "refreshed_at": now, "expires_at": now}
    return ResolutionItem.objects.create(**{**defaults, **fields})


def test_the_item_points_at_no_person_and_no_tenant() -> None:
    assert not issubclass(ResolutionItem, TenantScopedModel)
    for field in ResolutionItem._meta.get_fields():
        related = getattr(field, "related_model", None)
        if related is None:
            continue
        label = related._meta.label_lower
        assert label not in _PERSON_MODELS, field.name
        assert not issubclass(related, TenantScopedModel), field.name
    assert "tenant" not in {f.name for f in ResolutionItem._meta.get_fields()}


def test_no_other_model_points_at_the_item() -> None:
    """Rows are deleted when applied (plan: queue, not ledger); an inbound FK
    would either block that delete or cascade into something that remembers."""
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if getattr(field, "related_model", None) is ResolutionItem and field.concrete:
                pytest.fail(f"{model._meta.label}.{field.name} points at ResolutionItem")


def test_the_platform_marker_names_an_agency_and_nothing_else() -> None:
    """PlatformAgency holds one agency id -- no person, no tenant data."""
    related = {
        field.related_model._meta.label_lower
        for field in PlatformAgency._meta.get_fields()
        if getattr(field, "related_model", None) is not None and field.concrete
    }
    assert related == {"tenancy.agency"}
    assert not issubclass(PlatformAgency, TenantScopedModel)


def test_one_live_question_per_subject() -> None:
    _new(kind="HOST_UNREACHABLE", subject_key="host:a.test")
    with pytest.raises(IntegrityError):
        _new(kind="HOST_UNREACHABLE", subject_key="host:a.test")


def test_the_subject_prefix_matches_the_kind() -> None:
    with pytest.raises(IntegrityError):
        _new(kind="HOST_UNREACHABLE", subject_key="award:x")


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(IntegrityError):
        _new(kind="SOMETHING_ELSE", subject_key="host:c.test")


def test_a_decided_item_carries_its_resolution() -> None:
    with pytest.raises(IntegrityError):
        _new(kind="HOST_UNREACHABLE", subject_key="host:b.test", state="DECIDED")


def test_an_open_item_carries_no_resolution() -> None:
    with pytest.raises(IntegrityError):
        _new(kind="HOST_UNREACHABLE", subject_key="host:d.test", resolution={"option": "closed"})


def test_the_subject_facts_default_to_unknown_and_unregistered() -> None:
    """Delta D3: the web tier cannot read the catalogue, so the writer stamps
    the two facts the sort needs onto the item. Unstamped means unknown -- an
    empty country and not registered -- never a guess."""
    item = _new(kind="HOST_UNREACHABLE", subject_key="host:e.test")
    item.refresh_from_db()
    assert (item.country_code, item.registered) == ("", False)

import pytest

from apps.audit.exports import build_export


@pytest.mark.django_db
def test_export_denies_cross_tenant_student(agency_a, agency_b, membership_a):
    with pytest.raises(ValueError):
        build_export(agency_b.id, membership_a.id)


@pytest.mark.django_db
def test_export_includes_manifest_and_dossier(agency_a, membership_a):
    archive = build_export(agency_a.id, membership_a.id)
    assert b"manifest.json" in archive  # ZIP central directory carries entry names
    assert b"dossier.html" in archive

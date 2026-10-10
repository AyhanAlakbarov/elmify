import pytest

from apps.privacy import documents
from apps.privacy.models import LegalDocument


@pytest.mark.django_db
def test_publishing_new_text_adds_a_version_and_same_text_does_not():
    first, created = documents.publish("terms", "en", "Terms v1", material=True)
    assert created and first.version == 1
    again, created = documents.publish("terms", "en", "Terms v1", material=True)
    assert not created and again.pk == first.pk
    second, created = documents.publish("terms", "en", "Terms v2", material=False)
    assert created and second.version == 2 and second.material is False
    assert LegalDocument.objects.filter(kind="terms", language="en").count() == 2


@pytest.mark.django_db
def test_current_falls_back_to_english():
    documents.publish("terms", "en", "Terms", material=True)
    assert documents.current("terms", "az").language == "en"
    documents.publish("terms", "az", "Şərtlər", material=True)
    assert documents.current("terms", "az").language == "az"
    assert documents.current("privacy_notice_direct", "az") is None


@pytest.mark.django_db
def test_publish_refuses_unknown_kind_and_language():
    with pytest.raises(ValueError):
        documents.publish("cookies", "en", "x", material=True)
    with pytest.raises(ValueError):
        documents.publish("terms", "de", "x", material=True)


@pytest.mark.django_db
def test_command_publishes_every_shipped_file(capsys):
    from django.core.management import call_command

    call_command("publish_legal_documents")
    kinds = set(LegalDocument.objects.values_list("kind", flat=True))
    assert kinds == {"terms", "privacy_notice_direct", "privacy_notice_agency"}
    call_command("publish_legal_documents")  # idempotent
    assert LegalDocument.objects.filter(kind="terms", language="en").count() == 1


REQUIRED_NOTICE_TOPICS = ("privacy@", "7 working days", "12 months", "anonymised", "China")


def test_every_kind_ships_in_every_language():
    shipped = {(kind, lang) for kind, lang, _ in documents.shipped_files()}
    assert shipped == {(k, lang) for k in documents.KINDS for lang in documents.LANGUAGES}


def test_english_notices_carry_what_the_law_requires():
    for kind in ("privacy_notice_direct", "privacy_notice_agency"):
        text = (documents.LEGAL_DIR / f"{kind}.en.md").read_text(encoding="utf-8")
        for topic in REQUIRED_NOTICE_TOPICS:
            assert topic in text, (kind, topic)


def test_every_translation_is_marked_as_a_draft_for_the_lawyer():
    for kind, lang, path in documents.shipped_files():
        if lang != "en":
            assert "DRAFT" in path.read_text(encoding="utf-8").splitlines()[0], path.name


def test_agency_notice_names_the_agency_placeholder_in_every_language():
    for lang in documents.LANGUAGES:
        path = documents.LEGAL_DIR / f"privacy_notice_agency.{lang}.md"
        assert "{{ agency }}" in path.read_text(encoding="utf-8"), lang


def test_agency_notice_promises_no_marketing_in_any_language():
    # The English word, and the stems of the marketing sentences removed from az and ru.
    stems = {"en": "marketing", "az": "marketinq", "ru": "маркетинг"}
    for lang, stem in stems.items():
        path = documents.LEGAL_DIR / f"privacy_notice_agency.{lang}.md"
        assert stem not in path.read_text(encoding="utf-8").lower(), lang

import pytest

from apps.concierge.documents import DocumentUnavailable, apply_scan_result, register


@pytest.mark.django_db
def test_document_is_unreadable_until_clean(agency_a, membership_a, fake_store):
    document = register(agency_a.id, membership_a.id)
    assert document.state == "QUARANTINED"
    with pytest.raises(DocumentUnavailable):
        from apps.concierge.documents import open_document

        open_document(document, store=fake_store)


@pytest.mark.django_db
def test_no_threats_found_promotes_to_available(agency_a, membership_a, fake_store):
    document = register(agency_a.id, membership_a.id)
    updated = apply_scan_result(document, "NO_THREATS_FOUND")
    assert updated.state == "AVAILABLE"


@pytest.mark.django_db
def test_threats_found_permanently_blocked(agency_a, membership_a, fake_store):
    document = register(agency_a.id, membership_a.id)
    updated = apply_scan_result(document, "THREATS_FOUND")
    assert updated.state == "BLOCKED"


@pytest.mark.parametrize("result", ["UNSUPPORTED", "ACCESS_DENIED", "FAILED"])
@pytest.mark.django_db
def test_ambiguous_scan_results_require_review(agency_a, membership_a, fake_store, result):
    document = register(agency_a.id, membership_a.id)
    updated = apply_scan_result(document, result)
    assert updated.state == "REVIEW_REQUIRED"


@pytest.mark.django_db
def test_available_document_reads_its_checked_copy(agency_a, membership_a, fake_store):
    """The promoted copy, never the quarantine key: a newer version there is unchecked."""
    from apps.concierge.documents import open_document
    from tests.uploads import promoted_upload

    document = register(agency_a.id, membership_a.id)
    fake_store.put(document.object_key, b"clean-file-bytes")
    promoted_upload(document, fake_store, b"clean-file-bytes")
    fake_store.put(document.object_key, b"<html>uploaded again, never scanned")

    assert open_document(document, store=fake_store) == b"clean-file-bytes"


@pytest.mark.django_db
def test_a_scanned_clean_document_with_no_checked_copy_is_unreadable(
    agency_a, membership_a, fake_store
):
    from apps.concierge.documents import open_document

    document = register(agency_a.id, membership_a.id)
    fake_store.put(document.object_key, b"clean-file-bytes")
    apply_scan_result(document, "NO_THREATS_FOUND")
    with pytest.raises(DocumentUnavailable):
        open_document(document, store=fake_store)


@pytest.mark.django_db
def test_object_key_is_confined_to_the_owning_tenant(agency_a, agency_b, membership_a):
    """The key is derived, never supplied -- it cannot name another tenant."""
    document = register(agency_a.id, membership_a.id)
    assert document.object_key == f"quarantine/{agency_a.id}/{document.id}"
    assert str(agency_b.id) not in document.object_key


class _FakePresigner:
    """Captures what would be signed. boto3 does no network call for
    generate_presigned_post either, but the point here is the conditions."""

    def __init__(self):
        self.calls = []

    def generate_presigned_post(self, **kwargs):
        self.calls.append(kwargs)
        return {"url": "https://s3.example.test/bucket", "fields": {"key": kwargs["Key"]}}


@pytest.mark.django_db
def test_presigned_upload_pins_the_exact_key_by_equality(agency_a, membership_a):
    """Equality, never starts-with. A prefix condition would let one student's
    signed form write anywhere under that prefix -- including over another of
    their own documents, after it had already been scanned clean."""
    from apps.concierge.documents import presigned_upload

    document = register(agency_a.id, membership_a.id)
    client = _FakePresigner()

    presigned_upload(document, client=client)

    conditions = client.calls[0]["Conditions"]
    assert {"key": document.object_key} in conditions
    assert not any(
        isinstance(condition, list) and condition[0] == "starts-with"
        for condition in conditions
    )


@pytest.mark.django_db
def test_presigned_upload_caps_the_size_and_the_clock(agency_a, membership_a):
    from apps.concierge.documents import presigned_upload

    document = register(agency_a.id, membership_a.id)
    client = _FakePresigner()

    presigned_upload(document, client=client)

    call = client.calls[0]
    (ceiling,) = [
        condition
        for condition in call["Conditions"]
        if isinstance(condition, list) and condition[0] == "content-length-range"
    ]
    assert ceiling[1] == 1
    assert ceiling[2] == _ocr_max_bytes()
    assert 0 < call["ExpiresIn"] <= 900


def _ocr_max_bytes() -> int:
    """ocr/read_pages.py's MAX_BYTES, read from its source: the module imports
    cv2 and pdfium, which this environment does not carry."""
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).parents[2] / "ocr" / "read_pages.py").read_text())
    (value,) = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and [getattr(t, "id", None) for t in node.targets] == ["MAX_BYTES"]
        and isinstance(node.value, ast.Constant)
    ]
    assert isinstance(value, int)
    return value


def test_the_presigned_ceiling_is_the_ocr_functions_ceiling():
    """One limit. The Lambda refuses anything over MAX_BYTES before ``inspect``;
    a presign ceiling above it let a file pass S3 and the scan, then end
    REVIEW_REQUIRED after three redeliveries with no word to the student."""
    from apps.concierge.documents import _MAX_UPLOAD_BYTES

    assert _MAX_UPLOAD_BYTES == _ocr_max_bytes() == 10_000_000


@pytest.mark.django_db
def test_presigned_upload_takes_the_key_from_the_row(agency_a, membership_a, settings):
    """The key is not a parameter: register() derived it from the row, so a
    caller cannot aim an upload outside its own tenant's prefix."""
    from apps.concierge.documents import presigned_upload

    document = register(agency_a.id, membership_a.id)
    client = _FakePresigner()

    presigned_upload(document, client=client)

    assert client.calls[0]["Key"] == f"quarantine/{agency_a.id}/{document.id}"
    assert client.calls[0]["Bucket"] == settings.EVIDENCE_BUCKET_NAME


@pytest.mark.django_db
def test_an_unknown_scan_status_lands_in_review_instead_of_raising(agency_a, membership_a):
    """AWS may add a sixth scanResultStatus. A KeyError here would kill the
    scan handler, SQS would redeliver the same message, and every other
    student's upload would wait behind it until the DLQ caught it."""
    document = register(agency_a.id, membership_a.id)

    updated = apply_scan_result(document, "SOMETHING_NEW")

    assert updated.state == "REVIEW_REQUIRED"
    assert updated.scan_result == "SOMETHING_NEW"

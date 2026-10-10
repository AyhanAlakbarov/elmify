"""Every HTML page carries a Content-Security-Policy (security review L4).

Mail-derived text is rendered on the dashboard; autoescaping is the first line
of defence and this header the second.
"""

import re
from pathlib import Path
from urllib.parse import urlsplit

import boto3
import pytest
from django.conf import settings
from django.http import HttpResponse

from apps.tenancy.middleware import content_security_policy

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[2]


def _directives(response) -> dict[str, list[str]]:
    header = response["Content-Security-Policy"]
    return {
        name: values
        for name, *values in (part.split() for part in header.split(";") if part.strip())
    }


@pytest.mark.parametrize("page", ["/student/", "/student/documents/"])
def test_a_student_page_carries_a_strict_policy(client, domain_a, user_a, membership_a, page):
    client.force_login(user_a)

    response = client.get(page, HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    policy = _directives(response)
    assert policy["default-src"] == ["'self'"]
    assert policy["script-src"] == ["'self'"]
    assert policy["style-src"] == ["'self'"]
    assert policy["img-src"] == ["'self'", "data:"]
    assert policy["object-src"] == ["'none'"]
    assert policy["base-uri"] == ["'none'"]
    assert policy["frame-ancestors"] == ["'none'"]


def test_the_documents_script_loads_from_self_and_its_upload_target_is_allowed(
    client, domain_a, user_a, membership_a
):
    """documents.js is a same-origin static file, and it POSTs the file to the
    URL boto3 presigns for the evidence bucket -- connect-src must name that
    host and nothing wider."""
    client.force_login(user_a)
    response = client.get("/student/documents/", HTTP_HOST=domain_a.host)
    body = response.content.decode()
    policy = _directives(response)

    [src] = re.findall(r'<script src="([^"]+)"', body)
    assert src.startswith(settings.STATIC_URL) and src.startswith("/")
    presigned = boto3.client(
        "s3", region_name="eu-central-1", aws_access_key_id="x", aws_secret_access_key="y"
    ).generate_presigned_post(Bucket=settings.EVIDENCE_BUCKET_NAME, Key="quarantine/k")["url"]
    upload = urlsplit(presigned)
    assert policy["connect-src"] == ["'self'", f"{upload.scheme}://{upload.netloc}"]


def test_the_mailbox_connect_redirect_is_an_allowed_form_target(
    client, domain_a, user_a, membership_a
):
    """The Connect forms GET our own route, which redirects to the provider;
    browsers check form-action against that redirect too."""
    client.force_login(user_a)
    policy = _directives(client.get("/student/", HTTP_HOST=domain_a.host))

    assert policy["form-action"] == [
        "'self'",
        "https://accounts.google.com",
        "https://login.microsoftonline.com",
    ]


def test_a_json_response_is_left_alone(client, domain_a):
    response = client.post("/ext/mailbox/check", HTTP_HOST=domain_a.host)

    assert response.status_code == 401
    assert "Content-Security-Policy" not in response


def test_a_response_with_its_own_policy_keeps_it():
    served = HttpResponse(b"<p>x</p>", content_type="text/html")
    served["Content-Security-Policy"] = "sandbox; default-src 'none'"

    response = content_security_policy(lambda request: served)(None)

    assert response["Content-Security-Policy"] == "sandbox; default-src 'none'"


def test_no_served_template_carries_inline_script_style_or_handlers():
    """'self' only works if nothing is inline. The document templates under
    apps/documents/templates are rendered to PDF, never served, so they are out."""
    served = [ROOT / "templates", *ROOT.glob("apps/*/templates")]
    offenders = [
        f"{path.relative_to(ROOT)}: {match}"
        for directory in served
        for path in directory.rglob("*.html")
        if "apps/documents/templates" not in str(path)
        for match in re.findall(
            r"<script(?![^>]*\ssrc=)[^>]*>|<style|\sstyle=|\son[a-z]+=|javascript:",
            path.read_text(),
        )
    ]

    assert offenders == []

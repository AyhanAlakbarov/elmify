"""The owner's gold checking page: platform operator only, one label per item.

The test database role bypasses RLS, so these check the view's logic; the
GoldItem policies are proven in test_gold_rls.py.
"""

import pytest
from django.urls import reverse

from apps.funding.models import AuditEvent
from apps.research.models import GoldItem
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.conftest import verify_mfa_session
from tests.research.resolution import conftest as _resolution

pytestmark = pytest.mark.django_db

# The platform-operator fixtures the resolution console's tests already define.
platform = _resolution.platform
platform_domain = _resolution.platform_domain
operator = _resolution.operator
operator_user = _resolution.operator_user


def _item(**kw):
    base = dict(
        run="r1", kind="deadline", question="application_date", language="az",
        page_url="https://edu.gov.az/x", line_text="Müraciət 15 yanvar 2027-dək.",
        heading="Müraciət", claim="This line states a deadline or period for applying.",
        round=1, purpose="improvement",
    )
    return GoldItem.objects.create(**(base | kw))


@pytest.fixture
def signed_in(client, platform_domain, operator_user, operator):
    client.force_login(operator_user)
    verify_mfa_session(client, operator_user)
    return client


def _labelled(platform, **kw):
    with tenant_scope(platform.id):
        return AuditEvent.objects.filter(event="gold.labelled", **kw).exists()


def _post(client, host, item, data):
    return client.post(reverse("gold-label", args=[item.id]), data, HTTP_HOST=host)


def test_a_non_operator_is_refused(client, platform, platform_domain, django_user_model):
    user = django_user_model.objects.create_user(username="student-x")
    with tenant_scope(platform.id):
        Membership.objects.create(tenant=platform, user=user, role=Membership.Role.STUDENT)
    client.force_login(user)
    verify_mfa_session(client, user)
    item = _item()
    assert client.get(reverse("gold-queue"), HTTP_HOST=platform_domain.host).status_code == 403
    assert _post(client, platform_domain.host, item, {"verdict": "correct"}).status_code == 403
    item.refresh_from_db()
    assert item.verdict == ""


def test_an_operator_without_mfa_is_refused(
    client, platform_domain, operator_user, operator
):
    client.force_login(operator_user)  # no verify_mfa_session
    item = _item()
    resp = client.get(reverse("gold-queue"), HTTP_HOST=platform_domain.host)
    assert resp.status_code in (302, 403)
    resp = _post(client, platform_domain.host, item, {"verdict": "correct"})
    assert resp.status_code in (302, 403)
    item.refresh_from_db()
    assert item.verdict == ""


def test_the_queue_lists_unchecked_items_with_counts(signed_in, platform_domain):
    _item(line_text="open one")
    _item(line_text="done one", verdict="correct")
    resp = signed_in.get(reverse("gold-queue"), HTTP_HOST=platform_domain.host)
    assert resp.status_code == 200
    assert [i.line_text for i in resp.context["items"]] == ["open one"]
    assert resp.context["counts"] == [(("deadline", "improvement"), {"checked": 1, "unchecked": 1})]


def test_the_operator_labels_correct(signed_in, platform, platform_domain, operator):
    item = _item()
    resp = _post(signed_in, platform_domain.host, item, {"verdict": "correct"})
    assert resp.status_code == 302
    item.refresh_from_db()
    assert item.verdict == "correct" and item.labelled_at is not None
    assert _labelled(platform, object_id=item.id, actor=operator)


def test_wrong_needs_a_fix(signed_in, platform, platform_domain):
    item = _item()
    resp = _post(signed_in, platform_domain.host, item, {"verdict": "wrong"})
    assert resp.status_code == 400
    item.refresh_from_db()
    assert item.verdict == ""
    assert not _labelled(platform)


def test_wrong_with_a_fix_is_kept(signed_in, platform_domain):
    item = _item()
    _post(signed_in, platform_domain.host, item, {"verdict": "wrong", "fix": "15 fevral"})
    item.refresh_from_db()
    assert (item.verdict, item.fix) == ("wrong", "15 fevral")


def test_an_overlong_fix_is_refused(signed_in, platform_domain):
    item = _item()
    resp = _post(signed_in, platform_domain.host, item, {"verdict": "wrong", "fix": "x" * 2001})
    assert resp.status_code == 400
    item.refresh_from_db()
    assert item.verdict == ""


def test_an_unknown_verdict_is_refused(signed_in, platform_domain):
    item = _item()
    assert _post(signed_in, platform_domain.host, item, {"verdict": "maybe"}).status_code == 400


def test_not_on_page_is_kept_as_a_verdict(signed_in, platform_domain):
    item = _item()
    _post(signed_in, platform_domain.host, item, {"verdict": "not_on_page"})
    item.refresh_from_db()
    assert item.verdict == "not_on_page"


def test_a_labelled_item_is_not_relabelled(signed_in, platform, platform_domain):
    item = _item(verdict="correct")
    resp = _post(signed_in, platform_domain.host, item, {"verdict": "wrong", "fix": "x"})
    assert resp.status_code == 409
    item.refresh_from_db()
    assert (item.verdict, item.fix) == ("correct", "")
    assert not _labelled(platform)

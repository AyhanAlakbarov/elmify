"""Wizard sequencing 400s re-render the wizard, not a bare string.

The wizard posts with hx-target="#consultation" hx-swap="outerHTML", and
base.html's htmx-config makes 400 swap, so a bare-text 400 body replaces the
whole wizard section with the raw message. These two failures re-render the
state the student is actually in, carrying the message through the established
error context.

Both are out-of-sequence posts rather than typed-input mistakes: they are
reachable by a stale tab, a double submit, or a replayed form.
"""

import pytest

from apps.accounts.consultation import QUESTIONS


@pytest.mark.frontend
@pytest.mark.django_db
def test_confirm_before_completion_rerenders_the_wizard(
    client, domain_a, user_a, membership_a
) -> None:
    client.force_login(user_a)
    response = client.post(
        "/student/profile/",
        {"action": "confirm"},
        HTTP_HOST=domain_a.host,
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 400
    body = response.content.decode()
    assert 'role="alert"' in body
    assert "consultation is incomplete" in body
    # The wizard came back, not a bare string: the next question still renders.
    assert 'name="key"' in body


@pytest.mark.frontend
@pytest.mark.django_db
def test_answer_for_the_wrong_question_rerenders_the_wizard(
    client, domain_a, user_a, membership_a
) -> None:
    """A stale tab posts an answer keyed to a question that is no longer next."""
    client.force_login(user_a)
    stale_key = QUESTIONS[-1].key

    response = client.post(
        "/student/profile/",
        {"key": stale_key, "value": "whatever"},
        HTTP_HOST=domain_a.host,
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 400
    body = response.content.decode()
    assert 'role="alert"' in body
    assert "unexpected consultation question" in body
    # Re-rendered with the question that IS next, so the student can continue.
    assert 'name="key"' in body

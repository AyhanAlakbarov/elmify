"""Two vendors, one seam, and a scope list that is the whole privacy surface.

The transport is faked at the urllib3 level rather than at the class level: the
things worth pinning here are the URL, the scope and the fact that a metadata
sync never asks for a body, and a fake class would let all three drift.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
import urllib3.exceptions

from apps.mailbox.providers import (
    MAX_PAGES_PER_SYNC,
    SCOPES,
    GoogleMailbox,
    MessageHeader,
    MicrosoftMailbox,
    ProviderError,
    provider_for,
)

_LONG_AGO = datetime(2026, 1, 1, tzinfo=UTC)


class FakeHTTP:
    """Stands in for urllib3.PoolManager. Records every request it is given."""

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, str, dict[str, str]]] = []

    def request(self, method, url, *, headers=None, fields=None, body=None, timeout=None, **_):
        self.requests.append((method, url, dict(headers or {})))
        for prefix, payload in self.responses.items():
            if url.startswith(prefix):
                return _Response(200, payload)
        return _Response(404, {"error": "not found"})


class _Response:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self.data = json.dumps(payload).encode()


def test_no_scope_anywhere_can_send() -> None:
    """The one assertion in this file that is not about behaviour.

    Every scope this platform will ever ask for is in this dict. A send scope
    appearing here is the failure the whole design exists to prevent, and it
    would arrive as a one-word edit.
    """
    every = {scope for scopes in SCOPES.values() for scope in scopes}
    assert not any("send" in scope.casefold() for scope in every)
    assert not any("readwrite" in scope.casefold() for scope in every)
    assert not any("mail.send" in scope.casefold() for scope in every)


def test_the_scopes_are_the_ones_the_spec_names() -> None:
    assert SCOPES[("GOOGLE", "METADATA")] == (
        "openid",
        "email",
        "https://www.googleapis.com/auth/gmail.metadata",
    )
    assert SCOPES[("GOOGLE", "CONTENT")] == (
        "openid",
        "email",
        "https://www.googleapis.com/auth/gmail.readonly",
    )


def test_google_lists_headers_without_asking_for_a_body() -> None:
    # Deviation from the brief: internalDate shifted +365 days (1758182400000
    # -> 1789718400000, 1758186000000 -> 1789722000000) from the literal in
    # the brief. Those decode to 2025-09-18/19, over a year before this repo's
    # actual clock (2026-09-18), which is well past FIRST_SYNC_DAYS=90 and
    # made list_headers's since=None default filter both messages out. The
    # relative shape (m2 one hour after m1) is unchanged.
    http = FakeHTTP(
        {
            "https://gmail.googleapis.com/gmail/v1/users/me/messages?": {
                "messages": [{"id": "m1"}, {"id": "m2"}]
            },
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/m1": {
                "id": "m1",
                "internalDate": "1789718400000",
                "payload": {"headers": [{"name": "From", "value": "a@tum.de"}]},
            },
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/m2": {
                "id": "m2",
                "internalDate": "1789722000000",
                "payload": {"headers": [{"name": "From", "value": "b@daad.de"}]},
            },
        }
    )

    headers = GoogleMailbox(http=http).list_headers(access_token="at", since=_LONG_AGO)

    assert [header.sender for header in headers] == ["a@tum.de", "b@daad.de"]
    assert all(isinstance(header, MessageHeader) for header in headers)
    urls = [url for _method, url, _headers in http.requests]
    assert all("format=full" not in url for url in urls)
    assert all("format=metadata" in url for url in urls if "/messages/m" in url)


def test_the_bearer_token_travels_in_the_header_and_never_in_the_url() -> None:
    http = FakeHTTP({"https://gmail.googleapis.com": {"messages": []}})

    GoogleMailbox(http=http).list_headers(access_token="secret-token", since=_LONG_AGO)

    _method, url, headers = http.requests[0]
    assert "secret-token" not in url
    assert headers["Authorization"] == "Bearer secret-token"


def test_a_body_is_decoded_with_the_charset_it_declares_and_capped() -> None:
    """The charset is the point, not the decoding.

    A German university writes in latin-1 more often than anyone expects. Read
    as utf-8 it reaches the classifier as mojibake -- silently, and looking
    exactly like a badly written email rather than like a bug.
    """
    import base64
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = "admissions@tum.de"
    message.set_content("Prüfungsordnung " + "x" * 40_000, charset="iso-8859-1")
    http = FakeHTTP(
        {
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/m1": {
                "id": "m1",
                "raw": base64.urlsafe_b64encode(bytes(message)).decode(),
            }
        }
    )

    body = GoogleMailbox(http=http).fetch_body(access_token="at", message_id="m1").text

    assert body.startswith("Prüfungsordnung")
    assert len(body) <= 20_000


def test_an_html_only_message_reads_as_empty_rather_than_as_markup() -> None:
    """An empty body classifies as nothing, which beats classifying markup."""
    import base64
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = "admissions@tum.de"
    message.set_content("<p>Welcome</p>", subtype="html")
    http = FakeHTTP(
        {
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/m1": {
                "id": "m1",
                "raw": base64.urlsafe_b64encode(bytes(message)).decode(),
            }
        }
    )

    assert GoogleMailbox(http=http).fetch_body(access_token="at", message_id="m1").text == ""


def test_a_delivery_verdict_is_read_off_the_headers() -> None:
    """dmarc=pass is what separates "TUM wrote" from "someone typed TUM"."""
    # Deviation from the brief: internalDate shifted +365 days, same reason as
    # test_google_lists_headers_without_asking_for_a_body above.
    http = FakeHTTP(
        {
            "https://gmail.googleapis.com/gmail/v1/users/me/messages?": {
                "messages": [{"id": "m1"}]
            },
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/m1": {
                "id": "m1",
                "internalDate": "1789718400000",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "a@tum.de"},
                        {
                            "name": "Authentication-Results",
                            "value": "mx.google.com; dmarc=pass header.from=tum.de",
                        },
                    ]
                },
            },
        }
    )

    headers = GoogleMailbox(http=http).list_headers(access_token="at", since=_LONG_AGO)

    assert headers[0].authenticated is True
    assert any("Authentication-Results" in url for _m, url, _h in http.requests)


def test_an_authentication_results_header_not_written_by_google_is_not_trusted() -> None:
    """The core regression test for the authserv-id bypass.

    Anyone sending mail can write their own Authentication-Results header
    claiming dmarc=pass; nothing stops it. Before the fix, the substring check
    ran over every header literally named Authentication-Results regardless of
    who added it, so this forged header alone would have authenticated the
    message. The fix must check WHO added the header (its authserv-id), not
    just what it says.
    """
    http = FakeHTTP(
        {
            "https://gmail.googleapis.com/gmail/v1/users/me/messages?": {
                "messages": [{"id": "m1"}]
            },
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/m1": {
                "id": "m1",
                "internalDate": "1789718400000",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "a@tum.de"},
                        {
                            "name": "Authentication-Results",
                            "value": "attacker.example; dmarc=pass",
                        },
                    ]
                },
            },
        }
    )

    headers = GoogleMailbox(http=http).list_headers(access_token="at", since=_LONG_AGO)

    assert headers[0].authenticated is False


def test_a_genuine_google_header_is_trusted() -> None:
    """Proves the fix does not just reject everything: a header whose
    authserv-id really is mx.google.com and which carries dmarc=pass still
    authenticates the message."""
    http = FakeHTTP(
        {
            "https://gmail.googleapis.com/gmail/v1/users/me/messages?": {
                "messages": [{"id": "m1"}]
            },
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/m1": {
                "id": "m1",
                "internalDate": "1789718400000",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "a@tum.de"},
                        {
                            "name": "Authentication-Results",
                            "value": "mx.google.com; dkim=pass; dmarc=pass header.from=tum.de",
                        },
                    ]
                },
            },
        }
    )

    headers = GoogleMailbox(http=http).list_headers(access_token="at", since=_LONG_AGO)

    assert headers[0].authenticated is True


def test_only_the_first_of_two_authentication_results_headers_is_trusted() -> None:
    """A forged header ahead of Google's own real one must not authenticate the
    message, and Google's own real one behind a forged one must not either --
    only the FIRST header counts, full stop.

    Tested ordering: attacker-style header first, genuine Google header
    second. Gmail's API returns headers in message order, and Gmail prepends
    its own verdict at final delivery, so a message delivered straight to the
    account (no forwarding after receipt) has Google's real header topmost --
    a forged header appearing before it is the attack this whole fix closes,
    since a sender fully controls what they put in their own message before
    Gmail ever adds its verdict.
    """
    http = FakeHTTP(
        {
            "https://gmail.googleapis.com/gmail/v1/users/me/messages?": {
                "messages": [{"id": "m1"}]
            },
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/m1": {
                "id": "m1",
                "internalDate": "1789718400000",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "a@tum.de"},
                        {
                            "name": "Authentication-Results",
                            "value": "attacker.example; dmarc=pass",
                        },
                        {
                            "name": "Authentication-Results",
                            "value": "mx.google.com; dkim=pass; dmarc=pass",
                        },
                    ]
                },
            },
        }
    )

    headers = GoogleMailbox(http=http).list_headers(access_token="at", since=_LONG_AGO)

    # The forged header came first, so it is the only one read -- and it is
    # not Google's, so the message is not authenticated even though a genuine
    # Google verdict is present later in the list.
    assert headers[0].authenticated is False


def test_a_refusal_from_the_provider_is_a_typed_error_carrying_no_token() -> None:
    class Refusing(FakeHTTP):
        def request(self, method, url, **kwargs):
            self.requests.append((method, url, dict(kwargs.get("headers") or {})))
            return _Response(403, {"error": {"message": "insufficient scope"}})

    with pytest.raises(ProviderError) as raised:
        GoogleMailbox(http=Refusing({})).list_headers(access_token="secret-token", since=_LONG_AGO)

    assert "secret-token" not in str(raised.value)


def test_a_since_bound_is_applied_client_side_for_google() -> None:
    """Gmail's metadata scope forbids the `q` parameter, so the date bound
    cannot be pushed to the server. It is applied to what comes back instead --
    which is the reason MAX_MESSAGES_PER_SYNC exists."""
    # Deviation from the brief: internalDate shifted +365 days (same reason as
    # above), so m1 (2026-09-18 08:00) sits before `since` (2026-09-18 noon,
    # already a literal in the brief's own test) and m2 (2026-09-19 08:00)
    # sits after it -- the relative shape the assertion below depends on.
    http = FakeHTTP(
        {
            "https://gmail.googleapis.com/gmail/v1/users/me/messages?": {
                "messages": [{"id": "m1"}, {"id": "m2"}]
            },
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/m1": {
                "id": "m1",
                "internalDate": "1789718400000",
                "payload": {"headers": [{"name": "From", "value": "a@tum.de"}]},
            },
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/m2": {
                "id": "m2",
                "internalDate": "1789804800000",
                "payload": {"headers": [{"name": "From", "value": "b@daad.de"}]},
            },
        }
    )
    since = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)

    headers = GoogleMailbox(http=http).list_headers(access_token="at", since=since)

    assert [header.message_id for header in headers] == ["m2"]
    assert all("q=" not in url for _m, url, _h in http.requests)


def test_microsoft_scopes_include_offline_access_and_no_send() -> None:
    # No "email": the address comes from Graph's /me (User.Read), never the
    # unverified claim (security review L1).
    assert SCOPES[("MICROSOFT", "METADATA")] == (
        "openid",
        "offline_access",
        "User.Read",
        "Mail.ReadBasic",
    )
    assert SCOPES[("MICROSOFT", "CONTENT")] == (
        "openid",
        "offline_access",
        "User.Read",
        "Mail.Read",
    )


def test_microsoft_filters_server_side_and_never_searches() -> None:
    """$filter is permitted under Mail.ReadBasic; $search is not. Asking for
    $search is a 403 in production and a silent empty sync if it were caught."""
    http = FakeHTTP(
        {
            "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages": {
                "value": [
                    {
                        "id": "AAMk1",
                        "from": {"emailAddress": {"address": "a@tum.de"}},
                        "receivedDateTime": "2026-09-18T09:00:00Z",
                    }
                ]
            },
            "https://graph.microsoft.com/v1.0/me/mailFolders/junkemail/messages": {"value": []},
        }
    )
    since = datetime(2026, 9, 17, 0, 0, tzinfo=UTC)

    headers = MicrosoftMailbox(http=http).list_headers(access_token="at", since=since)

    assert [header.message_id for header in headers] == ["AAMk1"]
    _method, url, _headers = http.requests[0]
    assert "%24filter=receivedDateTime+gt+2026-09-17T00%3A00%3A00Z" in url or "$filter" in url
    assert "search" not in url.casefold()


def test_microsoft_body_is_capped() -> None:
    http = FakeHTTP(
        {
            "https://graph.microsoft.com/v1.0/me/messages/AAMk1": {
                "id": "AAMk1",
                "body": {"contentType": "text", "content": "y" * 40_000},
            }
        }
    )

    body = MicrosoftMailbox(http=http).fetch_body(
        access_token="at", message_id="AAMk1"
    )
    assert len(body.text) <= 20_000


@pytest.mark.parametrize(("name", "expected"), [("GOOGLE", "GOOGLE"), ("MICROSOFT", "MICROSOFT")])
def test_provider_for_returns_the_named_vendor(name: str, expected: str) -> None:
    assert provider_for(name).name == expected


def test_provider_for_refuses_anything_else() -> None:
    with pytest.raises(ProviderError):
        provider_for("IMAP")


_GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"


def _gmail_message(message_id: str, internal_date: str) -> dict[str, object]:
    return {
        "id": message_id,
        "internalDate": internal_date,
        "payload": {"headers": [{"name": "From", "value": "a@tum.de"}]},
    }


def test_google_pages_on_while_a_page_still_holds_new_mail() -> None:
    """The sync advances its cursor to the newest message it saw, so a listing
    that stopped at one page stepped silently over everything below it."""
    http = FakeHTTP(
        {
            f"{_GMAIL}?maxResults=100&pageToken=p2": {"messages": [{"id": "m2"}]},
            f"{_GMAIL}?": {"messages": [{"id": "m1"}], "nextPageToken": "p2"},
            f"{_GMAIL}/m1": _gmail_message("m1", "1789722000000"),
            f"{_GMAIL}/m2": _gmail_message("m2", "1789718400000"),
        }
    )

    headers = GoogleMailbox(http=http).list_headers(access_token="at", since=_LONG_AGO)

    assert [header.message_id for header in headers] == ["m1", "m2"]


def test_google_stops_at_a_page_holding_nothing_new() -> None:
    """Positive control: steady state is one page, not the whole inbox."""
    http = FakeHTTP(
        {
            f"{_GMAIL}?maxResults=100&pageToken=p2": {"messages": [{"id": "m2"}]},
            f"{_GMAIL}?": {"messages": [{"id": "m1"}], "nextPageToken": "p2"},
            f"{_GMAIL}/m1": _gmail_message("m1", "1789718400000"),
        }
    )
    since = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)

    headers = GoogleMailbox(http=http).list_headers(access_token="at", since=since)

    assert headers == ()
    assert not any("pageToken" in url for _m, url, _h in http.requests)


def test_google_stops_at_the_page_ceiling_and_says_so(caplog) -> None:
    http = FakeHTTP(
        {
            f"{_GMAIL}?": {"messages": [{"id": "m1"}], "nextPageToken": "again"},
            f"{_GMAIL}/m1": _gmail_message("m1", "1789722000000"),
        }
    )

    with caplog.at_level(logging.WARNING):
        GoogleMailbox(http=http).list_headers(access_token="at", since=_LONG_AGO)

    listings = [url for _m, url, _h in http.requests if url.startswith(f"{_GMAIL}?")]
    assert len(listings) == MAX_PAGES_PER_SYNC
    assert "not read" in caplog.text


_GRAPH = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
_JUNK = "https://graph.microsoft.com/v1.0/me/mailFolders/junkemail/messages"


def _graph_message(message_id: str) -> dict[str, object]:
    return {
        "id": message_id,
        "from": {"emailAddress": {"address": "a@tum.de"}},
        "receivedDateTime": "2026-09-18T09:00:00Z",
    }


def _graph_message_to(message_id: str, to: str) -> dict[str, object]:
    return {
        **_graph_message(message_id),
        "toRecipients": [{"emailAddress": {"address": to}}],
    }


def test_microsoft_follows_its_next_link() -> None:
    http = FakeHTTP(
        {
            f"{_GRAPH}?page2": {"value": [_graph_message("AAMk2")]},
            f"{_GRAPH}?": {
                "value": [_graph_message("AAMk1")],
                "@odata.nextLink": f"{_GRAPH}?page2",
            },
            f"{_JUNK}?": {"value": []},
        }
    )

    headers = MicrosoftMailbox(http=http).list_headers(
        access_token="at", since=datetime(2026, 9, 17, tzinfo=UTC)
    )

    assert [header.message_id for header in headers] == ["AAMk1", "AAMk2"]


def test_microsoft_never_sends_the_token_to_a_next_link_off_graph() -> None:
    """The bearer token goes wherever nextLink points."""
    http = FakeHTTP(
        {
            f"{_GRAPH}?": {
                "value": [_graph_message("AAMk1")],
                "@odata.nextLink": "https://graph.microsoft.com.evil.example/steal",
            },
            f"{_JUNK}?": {"value": []},
        }
    )

    with pytest.raises(ProviderError):
        MicrosoftMailbox(http=http).list_headers(
            access_token="at", since=datetime(2026, 9, 17, tzinfo=UTC)
        )

    assert [url for _m, url, _h in http.requests] == [http.requests[0][1]]
    assert http.requests[0][1].startswith(_GRAPH)


def test_microsoft_reports_recipients_lowercased():
    http = FakeHTTP(
        {
            f"{_GRAPH}?": {"value": [_graph_message_to("AAMk1", "Leyla+AB12cd@outlook.com")]},
            f"{_JUNK}?": {"value": []},
        }
    )

    [header] = MicrosoftMailbox(http=http).list_headers(access_token="at", since=_LONG_AGO)

    assert header.sender == "a@tum.de"
    assert header.recipients == ("leyla+ab12cd@outlook.com",)
    assert header.junk is False
    assert "toRecipients" in http.requests[0][1]


def test_graph_sender_survives_a_to_recipient_list():
    """Task 5 fix round 1, finding 1 (Critical): the recipient loop reused the
    same variable that held the From address, so any message with at least
    one To recipient reported that recipient as the sender instead. Probed:
    From noreply@tum.de to a tag on outlook.com read as sender
    student+ab12cd@outlook.com."""
    http = FakeHTTP(
        {
            f"{_GRAPH}?": {
                "value": [_graph_message_to("AAMk1", "student+ab12cd@outlook.com")]
            },
            f"{_JUNK}?": {"value": []},
        }
    )

    [header] = MicrosoftMailbox(http=http).list_headers(access_token="at", since=_LONG_AGO)

    assert header.sender == "a@tum.de"
    assert header.recipients == ("student+ab12cd@outlook.com",)


def test_microsoft_also_lists_junk_and_marks_it():
    """Real portal mail sometimes lands in Junk; sync.py decides what is read from there."""
    http = FakeHTTP(
        {
            f"{_GRAPH}?": {"value": [_graph_message_to("AAMk1", "a@outlook.com")]},
            f"{_JUNK}?": {"value": [_graph_message_to("AAMk2", "b@outlook.com")]},
        }
    )

    headers = MicrosoftMailbox(http=http).list_headers(access_token="at", since=_LONG_AGO)

    assert [(h.message_id, h.junk) for h in headers] == [("AAMk1", False), ("AAMk2", True)]


def test_microsoft_recipients_skip_malformed_and_strip_whitespace():
    """Malformed recipients (null, number, missing emailAddress) are skipped.
    Valid addresses are stripped and lowercased."""
    message = {
        **_graph_message("AAMk1"),
        "toRecipients": [
            # null address → skipped
            {"emailAddress": {"address": None}},
            # number address → skipped
            {"emailAddress": {"address": 12345}},
            # missing emailAddress field → skipped
            {"other_field": {"address": "valid@example.com"}},
            # whitespace-padded valid address → stripped and lowercased
            {"emailAddress": {"address": "  Valid@EXAMPLE.COM  "}},
            # another valid address
            {"emailAddress": {"address": "another@example.com"}},
        ],
    }
    http = FakeHTTP(
        {
            f"{_GRAPH}?": {"value": [message]},
            f"{_JUNK}?": {"value": []},
        }
    )

    [header] = MicrosoftMailbox(http=http).list_headers(access_token="at", since=_LONG_AGO)

    assert header.sender == "a@tum.de"
    assert header.recipients == ("valid@example.com", "another@example.com")


def test_a_gmail_search_names_every_sender_and_the_start() -> None:
    http = FakeHTTP({f"{_GMAIL}?": {"messages": []}})
    since = datetime(2026, 9, 1, tzinfo=UTC)

    GoogleMailbox(http=http).list_headers(
        access_token="at", since=since, senders=("tum.de", "daad.de")
    )

    query = parse_qs(urlsplit(http.requests[0][1]).query)
    assert query["q"] == [f"{{from:daad.de from:tum.de}} after:{int(since.timestamp())}"]


@pytest.mark.parametrize("bad", ["tum.de OR from:evil.example", "tum.de}", "TUM.DE", "localhost"])
def test_a_sender_that_is_not_a_plain_domain_drops_the_search_not_the_sender(bad) -> None:
    """Dropping just that domain would lose its mail; listing everything loses nothing."""
    http = FakeHTTP({f"{_GMAIL}?": {"messages": []}})

    GoogleMailbox(http=http).list_headers(
        access_token="at", since=_LONG_AGO, senders=("daad.de", bad)
    )

    assert "q" not in parse_qs(urlsplit(http.requests[0][1]).query)


class _Unreachable(FakeHTTP):
    """A transport that fails below HTTP: a reset, a timeout, a refused dial."""

    def __init__(self, error: Exception) -> None:
        super().__init__({})
        self.error = error

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, dict(kwargs.get("headers") or {})))
        raise self.error


@pytest.mark.parametrize(
    "error",
    [
        urllib3.exceptions.ProtocolError("connection reset secret-token"),
        urllib3.exceptions.ReadTimeoutError(None, "/x", "read timed out"),
        urllib3.exceptions.NewConnectionError(None, "dial refused"),
    ],
)
def test_a_transport_failure_is_a_typed_error_naming_only_host_and_class(error) -> None:
    """Final review I1(a): a raw urllib3 error used to escape _json, abort
    sync_mailboxes for every later student and 500 mailbox_check. It is a
    ProviderError now, and says which host and what kind of failure -- never
    the urllib3 message, which can quote the URL."""
    with pytest.raises(ProviderError) as raised:
        MicrosoftMailbox(http=_Unreachable(error)).fetch_body(
            access_token="secret-token", message_id="AAMk1"
        )

    assert str(raised.value) == (
        f"MICROSOFT could not reach graph.microsoft.com ({type(error).__name__})"
    )
    assert raised.value.status is None


def test_a_refusal_carries_its_http_status() -> None:
    """Final review I2: sync.py decides grant loss from the status."""

    class Refusing(FakeHTTP):
        def request(self, method, url, **kwargs):
            return _Response(401, {})

    with pytest.raises(ProviderError) as raised:
        GoogleMailbox(http=Refusing({})).list_headers(access_token="at", since=_LONG_AGO)

    assert raised.value.status == 401


def test_graph_is_asked_for_immutable_ids_on_every_call() -> None:
    """Final review M2: a default Graph id changes when a message moves
    between folders, so the same mail would come back as a new signal."""
    http = FakeHTTP(
        {
            "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages": {
                "value": [_graph_message("AAMk1")]
            },
            "https://graph.microsoft.com/v1.0/me/mailFolders/junkemail/messages": {"value": []},
            "https://graph.microsoft.com/v1.0/me/messages/": {"body": {"content": "hi"}},
        }
    )
    mailbox = MicrosoftMailbox(http=http)

    mailbox.list_headers(access_token="at", since=_LONG_AGO)
    mailbox.fetch_body(access_token="at", message_id="AAMk1")

    assert len(http.requests) == 3
    assert all(headers.get("Prefer") == 'IdType="ImmutableId"' for _m, _u, headers in http.requests)


def test_the_gmail_subject_comes_from_the_same_raw_message() -> None:
    """Ruling F19: one fetch per message carries the body and the subject."""
    import base64
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = "admissions@tum.de"
    message["Subject"] = "=?utf-8?q?Zulassungsbescheid_f=C3=BCr_Sie?="
    message.set_content("Sie wurden zugelassen.")
    http = FakeHTTP(
        {
            f"{_GMAIL}/m1": {
                "id": "m1",
                "raw": base64.urlsafe_b64encode(bytes(message)).decode(),
            }
        }
    )

    body = GoogleMailbox(http=http).fetch_body(access_token="at", message_id="m1")

    assert body.subject == "Zulassungsbescheid für Sie"
    assert body.text.startswith("Sie wurden zugelassen.")
    assert len(http.requests) == 1


def test_graph_returns_the_subject_on_the_body_call() -> None:
    http = FakeHTTP(
        {
            "https://graph.microsoft.com/v1.0/me/messages/AAMk1": {
                "subject": "Admission decision",
                "body": {"contentType": "text", "content": "You are admitted."},
            }
        }
    )

    body = MicrosoftMailbox(http=http).fetch_body(access_token="at", message_id="AAMk1")

    assert (body.subject, body.text) == ("Admission decision", "You are admitted.")
    [(_method, url, _headers)] = http.requests
    assert "subject" in url


def _gmail_verdict(sender: str, auth_results: str) -> bool:
    http = FakeHTTP(
        {
            f"{_GMAIL}?": {"messages": [{"id": "m1"}]},
            f"{_GMAIL}/m1": {
                "id": "m1",
                "internalDate": "1789718400000",
                "payload": {
                    "headers": [
                        {"name": "From", "value": sender},
                        {"name": "Authentication-Results", "value": auth_results},
                    ]
                },
            },
        }
    )
    return GoogleMailbox(http=http).list_headers(access_token="at", since=_LONG_AGO)[
        0
    ].authenticated


#: Google's own header shape: comments, then the DMARC resinfo with its header.from.
_GOOGLE_PASS = (
    "mx.google.com;\r\n       dkim=pass header.i=@tum.de header.s=s1 header.b=AbC;\r\n"
    "       spf=pass (google.com: domain of noreply@tum.de designates 192.0.2.1 as "
    "permitted sender) smtp.mailfrom=noreply@tum.de;\r\n"
    "       dmarc=pass (p=REJECT sp=REJECT dis=NONE) header.from=tum.de"
)


#: Gmail's shape for a message that arrived ARC-sealed (Microsoft 365, a list, a forward).
_GOOGLE_ARC = (
    "mx.google.com;\r\n       dkim=pass header.i=@uni.edu header.s=s1 header.b=AbC;\r\n"
    "       arc=pass (i=1 spf=pass spfdomain=uni.edu dkim=pass dkdomain=uni.edu "
    "dmarc=pass fromdomain=uni.edu);\r\n"
    "       spf=pass (google.com: domain of admissions@uni.edu designates 192.0.2.1 as "
    "permitted sender) smtp.mailfrom=admissions@uni.edu;\r\n"
    "       dmarc=pass (p=NONE sp=NONE dis=NONE) header.from=uni.edu"
)


@pytest.mark.parametrize(
    ("sender", "auth_results", "expected"),
    [
        ('"TUM" <admissions@tum.de>', _GOOGLE_PASS, True),
        ("admissions@TUM.de", _GOOGLE_PASS, True),
        # Re-review 2026-10-04: the envelope sender's local part carries the
        # token, From is tum.de at p=none, and DMARC failed.
        (
            "admissions@tum.de",
            "mx.google.com; spf=pass (google.com: domain of x+dmarc=pass@attacker.example "
            "designates 203.0.113.9 as permitted sender) "
            "smtp.mailfrom=x+dmarc=pass@attacker.example; "
            "dmarc=fail (p=NONE sp=NONE dis=NONE) header.from=tum.de",
            False,
        ),
        # A pass for another domain.
        ("admissions@tum.de", _GOOGLE_PASS.replace("header.from=tum.de", "header.from=evil.de"),
         False),
        # A pass only inside a comment.
        (
            "admissions@tum.de",
            "mx.google.com; spf=pass (dmarc=pass header.from=tum.de) smtp.mailfrom=tum.de",
            False,
        ),
        # Two DMARC results: one is not Google's.
        ("admissions@tum.de", _GOOGLE_PASS + "; dmarc=pass header.from=tum.de", False),
        # Unbalanced comment: the header cannot be read, so it says nothing.
        ("admissions@tum.de", _GOOGLE_PASS.replace("(p=REJECT", "((p=REJECT"), False),
        # Round 3, residual 1: an envelope sender that closes Google's comment,
        # writes a resinfo, and reopens one -- balanced, with no DMARC of Google's own.
        (
            "admissions@tum.de",
            'mx.google.com; spf=pass (google.com: domain of "x);dmarc=pass '
            'header.from=tum.de;("@attacker.example designates 203.0.113.9 as permitted '
            'sender) smtp.mailfrom="x);dmarc=pass header.from=tum.de;("@attacker.example',
            False,
        ),
        # Round 4: the same quoted injection beside Google's own dmarc=fail.
        (
            "admissions@tum.de",
            'mx.google.com; spf=pass (google.com: domain of "x);dmarc=pass '
            'header.from=tum.de;("@attacker.example designates 203.0.113.9 as permitted '
            'sender) smtp.mailfrom="x);dmarc=pass header.from=tum.de;("@attacker.example; '
            "dmarc=fail (p=NONE sp=NONE dis=NONE) header.from=tum.de",
            False,
        ),
        # Round 4: genuine Gmail mail carrying an ARC verdict writes `dmarc=`
        # twice -- once inside the arc comment, once as its own resinfo.
        ("admissions@uni.edu", _GOOGLE_ARC, True),
        # Residual 2: a stray ")" with no comment open.
        ("admissions@tum.de", "mx.google.com; spf=pass oops); dmarc=pass header.from=tum.de",
         False),
        # Residual 3: parseaddr reads evil.example; the mail is filed under tum.de.
        ('evil.example":mail.;:x@tum.de',
         "mx.google.com; dmarc=pass header.from=evil.example", False),
        ("tum.de", "mx.google.com; dmarc=pass header.from=tum.de", False),
        # A subdomain sender passes on its own exact domain.
        ("noreply@mail.tum.de", "mx.google.com; dmarc=pass header.from=mail.tum.de", True),
        ("noreply@mail.tum.de", "mx.google.com; dmarc=pass header.from=tum.de", False),
        # Residual 4: a duplicated property is not read.
        (
            "admissions@tum.de",
            "mx.google.com; dmarc=pass header.from=evil.example header.from=tum.de",
            False,
        ),
        # Task 8 minor: non-ASCII header text is no verdict (an address
        # literal the quote ban never saw).
        (
            "admissions@tum.de",
            "mx.google.com; spf=pass smtp.mailfrom=\u00e9@x.example; dmarc=pass header.from=tum.de",
            False,
        ),
    ],
)
def test_google_reads_the_dmarc_result_itself_for_the_from_domain(
    sender, auth_results, expected
) -> None:
    assert _gmail_verdict(sender, auth_results) is expected

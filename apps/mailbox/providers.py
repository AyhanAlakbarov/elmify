"""Two vendors behind one seam, and the scope list that is the privacy surface.

Origins are pinned in code, like apps/documents/europass.py's. There is no
legitimate reason to point this at another host, so there is no way to -- and
unlike the research tier these endpoints are fixed vendor APIs, so nothing here
goes through the egress proxy or validate_public_url: there is no attacker-
supplied URL to validate.

What this module must never gain: a scope that can send, a parameter that
searches (neither gmail.metadata nor Mail.ReadBasic permits one, and building
around that is the point), or a log line carrying a token, an address or a
subject.
"""

from __future__ import annotations

import base64
import email
import email.policy
import email.utils
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any, NamedTuple, Protocol
from urllib.parse import quote, urlencode, urlsplit

import urllib3
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # nosec B105 -- an endpoint URL, not a credential
GOOGLE_API_ORIGIN = "https://gmail.googleapis.com"
MICROSOFT_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = (  # nosec B105 -- an endpoint URL, not a credential
    "https://login.microsoftonline.com/common/oauth2/v2.0/token"
)
MICROSOFT_API_ORIGIN = "https://graph.microsoft.com"
#: A default Graph id changes when a message moves between folders (Junk to
#: Inbox, say), and the same mail would come back as a new signal. Immutable
#: ids do not (final review M2).
_GRAPH_HEADERS = {"Prefer": 'IdType="ImmutableId"'}

#: Every scope this platform will ever ask a student for.
#:
#: `openid email` is on both so the connected address can be read from the ID
#: token rather than by calling a profile endpoint, which would need a wider
#: scope on Microsoft (User.Read) for one string.
#:
#: Google's two mail scopes are both RESTRICTED: they need app verification and
#: an annual CASA assessment before the app leaves testing mode, which caps it
#: at 100 users. That is a launch blocker recorded in `phased requirements.md`
#: §10, not a footnote -- see the spec's decision 8.
#:
#: Microsoft needs `offline_access` explicitly or it returns no refresh token.
SCOPES: dict[tuple[str, str], tuple[str, ...]] = {
    ("GOOGLE", "METADATA"): ("openid", "email", "https://www.googleapis.com/auth/gmail.metadata"),
    ("GOOGLE", "CONTENT"): ("openid", "email", "https://www.googleapis.com/auth/gmail.readonly"),
    # User.Read: oauth._graph_address reads the mailbox's address from /me,
    # never the id_token's unverified `email` claim.
    ("MICROSOFT", "METADATA"): ("openid", "offline_access", "User.Read", "Mail.ReadBasic"),
    ("MICROSOFT", "CONTENT"): ("openid", "offline_access", "User.Read", "Mail.Read"),
}

#: One listing page. A sync pages on until it reaches mail older than its
#: cursor: the sync advances the cursor to the newest message it saw, so a
#: single page stepped silently over everything below it.
MAX_MESSAGES_PER_SYNC = 100
#: # ponytail: a page ceiling, so a first sync of a busy inbox cannot run
#: # unbounded (Gmail costs one request per message). Hitting it is logged;
#: # the older part of that window is not read. Resume from a stored page
#: # token if that warning is ever seen.
MAX_PAGES_PER_SYNC = 10
#: What the classifier is allowed to read. A university's mail is not long; a
#: newsletter is, and the cap is what stops one becoming a model bill.
MAX_BODY_CHARS = 20_000

_TIMEOUT = urllib3.Timeout(connect=5.0, read=20.0)
_MAX_RESPONSE_BYTES = 5_000_000


class ProviderError(Exception):
    """A provider refused or answered with something unusable.

    Its message names the provider and the status and nothing else: an
    exception string reaches logs, and a token in one is a token in the logs.

    ``status`` is the provider's HTTP status, or None when there was none (a
    transport failure, a malformed answer). sync.py reads it to tell a lost
    grant (401/403) from a passing outage.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class MessageHeader(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: str
    #: The full From value, used once to derive a domain and then dropped. It is
    #: never stored: MailSignal holds sender_domain, not this.
    sender: str
    received_at: datetime
    #: Whether the student's own provider says this message really came from the
    #: domain it claims. `From:` is a header anyone can write, so the allowlist
    #: alone decides nothing about authenticity -- it decides what we are
    #: WILLING to read, not who wrote it.
    #:
    #: Google reports it in Authentication-Results, which gmail.metadata may
    #: request, so a Gmail listing carries it. Microsoft's listing does not:
    #: Mail.ReadBasic exposes no verdict at all, and on Mail.Read the headers
    #: that carry it are ~16 KB a message and include the subject, so sync.py
    #: asks for them only for mail the filter kept (delivery_verified). False
    #: here then means "not known from the listing", not "forged".
    authenticated: bool = False
    #: The To addresses, lowercased. Used once to find a tag we issued, never
    #: stored.
    recipients: tuple[str, ...] = ()
    #: Listed from the provider's Junk folder. Only tagged mail is read from
    #: there, and it is never acted on (sync.py).
    junk: bool = False


def sender_domain(address: str) -> str:
    """The host part of an address, lowercased.

    Not casefolded: casefold() maps ß to ss, and straße.de is a different
    registration from strasse.de (Task 8 minor).

    Takes the last @ so a display name containing one does not win, and
    requires a dot so `localhost` and a bare word are not domains. Lives here,
    re-exported by filter.py, so the DMARC check below compares the very domain
    the filter files the mail under.
    """
    _name, _at, host = address.strip().rstrip(">").rpartition("@")
    host = host.strip().lower()
    return host if "." in host else ""


#: A subject longer than this is not a subject; capped like the body.
MAX_SUBJECT_CHARS = 300


class MailBody(NamedTuple):
    """One content-tier fetch: the text/plain body and the subject, from the same
    call (ruling F19). Neither is stored or logged; the subject reaches only the
    decision reader, stripped of identifiers like the body."""

    text: str
    subject: str = ""


class MailboxProvider(Protocol):
    name: str

    def list_headers(
        self, *, access_token: str, since: datetime, senders: tuple[str, ...] = ()
    ) -> tuple[MessageHeader, ...]: ...

    def fetch_body(self, *, access_token: str, message_id: str) -> MailBody: ...

    def delivery_verified(self, *, access_token: str, message_id: str, sender: str) -> bool:
        """The provider's own verdict for ONE message, fetched on demand.

        For a provider whose listing cannot carry the verdict cheaply. Called
        only for mail the filter already kept, never for a stranger's.
        `sender` is the listing's From value: the verdict must be for the
        domain the mail is filed under (dmarc_result).
        """
        ...


def _json(
    http: Any,
    method: str,
    url: str,
    *,
    access_token: str,
    provider: str,
    headers: dict[str, str] | None = None,
    body: dict[str, object] | None = None,
    ok: tuple[int, ...] = (200,),
) -> dict[str, object]:
    extra: dict[str, str] = {}
    if body is not None:
        extra["Content-Type"] = "application/json"
    try:
        response = http.request(
            method,
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                **extra,
                **(headers or {}),
            },
            body=json.dumps(body) if body is not None else None,
            timeout=_TIMEOUT,
            preload_content=True,
        )
    except urllib3.exceptions.HTTPError as error:
        # A reset, a timeout, a refused dial. Host and class only, and not
        # chained: urllib3's own message can quote the URL (final review I1).
        host = urlsplit(url).hostname
        raise ProviderError(
            f"{provider} could not reach {host} ({type(error).__name__})"
        ) from None
    if response.status not in ok:
        raise ProviderError(f"{provider} answered {response.status}", status=response.status)
    if len(response.data) > _MAX_RESPONSE_BYTES:
        raise ProviderError(f"{provider} answered with an oversized body")
    if response.status == 204:
        # A DELETE's No Content. Only here: an empty 200 stays malformed, or a
        # listing that came back blank would read as an inbox with no mail.
        return {}
    try:
        payload = json.loads(response.data)
    except json.JSONDecodeError as error:
        raise ProviderError(f"{provider} answered with malformed JSON") from error
    if not isinstance(payload, dict):
        raise ProviderError(f"{provider} answered with an unexpected shape")
    return payload


#: What may go into a Gmail search as a sender. The domains come from our own
#: rows, but a learned portal domain is text a page once gave us; anything
#: outside this shape would be search syntax, not a domain.
_SEARCHABLE_DOMAIN = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")


def _gmail_search(since: datetime, senders: tuple[str, ...]) -> str:
    """`{from:a from:b} after:<epoch>`, or "" to list unfiltered.

    Any domain outside _SEARCHABLE_DOMAIN drops the whole search rather than
    the one domain: listing everything and filtering here is today's path and
    loses nothing, where dropping a domain would lose its mail.

    Unverified: that `from:tum.de` also matches `x@mail.tum.de`. Nothing here
    can test Gmail's search without a real account; check one by hand before
    relying on subdomain mail.
    """
    if not senders or not all(_SEARCHABLE_DOMAIN.fullmatch(domain) for domain in senders):
        return ""
    wanted = " ".join(f"from:{domain}" for domain in sorted(senders))
    return f"{{{wanted}}} after:{int(since.timestamp())}"


class GoogleMailbox:
    """Gmail, read through the metadata or readonly scope.

    Listing is two calls per message -- ids, then that message's headers --
    because the list endpoint returns ids alone. On the readonly scope the
    list is a search for the pack's senders (`_gmail_search`), so only pack
    mail costs a call; gmail.metadata refuses `q`, so there every message does.
    # ponytail: N+1 requests, capped by MAX_PAGES_PER_SYNC. Gmail's batch
    # endpoint collapses it to one when that cost is measured to matter.
    """

    name = "GOOGLE"

    def __init__(self, http: object | None = None) -> None:
        self._http: Any = http if http is not None else urllib3.PoolManager()

    def list_headers(
        self, *, access_token: str, since: datetime, senders: tuple[str, ...] = ()
    ) -> tuple[MessageHeader, ...]:
        search = _gmail_search(since, senders)
        headers: list[MessageHeader] = []
        next_page = ""
        for page in range(1, MAX_PAGES_PER_SYNC + 1):
            query: dict[str, object] = {"maxResults": MAX_MESSAGES_PER_SYNC}
            if search:
                query["q"] = search
            if next_page:
                query["pageToken"] = next_page
            listing = _json(
                self._http,
                "GET",
                f"{GOOGLE_API_ORIGIN}/gmail/v1/users/me/messages?" + urlencode(query),
                access_token=access_token,
                provider=self.name,
            )
            fresh = self._read_page(listing, access_token, since, headers)
            next_page = str(listing.get("nextPageToken", "") or "")
            # Stop at the first page holding nothing newer than the bound, not
            # at the first old message: Google does not document the list's
            # order, so a page-level stop tolerates local disorder.
            if not fresh or not next_page:
                return tuple(headers)
        _log_truncated(self.name, page)
        return tuple(headers)

    def _read_page(
        self,
        listing: dict[str, object],
        access_token: str,
        bound: datetime,
        headers: list[MessageHeader],
    ) -> bool:
        """Append this page's headers newer than `bound`; say whether there were any."""
        fresh = False
        messages = listing.get("messages", [])
        for entry in messages if isinstance(messages, list) else []:
            if not isinstance(entry, dict):
                continue
            message_id = str(entry.get("id", ""))
            if not message_id:
                continue
            detail = _json(
                self._http,
                "GET",
                f"{GOOGLE_API_ORIGIN}/gmail/v1/users/me/messages/{quote(message_id)}?"
                + urlencode(
                    [
                        ("format", "metadata"),
                        ("metadataHeaders", "From"),
                        # What the student's own provider concluded about this
                        # message's delivery authentication. See MessageHeader.
                        ("metadataHeaders", "Authentication-Results"),
                        ("metadataHeaders", "To"),
                    ]
                ),
                access_token=access_token,
                provider=self.name,
            )
            header = _google_header(detail)
            if header is not None and header.received_at > bound:
                headers.append(header)
                fresh = True
        return fresh

    def delivery_verified(self, *, access_token: str, message_id: str, sender: str) -> bool:
        # The listing already asked for Authentication-Results (see
        # _read_page), so there is nothing more to fetch.
        return False

    def fetch_body(self, *, access_token: str, message_id: str) -> MailBody:
        detail = _json(
            self._http,
            "GET",
            f"{GOOGLE_API_ORIGIN}/gmail/v1/users/me/messages/{quote(message_id)}?format=raw",
            access_token=access_token,
            provider=self.name,
        )
        raw = str(detail.get("raw", ""))
        if not raw:
            return MailBody("")
        text, subject = _plain_text(base64.urlsafe_b64decode(raw + "==="))
        return MailBody(text[:MAX_BODY_CHARS], subject[:MAX_SUBJECT_CHARS])


#: Gmail's documented, stable authserv-id -- the token before the first `;` in
#: its own Authentication-Results header (RFC 8601). Matched case-insensitively.
_GOOGLE_AUTHSERV_ID = "mx.google.com"
_GOOGLE_DMARC_BINDING = frozenset({"pass"})


def _without_comments_and_quotes(value: str) -> str | None:
    """`value` with every RFC 8601 comment (nested) and quoted string blanked out,
    or None when one is left open -- a header we cannot read says nothing."""
    out: list[str] = []
    depth, quoted, escaped = 0, False, False
    for char in value:
        if escaped:
            escaped = False
        elif (quoted or depth) and char == "\\":
            escaped = True
        elif quoted:
            quoted = char != '"'
        elif char == "(":
            depth += 1
        elif depth:
            depth -= char == ")"
        elif char == ")":
            return None  # a close with nothing open: unreadable
        elif char == '"':
            quoted = True
        else:
            out.append(char)
            continue
        out.append(" ")
    return None if depth or quoted or escaped else "".join(out)


def dmarc_result(auth_results: str, *, authserv_id: str, sender: str) -> str:
    """The DMARC result one Authentication-Results header gives for the sender's
    From domain, or "" when it gives none we can trust (re-review 2026-10-04).

    The header must have been written by `authserv_id` (its first token, RFC 8601;
    a version may follow). Comments and quoted strings are removed first, the
    resinfo list is split on ";", and only a resinfo that STARTS with `dmarc=`
    counts -- never `dmarc=pass` found anywhere, because the provider repeats
    the envelope sender in full and `x+dmarc=pass@attacker.example` is a legal
    address. Exactly one such resinfo, and its `header.from` must be the From
    address's domain: a pass for another domain binds nothing.

    Fail closed (round 4): a header holding a double quote anywhere is no
    verdict. An SMTP envelope local part can carry "(", ")", ";" or a space
    only when quoted (RFC 5321 Quoted-string), so with quotes banned the
    envelope sender the provider repeats cannot close a comment or start a
    resinfo of its own; the exactly-one-DMARC-resinfo rule handles the rest.
    (Round 3 counted raw `dmarc=` instead, which refused Gmail's own ARC
    comment `arc=pass (... dmarc=pass fromdomain=...)` on genuine mail.) A
    stray `)`, an open comment, or a property repeated inside the DMARC
    resinfo is no verdict either.

    The domain compared is `sender_domain(sender)` -- the From value's host
    after its last "@", exactly what filter.py files the mail under (its
    registrable key is derived from this same host). The provider's
    `header.from` must equal that host exactly: `noreply@mail.tum.de` needs
    `header.from=mail.tum.de`, never just `tum.de`. A sender with no "@" has no
    domain and so no verdict.

    authres (PyPI, RFC 8601) was checked first and not used: its last release is
    1.2.0 of 2019-08-03, unmaintained.
    """
    # Non-ASCII anywhere is no verdict either: the quote ban reasons about
    # RFC 5321 ASCII local parts, and an internationalised address is a shape
    # it never examined (Task 8 minor).
    if '"' in auth_results or not auth_results.isascii() or "@" not in sender:
        return ""
    readable = _without_comments_and_quotes(auth_results)
    if readable is None:
        return ""
    head, _sep, rest = readable.partition(";")
    tokens = head.split()
    if not tokens or tokens[0].casefold() != authserv_id:
        return ""
    found = [
        words
        for resinfo in rest.split(";")
        if (words := resinfo.split()) and words[0].casefold().startswith("dmarc=")
    ]
    if len(found) != 1:
        return ""
    words = found[0]
    pairs = [word.casefold().partition("=") for word in words[1:]]
    keys = [key for key, eq, _value in pairs if eq]
    if len(keys) != len(set(keys)):
        return ""
    props = {key: value for key, eq, value in pairs if eq}
    domain = sender_domain(sender)
    if not domain or props.get("header.from") != domain:
        return ""
    return words[0].split("=", 1)[1].casefold()


def _google_header(detail: dict[str, object]) -> MessageHeader | None:
    payload = detail.get("payload")
    headers = payload.get("headers", []) if isinstance(payload, dict) else []
    sender = ""
    # Only the FIRST Authentication-Results header on the message counts.
    # Gmail prepends its own verdict at final delivery, so for a message
    # delivered straight to this account (no forwarding after receipt) that
    # header is topmost/first in what the API returns. A later header with
    # this exact name could be one an earlier hop added -- or one a hostile
    # sender typed into the message before it was ever delivered, since
    # nothing stops a sender writing a header that merely claims dmarc=pass.
    # ORing every occurrence together (the old bug) let that forged header
    # authenticate the message on its own.
    first_auth_results: str | None = None
    to_value: str | None = None
    for item in headers:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).casefold()
        if name == "from" and not sender:
            sender = str(item.get("value", ""))
        elif name == "authentication-results" and first_auth_results is None:
            first_auth_results = str(item.get("value", ""))
        elif name == "to" and to_value is None:
            to_value = str(item.get("value", ""))
    recipients = (
        tuple(
            address.casefold()
            for _name, address in email.utils.getaddresses([to_value])
            if address
        )
        if to_value
        else ()
    )
    # Even the first header is worthless as a verdict unless it names GOOGLE as
    # the one who wrote it -- otherwise "first header" is just "whichever header
    # a forger put first". dmarc_result checks that, and reads DMARC's own
    # result for the From domain rather than a substring anywhere.
    authenticated = first_auth_results is not None and dmarc_result(
        first_auth_results, authserv_id=_GOOGLE_AUTHSERV_ID, sender=sender
    ) in _GOOGLE_DMARC_BINDING
    try:
        received = datetime.fromtimestamp(int(str(detail.get("internalDate", 0))) / 1000, UTC)
    except (TypeError, ValueError):
        return None
    message_id = str(detail.get("id", ""))
    if not message_id or not sender:
        return None
    return MessageHeader(
        message_id=message_id,
        sender=sender,
        received_at=received,
        authenticated=authenticated,
        recipients=recipients,
    )


def _plain_text(raw: bytes) -> tuple[str, str]:
    """The message's text/plain part, decoded with the charset IT declares, and
    its decoded Subject (RFC 2047 words included), from one parse.

    `policy=email.policy.default` is not optional: without it
    `message_from_bytes` returns a bare `Message`, which has neither `get_body`
    nor `get_content`. With it, the stdlib handles nested multiparts,
    quoted-printable and base64 transfer encoding, and the part's own charset.

    That last one is why this is stdlib rather than a hand-rolled walk over
    Gmail's `format=full` JSON. Such a walk has to pick an encoding, and
    picking utf-8 turns a German university's latin-1 mail into mojibake before
    the classifier ever reads it -- silently, and looking exactly like a badly
    written email.

    HTML-only mail reads as empty rather than as markup. An empty body
    classifies as nothing, which is better than a wrong guess.
    """
    try:
        message = email.message_from_bytes(raw, policy=email.policy.default)
        subject = " ".join(str(message.get("Subject", "")).split())
        part = message.get_body(preferencelist=("plain",))
    except Exception:
        # A malformed message is not a body. Never re-raise the parser's error:
        # its message quotes the mail.
        return "", ""
    if part is None:
        return "", subject
    content = part.get_content()
    return (content if isinstance(content, str) else ""), subject


#: Microsoft's authserv-id, the first token of its own Authentication-Results
#: (RFC 8601 allows a version after it: "mx.microsoft.com 1"). Measured
#: 2026-10-03 on a live Outlook.com inbox: Microsoft prepends this header at
#: delivery and renames any an earlier hop wrote to
#: "Authentication-Results-Original".
_MICROSOFT_AUTHSERV_ID = "mx.microsoft.com"
#: DMARC results that bind the From domain. "bestguesspass" is Microsoft's
#: verdict for a domain that publishes no DMARC record but whose SPF or DKIM
#: aligns with From -- measured: ufaz.az mail arrives with exactly this, and a
#: university without a DMARC record is the common case, not the exception.
_DMARC_BINDING = frozenset({"pass", "bestguesspass"})


def _microsoft_authenticated(headers: object, sender: str) -> bool:
    """Microsoft's verdict, read the way _google_header reads Google's.

    Only the FIRST header named exactly Authentication-Results counts, and only
    if Microsoft wrote it: a sender can type a header that claims dmarc=pass,
    and it would sit further down the list. `sender` is the From address Graph
    reports; the DMARC result must be for its domain (dmarc_result).
    """
    for item in headers if isinstance(headers, list) else []:
        if not isinstance(item, dict) or str(item.get("name", "")).casefold() != (
            "authentication-results"
        ):
            continue
        return dmarc_result(
            str(item.get("value", "")), authserv_id=_MICROSOFT_AUTHSERV_ID, sender=sender
        ) in _DMARC_BINDING
    return False


class MicrosoftMailbox:
    """Outlook.com and Microsoft 365, through Graph.

    Unlike Gmail, Mail.ReadBasic permits `$filter`, so the date bound is pushed
    to the server and one request returns the headers. It does NOT permit
    `$search`, which is why subjects are classified in code and never queried.

    A university's Microsoft 365 tenant may refuse third-party consent outright.
    That is not an error to retry: it puts the student on tier 0 for that
    mailbox, and the dashboard says so.
    """

    name = "MICROSOFT"

    def __init__(self, http: object | None = None) -> None:
        self._http: Any = http if http is not None else urllib3.PoolManager()

    def list_headers(
        self, *, access_token: str, since: datetime, senders: tuple[str, ...] = ()
    ) -> tuple[MessageHeader, ...]:
        # `senders` is not used: Graph documents no filter on a sender's
        # domain, and an undocumented one risks InefficientFilter on every
        # sync. The date filter below is server-side; sync.py filters senders.
        query = urlencode(
            {
                "$select": "id,from,receivedDateTime,toRecipients",
                "$top": MAX_MESSAGES_PER_SYNC,
                "$orderby": "receivedDateTime desc",
                "$filter": f"receivedDateTime gt {since.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            }
        )
        # The INBOX, not every folder generally -- /me/messages spans Junk,
        # and mail the provider already judged as forged is exactly what the
        # sender allowlist cannot tell apart from the real thing. Gmail's
        # messages.list excludes spam by default; Graph does not. Junk is
        # listed separately below and marked, so sync.py can read tagged mail
        # from it and nothing else.
        return tuple(
            self._list_folder("inbox", query, access_token, junk=False)
            + self._list_folder("junkemail", query, access_token, junk=True)
        )

    def _list_folder(
        self, folder: str, query: str, access_token: str, *, junk: bool
    ) -> list[MessageHeader]:
        url = f"{MICROSOFT_API_ORIGIN}/v1.0/me/mailFolders/{folder}/messages?{query}"
        headers: list[MessageHeader] = []
        for page in range(1, MAX_PAGES_PER_SYNC + 1):
            listing = _json(
                self._http,
                "GET",
                url,
                access_token=access_token,
                provider=self.name,
                headers=_GRAPH_HEADERS,
            )
            headers.extend(_graph_headers(listing, junk=junk))
            # The $filter already bounds every page, so paging on is complete.
            url = str(listing.get("@odata.nextLink", "") or "")
            if not url:
                return headers
            if not url.startswith(f"{MICROSOFT_API_ORIGIN}/"):
                # The bearer token goes wherever this points. Never off Graph.
                raise ProviderError(f"{self.name} paged off its own origin")
        _log_truncated(self.name, page)
        return headers

    def fetch_body(self, *, access_token: str, message_id: str) -> MailBody:
        detail = _json(
            self._http,
            "GET",
            f"{MICROSOFT_API_ORIGIN}/v1.0/me/messages/{quote(message_id)}?"
            + urlencode({"$select": "body,subject"}),
            access_token=access_token,
            provider=self.name,
            headers=_GRAPH_HEADERS,
        )
        body = detail.get("body", {})
        content = str(body.get("content", "")) if isinstance(body, dict) else ""
        subject = " ".join(str(detail.get("subject") or "").split())
        return MailBody(content[:MAX_BODY_CHARS], subject[:MAX_SUBJECT_CHARS])

    def delivery_verified(self, *, access_token: str, message_id: str, sender: str) -> bool:
        """Needs Mail.Read: the CONTENT tier only (sync.py checks)."""
        detail = _json(
            self._http,
            "GET",
            f"{MICROSOFT_API_ORIGIN}/v1.0/me/messages/{quote(message_id)}?"
            + urlencode({"$select": "internetMessageHeaders"}),
            access_token=access_token,
            provider=self.name,
            headers=_GRAPH_HEADERS,
        )
        return _microsoft_authenticated(detail.get("internetMessageHeaders"), sender)


def _graph_address(field: object) -> str:
    """`{"emailAddress": {"address": ...}}`, as Graph shapes `from` and each
    `toRecipients` entry; "" for anything else."""
    mail = field.get("emailAddress") if isinstance(field, dict) else None
    value = mail.get("address") if isinstance(mail, dict) else None
    return value if isinstance(value, str) else ""


def _graph_headers(listing: dict[str, object], *, junk: bool = False) -> list[MessageHeader]:
    headers: list[MessageHeader] = []
    value = listing.get("value", [])
    for entry in value if isinstance(value, list) else []:
        if not isinstance(entry, dict):
            continue
        address = _graph_address(entry.get("from"))
        message_id = str(entry.get("id", ""))
        raw_received = str(entry.get("receivedDateTime", ""))
        if not message_id or not address or not raw_received:
            continue
        try:
            received = datetime.fromisoformat(raw_received.replace("Z", "+00:00"))
        except ValueError:
            continue
        to = entry.get("toRecipients")
        recipients = [
            to_address
            for recipient in (to if isinstance(to, list) else [])
            if (to_address := _graph_address(recipient).strip().casefold())
        ]
        # authenticated stays False here: the verdict lives in
        # internetMessageHeaders, which Mail.ReadBasic cannot read and which
        # sync.py fetches per KEPT message on Mail.Read (delivery_verified).
        headers.append(
            MessageHeader(
                message_id=message_id,
                sender=address,
                received_at=received,
                recipients=tuple(recipients),
                junk=junk,
            )
        )
    return headers


def _log_truncated(provider: str, pages: int) -> None:
    logger.warning(
        "%s listing stopped at %d pages; older mail in this window was not read",
        provider,
        pages,
    )


def provider_for(provider: str, *, http: object | None = None) -> MailboxProvider:
    if provider == "GOOGLE":
        return GoogleMailbox(http=http)
    if provider == "MICROSOFT":
        return MicrosoftMailbox(http=http)
    raise ProviderError(f"no such provider: {provider}")

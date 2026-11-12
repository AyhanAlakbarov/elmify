"""The form schema the content script sends, with every value stripped.

This is the input to the server-side learn pass that replaces Stagehand's
observe(). It describes controls -- what they are called, what they ask for,
what they offer -- and never what anyone typed into them. ``extra="forbid"``
is what makes that structural rather than a promise: a content script that
grew a ``value`` key would fail the request, not quietly ship one.

The guard exists because a FieldMap is platform-shared. learn.py's existing
_assert_no_pii checks the model's OUTPUT for student values; this checks the
INPUT, which is the earlier and cheaper place, and the only one that also
keeps the value out of the prompt.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

from pydantic import BaseModel, ConfigDict, Field


class SnapshotControl(BaseModel):
    """One control on the page. No value, and no room for one."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: A selector the content script can resolve again on the same page.
    #: Validated against the page by the content script, and against this list
    #: by learn_from_snapshot -- the model may only choose from these.
    selector: str = Field(min_length=1, max_length=300)
    tag: str = Field(max_length=20)
    type: str = Field(default="", max_length=30)
    name: str = Field(default="", max_length=200)
    id: str = Field(default="", max_length=200)
    label: str = Field(default="", max_length=300)
    placeholder: str = Field(default="", max_length=300)
    options: tuple[str, ...] = ()
    required: bool = False
    #: The nearest heading or legend before the control ("Degree 2"). Page text,
    #: so it is redacted of every student value before anything reads it.
    heading: str = Field(default="", max_length=200)
    #: The text of the control's own group (fieldset, row, list item), with every
    #: control removed. Redacted like `heading`.
    context: str = Field(default="", max_length=300)
    #: A file input's `accept` attribute ("application/pdf,.jpg").
    accept: str = Field(default="", max_length=100)
    #: A text input or textarea's positive `maxLength` cap (0 when uncapped).
    max_length: int = Field(default=0, ge=0, le=100_000)


class FormSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page_url: str = Field(max_length=500)
    #: Capped. A page with more than 200 controls is not an application form,
    #: and the cap is also the token budget of the one model call that reads it.
    controls: tuple[SnapshotControl, ...] = Field(max_length=200)


class SnapshotPIILeak(Exception):
    """The snapshot carried a student value. It must not reach a shared map."""


def assert_no_student_values(snapshot: FormSnapshot, forbidden_values: list[str]) -> None:
    """Refuse a snapshot containing any of this student's verified values.

    Substring, not equality: a label reading "Full name (Ada Byron)" is the
    leak, and it is not equal to anything. Blank forbidden values are skipped --
    "" is a substring of every string, and a student with one empty fact would
    otherwise make every snapshot on every portal a refusal.

    `page_url` is checked too, `unquote`-d: a tagged address reaches the page
    through its own URL (query string or path) as readily as through a label,
    and percent-encoding must not be a way past this. The comparison is
    case-folded on both sides -- an address is not case-sensitive, and neither
    is the page that echoes it back.
    """
    haystack = " ".join(
        part
        for control in snapshot.controls
        for part in (
            control.selector,
            control.name,
            control.id,
            control.label,
            control.placeholder,
            *control.options,
        )
    )
    haystack = f"{haystack} {unquote(snapshot.page_url)}".casefold()
    for value in forbidden_values:
        stripped = value.strip()
        if stripped and stripped.casefold() in haystack:
            raise SnapshotPIILeak("form snapshot contains a student value")


#: A forbidden value shorter than this is never redacted: a two-letter value
#: ("Al", a country code) would blank every word it starts.
_MIN_REDACTED = 3


def student_value_pattern(forbidden_values: list[str]) -> re.Pattern[str] | None:
    """One case-insensitive, whole-word pattern over every forbidden value.

    Whole word, so "Ali" never blanks "Aliyeva": `\\w` is Unicode in a str
    pattern, so "Ləman" is one word. Longest first, so "Leyla Aliyeva" wins
    over "Leyla". None when no value is long enough to look for. Shared with
    plan 6's bench recordings, which redact a saved copy's text the same way.
    """
    needles = sorted(
        {n for n in (" ".join(v.split()) for v in forbidden_values) if len(n) >= _MIN_REDACTED},
        key=len,
        reverse=True,
    )
    if not needles:
        return None
    # The client's clip() collapses whitespace, so a needle matches any run of it.
    alternation = "|".join(r"\s+".join(map(re.escape, n.split())) for n in needles)
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE)


def redact_student_values(snapshot: FormSnapshot, forbidden_values: list[str]) -> FormSnapshot:
    """Replace every student value in the free-text fields with "■".

    Redacted, not refused: free text is where a signed-in portal greets the
    student by name, so refusing it would make every logged-in form
    unlearnable. Labels, names, ids, options and the URL stay with
    assert_no_student_values, which refuses -- a control NAMED after the
    student is a leak worth stopping, not editing.
    """
    pattern = student_value_pattern(forbidden_values)
    if pattern is None:
        return snapshot
    controls = tuple(
        control.model_copy(
            update={
                "heading": pattern.sub("■", control.heading),
                "context": pattern.sub("■", control.context),
            }
        )
        for control in snapshot.controls
    )
    return snapshot.model_copy(update={"controls": controls})

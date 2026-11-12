from apps.documents.referee_needs import NOT_STATED, RefereeNeed, Stated, needs_for


def _record(field, value, *, text="Two academic letters.", conditional=False, condition=""):
    return {
        "field": field, "value": value, "date": "", "conditional": conditional,
        "condition": condition, "rule_text": text, "source_url": "https://uni.example.de/apply",
    }


def test_each_field_carries_its_value_and_its_sentence() -> None:
    need = needs_for([
        _record("count", "TWO"), _record("kind", "ACADEMIC"),
        _record("mode", "PORTAL_INVITE", text="Referees are invited by the portal."),
        _record("institutional_email_required", "YES", text="Use an institutional address."),
    ])
    assert need.letters == 2
    assert need.kind == Stated("ACADEMIC", "Two academic letters.")
    assert need.mode == Stated("PORTAL_INVITE", "Referees are invited by the portal.")
    assert need.institutional_email is True
    assert need.due is None


def test_a_page_that_states_nothing_is_not_stated_never_a_default() -> None:
    need = needs_for([])
    assert need == RefereeNeed()
    assert need.letters is None and need.institutional_email is False
    assert NOT_STATED == "Not stated — check the page"


def test_none_required_is_zero_letters_not_unknown() -> None:
    assert needs_for([_record("count", "NONE_REQUIRED")]).letters == 0
    assert needs_for([_record("count", "THREE_OR_MORE")]).letters == 3


def test_a_scholarship_track_record_applies_only_to_a_funded_card() -> None:
    track = _record(
        "count", "THREE_OR_MORE", conditional=True, condition="track",
        text="Scholarship applicants need a third letter.",
    )
    records = [_record("count", "TWO"), track]
    plain = needs_for(records, route_kind="SELF_FUNDED")
    assert plain.letters == 2
    assert plain.other_conditions == ("Scholarship applicants need a third letter.",)
    assert needs_for(records, award=True).letters == 3
    assert needs_for(records, route_kind="SCHOLARSHIP").letters == 3
    assert needs_for(records, award=True).other_conditions == ()


def test_a_condition_the_card_cannot_answer_never_applies_and_is_shown() -> None:
    nationality = _record(
        "count", "ONE", conditional=True, condition="nationality",
        text="Applicants from outside the EU send one more letter.",
    )
    need = needs_for([nationality], award=True)
    assert need.count is None
    assert need.other_conditions == ("Applicants from outside the EU send one more letter.",)


def test_not_stated_values_and_unknown_fields_are_skipped() -> None:
    need = needs_for([_record("count", "NOT_STATED"), _record("colour", "RED"), "junk"])
    assert need == RefereeNeed()

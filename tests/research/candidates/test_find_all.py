from apps.research.candidates import find_all


def test_candidates_are_keyed_by_name_across_lines():
    c = find_all(["Stipend: 43,000 HUF per month for 12 months", "Deadline: 15 January 2027",
                  "Open to citizens of Azerbaijan", "Campus life"])
    assert set(c.amounts) == {"m1"} and c.amounts["m1"][0] == 0
    assert set(c.dates) == {"d1"} and c.dates["d1"].line == 1
    assert c.places["p1"].value.code == "AZ"
    assert c.state()["amounts"]["m1"] == {"text": "43,000 HUF", "line": 0, "from_header": False,
                                          "conversion_of": None}


def test_no_candidate_is_counted_per_kind_over_the_flagged_lines():
    c = find_all(["Stipend: 43,000 HUF", "Deadline: 15 January 2027", "Campus life",
                  "All costs are covered"])
    assert c.no_candidate("amounts", [0, 3]) == [3]
    assert c.no_candidate("dates", [1]) == []
    assert c.no_candidate("dates", [0, 1, 2]) == [0, 2]


def test_a_conversion_points_at_its_amount_by_key():
    c = find_all(["Tuition: 1,000 EUR", "Stipend: HUF 65,000 (approx. 180 EUR)"])
    assert c.state()["amounts"]["m3"]["conversion_of"] == "m2"
    assert c.state()["amounts"]["m2"]["conversion_of"] is None


def test_a_relative_date_is_never_also_a_duration():
    c = find_all(["opens approximately 15 months before the anticipated start of the grant"])
    assert len(c.relative_dates) == 1 and c.durations == {}


def test_a_header_that_repeats_the_text_adds_no_second_candidate():
    from apps.research.candidates import Line
    c = find_all([Line("43,000 HUF", header="Stipend 43,000 HUF"),
                  Line("15 January 2027", header="15 January 2027")])
    assert list(c.amounts) == ["m1"] and c.amounts["m1"].from_header is False
    assert list(c.dates) == ["d1"] and c.dates["d1"].from_header is False


def test_a_header_only_or_different_value_is_kept():
    from apps.research.candidates import Line
    c = find_all([Line("hdr only", header="Deadline 1 March 2027"),
                  Line("Stipend 100 EUR", header="Stipend 200 EUR")])
    assert c.dates["d1"].from_header is True
    assert [f.from_header for f in c.amounts.values()] == [False, True]


def test_state_is_json_serialisable():
    import json

    from apps.research.candidates import Line
    c = find_all([Line("Stipend: 1,000-2,000 EUR", header="Money"), "Tuition: 500 USD",
                  "Stipend: HUF 65,000 (approx. 180 EUR)", "opens 3 months before the start",
                  "Open to citizens of Azerbaijan", Line("x", header="Deadline 1 March 2027")])
    state = json.loads(json.dumps(c.state()))
    assert state["places"]["p1"]["text"] and state["dates"]["d1"]["from_header"] is True
    assert "conversion_of" in state["amounts"]["m1"]

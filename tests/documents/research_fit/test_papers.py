from apps.documents.research_fit.papers import (
    PaperMatch,
    discover_literature_person_on_page,
    extract_work_phrase,
    lookup_group_paper,
    lookup_person_paper,
    person_matches_author,
    reconstruct_abstract,
    strip_academic_titles,
)


def test_strip_academic_titles_and_person_matching():
    assert strip_academic_titles("Prof. Dr.-Ing. M. Kaya") == "M. Kaya"
    assert person_matches_author("Prof. Dr. M. Kaya", ("Mehmet Kaya",))
    assert person_matches_author("Prof. Jane Smith", ("J. Smith", "A. N. Other"))
    assert not person_matches_author("Prof. Jane Smith", ("John Smith",))
    assert not person_matches_author("Prof. Jane Smith", ("Jane Doe",))


def test_reconstruct_abstract_rebuilds_sentence_from_inverted_index():
    inverted = {
        "We": [0],
        "derive": [1],
        "stability": [2],
        "bounds": [3],
        "for": [4],
        "model": [5],
        "predictive": [6],
        "control.": [7],
    }
    assert (
        reconstruct_abstract(inverted)
        == "We derive stability bounds for model predictive control."
    )
    assert reconstruct_abstract(None) == ""
    assert reconstruct_abstract({}) == ""


def test_lookup_person_paper_uses_scoped_search_skips_retracted_and_checks_affiliation():
    sent_calls = []

    def fake_get_json(url, *, params, headers):
        sent_calls.append((url, params, headers))
        return {
            "results": [
                {
                    "id": "https://openalex.org/W_RETRACTED",
                    "title": "Retracted MPC Paper",
                    "publication_year": 2025,
                    "is_retracted": True,
                    "authorships": [
                        {
                            "author": {"display_name": "Mehmet Kaya"},
                            "institutions": [{"display_name": "Technical University of Munich"}],
                        }
                    ],
                },
                {
                    "id": "https://openalex.org/W_WRONG_UNI",
                    "title": "Unrelated Affiliation Paper",
                    "publication_year": 2025,
                    "is_retracted": False,
                    "authorships": [
                        {
                            "author": {"display_name": "Mehmet Kaya"},
                            "institutions": [{"display_name": "Somewhere Else University"}],
                            "raw_affiliation_strings": ["Somewhere Else University"],
                        }
                    ],
                },
                {
                    "id": "https://openalex.org/W_MATCH",
                    "doi": "https://doi.org/10.1000/mpc.2025",
                    "title": "Robust MPC under Actuator Saturation",
                    "publication_year": 2025,
                    "is_retracted": False,
                    "authorships": [
                        {
                            "author": {
                                "display_name": "M. Kaya",
                                "display_name_alternatives": ["Mehmet Kaya"],
                            },
                            "institutions": [{"display_name": "Technical University of Munich"}],
                        }
                    ],
                    "abstract_inverted_index": {
                        "Background": [0],
                        "on": [1],
                        "legged": [2],
                        "robots": [3],
                        "in": [4],
                        "rough": [5],
                        "terrain.": [6],
                        "We": [7],
                        "prove": [8],
                        "closed-loop": [9],
                        "stability": [10],
                        "bounds": [11],
                        "under": [12],
                        "packet": [13],
                        "loss.": [14],
                    },
                },
            ]
        }

    match = lookup_person_paper(
        entity="Prof. Dr. M. Kaya",
        topic="legged locomotion control",
        institution_name="Technical University of Munich",
        domains=("tum.de",),
        current_year=2026,
        api_key="oa-key",
        get_json=fake_get_json,
    )
    assert match == PaperMatch(
        title="Robust MPC under Actuator Saturation",
        year=2025,
        url="https://doi.org/10.1000/mpc.2025",
        finding="We prove closed-loop stability bounds under packet loss.",
    )
    url, params, headers = sent_calls[0]
    assert url == "https://api.openalex.org/works"
    assert params["search.title_and_abstract"] == "legged locomotion control"
    assert "is_retracted:false" in str(params["filter"])
    assert "publication_year:2020-2026" in str(params["filter"])
    assert params["per-page"] == "15"
    assert headers == {"api-key": "oa-key"}


def test_lookup_person_paper_falls_back_to_title_when_elsevier_abstract_missing():
    def fake_get_json(url, *, params, headers):
        return {
            "results": [
                {
                    "id": "https://openalex.org/W_NO_ABSTRACT",
                    "title": "Nonlinear Observer Design for Quadruped Gait",
                    "publication_year": 2024,
                    "is_retracted": False,
                    "authorships": [
                        {
                            "author": {"display_name": "Jane Smith"},
                            "raw_affiliation_strings": [
                                "Department of Engineering, Stub University"
                            ],
                        }
                    ],
                    "abstract_inverted_index": None,
                }
            ]
        }

    match = lookup_person_paper(
        entity="Prof. Jane Smith",
        topic="quadruped gait",
        institution_name="Stub University",
        current_year=2026,
        api_key="oa-key",
        get_json=fake_get_json,
    )
    assert match is not None
    assert match.title == "Nonlinear Observer Design for Quadruped Gait"
    assert match.finding == "Nonlinear Observer Design for Quadruped Gait"
    assert (
        lookup_person_paper(
            entity="Prof. Jane Smith",
            topic="quadruped gait",
            institution_name="Stub University",
            current_year=2026,
            api_key="",
            get_json=fake_get_json,
        )
        is None
    )


def test_extract_work_phrase_prefers_result_cue_and_lookup_ranks_lead_and_relevance():
    abstract = (
        "Legged robots face severe actuator saturation on steep terrain. "
        "We demonstrate a tube-based MPC formulation that guarantees recursive feasibility. "
        "Future work will test hardware deployment on quadrupeds."
    )
    assert (
        extract_work_phrase(abstract, "Tube MPC")
        == "We demonstrate a tube-based MPC formulation that guarantees recursive feasibility."
    )

    def fake_get_json(url, *, params, headers):
        return {
            "results": [
                {
                    "id": "https://openalex.org/W_MIDDLE_STUB",
                    "title": "General Robotics Overview",
                    "publication_year": 2026,
                    "is_retracted": False,
                    "authorships": [
                        {
                            "author": {"display_name": "A. First"},
                            "author_position": "first",
                            "institutions": [{"display_name": "Stub University"}],
                        },
                        {
                            "author": {"display_name": "Jane Smith"},
                            "author_position": "middle",
                            "is_corresponding": False,
                            "institutions": [{"display_name": "Stub University"}],
                        },
                        {
                            "author": {"display_name": "Z. Last"},
                            "author_position": "last",
                            "institutions": [{"display_name": "Stub University"}],
                        },
                    ],
                    "abstract_inverted_index": None,
                },
                {
                    "id": "https://openalex.org/W_LEAD_RELEVANT",
                    "doi": "https://doi.org/10.1000/lead.2024",
                    "title": "Quadruped Gait Stabilization via Tube MPC",
                    "publication_year": 2024,
                    "is_retracted": False,
                    "authorships": [
                        {
                            "author": {"display_name": "A. Student"},
                            "author_position": "first",
                            "institutions": [{"display_name": "Stub University"}],
                        },
                        {
                            "author": {"display_name": "Jane Smith"},
                            "author_position": "last",
                            "is_corresponding": True,
                            "institutions": [{"display_name": "Stub University"}],
                        },
                    ],
                    "abstract_inverted_index": {
                        "We": [0],
                        "demonstrate": [1],
                        "quadruped": [2],
                        "gait": [3],
                        "stabilization": [4],
                        "under": [5],
                        "disturbances.": [6],
                    },
                },
            ]
        }

    match = lookup_person_paper(
        entity="Prof. Jane Smith",
        topic="quadruped gait stabilization",
        institution_name="Stub University",
        current_year=2026,
        api_key="oa-key",
        get_json=fake_get_json,
    )
    assert match is not None
    assert match.url == "https://doi.org/10.1000/lead.2024"
    assert match.author_role == "lead"
    assert match.finding == "We demonstrate quadruped gait stabilization under disturbances."


def test_discover_literature_person_on_page_confirms_author_verbatim_on_directory_page():
    sentences = (
        "Prof. Dr. H. Weber (Emeritus), Control Systems.",
        "Department Faculty: Prof. Dr. Mehmet Kaya, Chair of Autonomous Systems.",
    )

    def fake_get_json(url, *, params, headers):
        return {
            "results": [
                {
                    "id": "https://openalex.org/W_KAYA",
                    "doi": "https://doi.org/10.1000/kaya.2025",
                    "title": "Model Predictive Control for Legged Locomotion",
                    "publication_year": 2025,
                    "is_retracted": False,
                    "authorships": [
                        {
                            "author": {"display_name": "H. Weber"},
                            "author_position": "first",
                            "institutions": [{"display_name": "Technical University of Munich"}],
                        },
                        {
                            "author": {"display_name": "Mehmet Kaya"},
                            "author_position": "last",
                            "is_corresponding": True,
                            "institutions": [{"display_name": "Technical University of Munich"}],
                        },
                    ],
                    "abstract_inverted_index": {
                        "We": [0],
                        "propose": [1],
                        "real-time": [2],
                        "model": [3],
                        "predictive": [4],
                        "control": [5],
                        "for": [6],
                        "legged": [7],
                        "locomotion.": [8],
                    },
                }
            ]
        }

    found = discover_literature_person_on_page(
        sentences,
        topic="legged locomotion control",
        institution_name="Technical University of Munich",
        domains=("tum.de",),
        current_year=2026,
        api_key="oa-key",
        get_json=fake_get_json,
    )
    assert found is not None
    classified_sent, paper = found
    # Emeritus Weber on sentence 0 is skipped; active Mehmet Kaya on sentence 1 is matched.
    assert classified_sent.index == 1
    assert classified_sent.entity == "Mehmet Kaya"
    assert classified_sent.kind == "named_person"
    assert paper.title == "Model Predictive Control for Legged Locomotion"
    assert paper.author_role == "lead"


def test_six_year_window_ranks_higher_profile_overlap_above_weak_recent_paper():
    def fake_get_json(url, *, params, headers):
        return {
            "results": [
                {
                    "id": "https://openalex.org/W_RECENT_GENERIC",
                    "doi": "https://doi.org/10.1000/recent.2025",
                    "title": "Legged Locomotion Overview",
                    "publication_year": 2025,
                    "is_retracted": False,
                    "authorships": [
                        {
                            "author": {"display_name": "Jane Smith"},
                            "author_position": "last",
                            "is_corresponding": True,
                            "institutions": [{"display_name": "Stub University"}],
                        }
                    ],
                    "abstract_inverted_index": {
                        "We": [0],
                        "present": [1],
                        "general": [2],
                        "legged": [3],
                        "locomotion": [4],
                        "benchmarks.": [5],
                    },
                },
                {
                    "id": "https://openalex.org/W_SEMINAL_EXACT",
                    "doi": "https://doi.org/10.1000/seminal.2021",
                    "title": "Lyapunov Tube Control for Legged Locomotion under Delay",
                    "publication_year": 2021,
                    "is_retracted": False,
                    "authorships": [
                        {
                            "author": {"display_name": "Jane Smith"},
                            "author_position": "last",
                            "is_corresponding": True,
                            "institutions": [{"display_name": "Stub University"}],
                        }
                    ],
                    "abstract_inverted_index": {
                        "We": [0],
                        "prove": [1],
                        "lyapunov": [2],
                        "stability": [3],
                        "for": [4],
                        "quadruped": [5],
                        "torque": [6],
                        "saturation": [7],
                        "under": [8],
                        "estimator": [9],
                        "delay.": [10],
                    },
                },
            ]
        }

    match = lookup_person_paper(
        entity="Prof. Jane Smith",
        topic="legged locomotion control",
        institution_name="Stub University",
        profile_terms=("lyapunov", "quadruped", "torque", "saturation", "estimator"),
        current_year=2026,
        api_key="oa-key",
        get_json=fake_get_json,
    )
    assert match is not None
    assert match.year == 2021
    assert match.url == "https://doi.org/10.1000/seminal.2021"


def test_crossref_abstract_recovery_and_ror_matching():
    def fake_get_json(url, *, params, headers):
        if url.startswith("https://api.crossref.org/works/"):
            return {
                "message": {
                    "abstract": (
                        "<jats:p>Closed-loop gait control is difficult on gravel.</jats:p>"
                        "<jats:p>We demonstrate a disturbance observer "
                        "that halves slip rate.</jats:p>"
                    )
                }
            }
        return {
            "results": [
                {
                    "id": "https://openalex.org/W_CLOSED_ABS",
                    "doi": "https://doi.org/10.1016/j.robot.2025.01",
                    "title": "Disturbance Observer for Gravel Locomotion",
                    "publication_year": 2025,
                    "is_retracted": False,
                    "authorships": [
                        {
                            "author": {"display_name": "Mehmet Kaya"},
                            "author_position": "first",
                            "institutions": [
                                {
                                    "display_name": "Technische Universität München",
                                    "ror": "https://ror.org/02kkvpp62",
                                }
                            ],
                        }
                    ],
                    "abstract_inverted_index": None,
                }
            ]
        }

    match = lookup_person_paper(
        entity="Prof. Dr. Mehmet Kaya",
        topic="gravel locomotion observer",
        institution_name="Technical University of Munich",
        ror_ids=("02kkvpp62",),
        current_year=2026,
        api_key="oa-key",
        get_json=fake_get_json,
    )
    assert match is not None
    assert match.finding == "We demonstrate a disturbance observer that halves slip rate."


def test_lookup_group_paper_matches_chair_affiliation():
    def fake_get_json(url, *, params, headers):
        return {
            "results": [
                {
                    "id": "https://openalex.org/W_CHAIR",
                    "doi": "https://doi.org/10.1000/chair.2025",
                    "title": "Stochastic MPC for Autonomous Quadrupeds",
                    "publication_year": 2025,
                    "is_retracted": False,
                    "authorships": [
                        {
                            "author": {"display_name": "L. Researcher"},
                            "institutions": [{"display_name": "Technical University of Munich"}],
                            "raw_affiliation_strings": [
                                "Chair of Autonomous Systems, Technical University of Munich"
                            ],
                        }
                    ],
                    "abstract_inverted_index": {
                        "We": [0],
                        "propose": [1],
                        "stochastic": [2],
                        "MPC": [3],
                        "for": [4],
                        "quadrupeds": [5],
                        "on": [6],
                        "uneven": [7],
                        "ground.": [8],
                    },
                }
            ]
        }

    match = lookup_group_paper(
        group_entity="Chair of Autonomous Systems",
        topic="stochastic mpc quadrupeds",
        institution_name="Technical University of Munich",
        domains=("tum.de",),
        current_year=2026,
        api_key="oa-key",
        get_json=fake_get_json,
    )
    assert match is not None
    assert match.title == "Stochastic MPC for Autonomous Quadrupeds"
    assert match.author_role == "group"
    assert match.finding == "We propose stochastic MPC for quadrupeds on uneven ground."


def test_default_paper_lookup_caches_openalex_responses_across_calls(monkeypatch):
    from django.core.cache import cache

    cache.clear()
    calls = []

    def fake_fetch(url, *, params, headers):
        calls.append((url, params))
        return {
            "results": [
                {
                    "id": "https://openalex.org/W_CACHE",
                    "doi": "https://doi.org/10.1000/cache.2025",
                    "title": "Cached Quadruped Control",
                    "publication_year": 2025,
                    "is_retracted": False,
                    "authorships": [
                        {
                            "author": {"display_name": "Jane Smith"},
                            "institutions": [{"display_name": "Stub University"}],
                        }
                    ],
                    "abstract_inverted_index": {"We": [0], "show": [1], "stability.": [2]},
                }
            ]
        }

    monkeypatch.setattr("apps.documents.research_fit.papers.fetch_json_api", fake_fetch)
    first = lookup_person_paper(
        entity="Prof. Jane Smith",
        topic="cached quadruped control",
        institution_name="Stub University",
        current_year=2026,
        api_key="oa-key",
    )
    second = lookup_person_paper(
        entity="Prof. Jane Smith",
        topic="cached quadruped control",
        institution_name="Stub University",
        current_year=2026,
        api_key="oa-key",
    )
    assert first is not None and second == first
    assert len(calls) == 1



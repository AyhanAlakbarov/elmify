from apps.documents.research_fit.papers import (
    PaperMatch,
    TopicCount,
    discover_literature_person_on_page,
    extract_work_phrase,
    lookup_group_paper,
    lookup_person_paper,
    person_matches_author,
    rank_candidates,
    recency_shift,
    reconstruct_abstract,
    resolve_openalex_author_id,
    rrf_order,
    strip_academic_titles,
)


def test_strip_academic_titles_and_person_matching():
    assert strip_academic_titles("Prof. Dr.-Ing. M. Kaya") == "M. Kaya"
    assert strip_academic_titles("Проф. д-р И. Петров") == "И. Петров"
    assert person_matches_author("Prof. Dr. M. Kaya", ("Mehmet Kaya",))
    assert person_matches_author("Prof. Jane Smith", ("J. Smith", "A. N. Other"))
    assert person_matches_author("Prof. Dr. Orxan Əliyev", ("Orkhan Aliyev",))
    assert person_matches_author("Prof. Dr. Orxan Quliyev", ("Orkhan Guliyev",))
    assert person_matches_author("Prof. Dr. Fərid Cəfərov", ("Farid Jafarov",))
    assert person_matches_author("Prof. Dr. Mehmet Işıklı", ("Mehmet Isikli",))
    assert person_matches_author("Prof. Dr. Jürgen Müller", ("Juergen Mueller",))
    assert person_matches_author("Проф. д-р И. Петров", ("Ivan Petrov",))
    assert person_matches_author("Проф. Иван Петров", ("I. Petrov",))
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


def test_discover_literature_person_skips_single_paper_first_author_student_and_selects_pi():
    sentences = (
        "Lab Members: Alex Student, PhD Candidate in Robotics.",
        "Lab Members: Lukas Weber, Doktorand am Lehrstuhl.",
        "Lab Members: Иван Сидоров, аспирант кафедры.",
        "Lab Members: Tim Trainee, Research Group.",
        "Faculty: Prof. Dr. Mehmet Kaya, Head of Autonomous Systems.",
    )

    def fake_get_json(url, *, params, headers):
        return {
            "results": [
                {
                    "id": "https://openalex.org/W_STUDENT_FIRST",
                    "doi": "https://doi.org/10.1000/student.2025",
                    "title": "Legged Locomotion Control under Slip",
                    "publication_year": 2025,
                    "is_retracted": False,
                    "authorships": [
                        {
                            "author": {"display_name": "Lukas Weber"},
                            "author_position": "last",
                            "is_corresponding": True,
                            "institutions": [{"display_name": "Technical University of Munich"}],
                        },
                        {
                            "author": {"display_name": "Tim Trainee"},
                            "author_position": "first",
                            "is_corresponding": False,
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
                        "legged": [2],
                        "locomotion": [3],
                        "control": [4],
                        "under": [5],
                        "slip.": [6],
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
    assert classified_sent.entity == "Mehmet Kaya"
    assert classified_sent.index == 4
    assert paper.author_role == "lead"


def test_recency_shift_and_rrf_order_prioritize_emerging_research_agenda():
    career = [
        TopicCount(topic_id="T_LEGACY", display_name="Classical PID Control", count=18),
        TopicCount(topic_id="T_EMERGING", display_name="Legged Robot Locomotion", count=3),
    ]
    recent = [
        TopicCount(topic_id="T_LEGACY", display_name="Classical PID Control", count=1),
        TopicCount(topic_id="T_EMERGING", display_name="Legged Robot Locomotion", count=3),
    ]
    shifts = recency_shift(career, recent)
    assert shifts["T_EMERGING"][2] > 0.5
    assert shifts["T_LEGACY"][2] < -0.5

    suggestions = rank_candidates(career, recent)
    assert any(s.topic_id == "T_EMERGING" and s.shift > 0 for s in suggestions)

    def fake_get_json(url, *, params, headers):
        # 4 legacy works (3 older + 1 recent) vs 2 recent works in emerging topic T_EMERGING
        return {
            "results": [
                {
                    "id": f"https://openalex.org/W_OLD_{idx}",
                    "doi": f"https://doi.org/10.1000/old.{idx}",
                    "title": f"Nonlinear Control Systems Study {idx}",
                    "publication_year": 2020 + (idx % 2),
                    "is_retracted": False,
                    "primary_topic": {"id": "T_LEGACY", "display_name": "Classical PID"},
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
                        "nonlinear": [2],
                        "control": [3],
                        "stability": [4],
                        "bounds.": [5],
                    },
                }
                for idx in range(4)
            ]
            + [
                {
                    "id": "https://openalex.org/W_LEGACY_2025",
                    "doi": "https://doi.org/10.1000/legacy.2025",
                    "title": "Nonlinear Control Systems Benchmark",
                    "publication_year": 2025,
                    "is_retracted": False,
                    "primary_topic": {"id": "T_LEGACY", "display_name": "Classical PID"},
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
                        "nonlinear": [2],
                        "control": [3],
                        "stability": [4],
                        "bounds.": [5],
                    },
                },
                {
                    "id": "https://openalex.org/W_EMERGING_2025",
                    "doi": "https://doi.org/10.1000/emerging.2025",
                    "title": "Nonlinear Control Systems for Actuators",
                    "publication_year": 2025,
                    "is_retracted": False,
                    "primary_topic": {"id": "T_EMERGING", "display_name": "Legged Locomotion"},
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
                        "nonlinear": [2],
                        "control": [3],
                        "stability": [4],
                        "bounds.": [5],
                    },
                },
            ]
        }

    match = lookup_person_paper(
        entity="Prof. Jane Smith",
        topic="nonlinear control stability",
        institution_name="Stub University",
        current_year=2026,
        api_key="oa-key",
        get_json=fake_get_json,
    )
    assert match is not None
    assert match.url == "https://doi.org/10.1000/emerging.2025"

    p_stub = PaperMatch(
        title="Nonlinear Control Stability",
        year=2025,
        url="https://doi.org/10.1000/stub",
        finding="Nonlinear Control Stability",
    )
    p_full = PaperMatch(
        title="Nonlinear Control Stability",
        year=2025,
        url="https://doi.org/10.1000/full",
        finding="We prove nonlinear control stability bounds under delay.",
    )
    ranked = rrf_order("nonlinear control stability", [p_stub, p_full])
    assert ranked[0] == p_full


def test_two_step_author_resolution_fallback_when_global_topic_search_misses():
    calls = []

    def fake_get_json(url, *, params, headers):
        calls.append((url, params))
        if url == "https://api.openalex.org/works" and "search.title_and_abstract" in params:
            # Global top-15 topic page has no paper by Jane Smith
            return {"results": []}
        if url == "https://api.openalex.org/authors":
            return {
                "results": [
                    {
                        "id": "https://openalex.org/A5023888391",
                        "display_name": "Jane Smith",
                        "last_known_institutions": [
                            {"display_name": "Stub University"}
                        ],
                    }
                ]
            }
        if url == "https://api.openalex.org/works" and "authorships.author.id:A5023888391" in str(
            params.get("filter")
        ):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W_AUTHOR_RESOLVED",
                        "doi": "https://doi.org/10.1000/resolved.2025",
                        "title": "Equivariant Message Passing on Molecular Graphs",
                        "publication_year": 2025,
                        "is_retracted": False,
                        "primary_topic": {
                            "id": "https://openalex.org/T1001",
                            "display_name": "Geometric Deep Learning",
                            "subfield": {"display_name": "Artificial Intelligence"},
                        },
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
                            "introduce": [1],
                            "equivariant": [2],
                            "message": [3],
                            "passing": [4],
                            "for": [5],
                            "conformers.": [6],
                        },
                    }
                ]
            }
        return {"results": []}

    aid = resolve_openalex_author_id(
        entity="Prof. Jane Smith",
        institution_name="Stub University",
        api_key="oa-key",
        get_json=fake_get_json,
    )
    assert aid == "A5023888391"

    match = lookup_person_paper(
        entity="Prof. Jane Smith",
        topic="geometric deep learning",
        institution_name="Stub University",
        current_year=2026,
        api_key="oa-key",
        get_json=fake_get_json,
    )
    assert match is not None
    assert match.url == "https://doi.org/10.1000/resolved.2025"
    assert match.finding == "We introduce equivariant message passing for conformers."


def test_europepmc_and_arxiv_abstract_recovery_and_method_or_question_extraction():
    arxiv_atom = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2502.12345v1</id>
        <title>Constrained Diffusion Policies for Dexterous Manipulation</title>
        <summary>
          However, contact-rich manipulation remains challenging under latency.
          We demonstrate a projected diffusion policy that halves grasp failure rates.
        </summary>
      </entry>
    </feed>
    """

    def fake_get_json(url, *, params, headers):
        if url.startswith("https://api.crossref.org/works/"):
            return {"message": {}}
        if url == "https://www.ebi.ac.uk/europepmc/webservices/rest/search":
            return {
                "resultList": {
                    "result": [
                        {
                            "abstractText": (
                                "Single-cell trajectory inference remains limited by "
                                "dropout noise. We show that optimal-transport "
                                "regularization recovers lineage trees."
                            )
                        }
                    ]
                }
            }
        if url == "https://export.arxiv.org/api/query":
            return {"xml": arxiv_atom}
        if params.get("search.title_and_abstract") == "single-cell trajectory inference":
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W_BIOMED",
                        "doi": "https://doi.org/10.1038/s41587-025-0001-x",
                        "title": "Optimal-Transport Lineage Inference",
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
                        "abstract_inverted_index": None,
                    }
                ]
            }
        return {
            "results": [
                {
                    "id": "https://openalex.org/W_ARXIV",
                    "doi": "https://doi.org/10.48550/arXiv.2502.12345",
                    "title": "Constrained Diffusion Policies for Dexterous Manipulation",
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
                    "abstract_inverted_index": None,
                }
            ]
        }

    biomed_match = lookup_person_paper(
        entity="Prof. Jane Smith",
        topic="single-cell trajectory inference",
        institution_name="Stub University",
        current_year=2026,
        api_key="oa-key",
        get_json=fake_get_json,
    )
    assert biomed_match is not None
    assert (
        biomed_match.finding
        == "We show that optimal-transport regularization recovers lineage trees."
    )
    assert (
        biomed_match.method_or_question
        == "Single-cell trajectory inference remains limited by dropout noise."
    )

    arxiv_match = lookup_person_paper(
        entity="Prof. Jane Smith",
        topic="constrained diffusion manipulation",
        institution_name="Stub University",
        current_year=2026,
        api_key="oa-key",
        get_json=fake_get_json,
    )
    assert arxiv_match is not None
    assert (
        arxiv_match.finding
        == "We demonstrate a projected diffusion policy that halves grasp failure rates."
    )
    assert (
        arxiv_match.method_or_question
        == "However, contact-rich manipulation remains challenging under latency."
    )


def test_humanities_monograph_metadata_and_multilingual_abstract_extraction():
    from apps.documents.research_fit.papers import extract_method_or_question, extract_work_phrase

    de_abstract = (
        "Die Quantifizierung von Übergangszuständen erfordert hohe Genauigkeit. "
        "Jedoch bleibt ungeklärt, wie sich Spin-Bahn-Kopplungen auf große Liganden auswirken. "
        "Wir zeigen, dass äquivariante Netzwerke die Barrieren auf 1.0 kcal/mol genau vorhersagen."
    )
    assert "Wir zeigen, dass äquivariante Netzwerke" in extract_work_phrase(
        de_abstract, "Übergangszustände"
    )
    assert "Jedoch bleibt ungeklärt" in extract_method_or_question(de_abstract)

    law_abstract = (
        "At issue is whether bilateral investment treaties constrain sovereign climate measures. "
        "This article argues that proportionality review reconciles treaty obligations with "
        "regulatory autonomy."
    )
    assert "This article argues that proportionality review" in extract_work_phrase(
        law_abstract, "Investment Treaties"
    )
    assert "At issue is whether bilateral investment treaties" in extract_method_or_question(
        law_abstract
    )

    def fake_monograph_json(url, *, params, headers):
        if "authors" in url:
            return {"results": []}
        if "crossref.org" in url or "europepmc" in url:
            return {}
        return {
            "results": [
                {
                    "id": "https://openalex.org/W777",
                    "title": "Byzantine Epigraphy and Imperial Chancery Seals",
                    "publication_year": 2025,
                    "doi": "https://doi.org/10.1000/byz.2025",
                    "is_retracted": False,
                    "authorships": [
                        {
                            "author": {"display_name": "Elena Papadopoulou"},
                            "author_position": "first",
                            "is_corresponding": True,
                            "institutions": [{"display_name": "Stub University"}],
                        }
                    ],
                    "abstract_inverted_index": None,
                    "keywords": [
                        {"display_name": "Lead Seals"},
                        {"display_name": "Sigillography"},
                    ],
                    "primary_topic": {
                        "id": "https://openalex.org/T99",
                        "display_name": "Byzantine Administrative History",
                    },
                }
            ]
        }

    monograph = lookup_person_paper(
        entity="Prof. Elena Papadopoulou",
        topic="byzantine epigraphy sigillography",
        institution_name="Stub University",
        current_year=2026,
        api_key="oa-key",
        get_json=fake_monograph_json,
    )
    assert monograph is not None
    assert monograph.finding == "Byzantine Epigraphy and Imperial Chancery Seals"
    assert (
        monograph.method_or_question
        == "Addresses Lead Seals, Sigillography, Byzantine Administrative History."
    )


def test_normalize_inverted_person_name_and_bitstream_url_filtering():
    from apps.documents.research_fit.papers import (
        normalize_inverted_person_name,
        strip_academic_titles,
    )
    from apps.documents.research_fit.service import _prioritize_web_page_urls

    assert normalize_inverted_person_name("Broeders, D.W.J.") == "D.W.J. Broeders"
    assert normalize_inverted_person_name("Copéret, Christophe") == "Christophe Copéret"
    assert normalize_inverted_person_name("Jane Doe, PhD") == "Jane Doe, PhD"
    assert strip_academic_titles("Broeders, D.W.J.") == "D.W.J. Broeders"

    urls = (
        "https://www.research-collection.ethz.ch/bitstreams/a5ebf4bd/download",
        "https://coperetgroup.ethz.ch/research/designing/descriptors.html",
        "https://www.research-collection.ethz.ch/server/api/core/bitstreams/af00799f/content",
        "https://scholarlypublications.universiteitleiden.nl/handle/1887/138552",
        "https://ethz.ch/content/dam/ethz/brochure.pdf",
    )
    filtered = _prioritize_web_page_urls(urls)
    assert filtered == (
        "https://coperetgroup.ethz.ch/research/designing/descriptors.html",
        "https://scholarlypublications.universiteitleiden.nl/handle/1887/138552",
    )







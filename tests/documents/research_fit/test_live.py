"""Live gate, run with `-m live` and real keys: the ladder on real programme
domains with synthetic anchors (Task 13)."""

import os

import pytest

pytestmark = pytest.mark.live

_DOMAINS = (
    ("DE", "https://www.tum.de/"),
    ("CH", "https://ethz.ch/"),
    ("NL", "https://www.tudelft.nl/"),
    ("BE", "https://www.kuleuven.be/"),
    ("DE", "https://www.uni-heidelberg.de/"),
    ("TR", "https://www.itu.edu.tr/"),
    ("TR", "https://www.metu.edu.tr/"),
    ("SE", "https://www.kth.se/"),
    ("IT", "https://www.polimi.it/"),
    ("NL", "https://www.uva.nl/"),
)
_ANCHORS = (
    (
        "RESEARCH",
        {
            "thesis_title": "A model predictive gait controller for a quadruped robot",
            "methods": ["MPC"],
        },
    ),
    (
        "RESEARCH",
        {
            "thesis_title": "Grid integration of rooftop solar in a distribution network",
            "methods": ["power flow"],
        },
    ),
    (None, "machine translation for low-resource languages"),
    (None, "protein structure prediction with deep learning"),
)


@pytest.mark.django_db
@pytest.mark.skipif(not os.getenv("EXA_API_KEY"), reason="EXA_API_KEY not set")
def test_the_ladder_on_real_programme_domains(
    agency_a, membership_a, institution_factory, program_factory
):
    from uuid import uuid4

    from apps.documents.letter_schemas import Storyline
    from apps.documents.research_fit.service import propose_research_fit
    from apps.tenancy.context import tenant_scope

    from ..conftest import make_fact
    from .test_service import _prompt

    tally: dict[str, int] = {}
    with tenant_scope(agency_a.id):
        for country, site in _DOMAINS:
            institution = institution_factory(official_website=site)
            program = program_factory(country_code=country, institution=institution)
            prompt = _prompt(program)
            for category, payload in _ANCHORS:
                facts = {}
                storyline = None
                if category:
                    fact = make_fact(membership_a, category, payload)
                    fact.confirmed_by = membership_a
                    fact.save(update_fields=["confirmed_by"])
                    facts = {fact.id: fact}
                else:
                    storyline = Storyline(
                        theme=payload, theme_kind="MATCH", anchors=(uuid4(),), future="f"
                    )
                out = propose_research_fit(
                    student=membership_a,
                    program=program,
                    prompt=prompt,
                    facts=facts,
                    storyline=storyline,
                )
                key = f"{out.status}/rung{out.rung}"
                tally[key] = tally.get(key, 0) + 1
                if out.narrative_input is not None:
                    p = out.narrative_input.provenance
                    assert p["entity"].casefold() in p["sentence"].casefold()  # by construction
                    title = payload if isinstance(payload, str) else payload["thesis_title"]
                    print(
                        f"{site} | {title} | rung {out.rung} | {p['entity']} | "
                        f"{p['source_url']} | ${p['cost_usd']:.4f}"
                    )
                else:
                    title = payload if isinstance(payload, str) else payload["thesis_title"]
                    print(f"{site} | {title} | {out.status}")
    print(tally)

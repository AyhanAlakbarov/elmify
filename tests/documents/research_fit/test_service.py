from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone
from openai import OpenAIError

from apps.documents.letter_schemas import Storyline
from apps.documents.models import NarrativeInput, VerifiedFact
from apps.documents.research_fit.classify import ClassifiedSentence
from apps.documents.research_fit.judge import AlignmentReading
from apps.documents.research_fit.pages import fetch_page
from apps.documents.research_fit.service import (
    MAX_MODEL_CALLS,
    MAX_PAGES_CLASSIFIED,
    ResearchFitOutcome,
    institution_domains,
    propose_research_fit,
    recheck_research_fit,
    research_fit_inputs,
    spend_within_ceiling,
)
from apps.funding.models import ApplicationPrompt, AuditEvent
from apps.research.egress import FetchResult
from apps.research.providers.base import ProviderUnavailable, SiteSearchResult
from apps.tenancy.context import tenant_scope

from ..conftest import make_fact

pytestmark = pytest.mark.django_db

_HTML = (
    b"<html><body><main><p>The Chair of Robotics hosts master's theses on legged "
    b"locomotion.</p><p>The canteen is open.</p></main></body></html>"
)


class _Response:
    def __init__(self, parsed):
        self.output_parsed = parsed
        self.output = []
        self.stop_reason = "end_turn"


class _Parser:
    """Answers, in order: topic phrase, then judge readings."""

    def __init__(self, *parsed):
        self.responses = [_Response(p) for p in parsed]
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class _Classifier:
    def __init__(self, *out):
        self.out = out
        self.calls = []

    def classify(self, sentences, *, topic):
        self.calls.append((tuple(sentences), topic))
        return self.out


def _search(urls=("https://www.university.example.test/robotics",), cost=0.007, provider="exa"):
    sent = []

    def search(*, query, domain):
        sent.append((query, domain))
        return SiteSearchResult(urls=tuple(urls), cost_usd=cost, provider=provider)

    search.sent = sent
    return search


# Every programme below is country GB: no site-language query runs, so a test
# can assert exactly one search per anchor. D12 is covered in test_anchors.


def _fetch(url, **_):
    return FetchResult(url, (), "text/html", _HTML)


def _prompt(program, **overrides):
    fields = dict(
        programme=program,
        cycle="2027/28",
        source_url="https://x.example/p",
        confidence=1.0,
        verified_for_cycle="2027",
        source=ApplicationPrompt.Source.VERIFIED,
        funder_kind=ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
        structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        archetypes=["WHY_PROGRAMME"],
        questions=[],
        programme_evidence={},
        document_language="en",
    )
    fields.update(overrides)
    return ApplicationPrompt.objects.create(**fields)


def _research_fact(student):
    fact = make_fact(
        student,
        "RESEARCH",
        {"thesis_title": "A gait controller for a quadruped", "methods": ["MPC"]},
    )
    fact.confirmed_by = student
    fact.confirmed_at = timezone.now()
    fact.save(update_fields=["confirmed_by", "confirmed_at"])
    return fact


@pytest.fixture(autouse=True)
def _clear():
    cache.clear()


def _strong():
    return AlignmentReading(strength="strong", excerpt="legged locomotion")


def test_institution_domains_strip_www_and_include_awarding_partners(
    program_factory, institution_factory
):
    program = program_factory(country_code="GB")
    partner = institution_factory(official_website="https://www.partner.example.test/")
    program.awarding_institutions.add(partner)
    assert institution_domains(program) == ("university.example.test", "partner.example.test")


def test_a_matched_run_writes_a_pre_accepted_input_with_provenance(
    agency_a, membership_a, program_factory
):
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        prompt = _prompt(program)
        fact = _research_fact(membership_a)
        from apps.documents.research_fit.anchors import TopicPhrase

        parser = _Parser(TopicPhrase(phrase="legged locomotion control"), _strong(), _strong())
        classifier = _Classifier(
            ClassifiedSentence(0, 0.9, "research_group", "Chair of Robotics"),
            ClassifiedSentence(1, 0.1, "none", None),
        )
        search = _search()
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=prompt,
            facts={fact.id: fact},
            storyline=None,
            parser=parser,
            claude=None,
            classifier=classifier,
            search=search,
            fallback_search=None,
            fetch=_fetch,
        )
        assert out.status == "matched" and out.rung == 1
        row = out.narrative_input
        assert row.kind == NarrativeInput.Kind.RESEARCH_FIT
        assert row.proposed_by == NarrativeInput.ProposedBy.ENGINE
        assert row.confirmed_at is not None
        assert row.text == "The Chair of Robotics hosts master's theses on legged locomotion."
        p = row.provenance
        assert p["entity"] == "Chair of Robotics"
        assert p["rung"] == 1
        assert p["anchor_fact_id"] == str(fact.id)
        assert p["source_url"] == "https://www.university.example.test/robotics"
        assert p["program_id"] == str(program.pk)
        assert p["judgement"] == "strong"
        assert p["provider"] == "exa"
        assert p["cost_usd"] >= 0.007
        assert len(p["page_digest"]) == 64
        assert search.sent == [("legged locomotion control", "university.example.test")]
        assert classifier.calls[0][1] == "legged locomotion control"
        assert AuditEvent.objects.filter(
            event="document.research_fit.matched", object_id=membership_a.id
        ).exists()
        assert research_fit_inputs(membership_a, program) == {row.id: row}


def test_a_broken_openai_client_construction_is_recorded_not_raised(
    agency_a, membership_a, program_factory
):
    """openai.OpenAIError is not a ValueError, so a missing/invalid key or bad
    base URL would otherwise escape propose_research_fit and block the letter
    (D11) -- the same escape class letters.py::generate_letter already guards."""
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        prompt = _prompt(program)
        fact = _research_fact(membership_a)
        with patch("openai.OpenAI", side_effect=OpenAIError("no key")):
            out = propose_research_fit(
                student=membership_a,
                program=program,
                prompt=prompt,
                facts={fact.id: fact},
                storyline=None,
            )
        assert out.status == "no_match"
        assert AuditEvent.objects.filter(
            event="document.research_fit.no_match", object_id=membership_a.id
        ).exists()


def test_no_query_ever_carries_the_student(agency_a, membership_a, program_factory):
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        prompt = _prompt(program)
        make_fact(membership_a, "IDENTITY", {"full_name": "Aysel Mammadova"})
        fact = make_fact(
            membership_a,
            "RESEARCH",
            {
                "thesis_title": "Gait control at Baku State University by Aysel Mammadova 2024",
                "institution": "Baku State University",
            },
        )
        fact.confirmed_by = membership_a
        fact.confirmed_at = timezone.now()
        fact.save(update_fields=["confirmed_by", "confirmed_at"])
        from apps.documents.research_fit.anchors import TopicPhrase

        parser = _Parser(
            TopicPhrase(phrase="Gait control at Baku State University by Aysel Mammadova 2024")
        )
        search = _search(urls=())
        facts = {f.id: f for f in VerifiedFact.objects.filter(student=membership_a)}
        propose_research_fit(
            student=membership_a,
            program=program,
            prompt=prompt,
            facts=facts,
            storyline=None,
            parser=parser,
            claude=None,
            classifier=_Classifier(),
            search=search,
            fallback_search=None,
            fetch=_fetch,
        )
        for query, _domain in search.sent:
            assert "aysel" not in query and "mammadova" not in query
            assert "baku" not in query and "2024" not in query


class _DownParser:
    """The topic-phrase model is down: every call raises, as an SDK transport error does."""

    def __init__(self):
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError("model down")


def test_with_the_model_down_no_third_party_name_reaches_a_query(
    agency_a, membership_a, program_factory
):
    """banned_terms holds the student's own name and schools, not a supervisor's;
    the fallback must strip the name on its own (2026-10-14)."""
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        prompt = _prompt(program)
        make_fact(membership_a, "IDENTITY", {"full_name": "Aysel Mammadova"})
        fact = make_fact(
            membership_a, "RESEARCH",
            {"thesis_title": "Protein folding kinetics with Ayse Yilmaz",
             "institution": "Baku State University"},
        )
        fact.confirmed_by = membership_a
        fact.confirmed_at = timezone.now()
        fact.save(update_fields=["confirmed_by", "confirmed_at"])
        search = _search(urls=())
        facts = {f.id: f for f in VerifiedFact.objects.filter(student=membership_a)}
        propose_research_fit(
            student=membership_a, program=program, prompt=prompt, facts=facts, storyline=None,
            parser=_DownParser(), claude=None, classifier=_Classifier(), search=search,
            fallback_search=None, fetch=_fetch,
        )
        for query, _domain in search.sent:
            assert "ayse" not in query and "yilmaz" not in query



def test_the_theme_is_the_last_rung_and_needs_no_model_call_for_the_phrase(
    agency_a, membership_a, program_factory
):
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        prompt = _prompt(program)
        theme = Storyline(
            theme="grid integration of renewable energy",
            theme_kind="MATCH",
            anchors=(uuid4(),),
            future="f",
        )
        parser = _Parser(_strong(), _strong())
        classifier = _Classifier(ClassifiedSentence(0, 0.9, "research_group", "Chair of Robotics"))
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=prompt,
            facts={},
            storyline=theme,
            parser=parser,
            claude=None,
            classifier=classifier,
            search=_search(),
            fallback_search=None,
            fetch=_fetch,
        )
        assert out.status == "matched" and out.rung == 4


def test_immigration_prompts_run_nothing(agency_a, membership_a, program_factory):
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        prompt = _prompt(
            program,
            funder_kind=ApplicationPrompt.FunderKind.IMMIGRATION_AUTHORITY,
            immigration=True,
        )
        search = _search()
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=prompt,
            facts={},
            storyline=None,
            parser=_Parser(),
            claude=None,
            classifier=_Classifier(),
            search=search,
            fallback_search=None,
            fetch=_fetch,
        )
        assert out == ResearchFitOutcome(
            status="skipped_immigration", rung=None, narrative_input=None, cost_usd=0.0
        )
        assert search.sent == [] and not NarrativeInput.objects.exists()


def test_consortium_specific_structure_gets_no_search(agency_a, membership_a, program_factory):
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        prompt = _prompt(program, structure=ApplicationPrompt.Structure.CONSORTIUM_SPECIFIC)
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=prompt,
            facts={},
            storyline=None,
            parser=_Parser(),
            claude=None,
            classifier=_Classifier(),
            search=_search(),
            fallback_search=None,
            fetch=_fetch,
        )
        assert out.status == "skipped_structure"


def test_no_anchor_at_all_is_an_outcome(agency_a, membership_a, program_factory):
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=_prompt(program),
            facts={},
            storyline=None,
            parser=_Parser(),
            claude=None,
            classifier=_Classifier(),
            search=_search(),
            fallback_search=None,
            fetch=_fetch,
        )
        assert out.status == "no_anchor"


def test_exa_failure_falls_back_to_tavily_then_records_provider_unavailable(
    agency_a, membership_a, program_factory
):
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        theme = Storyline(
            theme="renewable energy", theme_kind="MATCH", anchors=(uuid4(),), future="f"
        )

        def broken(*, query, domain):
            raise ProviderUnavailable("down")

        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=_prompt(program),
            facts={},
            storyline=theme,
            parser=_Parser(),
            claude=None,
            classifier=_Classifier(),
            search=broken,
            fallback_search=broken,
            fetch=_fetch,
        )
        assert out.status == "provider_unavailable"
        fallback = _search(provider="tavily")
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=_prompt(program, cycle="2028/29"),
            facts={},
            storyline=theme,
            parser=_Parser(_strong(), _strong()),
            claude=None,
            classifier=_Classifier(
                ClassifiedSentence(0, 0.9, "research_group", "Chair of Robotics")
            ),
            search=broken,
            fallback_search=fallback,
            fetch=_fetch,
        )
        assert out.status == "matched"
        assert out.narrative_input.provenance["provider"] == "tavily"


def test_a_weak_judgement_is_no_match_and_writes_nothing(agency_a, membership_a, program_factory):
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        theme = Storyline(
            theme="renewable energy", theme_kind="MATCH", anchors=(uuid4(),), future="f"
        )
        weak = AlignmentReading(strength="weak", excerpt="x")
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=_prompt(program),
            facts={},
            storyline=theme,
            parser=_Parser(weak, weak),
            claude=None,
            classifier=_Classifier(
                ClassifiedSentence(0, 0.9, "research_group", "Chair of Robotics")
            ),
            search=_search(),
            fallback_search=None,
            fetch=_fetch,
        )
        assert out.status == "no_match" and not NarrativeInput.objects.exists()
        assert AuditEvent.objects.filter(event="document.research_fit.no_match").exists()


def test_a_second_run_within_seven_days_reuses_the_stored_input(
    agency_a, membership_a, program_factory
):
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        theme = Storyline(
            theme="renewable energy", theme_kind="MATCH", anchors=(uuid4(),), future="f"
        )
        kwargs = dict(
            student=membership_a,
            program=program,
            prompt=_prompt(program),
            facts={},
            storyline=theme,
            claude=None,
            classifier=_Classifier(
                ClassifiedSentence(0, 0.9, "research_group", "Chair of Robotics")
            ),
            fallback_search=None,
            fetch=_fetch,
        )
        first = propose_research_fit(
            parser=_Parser(_strong(), _strong()), search=_search(), **kwargs
        )
        second_search = _search()
        second = propose_research_fit(parser=_Parser(), search=second_search, **kwargs)
        assert second.status == "matched"
        assert second.narrative_input.id == first.narrative_input.id
        assert second_search.sent == [] and second.cost_usd == 0.0
        NarrativeInput.objects.filter(pk=first.narrative_input.pk).update(
            created_at=timezone.now() - timedelta(days=8)
        )
        third = propose_research_fit(
            parser=_Parser(_strong(), _strong()), search=_search(), **kwargs
        )
        assert third.narrative_input.id != first.narrative_input.id


def test_the_rate_limit_is_an_outcome(agency_a, membership_a, program_factory):
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        theme = Storyline(
            theme="renewable energy", theme_kind="MATCH", anchors=(uuid4(),), future="f"
        )
        from apps.ratelimit import rate_limited

        for _ in range(20):
            rate_limited("research-fit", membership_a.id, limit=20, window_seconds=3600)
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=_prompt(program),
            facts={},
            storyline=theme,
            parser=_Parser(),
            claude=None,
            classifier=_Classifier(),
            search=_search(),
            fallback_search=None,
            fetch=_fetch,
        )
        assert out.status == "rate_limited"


def test_the_daily_ceiling_is_an_outcome(agency_a, membership_a, program_factory, settings):
    settings.RESEARCH_FIT_DAILY_CEILING_USD = 0.01
    assert spend_within_ceiling(agency_a.id, 0.005)
    assert not spend_within_ceiling(agency_a.id, 0.02)
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        theme = Storyline(
            theme="renewable energy", theme_kind="MATCH", anchors=(uuid4(),), future="f"
        )
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=_prompt(program),
            facts={},
            storyline=theme,
            parser=_Parser(),
            claude=None,
            classifier=_Classifier(),
            search=_search(),
            fallback_search=None,
            fetch=_fetch,
        )
        assert out.status == "ceiling"


def test_a_classifier_that_is_down_is_no_match_not_an_exception(
    agency_a, membership_a, program_factory
):
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        theme = Storyline(
            theme="renewable energy", theme_kind="MATCH", anchors=(uuid4(),), future="f"
        )

        class _Down:
            def classify(self, sentences, *, topic):
                raise ProviderUnavailable("jev down")

        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=_prompt(program),
            facts={},
            storyline=theme,
            parser=_Parser(),
            claude=None,
            classifier=_Down(),
            search=_search(),
            fallback_search=None,
            fetch=_fetch,
        )
        assert out.status == "no_match" and not NarrativeInput.objects.exists()


def test_an_unreadable_only_page_set_is_unreadable(agency_a, membership_a, program_factory):
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        theme = Storyline(
            theme="renewable energy", theme_kind="MATCH", anchors=(uuid4(),), future="f"
        )
        shell = (
            b"<html><body><div id='app'></div>" + b"<script>x</script>" * 2000 + b"</body></html>"
        )
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=_prompt(program),
            facts={},
            storyline=theme,
            parser=_Parser(),
            claude=None,
            classifier=_Classifier(),
            search=_search(),
            fallback_search=None,
            fetch=lambda url, **_: FetchResult(url, (), "text/html", shell),
        )
        assert out.status == "unreadable"


def test_a_transport_failure_from_the_model_sdk_is_an_outcome_not_a_raise(
    agency_a, membership_a, program_factory
):
    # Stands for a model SDK's transport errors (e.g. openai.APIConnectionError):
    # a plain Exception, not ValueError/ValidationError. If anchors._ask or
    # judge._openai_reading narrow their except back, this raises instead of
    # propose_research_fit returning a degraded outcome (D11).
    class _Boom(Exception):
        pass

    class _RaisingParser:
        def parse(self, **kwargs):
            raise _Boom("network down")

    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        theme = Storyline(
            theme="renewable energy", theme_kind="MATCH", anchors=(uuid4(),), future="f"
        )
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=_prompt(program),
            facts={},
            storyline=theme,
            parser=_RaisingParser(),
            claude=None,
            classifier=_Classifier(
                ClassifiedSentence(0, 0.9, "research_group", "Chair of Robotics")
            ),
            search=_search(),
            fallback_search=None,
            fetch=_fetch,
        )
        assert out.status == "no_match" and not NarrativeInput.objects.exists()


def test_research_fit_inputs_are_tenant_scoped_and_program_scoped(
    agency_a, agency_b, membership_a, membership_b, program_factory
):
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        other = program_factory(country_code="GB")
        NarrativeInput.objects.create(
            student=membership_a,
            kind=NarrativeInput.Kind.RESEARCH_FIT,
            text="s",
            proposed_by="ENGINE",
            provenance={
                "program_id": str(program.pk),
                "entity": "e",
                "sentence": "s",
                "source_url": "u",
            },
        )
        NarrativeInput.objects.create(
            student=membership_a,
            kind=NarrativeInput.Kind.RESEARCH_FIT,
            text="s",
            proposed_by="ENGINE",
            provenance={
                "program_id": str(other.pk),
                "entity": "e",
                "sentence": "s",
                "source_url": "u",
            },
        )
        assert len(research_fit_inputs(membership_a, program)) == 1
    with tenant_scope(agency_b.id):
        assert research_fit_inputs(membership_b, program) == {}


_ROBOTICS_SENTENCE = "The Chair of Robotics hosts master's theses on legged locomotion."


def _fit_input(student, sentence, entity, digest="d" * 64):
    return NarrativeInput.objects.create(
        student=student,
        kind=NarrativeInput.Kind.RESEARCH_FIT,
        text=sentence,
        proposed_by="ENGINE",
        confirmed_at=timezone.now(),
        provenance={
            "program_id": "p",
            "sentence": sentence,
            "entity": entity,
            "source_url": "https://www.university.example.test/robotics",
            "page_digest": digest,
            "kind": "research_group",
            "rung": 1,
            "anchor_fact_id": None,
            "judgement": "strong",
            "topic_hash": "t",
            "cost_usd": 0.0,
            "provider": "exa",
        },
    )


def test_recheck_skips_the_entity_search_when_the_digest_is_unchanged(
    agency_a, membership_a, monkeypatch
):
    # A digest match means the refetched page is byte-identical to what
    # produced the stored digest, so the entity is trivially present whichever
    # branch runs -- asserting an empty result alone proves nothing about the
    # skip (a digest match can't be paired with an absent entity without a
    # hash collision). Instrument the search path instead: if the
    # digest-compare-first skip is ever removed, this raises.
    def _must_not_run(_text):
        raise AssertionError("entity search ran on an unchanged page")

    monkeypatch.setattr("apps.documents.research_fit.service._normalize", _must_not_run)
    with tenant_scope(agency_a.id):
        from apps.research.harvest import content_digest

        row = _fit_input(
            membership_a, _ROBOTICS_SENTENCE, "Chair of Robotics", digest=content_digest(_HTML)
        )
        assert recheck_research_fit({row.id: row}, fetch=_fetch) == ()


def test_recheck_passes_a_changed_page_that_still_carries_the_entity(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        row = _fit_input(membership_a, _ROBOTICS_SENTENCE, "Chair of Robotics", digest="0" * 64)
        assert recheck_research_fit({row.id: row}, fetch=_fetch) == ()


def test_recheck_flags_a_page_that_dropped_the_entity(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        row = _fit_input(membership_a, _ROBOTICS_SENTENCE, "Chair of Robotics", digest="0" * 64)
        gone = b"<html><body><main><p>This chair has been dissolved.</p></main></body></html>"
        assert recheck_research_fit(
            {row.id: row}, fetch=lambda url, **_: FetchResult(url, (), "text/html", gone)
        ) == (row.id,)


def test_recheck_treats_a_vendor_outage_as_unknown_not_stale(agency_a, membership_a):
    """A fetch failure (vendor down, timeout) never even read the page -- flagging
    it the same as a dropped entity would dump every citation into the counselor
    queue on a third-party hiccup at approval, the wrong-way degradation D11
    forbids."""
    with tenant_scope(agency_a.id):
        row = _fit_input(membership_a, "s", "Chair of Robotics", digest="0" * 64)

        def broken(url):
            raise RuntimeError("down")

        assert recheck_research_fit({row.id: row}, fetch=broken) == ()


def test_recheck_flags_an_off_domain_redirect_as_stale(agency_a, membership_a):
    """The cited URL now redirects off the institution's domain -- the source
    moved, a genuine staleness signal, not a transient failure like
    fetch_failed."""
    with tenant_scope(agency_a.id):
        row = _fit_input(membership_a, "s", "Chair of Robotics", digest="0" * 64)
        assert recheck_research_fit(
            {row.id: row},
            fetch=lambda url, **_: FetchResult(
                "https://www.evil.example.test/robotics", (), "text/html", _HTML
            ),
        ) == (row.id,)


def test_recheck_flags_a_genuinely_unreadable_page_as_stale(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        row = _fit_input(membership_a, "s", "Chair of Robotics", digest="0" * 64)
        shell = (
            b"<html><body><div id='app'></div>" + b"<script>x</script>" * 2000 + b"</body></html>"
        )
        assert recheck_research_fit(
            {row.id: row}, fetch=lambda url, **_: FetchResult(url, (), "text/html", shell)
        ) == (row.id,)


def test_recheck_does_not_raise_when_the_page_pipeline_throws(agency_a, membership_a, monkeypatch):
    """fetch_page's own except Exception wraps only the fetch() call --
    page_lines/content_digest/page_sentences and the stored URL's urlsplit sit
    outside it, on a path mark_letter_ready calls by default. recheck_research_fit
    must not let any of that raise out."""
    with tenant_scope(agency_a.id):
        row = _fit_input(membership_a, "s", "Chair of Robotics", digest="0" * 64)

        def boom(*args, **kwargs):
            raise ValueError("unexpected shape")

        monkeypatch.setattr("apps.documents.research_fit.service.fetch_page", boom)
        assert recheck_research_fit({row.id: row}, fetch=_fetch) == ()


def test_recheck_ignores_non_research_inputs(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        row = NarrativeInput.objects.create(
            student=membership_a, kind=NarrativeInput.Kind.RESEARCH_PLAN, text="x",
            proposed_by="STUDENT",
        )

        def must_not_fetch(url):
            raise AssertionError("must not fetch")

        assert recheck_research_fit({row.id: row}, fetch=must_not_fetch) == ()


def test_recheck_reads_the_page_again_even_when_the_cache_still_holds_it(
    agency_a, membership_a
):
    """PR #114 review, measured: the page cache answered the re-check.

    Its TTL is a week and propose-then-approve routinely falls inside one, so
    the re-check compared the propose-time page against its own propose-time
    digest -- true by construction -- and a professor who had left the page came
    back not stale. Every other recheck test starts with a cleared cache, which
    is why none of them could see it.
    """
    with tenant_scope(agency_a.id):
        row = _fit_input(membership_a, _ROBOTICS_SENTENCE, "Chair of Robotics", digest="0" * 64)
        # Warm the cache exactly as a propose-time fetch would.
        fetch_page(
            row.provenance["source_url"],
            domain="tum.de",
            tenant_id=membership_a.tenant_id,
            fetch=_fetch,
        )
        gone = b"<html><body><main><p>The chair is currently vacant.</p></main></body></html>"
        calls: list[str] = []

        def _second_fetch(url: str, **_: object) -> FetchResult:
            calls.append(url)
            return FetchResult(url, (), "text/html", gone)

        assert recheck_research_fit({row.id: row}, fetch=_second_fetch) == (row.id,)
        assert calls, "the re-check must fetch, not read last week's copy"


def test_every_fetch_failing_is_unreadable_not_no_match(agency_a, membership_a, program_factory):
    """PR #114 review: "no_match" claims we read the institution's pages and
    nothing aligned. With every fetch raising, nothing was read at all -- the
    same silence-versus-absence confusion CLAUDE.md pins for the programme-page
    reader. No claim was invented either way; the label was what lied."""
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        theme = Storyline(
            theme="renewable energy", theme_kind="MATCH", anchors=(uuid4(),), future="f"
        )
        strong = AlignmentReading(strength="strong", excerpt="x")

        def _down(url: str) -> FetchResult:
            raise RuntimeError("vendor 502")

        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=_prompt(program),
            facts={},
            storyline=theme,
            parser=_Parser(strong, strong),
            claude=None,
            classifier=_Classifier(
                ClassifiedSentence(0, 0.9, "research_group", "Chair of Robotics")
            ),
            search=_search(),
            fallback_search=None,
            fetch=_down,
        )
        assert out.status == "unreadable" and not NarrativeInput.objects.exists()


class _EndlessParser:
    """A topic phrase, then a `weak` reading for every judgement, forever.

    `_Parser` pops a fixed list, which is exactly what a test of an UNBOUNDED
    search cannot use: it would fail on an IndexError rather than on the
    number of calls.
    """

    def __init__(self, phrase):
        from apps.documents.research_fit.anchors import TopicPhrase

        self.first = TopicPhrase(phrase=phrase)
        self.calls = 0

    def parse(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _Response(self.first)
        return _Response(AlignmentReading(strength="weak", excerpt=""))


def test_one_proposal_cannot_spend_more_than_the_model_call_cap(
    agency_a, membership_a, program_factory, institution_factory
):
    """The search space is combinatorial and nothing used to bound it.

    Four domains x three pages is twelve classifications and twelve
    three-reading judgements for one letter -- spent in full exactly when
    nothing matches, which is the common case. `rate_limited` counts
    proposals, and the daily ceiling meters search spend, so neither saw it.
    """
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        for n in range(3):
            program.awarding_institutions.add(
                institution_factory(official_website=f"https://partner{n}.example.test/")
            )
        prompt = _prompt(program)
        fact = _research_fact(membership_a)
        parser = _EndlessParser("legged locomotion control")
        classifier = _Classifier(ClassifiedSentence(0, 0.9, "research_group", "Chair of Robotics"))

        def search(*, query, domain):
            return SiteSearchResult(
                urls=tuple(f"https://{domain}/page{i}" for i in range(3)),
                cost_usd=0.0,
                provider="exa",
            )

        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=prompt,
            facts={fact.id: fact},
            storyline=None,
            parser=parser,
            claude=None,
            classifier=classifier,
            search=search,
            fallback_search=None,
            fetch=_fetch,
        )
    assert out.status == "no_match"
    # Twelve pages were reachable; six were read.
    assert len(classifier.calls) == MAX_PAGES_CLASSIFIED
    # 1 topic phrase + 2 OpenAI readings per judged page (no Claude client).
    assert parser.calls == 1 + MAX_PAGES_CLASSIFIED * 2
    assert out.model_calls == 1 + MAX_PAGES_CLASSIFIED * 3
    assert out.model_calls <= MAX_MODEL_CALLS


def test_the_fetch_budget_stops_a_proposal_and_is_charged_to_the_tenant(
    agency_a, membership_a, program_factory, settings
):
    """D15: every page read is a billable vendor credit, and the daily ceiling
    used to meter SEARCH spend only.

    `MAX_PAGES_CLASSIFIED` does not bound this half -- it counts pages
    successfully READ, so a run whose fetches all fail or all get refused
    walks the whole 2 x domains x 2 x TOP_PAGES search space paying for every
    attempt. The budget is what bounds it, and its dollars go into the same
    per-tenant ceiling as the search dollars.
    """
    settings.RESEARCH_FIT_FETCH_CREDITS = {"FIRECRAWL": 2, "SCRAPE_DO": 0}
    spent: list[str] = []

    def _charging_fetch(url, **kwargs):
        # Check then spend, in that order, because that is what the vendor
        # modules do (SweepBudget's own docstring: the cap is checked after the
        # cost is known, and `check` refuses the NEXT rung). Two credits
        # against a cap of two, so the second page is refused before its
        # request is made rather than after it is paid for.
        kwargs["budget"].check("FIRECRAWL")
        spent.append(url)
        kwargs["budget"].spend("FIRECRAWL", 2)
        return FetchResult(url, (), "text/html", _HTML)

    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        fact = _research_fact(membership_a)
        from apps.documents.research_fit.anchors import TopicPhrase

        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=_prompt(program),
            facts={fact.id: fact},
            storyline=None,
            parser=_Parser(TopicPhrase(phrase="legged locomotion control")),
            claude=None,
            classifier=_Classifier(),
            search=_search(urls=("https://www.university.example.test/a",
                                "https://www.university.example.test/b",
                                "https://www.university.example.test/c")),
            fallback_search=None,
            fetch=_charging_fetch,
        )

    assert out.status == "ceiling"
    # One page paid for, the next refused before its request -- not all three.
    assert len(spent) == 1
    # 2 Firecrawl credits at the 2026-09-19 plan price, reported in dollars.
    assert out.cost_usd == pytest.approx(0.007 + 2 * (83 / 100_000))


def test_a_sentence_quoted_from_a_capture_says_when_the_page_was_captured(
    agency_a, membership_a, program_factory
):
    """FIX 1: this consumer's sentences are cited in a student's letter, and
    `retrieve_official_source` returns ARCHIVED as SERVED under the ORIGINAL
    url -- so a capture up to a year old reads as what the institution says
    today. `provenance` is the row's own carrier and is where the capture date
    belongs; a live page leaves it empty."""
    from apps.documents.research_fit.anchors import TopicPhrase
    from apps.research.fetch.types import FetchedPage, Outcome

    def _archived_fetch(url, **_):
        return FetchedPage(
            final_url=url, redirects=(), content_type="text/html", body=_HTML,
            fetched_via="ARCHIVE", outcome=Outcome.ARCHIVED, rung=6, captured_at="2026-06-25",
        )

    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        prompt = _prompt(program)
        fact = _research_fact(membership_a)
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=prompt,
            facts={fact.id: fact},
            storyline=None,
            parser=_Parser(TopicPhrase(phrase="legged locomotion control"), _strong(), _strong()),
            claude=None,
            classifier=_Classifier(
                ClassifiedSentence(0, 0.9, "research_group", "Chair of Robotics"),
                ClassifiedSentence(1, 0.1, "none", None),
            ),
            search=_search(),
            fallback_search=None,
            fetch=_archived_fetch,
        )
        assert out.status == "matched"
        assert out.narrative_input.provenance["captured_at"] == "2026-06-25"


def test_a_sentence_quoted_from_a_live_page_carries_no_capture_date(
    agency_a, membership_a, program_factory
):
    from apps.documents.research_fit.anchors import TopicPhrase

    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        prompt = _prompt(program)
        fact = _research_fact(membership_a)
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=prompt,
            facts={fact.id: fact},
            storyline=None,
            parser=_Parser(TopicPhrase(phrase="legged locomotion control"), _strong(), _strong()),
            claude=None,
            classifier=_Classifier(
                ClassifiedSentence(0, 0.9, "research_group", "Chair of Robotics"),
                ClassifiedSentence(1, 0.1, "none", None),
            ),
            search=_search(),
            fallback_search=None,
            fetch=_fetch,
        )
        assert out.status == "matched"
        assert out.narrative_input.provenance["captured_at"] == ""


def test_forbidden_naming_skips_people_and_groups_and_keeps_modules(
    agency_a, membership_a, program_factory
):
    from apps.documents.research_fit.anchors import TopicPhrase

    html = (
        b"<html><body><main>"
        b"<p>Prof. Jane Smith leads the Chair of Robotics on legged locomotion.</p>"
        b"<p>The Autonomous Locomotion Track covers model predictive gait control.</p>"
        b"</main></body></html>"
    )
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="US")
        prompt = _prompt(
            program,
            funder_kind=ApplicationPrompt.FunderKind.DEVELOPMENT_FOUNDATION,
            letter_naming="FORBIDDEN",
        )
        fact = _research_fact(membership_a)
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=prompt,
            facts={fact.id: fact},
            storyline=None,
            parser=_Parser(TopicPhrase(phrase="legged locomotion control"), _strong(), _strong()),
            claude=None,
            classifier=_Classifier(
                ClassifiedSentence(0, 0.98, "named_person", "Prof. Jane Smith"),
                ClassifiedSentence(0, 0.95, "research_group", "Chair of Robotics"),
                ClassifiedSentence(1, 0.80, "module_or_track", "Autonomous Locomotion Track"),
            ),
            search=_search(),
            fallback_search=None,
            fetch=lambda url, **_: FetchResult(url, (), "text/html", html),
        )
        assert out.status == "matched"
        assert out.narrative_input.provenance["kind"] == "module_or_track"
        assert out.narrative_input.provenance["entity"] == "Autonomous Locomotion Track"


def test_named_person_match_attaches_verified_paper_provenance(
    agency_a, membership_a, program_factory
):
    from apps.documents.research_fit.anchors import TopicPhrase
    from apps.documents.research_fit.papers import PaperMatch

    html = (
        b"<html><body><main>"
        b"<p>Prof. Jane Smith leads research on legged locomotion control.</p>"
        b"</main></body></html>"
    )
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        prompt = _prompt(program)
        fact = _research_fact(membership_a)
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=prompt,
            facts={fact.id: fact},
            storyline=None,
            parser=_Parser(TopicPhrase(phrase="legged locomotion control"), _strong(), _strong()),
            claude=None,
            classifier=_Classifier(
                ClassifiedSentence(0, 0.95, "named_person", "Prof. Jane Smith"),
            ),
            search=_search(),
            fallback_search=None,
            fetch=lambda url, **_: FetchResult(url, (), "text/html", html),
            paper_lookup=lambda **_: PaperMatch(
                title="Torque-Controlled Quadruped Trotting",
                year=2025,
                url="https://doi.org/10.1000/quad.2025",
                finding="Demonstrated stable trotting on 25-degree inclines.",
            ),
        )
        assert out.status == "matched"
        prov = out.narrative_input.provenance
        assert prov["kind"] == "named_person"
        assert prov["entity"] == "Prof. Jane Smith"
        assert prov["paper_title"] == "Torque-Controlled Quadruped Trotting"
        assert prov["paper_year"] == 2025
        assert prov["paper_url"] == "https://doi.org/10.1000/quad.2025"
        assert prov["paper_finding"] == "Demonstrated stable trotting on 25-degree inclines."
        assert prov["paper_author_role"] == "lead"


def test_duplicate_urls_across_queries_are_classified_only_once(
    agency_a, membership_a, program_factory
):
    from apps.documents.research_fit.anchors import TopicPhrase

    with tenant_scope(agency_a.id):
        # DE programme triggers English query first, then lazy German translation after English
        # does not produce a strong match.
        program = program_factory(country_code="DE")
        prompt = _prompt(program)
        fact = _research_fact(membership_a)
        weak = AlignmentReading(strength="weak", excerpt="x")
        parser = _Parser(
            TopicPhrase(phrase="legged locomotion control"),
            weak,
            weak,
            TopicPhrase(phrase="laufroboter regelung"),
        )
        classifier = _Classifier(
            ClassifiedSentence(0, 0.9, "research_group", "Chair of Robotics")
        )
        # Both queries return the exact same URL; it must be classified and judged once.
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=prompt,
            facts={fact.id: fact},
            storyline=None,
            parser=parser,
            claude=None,
            classifier=classifier,
            search=_search(urls=("https://www.university.example.test/robotics",)),
            fallback_search=None,
            fetch=_fetch,
        )
        assert out.status == "no_match"
        assert len(classifier.calls) == 1


def test_lazy_translation_skips_translate_phrase_when_english_query_matches(
    agency_a, membership_a, program_factory
):
    from apps.documents.research_fit.anchors import TopicPhrase

    with tenant_scope(agency_a.id):
        program = program_factory(country_code="DE")
        prompt = _prompt(program)
        fact = _research_fact(membership_a)
        # Only topic_phrase + 2 judge readings; if translate_phrase were called eagerly,
        # _Parser would pop the wrong response type and fail.
        parser = _Parser(
            TopicPhrase(phrase="legged locomotion control"),
            _strong(),
            _strong(),
        )
        classifier = _Classifier(
            ClassifiedSentence(0, 0.9, "research_group", "Chair of Robotics")
        )
        search = _search(urls=("https://www.university.example.test/robotics",))
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=prompt,
            facts={fact.id: fact},
            storyline=None,
            parser=parser,
            claude=None,
            classifier=classifier,
            search=search,
            fallback_search=None,
            fetch=_fetch,
        )
        assert out.status == "matched"
        assert search.sent == [("legged locomotion control", "university.example.test")]
        assert len(parser.calls) == 3


def test_research_group_match_resolves_same_page_pi_paper_and_fit_mode(
    agency_a, membership_a, program_factory
):
    from apps.documents.research_fit.anchors import TopicPhrase
    from apps.documents.research_fit.papers import PaperMatch

    html = (
        b"<html><body><main>"
        b"<p>The Chair of Autonomous Systems investigates legged locomotion control.</p>"
        b"<p>The chair is headed by Prof. Jane Smith.</p>"
        b"</main></body></html>"
    )
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        prompt = _prompt(program)
        fact = _research_fact(membership_a)
        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=prompt,
            facts={fact.id: fact},
            storyline=None,
            parser=_Parser(TopicPhrase(phrase="legged locomotion control"), _strong(), _strong()),
            claude=None,
            classifier=_Classifier(
                ClassifiedSentence(0, 0.92, "research_group", "Chair of Autonomous Systems"),
                ClassifiedSentence(1, 0.75, "named_person", "Prof. Jane Smith"),
            ),
            search=_search(),
            fallback_search=None,
            fetch=lambda url, **_: FetchResult(url, (), "text/html", html),
            paper_lookup=lambda **kwargs: PaperMatch(
                title="Closed-Loop Gait Control on Rough Terrain",
                year=2025,
                url="https://doi.org/10.1000/chair.2025",
                finding="We prove stability bounds under terrain uncertainty.",
            )
            if kwargs.get("entity") == "Prof. Jane Smith"
            else None,
        )
        assert out.status == "matched"
        prov = out.narrative_input.provenance
        assert prov["kind"] == "research_group"
        assert prov["entity"] == "Chair of Autonomous Systems"
        assert prov["paper_title"] == "Closed-Loop Gait Control on Rough Terrain"
        assert prov["fit_mode"] == "direct"


def test_partner_domain_match_passes_partner_institution_name_to_paper_lookup(
    agency_a, membership_a, program_factory, institution_factory
):
    from apps.documents.research_fit.anchors import TopicPhrase
    from apps.documents.research_fit.papers import PaperMatch

    html = (
        b"<html><body><main>"
        b"<p>Prof. Elena Rossi leads the Partner Robotics Lab on legged locomotion.</p>"
        b"</main></body></html>"
    )
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="GB")
        partner = institution_factory(
            name="Politecnico di Milano",
            official_website="https://www.polimi.example.test/",
        )
        program.awarding_institutions.add(partner)
        prompt = _prompt(program)
        fact = _research_fact(membership_a)
        captured_kwargs: dict[str, object] = {}

        def _lookup(**kwargs):
            captured_kwargs.update(kwargs)
            return PaperMatch(
                title="Partner Quadruped Control",
                year=2025,
                url="https://doi.org/10.1000/polimi.2025",
                finding="Demonstrated partner lab gait stability.",
            )

        def _partner_search(*, query, domain):
            if domain == "polimi.example.test":
                return SiteSearchResult(
                    urls=("https://www.polimi.example.test/robotics",),
                    cost_usd=0.007,
                    provider="exa",
                )
            return SiteSearchResult(urls=(), cost_usd=0.007, provider="exa")

        out = propose_research_fit(
            student=membership_a,
            program=program,
            prompt=prompt,
            facts={fact.id: fact},
            storyline=None,
            parser=_Parser(TopicPhrase(phrase="legged locomotion control"), _strong(), _strong()),
            claude=None,
            classifier=_Classifier(
                ClassifiedSentence(0, 0.95, "named_person", "Prof. Elena Rossi")
            ),
            search=_partner_search,
            fallback_search=None,
            fetch=lambda url, **_: FetchResult(url, (), "text/html", html),
            paper_lookup=_lookup,
        )
        assert out.status == "matched"
        assert captured_kwargs["institution_name"] == "Politecnico di Milano"
        assert captured_kwargs["domains"][0] == "polimi.example.test"





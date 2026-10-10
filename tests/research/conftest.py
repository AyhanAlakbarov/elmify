import itertools
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest


@dataclass
class FakeResponse:
    output_parsed: object
    id: str = "resp_funding_123"
    usage: object = field(
        default_factory=lambda: SimpleNamespace(input_tokens=31, output_tokens=17, total_tokens=48)
    )
    output: list[object] | None = None
    #: The Anthropic side of the same fake: messages.parse returns
    #: parsed_output and a stop_reason, so one script answers both clients.
    stop_reason: str = "end_turn"
    status: str = "completed"

    @property
    def parsed_output(self) -> object:
        return self.output_parsed


class FakeResponses:
    """One response per call, the last one repeating -- three reads may disagree."""

    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


def verdict(line: int, **overrides: object):
    """A funding verdict for a 50% tuition waiver on `line`; override any field."""
    from apps.research.funding_judge import LineVerdict

    fields: dict[str, object] = {
        "line": line,
        "offered": "YES",
        "kind": "I2_PROGRAMME_ATTACHED",
        "scope": "PROGRAM",
        "internationals_included": "YES",
        "nationality_shape": "OPEN",
        "route": "AUTOMATIC_ON_ADMISSION",
        "money_form": "FEE_WAIVER",
        "tuition": "PARTIAL",
        "living": "NONE",
        "name": "Tuition waiver",
    }
    fields.update(overrides)
    return LineVerdict(**fields)  # type: ignore[arg-type]


class ScriptedReaders:
    """Stands in for BOTH funding clients, answering calls in order.

    readings[n] maps a sentence to verdict overrides for call n (the last
    mapping repeats). Each call reads the listing it was sent and returns a
    verdict for every line ending with a scripted sentence, so a test never
    hard-codes a line index. fail_calls holds 1-based call numbers that raise.
    """

    def __init__(self, *readings: dict[str, dict[str, object]], fail_calls: tuple[int, ...] = ()):
        self.readings = readings or ({},)
        self.fail_calls = fail_calls
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> FakeResponse:
        from apps.research.funding_judge import FundingVerdicts

        self.calls.append(kwargs)
        if len(self.calls) in self.fail_calls:
            raise RuntimeError("upstream 500")
        script = self.readings[min(len(self.calls) - 1, len(self.readings) - 1)]
        if "input" in kwargs:
            data = kwargs["input"][1]["content"]  # type: ignore[index]
        else:
            data = kwargs["messages"][0]["content"]  # type: ignore[index]
        verdicts = []
        for row in str(data).split("\n")[1:]:
            index, _, rest = row.partition(" | ")
            for sentence, overrides in script.items():
                if rest.endswith(sentence):
                    verdicts.append(verdict(int(index), **overrides))
        return FakeResponse(output_parsed=FundingVerdicts(verdicts=tuple(verdicts)))


@pytest.fixture
def snapshot_factory(db):
    """The smallest OfficialSource + OfficialSourceSnapshot pair that
    satisfies both models' required fields (see test_freshness.py, which
    builds the same shape inline). Each call gets its own OfficialSource --
    `canonical_url` is unique -- so callers never collide on it.

    Takes `final_url` as a keyword because that is the only field the monitor
    commands look up a snapshot by (`snapshot__final_url` /
    `OfficialSourceSnapshot.objects.filter(final_url=url)`); every other
    field is a default a caller can override by keyword.
    """
    from django.utils import timezone

    from apps.funding.models import OfficialSource, OfficialSourceSnapshot

    counter = itertools.count()

    def make(*, final_url, **overrides):
        n = next(counter)
        source = OfficialSource.objects.create(
            canonical_url=overrides.pop("canonical_url", f"https://official.example/{n}"),
            publisher=overrides.pop("publisher", "Official University"),
            source_type=overrides.pop("source_type", OfficialSource.Type.PROGRAM),
        )
        fields: dict[str, object] = dict(
            source=source,
            s3_key=f"official-sources/{n}",
            s3_version_id="1",
            sha256=f"{n:064x}",
            final_url=final_url,
            redirect_chain=[],
            retrieved_at=timezone.now(),
            admissions_cycle="2027",
            content_type="text/html",
            byte_size=1,
        )
        fields.update(overrides)
        return OfficialSourceSnapshot.objects.create(**fields)

    return make


@pytest.fixture
def profile_snapshot():
    """A valid schema-3 StudentProfileSnapshot with keyword overrides.

    Delegates to tests/funding/conftest.py::make_profile -- the base's existing
    factory -- rather than keeping a second default profile here that could
    drift from it.
    """
    from tests.funding.conftest import make_profile

    return make_profile


@pytest.fixture
def student_profile_version(agency_a, membership_a, profile_snapshot):
    """A published schema-3 profile version for membership_a, written through
    the real writer (accounts.profile_versions.create_profile_version)."""
    from apps.accounts.profile_versions import create_profile_version
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        return create_profile_version(
            student=membership_a,
            snapshot=profile_snapshot(
                target_field="Physical chemistry", research_interests=("catalysis",)
            ),
        )


@pytest.fixture
def student(agency_a, membership_a):
    """membership_a, with its tenant scope held for the whole test -- the
    wallet functions, like every service here, run inside the caller's scope."""
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        yield membership_a


@pytest.fixture
def tap_for(agency_a):
    """tap_for(wallet, allowance=Decimal("5")) -> a SearchTap on a fresh run."""
    from decimal import Decimal

    from apps.research.models import SearchTap
    from apps.tenancy.context import tenant_scope
    from tests.funding.conftest import make_run

    def make(wallet, *, allowance=Decimal("5")):
        run = make_run(agency_a, wallet.student)
        with tenant_scope(agency_a.id):
            return SearchTap.objects.create(
                student=wallet.student, wallet=wallet, run_id=run.id, allowance_usd=allowance
            )

    return make



@pytest.fixture
def served_award():
    """served_award(holder=..., nationalities=(...)) -> a served HOLDER award
    (tests/research/coverage_factories.py::make_served_award)."""
    from tests.research.coverage_factories import make_served_award

    return make_served_award


@pytest.fixture
def published_student(agency_a, django_user_model):
    """published_student(nationality=..., allowed=..., eligible_awards=...) -> an
    active student with a published pack
    (tests/research/coverage_factories.py::make_published_student)."""
    from tests.research.coverage_factories import make_published_student

    def make(**kwargs):
        return make_published_student(agency_a, django_user_model, **kwargs)

    return make

import pytest

from scripts.evaluate_phase1 import compute_scorecard


@pytest.fixture
def benchmark_scorecard():
    """The six core Phase1Scorecard metrics computed from tests/benchmarks/ fixtures.

    These fixtures are SYNTHETIC placeholders (see tests/benchmarks/README.md) --
    this proves the precision/recall/support/lift arithmetic is wired correctly,
    not that Phase 1 has passed real acceptance.
    """
    score, missing, used_synthetic = compute_scorecard()
    assert not missing, f"benchmark evidence missing: {missing}"
    return score


@pytest.fixture
def cross_tenant_failures(agency_a, agency_b, domain_a, domain_b, user_a, membership_a) -> int:
    """Re-run a small curated set of already-proven cross-tenant checks directly.

    Deliberately does not shell out to pytest (this fixture already runs inside a
    pytest process) -- it reuses the same service functions the dedicated test
    suites already cover, as a regression check.
    """
    from apps.audit.exports import build_export

    failures = 0

    try:
        build_export(agency_b.id, membership_a.id)
    except ValueError:
        pass
    else:
        failures += 1

    from django.test import Client

    client = Client()
    client.force_login(user_a)
    response = client.get("/", HTTP_HOST=domain_b.host)
    if response.status_code != 403:
        failures += 1

    return failures


@pytest.fixture
def scorecard(benchmark_scorecard, cross_tenant_failures):
    from dataclasses import replace

    return replace(benchmark_scorecard, cross_tenant_failures=cross_tenant_failures)

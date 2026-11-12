"""Where a student who picks no country is searched."""

from django.db.models import Count

from .models import Organisation

#: The owner's target list of 2026-09-26: the 27 EU members, then the rest. Africa,
#: South America and Mexico ("top universities only") stay out until a
#: top-universities mechanism exists.
TARGET_COUNTRIES: tuple[str, ...] = tuple(
    (
        "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE "
        "NO CH IS GB SA AE QA KW BH AU NZ SG BN RS TR CN JP KR RU VN AM AZ GE KZ US CA"
    ).split()
)


def anywhere(excluded: frozenset[str] | set[str] | tuple[str, ...] = ()) -> tuple[str, ...]:
    """Every target country not excluded, thinnest catalogue first (known
    INSTITUTION organisations per country; ties keep TARGET_COUNTRIES order).
    One aggregate read of the shared catalogue: call it in the worker, never in
    the web hook (`runtime_web` holds no grant on research_organisation)."""
    counts = dict(
        Organisation.objects.filter(
            kind="INSTITUTION",
            status__in=[Organisation.Status.REGISTERED, Organisation.Status.CANDIDATE],
            country_code__in=TARGET_COUNTRIES,
        )
        .values_list("country_code")
        .annotate(n=Count("id"))
    )
    wanted = [code for code in TARGET_COUNTRIES if code not in excluded]
    return tuple(sorted(wanted, key=lambda code: counts.get(code, 0)))  # sorted is stable

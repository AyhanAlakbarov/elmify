import pytest


@pytest.mark.django_db
def test_unverified_domain_denies_data_access(client, unverified_domain):
    response = client.get("/student/recommendation/", HTTP_HOST=unverified_domain.host)
    assert response.status_code in (400, 404)


@pytest.mark.django_db
def test_branding_contrast_validated(agency_a):
    from apps.tenancy.services import validate_brand_contrast

    assert validate_brand_contrast("#FFFFFF", "#FFFFF0") is False
    assert validate_brand_contrast("#000000", "#FFFFFF") is True


def test_derive_brand_tint_mirrors_css_color_mix():
    from apps.tenancy.services import derive_brand_tint

    # 22% of pure black over the cream canvas #f9f7f0: each channel * 0.78.
    assert derive_brand_tint("#000000") == "#c2c1bb"
    # Mixing the canvas with itself is a no-op.
    assert derive_brand_tint("#f9f7f0") == "#f9f7f0"


# The swap test, automated: every text-on-surface pair the component contracts
# compose must hold under any tenant primary that passes save-time validation.
#
# These hexes mirrored static/css/app.css and the design contract, and both are
# gone with the presentation layer (DESIGN.md, deleted 2026-09-19). So this
# table is now the palette contract rather than a copy of one: a stylesheet
# built later has to adopt these values, because they are what every primary a
# tenant can save was validated against.
INK = "#333333"
DEEP_HARBOR = "#13426f"
CANVAS = "#f9f7f0"
RAISED = "#ffffff"
SLATE = "#616c8a"
SEMANTIC_ON_TINT = [
    ("#166a2f", "#e2f1e6"),  # eligible text on its tint
    ("#805500", "#f6ecd7"),  # review text on its tint
    ("#b42318", "#f9e4e1"),  # ineligible text on its tint
]
SWAP_PRIMARIES = ["#0254a5", "#1d4ed8", "#b45309", "#1a7f37", "#000000"]


@pytest.mark.parametrize("primary", SWAP_PRIMARIES)
def test_swap_matrix_tenant_variable_pairs(primary):
    """Tenant-dependent pairs hold for representative and worst-case primaries."""
    from apps.tenancy.services import derive_brand_tint, validate_brand_contrast

    tint = derive_brand_tint(primary)
    # Filled interactive: white text on the primary (buttons, filled pills).
    assert validate_brand_contrast("#ffffff", primary) is True
    # Text permitted on the derived tint: Ink and Deep Harbor only.
    assert validate_brand_contrast(INK, tint) is True
    assert validate_brand_contrast(DEEP_HARBOR, tint) is True
    # Links / brand-colored text on both light surfaces.
    assert validate_brand_contrast(primary, CANVAS) is True
    assert validate_brand_contrast(primary, RAISED) is True


@pytest.mark.parametrize("surface", [CANVAS, RAISED])
def test_swap_matrix_platform_fixed_pairs(surface):
    """Tenant-independent pairs: body text, headings, metadata, status."""
    from apps.tenancy.services import validate_brand_contrast

    assert validate_brand_contrast(INK, surface) is True
    assert validate_brand_contrast(DEEP_HARBOR, surface) is True
    assert validate_brand_contrast(SLATE, surface) is True  # ≥14px text only
    for text, tint in SEMANTIC_ON_TINT:
        assert validate_brand_contrast(text, surface) is True
        assert validate_brand_contrast(text, tint) is True
    # Dark blocks and inverse text (navy cards, filled roadmap pills).
    assert validate_brand_contrast("#ffffff", DEEP_HARBOR) is True


def test_swap_matrix_documents_banned_pairs():
    """The banned combinations really do fail — guards the rule's rationale."""
    from apps.tenancy.services import derive_brand_tint, validate_brand_contrast

    for primary in ("#b45309", "#1a7f37"):
        tint = derive_brand_tint(primary)
        assert validate_brand_contrast(primary, tint) is False  # primary-as-text on tint
        assert validate_brand_contrast("#ffffff", tint) is False  # white on tint


def test_brand_palette_checks_primary_and_derived_tint():
    from apps.tenancy.services import (
        derive_brand_tint,
        validate_brand_contrast,
        validate_brand_palette,
    )

    # Deep Wave passes; Relief's Sky Pop fails the
    # primary-vs-white leg (3.03:1) and must be rejected.
    assert validate_brand_palette("#0254a5") is True
    assert validate_brand_palette("#2e96ff") is False

    # The darkest possible primary still yields a tint that passes for both
    # permitted text colors — the 22% mix bounds tint darkness.
    darkest_tint = derive_brand_tint("#000000")
    assert validate_brand_contrast("#333333", darkest_tint) is True
    assert validate_brand_contrast("#13426f", darkest_tint) is True

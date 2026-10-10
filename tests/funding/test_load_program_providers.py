import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.funding.models import Institution, Program, ProgramAwardingInstitution

pytestmark = pytest.mark.django_db

HEADER = "program_key,institution_key,name,country_code,official_website\n"


def _csv(tmp_path, body: str):
    path = tmp_path / "providers.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return str(path)


def _joint(
    canonical_key: str = "master:imlex",
    provider_text: str = "A; B",
    location_key: str = "fi:joensuu",
) -> Program:
    return Program._base_manager.create(
        institution=None,
        provision_type=Program.ProvisionType.JOINT,
        provider_text=provider_text,
        canonical_key=canonical_key,
        name="IMLEX",
        campus_name="Joensuu",
        city="Joensuu",
        country_code="FI",
        location_key=location_key,
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )


def test_it_binds_several_institutions_to_one_joint_programme(tmp_path) -> None:
    program = _joint()
    path = _csv(
        tmp_path,
        "master:imlex,fi:uef,University of Eastern Finland,FI,https://www.uef.fi/\n"
        "master:imlex,jp:toyohashi,Toyohashi University of Technology,JP,https://www.tut.ac.jp/\n",
    )

    call_command("load_program_providers", path)

    program.refresh_from_db()
    assert program.awarding_institutions.count() == 2
    assert program.provision_type == "JOINT"


def test_it_creates_an_institution_the_catalog_does_not_have(tmp_path) -> None:
    """This is the hand-curation path two specs assumed already existed: a
    person wrote the row, so canonical_key is hand-curated."""
    _joint()
    path = _csv(
        tmp_path,
        "master:imlex,se:orebro,Örebro University,SE,https://www.oru.se/\n"
        "master:imlex,rs:belgrade,University of Belgrade,RS,https://www.bg.ac.rs/\n",
    )

    call_command("load_program_providers", path)

    created = Institution._base_manager.get(canonical_key="se:orebro")
    assert created.name == "Örebro University"
    assert created.country_code == "SE"


def test_one_named_provider_resolves_the_programme_to_single(tmp_path) -> None:
    """The Basque and Finnish false positives of the name rule land here and
    need no special case."""
    program = _joint(provider_text="Universidad del País Vasco / Euskal Herriko Unibertsitatea")
    path = _csv(
        tmp_path,
        "master:imlex,es:ehu,Universidad del País Vasco,ES,https://www.ehu.eus/\n",
    )

    call_command("load_program_providers", path)

    program.refresh_from_db()
    assert program.provision_type == "SINGLE"
    assert program.institution.canonical_key == "es:ehu"
    assert program.provider_text == ""


def test_it_refuses_a_programme_key_that_names_nothing(tmp_path) -> None:
    path = _csv(tmp_path, "master:nope,fi:uef,University of Eastern Finland,FI,https://www.uef.fi/\n")

    with pytest.raises(CommandError, match="no joint programme"):
        call_command("load_program_providers", path)


def test_it_refuses_an_ambiguous_programme_key(tmp_path) -> None:
    _joint()
    _joint(canonical_key="master:imlex", location_key="be:ghent")
    path = _csv(tmp_path, "master:imlex,fi:uef,University of Eastern Finland,FI,https://www.uef.fi/\n")

    with pytest.raises(CommandError, match="matches 2 joint programmes"):
        call_command("load_program_providers", path)


def test_it_refuses_a_missing_column(tmp_path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("program_key,institution_key\nmaster:imlex,fi:uef\n", encoding="utf-8")

    with pytest.raises(CommandError, match="missing expected column"):
        call_command("load_program_providers", str(path))


def test_it_refuses_a_plaintext_website(tmp_path) -> None:
    _joint()
    path = _csv(tmp_path, "master:imlex,fi:uef,University of Eastern Finland,FI,http://www.uef.fi/\n")

    with pytest.raises(CommandError, match="must be https"):
        call_command("load_program_providers", path)


def test_it_refuses_re_loading_a_pair_already_bound(tmp_path) -> None:
    """The ordinary workflow is re-running the same CSV as it grows, so a
    collision with an already-loaded pair must name the pair, not surface a
    raw IntegrityError traceback. Two institutions keep the programme JOINT
    after the first run, so the second run still finds it and reaches the
    pair INSERT rather than "no joint programme"."""
    _joint()
    path = _csv(
        tmp_path,
        "master:imlex,fi:uef,University of Eastern Finland,FI,https://www.uef.fi/\n"
        "master:imlex,jp:toyohashi,Toyohashi University of Technology,JP,https://www.tut.ac.jp/\n",
    )
    call_command("load_program_providers", path)

    with pytest.raises(CommandError, match="already bound"):
        call_command("load_program_providers", path)

    assert ProgramAwardingInstitution._base_manager.count() == 2


def test_it_refuses_a_country_code_that_is_two_letters_but_not_real_iso(tmp_path) -> None:
    """The line-numbered length check only rejects the wrong length; a bogus
    but two-character code like XX passes it and must be caught by the
    database's institution_country_iso3166_alpha2 constraint instead, with a
    CommandError naming the problem rather than a raw IntegrityError."""
    _joint()
    path = _csv(tmp_path, "master:imlex,xx:nowhere,Nowhere University,XX,https://www.nowhere.example/\n")

    with pytest.raises(CommandError, match="institution_country_iso3166_alpha2"):
        call_command("load_program_providers", path)

    assert Institution._base_manager.filter(canonical_key="xx:nowhere").count() == 0


def test_it_refuses_a_csv_name_that_disagrees_with_the_stored_institution(tmp_path) -> None:
    """get_or_create silently drops `defaults` when canonical_key already
    exists, so a curator who reuses a wrong-but-existing key would otherwise
    get a clean run and a ProgramAwardingInstitution row nobody approved,
    with the checked-in diff lying about which institution it is."""
    _joint()
    Institution._base_manager.create(
        canonical_key="fi:uef",
        name="University of Eastern Finland",
        country_code="FI",
        official_website="https://www.uef.fi/",
    )
    path = _csv(
        tmp_path,
        "master:imlex,fi:uef,Not The Same University,FI,https://www.uef.fi/\n",
    )

    with pytest.raises(CommandError) as excinfo:
        call_command("load_program_providers", path)

    assert "University of Eastern Finland" in str(excinfo.value)
    assert "Not The Same University" in str(excinfo.value)
    assert ProgramAwardingInstitution._base_manager.count() == 0


@pytest.fixture
def joint_program():
    """Committed as the test superuser, before rls_enforced_orm swaps the role.

    Same shape as tests/portals/test_rls_spine.py's prepared_application: a
    fixture requested ahead of rls_enforced_orm in the test signature runs
    (and, under transaction=True, commits) before the connection is
    repointed at the restricted role.
    """
    return _joint()


@pytest.mark.django_db(transaction=True)
def test_it_fails_under_the_ordinary_runtime_role(
    joint_program, tmp_path, rls_enforced_orm
) -> None:
    """The suite otherwise runs as a BYPASSRLS superuser, so without this
    fixture a wrong-role run passes here and fails in production. This is the
    coverage the register adapters still lack."""
    path = _csv(
        tmp_path,
        "master:imlex,fi:uef,University of Eastern Finland,FI,https://www.uef.fi/\n",
    )

    with pytest.raises(Exception, match="row-level security"):
        call_command("load_program_providers", path)

    assert ProgramAwardingInstitution._base_manager.count() == 0

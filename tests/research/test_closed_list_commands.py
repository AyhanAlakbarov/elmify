from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.research.models import ClosedList, RegisterEntry

pytestmark = pytest.mark.django_db

_REGISTRY = (
    "slug,title,country_code,holder_kinds,rung,source_url,maintainer,carries_purpose,"
    "carries_website,reuse_terms,reuse_terms_url,is_denominator,read_policy,printed_size,"
    "verified_on\n"
    "tr_banks,Licensed banks,TR,BANK_OR_LENDER,2,https://www.bddk.org.tr/,BDDK,no,yes,"
    "UNREAD,,yes,SIGNAL_ONLY,2,2026-09-25\n"
)
_ROWS = (
    "external_key,name,kind,website,page_url,country_code,home_cells,host_cells,"
    "rejected_reason,source_url,verified_on,notes\n"
    "b1,Birinci Bankası,BANK_OR_LENDER,https://www.birinci.com.tr,,TR,TR,ANY,,"
    "https://www.bddk.org.tr/,2026-09-25,\n"
)


def _files(tmp_path: Path) -> tuple[Path, Path]:
    registry = tmp_path / "closed-lists.csv"
    registry.write_text(_REGISTRY, encoding="utf-8")
    lists = tmp_path / "closed-lists"
    lists.mkdir()
    (lists / "tr_banks.csv").write_text(_ROWS, encoding="utf-8")
    return registry, lists


def test_load_then_coverage_fails_the_gate_on_a_short_list(tmp_path: Path) -> None:
    registry, lists = _files(tmp_path)
    out = StringIO()
    call_command("load_closed_lists", registry=str(registry), lists_dir=str(lists), stdout=out)
    assert "tr_banks: listed 1, bound 1" in out.getvalue()
    assert RegisterEntry.objects.filter(register="tr_banks").count() == 1

    out = StringIO()
    with pytest.raises(CommandError, match="tr_banks"):
        call_command("closed_list_coverage", list=["tr_banks"], gate=True, stdout=out)
    line = out.getvalue()
    assert "tr_banks  listed 1/2" in line and "GATED=1" in line and "FAIL" in line


def test_coverage_passes_when_every_row_is_bound_and_recorded(tmp_path: Path) -> None:
    registry, lists = _files(tmp_path)
    registry.write_text(_REGISTRY.replace(",2,2026-09-25", ",1,2026-09-25"), encoding="utf-8")
    call_command("load_closed_lists", registry=str(registry), lists_dir=str(lists),
                 stdout=StringIO())
    out = StringIO()
    call_command("closed_list_coverage", list=["tr_banks"], gate=True, stdout=out)
    assert "PASS" in out.getvalue()


def test_read_closed_list_refuses_a_list_nothing_reads(tmp_path: Path) -> None:
    registry, lists = _files(tmp_path)
    registry.write_text(_REGISTRY.replace("SIGNAL_ONLY", "CLASSIFY"), encoding="utf-8")
    call_command("load_closed_lists", registry=str(registry), lists_dir=str(lists),
                 stdout=StringIO())
    with pytest.raises(CommandError, match="classify_organisations --found-via R2_LIST:tr_banks"):
        call_command("read_closed_list", list="tr_banks",
                     tenant="00000000-0000-0000-0000-000000000001")
    assert ClosedList.objects.get().read_policy == "CLASSIFY"

import pytest


@pytest.mark.django_db
def test_a_page_record_holds_a_snapshot_and_no_value_column(agency_a) -> None:
    from apps.portals.models import PageRecord, PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="rec-1")
    record = PageRecord.objects.create(
        portal_form=form, source=PageRecord.Source.LIVE_LEARN, page_kind=PageRecord.Kind.FORM,
        step=1, snapshot={"page_url": "https://apply.example.edu", "controls": []},
        learned_by_tenant=agency_a,
    )
    assert record.html_key == "" and record.password_rules == "" and record.walk_ok is False
    assert record.superseded_at is None
    assert "value" not in {f.name for f in PageRecord._meta.get_fields()}

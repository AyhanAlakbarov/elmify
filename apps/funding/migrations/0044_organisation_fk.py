"""`FundingOpportunity.organisation` -- a real link, backfilled from the string.

`holder_domain` was a string "because the register lives on another branch"
(2026-09-18). It does not any more, and a string holder cannot carry the second
domain, the cadence or the read state the verifier needs.

`holder_domain` is NOT dropped here. It goes in a later migration, once a test
asserts every HOLDER row carries the FK: dropping the column in the same change
that backfills from it leaves no way to check the backfill was right.

The backfill uses historical models rather than
`apps.research.register.record_organisation` -- a migration that calls live app
code breaks the day that code changes. It is the same lookup for the one case it
has to handle, and only that case: a domain the register has not seen becomes a
CANDIDATE row, because a funder we have already read is a body we already know.

It also carries the register's RLS, which looks like it belongs in
`research/0003` and cannot live there. The policies name `catalog_ingestion`,
created by `funding/0006`; depending on that from `research` makes research
downstream of funding and breaks every test that rolls funding back while other
apps stay at their head (`InvalidMigrationPlan`: a plan cannot mix directions).
This migration already depends on `research/0003` for the FK, so it is the first
node where both the tables and the role certainly exist. Same policy shape as
`funding/0030_program_awarding_institutions_rls` and nothing more.
"""

import django.db.models.deletion
from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

_FOUND_VIA = "BACKFILL:holder_domain"

_REGISTER_TABLES = (
    "research_organisation",
    "research_organisationdomain",
    "research_organisationidentifier",
)

REGISTER_RLS_SQL = "\n".join(
    f"""
ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{table}
    FOR SELECT USING (true);
CREATE POLICY catalog_ingestion_write ON public.{table}
    FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
"""
    for table in _REGISTER_TABLES
)

REVERSE_REGISTER_RLS_SQL = "\n".join(
    f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{table};
DROP POLICY IF EXISTS shared_catalog_select ON public.{table};
ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;
"""
    for table in _REGISTER_TABLES
)


def link_holder_rows(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    FundingOpportunity = apps.get_model("funding", "FundingOpportunity")
    Organisation = apps.get_model("research", "Organisation")
    OrganisationDomain = apps.get_model("research", "OrganisationDomain")

    rows = FundingOpportunity.objects.filter(
        scope_type="HOLDER", organisation__isnull=True
    ).exclude(holder_domain="")
    for row in rows.iterator():
        known = OrganisationDomain.objects.filter(
            registrable_domain=row.holder_domain
        ).first()
        if known is None:
            organisation = Organisation.objects.create(
                primary_domain=row.holder_domain,
                name=row.holder_name or row.holder_domain,
                names=[row.holder_name] if row.holder_name else [],
                # The reader's holder vocabulary IS the register's kind. A row
                # written before the holder axis has neither, and UNSTATED is
                # what the vocabulary says for that.
                kind=row.holder or "UNSTATED",
                country_code="",
                found_via=[_FOUND_VIA],
                status="CANDIDATE",
            )
            known = OrganisationDomain.objects.create(
                organisation=organisation,
                registrable_domain=row.holder_domain,
                found_via=[_FOUND_VIA],
            )
        row.organisation_id = known.organisation_id
        row.save(update_fields=["organisation"])


def unlink_holder_rows(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Reverse: drop the link. The Organisation rows this created are left --
    they are a register the rest of the system now uses, not this migration's
    private state."""
    FundingOpportunity = apps.get_model("funding", "FundingOpportunity")
    FundingOpportunity.objects.filter(scope_type="HOLDER").update(organisation=None)


class Migration(migrations.Migration):

    dependencies = [
        ('funding', '0043_grade_key'),
        ('research', '0003_organisation_register'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='fundingopportunity',
            name='funding_opportunity_scope_shape_valid',
        ),
        migrations.AddField(
            model_name='fundingopportunity',
            name='organisation',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='research.organisation'),
        ),
        migrations.RunSQL(REGISTER_RLS_SQL, REVERSE_REGISTER_RLS_SQL),
        migrations.RunPython(link_holder_rows, unlink_holder_rows),
        migrations.AddConstraint(
            model_name='fundingopportunity',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('scope_type__in', ['GLOBAL', 'COUNTRY', 'INSTITUTION', 'PROGRAM', 'HOLDER']), _negated=True), models.Q(('country_code__isnull', True), ('institution__isnull', True), ('program__isnull', True), ('scope_type', 'GLOBAL')), models.Q(('country_code__isnull', False), ('institution__isnull', True), ('program__isnull', True), ('scope_type', 'COUNTRY')), models.Q(('country_code__isnull', True), ('institution__isnull', False), ('program__isnull', True), ('scope_type', 'INSTITUTION')), models.Q(('country_code__isnull', True), ('institution__isnull', True), ('program__isnull', False), ('scope_type', 'PROGRAM')), models.Q(('country_code__isnull', True), ('institution__isnull', True), ('organisation__isnull', False), ('program__isnull', True), ('scope_type', 'HOLDER')), _connector='OR'), name='funding_opportunity_scope_shape_valid'),
        ),
    ]

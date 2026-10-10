"""The Organisation register: three shared-catalog tables.

Spec: docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
section 6.1. These tables hold hosts and organisations. Nothing about a person
is in them, which is why they can be readable by every tenant at all.

**Their RLS is in `funding/0044_organisation_fk`, not here, and that is not
tidiness.** The policies name `catalog_ingestion`, a role created by
`funding/0006_official_snapshots`, so they cannot run before it. Expressing that
as a dependency here -- `('funding', '0006_official_snapshots')` -- was tried and
is wrong: it makes `research` DOWNSTREAM of funding, so every test that rolls
funding back while other apps stay at their head (six in
`tests/migrations/test_task7_migrations.py`) produces a plan containing both
directions and Django refuses it with `InvalidMigrationPlan`. The edge has to run
funding -> research, which is the direction `0044` already needs for its FK.
"""

import django.contrib.postgres.fields
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('research', '0002_rls'),
    ]

    operations = [
        migrations.CreateModel(
            name='Organisation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('primary_domain', models.CharField(max_length=253, unique=True)),
                ('name', models.CharField(max_length=300)),
                ('names', django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=300), blank=True, default=list, size=None)),
                ('kind', models.CharField(choices=[('NATIONAL_GOVERNMENT', 'NATIONAL_GOVERNMENT'), ('SUBNATIONAL_GOVERNMENT', 'SUBNATIONAL_GOVERNMENT'), ('POLITICAL_FOUNDATION', 'POLITICAL_FOUNDATION'), ('RELIGIOUS', 'RELIGIOUS'), ('PRIVATE_FOUNDATION', 'PRIVATE_FOUNDATION'), ('EMPLOYER', 'EMPLOYER'), ('INTERGOVERNMENTAL', 'INTERGOVERNMENTAL'), ('REGIONAL_FUND', 'REGIONAL_FUND'), ('EMBASSY_BILATERAL', 'EMBASSY_BILATERAL'), ('DIASPORA_AFFINITY', 'DIASPORA_AFFINITY'), ('PROFESSIONAL_BODY', 'PROFESSIONAL_BODY'), ('BANK_OR_LENDER', 'BANK_OR_LENDER'), ('ALUMNI', 'ALUMNI'), ('INSTITUTION', 'INSTITUTION'), ('UNSTATED', 'UNSTATED')], max_length=24)),
                ('country_code', models.CharField(blank=True, default='', max_length=2)),
                ('official_website', models.URLField(blank=True, default='', max_length=2048)),
                ('status', models.CharField(choices=[('REGISTERED', 'Registered'), ('CANDIDATE', 'Candidate'), ('REJECTED', 'Rejected')], default='CANDIDATE', max_length=12)),
                ('rejected_reason', models.CharField(blank=True, choices=[('INFRASTRUCTURE', 'Infrastructure'), ('NOT_A_FUNDER', 'Not A Funder'), ('DOES_NOT_EXIST', 'Does Not Exist'), ('UNREACHABLE', 'Unreachable')], default='', max_length=16)),
                ('found_via', django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=120), blank=True, default=list, size=None)),
                ('first_seen', models.DateTimeField(auto_now_add=True)),
                ('last_verified', models.DateTimeField(blank=True, null=True)),
                ('last_read_at', models.DateTimeField(blank=True, null=True)),
                ('pages_read', models.PositiveIntegerField(default=0)),
                ('pages_unreadable', models.PositiveIntegerField(default=0)),
                ('cadence', models.CharField(blank=True, max_length=20, null=True)),
                ('cadence_open_month', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('cadence_deadline_month', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('cadence_source', models.URLField(blank=True, max_length=2048, null=True)),
                ('cadence_verified_for_cycle', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='children', to='research.organisation')),
            ],
        ),
        migrations.CreateModel(
            name='OrganisationDomain',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('registrable_domain', models.CharField(max_length=253, unique=True)),
                ('found_via', django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=120), blank=True, default=list, size=None)),
                ('first_seen', models.DateTimeField(auto_now_add=True)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='domains', to='research.organisation')),
            ],
        ),
        migrations.CreateModel(
            name='OrganisationIdentifier',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('scheme', models.CharField(choices=[('ROR', 'ROR'), ('WIKIDATA', 'WIKIDATA'), ('EACEA_PIC', 'EACEA_PIC'), ('UKPRN', 'UKPRN'), ('CRICOS', 'CRICOS'), ('DLI', 'DLI'), ('NZQA', 'NZQA'), ('IPEDS', 'IPEDS'), ('DEQARINST', 'DEQARINST'), ('ETER', 'ETER'), ('WHED', 'WHED')], max_length=20)),
                ('value', models.CharField(max_length=200)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='identifiers', to='research.organisation')),
            ],
        ),
        migrations.AddConstraint(
            model_name='organisation',
            constraint=models.CheckConstraint(condition=models.Q(('kind__in', ('NATIONAL_GOVERNMENT', 'SUBNATIONAL_GOVERNMENT', 'POLITICAL_FOUNDATION', 'RELIGIOUS', 'PRIVATE_FOUNDATION', 'EMPLOYER', 'INTERGOVERNMENTAL', 'REGIONAL_FUND', 'EMBASSY_BILATERAL', 'DIASPORA_AFFINITY', 'PROFESSIONAL_BODY', 'BANK_OR_LENDER', 'ALUMNI', 'INSTITUTION', 'UNSTATED'))), name='organisation_kind_valid'),
        ),
        migrations.AddConstraint(
            model_name='organisation',
            constraint=models.CheckConstraint(condition=models.Q(('status', 'REJECTED'), ('rejected_reason', ''), _connector='OR'), name='organisation_rejected_reason_shape'),
        ),
        migrations.AddConstraint(
            model_name='organisationidentifier',
            constraint=models.UniqueConstraint(fields=('scheme', 'value'), name='organisation_identifier_scheme_value_uniq'),
        ),
        migrations.AddConstraint(
            model_name='organisationidentifier',
            constraint=models.CheckConstraint(condition=models.Q(('scheme__in', ('ROR', 'WIKIDATA', 'EACEA_PIC', 'UKPRN', 'CRICOS', 'DLI', 'NZQA', 'IPEDS', 'DEQARINST', 'ETER', 'WHED'))), name='organisation_identifier_scheme_valid'),
        ),
    ]

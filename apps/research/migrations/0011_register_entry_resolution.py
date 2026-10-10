"""The resolver's record on RegisterEntry: the names store and how a row was
bound, or why it was not (build item 8 plan, Task 6).

No new table, so no RLS block: the five columns inherit research/0007's
policies on research_registerentry as funding/0049 left them --
`shared_catalog_select` (every tenant reads) and `runtime_engine_write` (only
the engine writes; `catalog_ingestion` is gone), with `runtime_web` holding no
table grant at all. Verified in tests/research/test_register_entry_resolution_rls.py
through `runtime_connection` (reads, and an UPDATE of the new columns matches
zero rows) and `role_connection` (the engine's UPDATE matches one; the web
tier's SELECT is refused) -- never through the test role, which bypasses RLS.

The backfill runs between the AddFields and the AddConstraint, because rows
written before this migration are RESOLVED with no route and the constraint
would refuse them.
"""

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("research", "0010_closed_lists"),
    ]

    operations = [
        migrations.AddField(
            model_name="registerentry",
            name="diffbot_asked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="registerentry",
            name="names",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=300),
                blank=True,
                default=list,
                size=None,
            ),
        ),
        migrations.AddField(
            model_name="registerentry",
            name="resolution_attempted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="registerentry",
            name="resolved_via",
            field=models.CharField(
                blank=True,
                choices=[
                    ("EMAIL", "Email"),
                    ("LISTED", "Listed"),
                    ("WIKIDATA", "Wikidata"),
                    ("SEARCH_SLUG", "Search Slug"),
                    ("SEARCH_TITLE", "Search Title"),
                    ("DIFFBOT", "Diffbot"),
                    ("HUMAN", "Human"),
                ],
                default="",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="registerentry",
            name="unresolved_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("ONE_TOKEN_NAME", "One Token Name"),
                    ("NO_CANDIDATE", "No Candidate"),
                    ("DIRECTORY", "Directory"),
                    ("TITLE_MISMATCH", "Title Mismatch"),
                    ("FETCH_FAILED", "Fetch Failed"),
                    ("IDENTIFIER_CONFLICT", "Identifier Conflict"),
                ],
                default="",
                max_length=20,
            ),
        ),
        # Every RESOLVED row before this migration was bound by its own list:
        # rung 0's e-mail on VGM (vgm.record_vgm), the list's key everywhere
        # else (record_list's website, record_items' P856, record_projects'
        # PIC/website). UNRESOLVED and CONFLICT rows already carry
        # resolved_via = '' from the column default. Plain SQL: research tables
        # are ENABLE, not FORCE, row-level security, so the owner running the
        # migration is not filtered -- and a RunPython would drag the ORM's
        # manager in for nothing.
        migrations.RunSQL(
            "UPDATE research_registerentry SET resolved_via = CASE "
            "WHEN register = 'vgm_tr' THEN 'EMAIL' ELSE 'LISTED' END "
            "WHERE resolution = 'RESOLVED' AND resolved_via = '';"
            "UPDATE research_registerentry SET names = ARRAY[name] WHERE names = '{}';",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddConstraint(
            model_name="registerentry",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("resolution", "RESOLVED"),
                        ("unresolved_reason", ""),
                        models.Q(("resolved_via", ""), _negated=True),
                    ),
                    models.Q(
                        ("resolution__in", ("UNRESOLVED", "CONFLICT")),
                        ("resolved_via", ""),
                    ),
                    _connector="OR",
                ),
                name="register_entry_resolution_shape",
            ),
        ),
    ]

import django.db.models.deletion
import uuid
from django.db import migrations, models


#: The policy every tenant table in this repository carries, copied from
#: apps/portals/migrations/0010_extension_pairing.py. Generated migrations
#: create tables and constraints and none of this.
TABLES = ("mailbox_mailboxconnection", "mailbox_mailsignal")

RLS_SQL = "\n".join(
    f"""
    ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON {table}
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """
    for table in TABLES
)

REVERSE_RLS_SQL = "\n".join(
    f"""
    DROP POLICY IF EXISTS tenant_isolation ON {table};
    ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
    """
    for table in reversed(TABLES)
)


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        # The earliest migrations that satisfy this one, never the latest the
        # autodetector writes: tenancy 0002 adds the (tenant_id, id) key the
        # membership guard references, and the portals migration below creates
        # portals_application with its own. Same pinning every portals
        # migration uses, and for the same reason -- the migration tests roll
        # other apps back and Django refuses a mixed-direction plan.
        ("tenancy", "0002_rls"),
        ("portals", "0002_application"),
    ]

    operations = [
        migrations.CreateModel(
            name="MailboxConnection",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(choices=[("GOOGLE", "Google"), ("MICROSOFT", "Microsoft")], max_length=20)),
                ("address", models.CharField(max_length=320)),
                ("tier", models.CharField(choices=[("METADATA", "Headers only"), ("CONTENT", "Headers and body")], default="CONTENT", max_length=20)),
                ("status", models.CharField(choices=[("ACTIVE", "Active"), ("REVOKED", "Revoked"), ("ERROR", "Needs reconnecting")], default="ACTIVE", max_length=20)),
                ("sync_cursor", models.CharField(blank=True, max_length=40)),
                ("connected_at", models.DateTimeField(auto_now_add=True)),
                ("last_sync_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("membership", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mailbox_connections", to="tenancy.membership")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="tenancy.agency")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("tenant", "id"), name="mailbox_connection_tenant_id_uniq"),
                    models.UniqueConstraint(condition=models.Q(("status", "ACTIVE")), fields=("membership", "provider"), name="mailbox_one_active_connection_per_provider"),
                ],
            },
        ),
        migrations.CreateModel(
            name="MailSignal",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider_message_id", models.CharField(max_length=200)),
                ("sender_domain", models.CharField(max_length=253)),
                ("received_at", models.DateTimeField()),
                ("label", models.CharField(blank=True, choices=[("RECEIVED", "Application received"), ("DOCUMENT_REQUEST", "A document was requested"), ("INTERVIEW", "Interview invitation"), ("DECISION", "A decision"), ("VERIFICATION", "Verify your address"), ("FEE", "A fee is due"), ("OTHER", "Something else")], max_length=30)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("application", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="mail_signals", to="portals.application")),
                ("connection", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="signals", to="mailbox.mailboxconnection")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="tenancy.agency")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("tenant", "id"), name="mailbox_signal_tenant_id_uniq"),
                    models.UniqueConstraint(fields=("connection", "provider_message_id"), name="mailbox_signal_message_uniq"),
                ],
            },
        ),
        # The composite guards every tenant table here carries. Without them a
        # row may name a membership, a connection or an application in ANOTHER
        # tenant, which the policy above would then happily show to this one --
        # the policy checks the row's own tenant_id, not its parents'.
        migrations.RunSQL(
            """
            ALTER TABLE mailbox_mailboxconnection
                ADD CONSTRAINT mailbox_connection_membership_tenant_fk
                FOREIGN KEY (tenant_id, membership_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE mailbox_mailsignal
                ADD CONSTRAINT mailbox_signal_connection_tenant_fk
                FOREIGN KEY (tenant_id, connection_id)
                REFERENCES mailbox_mailboxconnection (tenant_id, id);
            ALTER TABLE mailbox_mailsignal
                ADD CONSTRAINT mailbox_signal_app_tenant_fk
                FOREIGN KEY (tenant_id, application_id)
                REFERENCES portals_application (tenant_id, id);
            """,
            """
            ALTER TABLE mailbox_mailsignal DROP CONSTRAINT mailbox_signal_app_tenant_fk;
            ALTER TABLE mailbox_mailsignal DROP CONSTRAINT mailbox_signal_connection_tenant_fk;
            ALTER TABLE mailbox_mailboxconnection DROP CONSTRAINT mailbox_connection_membership_tenant_fk;
            """,
        ),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]

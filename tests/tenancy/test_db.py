def test_tenant_transaction_sets_the_guc_inside_its_own_block(agency_a):
    from django.db import connection

    from apps.tenancy.db import tenant_transaction

    with tenant_transaction(agency_a.id):
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('app.tenant_id', true)")
            assert cursor.fetchone()[0] == str(agency_a.id)

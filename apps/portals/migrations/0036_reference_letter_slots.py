from django.db import migrations


def _rename(old: str, new: str) -> str:
    # A learned upload box's kind (FieldMap.slots[*].kind) follows the upload kind's
    # rename: parse_slots drops a box whose kind is not a DocKind, so an unrenamed
    # box would silently take nothing. portals_fieldmap is not RLS-covered (shared
    # on purpose, see FieldMap.learned_by_tenant), so a plain UPDATE reaches every row.
    return f"""
    UPDATE portals_fieldmap SET slots = (
        SELECT jsonb_agg(
            CASE WHEN slot->>'kind' = '{old}'
                 THEN jsonb_set(slot, '{{kind}}', '"{new}"') ELSE slot END
            ORDER BY position)
        FROM jsonb_array_elements(slots) WITH ORDINALITY AS t(slot, position)
    )
    WHERE jsonb_typeof(slots) = 'array' AND slots @> '[{{"kind": "{old}"}}]';
    """


class Migration(migrations.Migration):

    dependencies = [
        ("portals", "0035_extension_pairing_passwords_allowed"),
    ]

    operations = [
        migrations.RunSQL(
            _rename("RECOMMENDATION", "REFERENCE_LETTER"),
            _rename("REFERENCE_LETTER", "RECOMMENDATION"),
        ),
    ]

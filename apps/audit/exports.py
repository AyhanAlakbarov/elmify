import io
import json
import zipfile
from uuid import UUID

from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope

from .services import build_dossier, resolve_student


def build_export(tenant_id: UUID, student_id: UUID) -> bytes:
    resolve_student(tenant_id, student_id)  # raises ValueError on cross-tenant lookup
    with tenant_scope(tenant_id):
        event_count = AuditEvent.objects.filter(object_id=student_id).count()
    manifest = {
        "tenant_id": str(tenant_id),
        "student_id": str(student_id),
        "event_count": event_count,
    }
    dossier_html = build_dossier(tenant_id, student_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("dossier.html", dossier_html)
    return buffer.getvalue()

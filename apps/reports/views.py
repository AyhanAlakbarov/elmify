from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse

from apps.research.storage import S3ObjectStore
from apps.tenancy.models import Membership

from .models import ConsultationReport


@login_required
def download(request: HttpRequest, report_id: str) -> HttpResponse:
    assert request.user.pk is not None
    membership = Membership.objects.get(user_id=request.user.pk, active=True)
    try:
        report = ConsultationReport.objects.get(
            id=report_id, pack_version__run__profile_version__student=membership
        )
    except ConsultationReport.DoesNotExist as error:
        raise Http404 from error
    body = S3ObjectStore().get(report.object_key)
    response = HttpResponse(body, content_type=report.content_type)
    response["Content-Disposition"] = f'attachment; filename="report-{report.id}.html"'
    return response

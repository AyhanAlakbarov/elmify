from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

from apps.research.storage import S3ObjectStore
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .models import ConsultationPayment, ConsultationReport


@login_required
def download(request: HttpRequest, report_id: str) -> HttpResponse:
    from apps.portals.http import inert_response

    membership = current_membership(request, Membership.Role.STUDENT)
    try:
        report = ConsultationReport.objects.get(
            id=report_id, pack_version__run__profile_version__student=membership
        )
    except ConsultationReport.DoesNotExist as error:
        raise Http404 from error
    body = S3ObjectStore().get(report.object_key)
    return inert_response(body, report.content_type, f"report-{report.id}.html")


@login_required
def student_reports(request: HttpRequest) -> HttpResponse:
    """The student's consultation reports and what they paid for them.

    Tenant rows only. A report is written by the worker once a consultation
    payment settles (services.generate_report); until then this lists the
    payment, so a student who paid sees it was received.
    """
    student = current_membership(request, Membership.Role.STUDENT)
    return render(
        request,
        "student/reports.html",
        {
            "reports": ConsultationReport.objects.filter(
                pack_version__run__profile_version__student=student
            ).order_by("-generated_at"),
            "payments": ConsultationPayment.objects.filter(student=student).order_by(
                "-created_at"
            ),
        },
    )

from django.urls import path

from .views import download, student_reports

urlpatterns = [
    path("reports/<uuid:report_id>/download/", download, name="report-download"),
    path("student/reports/", student_reports, name="student-reports"),
]

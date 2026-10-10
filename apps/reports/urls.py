from django.urls import path

from .views import download

urlpatterns = [
    path("reports/<uuid:report_id>/download/", download, name="report-download"),
]

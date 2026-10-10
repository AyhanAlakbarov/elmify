from django.urls import path

from . import views

_BASE = "counselor/students/<uuid:student_id>/"

urlpatterns = [
    path(_BASE, views.student_board, name="counselor-student-board"),
    path(
        _BASE + "applications/add/<uuid:candidate_id>/",
        views.add,
        name="counselor-student-application-add",
    ),
    path(
        _BASE + "applications/<uuid:application_id>/outcome/",
        views.record_outcome,
        name="counselor-student-outcome",
    ),
    path(
        _BASE + "applications/<uuid:application_id>/remove/",
        views.remove,
        name="counselor-student-application-remove",
    ),
    path(
        _BASE + "applications/<uuid:application_id>/portal/",
        views.portal,
        name="counselor-student-application-portal",
    ),
    path(
        _BASE + "notifications/<uuid:notification_id>/acknowledge/",
        views.acknowledge,
        name="counselor-student-acknowledge",
    ),
    path(_BASE + "messages/send/", views.message, name="counselor-student-message"),
    path(_BASE + "gap-interview/", views.gap_interview, name="counselor-student-gap-interview"),
    path(_BASE + "uploads/", views.upload, name="counselor-student-upload"),
    path(
        _BASE + "offers/<uuid:signal_id>/accept/",
        views.offer_accept,
        name="counselor-student-offer-accept",
    ),
    path(
        _BASE + "offers/<uuid:signal_id>/ignore/",
        views.offer_ignore,
        name="counselor-student-offer-ignore",
    ),
]

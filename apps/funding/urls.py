from django.urls import path

from .views import (
    consider_named_program_view,
    recommendation,
    reject_candidate_view,
    replace_candidate_view,
    resolve_named_program_view,
    review,
)

urlpatterns = [
    path("student/recommendation/", recommendation, name="student-recommendation"),
    path(
        "student/recommendation/candidates/<uuid:candidate_id>/reject/",
        reject_candidate_view,
        name="student-reject-candidate",
    ),
    path(
        "student/recommendation/candidates/<uuid:candidate_id>/replace/",
        replace_candidate_view,
        name="student-replace-candidate",
    ),
    path(
        "student/recommendation/named-program/",
        consider_named_program_view,
        name="student-consider-named-program",
    ),
    path("counselor/runs/<uuid:run_id>/approve/", review, name="counselor-review"),
    path(
        "counselor/runs/<uuid:run_id>/named-program/<uuid:candidate_id>/resolve/",
        resolve_named_program_view,
        name="counselor-resolve-named-program",
    ),
]

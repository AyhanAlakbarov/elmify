from django.urls import path

from .views import (
    account_settings,
    deletion_console,
    deletion_pending,
    deny_deletion_request,
    release_deletion_request,
    request_account_deletion,
    restore_account,
)

urlpatterns = [
    path(
        "student/account/delete/",
        request_account_deletion,
        name="audit-request-account-deletion",
    ),
    path("student/settings/account/", account_settings, name="student-settings-account"),
    path("student/account/deletion/", deletion_pending, name="audit-deletion-pending"),
    path(
        "student/account/restore/<uuid:request_id>/",
        restore_account,
        name="audit-restore-account",
    ),
    path("owner/deletions/", deletion_console, name="audit-deletion-console"),
    path(
        "owner/deletions/<uuid:request_id>/release/",
        release_deletion_request,
        name="audit-release-deletion",
    ),
    path(
        "owner/deletions/<uuid:request_id>/deny/",
        deny_deletion_request,
        name="audit-deny-deletion",
    ),
]

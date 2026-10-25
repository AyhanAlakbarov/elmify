from django.urls import path

from . import api, review, views, workspace, writing

urlpatterns = [
    path(
        "documents/<uuid:draft_id>/<str:filename>",
        views.download_document,
        name="documents-download",
    ),
    path("student/gap-interview/", views.gap_interview, name="student-gap-interview"),
    path("student/documents/", views.documents_page, name="student-documents"),
    path("student/writing/", writing.writing_page, name="student-writing"),
    path(
        "student/writing/letters/<uuid:application_id>/",
        workspace.letter_workspace,
        name="student-letter-workspace",
    ),
    path("student/writing/references/", workspace.references_page, name="student-references"),
    path("counselor/letters/", review.letter_review_queue, name="counselor-letter-review"),
    path(
        "student/writing/letters/<uuid:application_id>/write/",
        writing.letter_write,
        name="student-letter-write",
    ),
    path(
        "student/writing/letters/<uuid:draft_id>/approve/",
        writing.letter_approve,
        name="student-letter-approve",
    ),
    path("student/documents/submit/", views.submit_document, name="student-document-submit"),
    path(
        "student/documents/<uuid:document_id>/expiry/",
        views.document_expiry,
        name="student-document-expiry",
    ),
    path(
        "student/documents/requests/<uuid:signal_id>/",
        views.document_request,
        name="student-document-request",
    ),
    path("api/auth/login", api.auth_login, name="api-auth-login"),
    path("api/auth/logout", api.auth_logout, name="api-auth-logout"),
    path("api/documents/uploads", api.uploads, name="api-documents-uploads"),
    path(
        "api/documents/uploads/<uuid:document_id>",
        api.upload_status,
        name="api-documents-upload-status",
    ),
    path("api/documents/transcript", api.transcript, name="api-documents-transcript"),
    path(
        "api/documents/facts/candidates",
        api.fact_candidates,
        name="api-documents-fact-candidates",
    ),
    path("api/documents/facts/confirm", api.confirm, name="api-documents-fact-confirm"),
    path("api/documents/generate", api.generate, name="api-documents-generate"),
    path("api/documents/drafts", api.drafts, name="api-documents-drafts"),
    path("api/documents/drafts/<uuid:draft_id>", api.draft_detail, name="api-documents-draft"),
    path(
        "api/documents/drafts/<uuid:draft_id>/approve",
        api.approve,
        name="api-documents-draft-approve",
    ),
]

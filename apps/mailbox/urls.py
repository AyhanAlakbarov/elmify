from django.urls import path

from . import views

urlpatterns = [
    # Exact paths, mirrored by push.NOTIFICATION_PATH and push.LIFECYCLE_PATH:
    # they are what each Graph subscription was created with.
    path("mailbox/push/graph/", views.graph_notification, name="mailbox-push-graph"),
    path(
        "mailbox/push/graph/lifecycle/",
        views.graph_lifecycle,
        name="mailbox-push-graph-lifecycle",
    ),
    path("student/settings/mailbox/", views.mailbox_settings, name="student-settings-mailbox"),
    path("mailbox/connect/<str:provider>/", views.connect, name="mailbox-connect"),
    path("mailbox/callback/<str:provider>/", views.callback, name="mailbox-callback"),
    path("mailbox/<uuid:connection_id>/revoke/", views.revoke, name="mailbox-revoke"),
    path("mailbox/<uuid:connection_id>/tier/", views.tier, name="mailbox-tier"),
    path(
        "mailbox/senders/<uuid:sender_id>/confirm/",
        views.confirm_sender,
        name="mailbox-confirm-sender",
    ),
]

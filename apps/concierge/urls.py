from django.urls import path

from .plan import plan_page
from .views import (
    acknowledge_notification_view,
    admin_support_grant,
    counselor_dashboard,
    mark_roadmap_item_done,
    messages_page,
    owner_assign_counselor,
    owner_dashboard,
    send_student_message,
    settings_page,
    student_applications,
    student_dashboard,
    student_option,
)

urlpatterns = [
    path("counselor/", counselor_dashboard, name="concierge-counselor-dashboard"),
    path(
        "counselor/roadmap/<uuid:item_id>/done/",
        mark_roadmap_item_done,
        name="concierge-mark-roadmap-item-done",
    ),
    path("owner/", owner_dashboard, name="concierge-owner-dashboard"),
    path(
        "owner/students/<uuid:student_id>/counselor/",
        owner_assign_counselor,
        name="concierge-owner-assign-counselor",
    ),
    path("student/", student_dashboard, name="concierge-student-dashboard"),
    path("student/applications/", student_applications, name="student-applications"),
    path(
        "student/applications/<uuid:application_id>/", student_option, name="student-option"
    ),
    path(
        "student/notifications/<uuid:notification_id>/acknowledge/",
        acknowledge_notification_view,
        name="concierge-acknowledge-notification",
    ),
    path("student/settings/", settings_page, name="student-settings"),
    path("student/settings/plan/", plan_page, name="student-settings-plan"),
    path("student/messages/", messages_page, name="student-messages"),
    path("student/messages/send/", send_student_message, name="concierge-send-student-message"),
    path("admin/support-grant/", admin_support_grant, name="concierge-admin-support-grant"),
]

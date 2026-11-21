from django.urls import path

from . import views

urlpatterns = [
    path("staff/", views.overview, name="staff-overview"),
    path("staff/students/", views.students, name="staff-students"),
    path("staff/students/<uuid:student_id>/", views.student_detail, name="staff-student"),
    path("staff/inbox/", views.inbox, name="staff-inbox"),
    path("staff/inbox/<uuid:student_id>/", views.thread, name="staff-thread"),
    path("staff/inbox/<uuid:student_id>/reply/", views.reply, name="staff-reply"),
]

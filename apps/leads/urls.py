from django.urls import path

from . import views

urlpatterns = [
    path("demo/", views.book_demo, name="leads-book-demo"),
    path(
        "demo/student/",
        views.book_demo,
        {"audience": "student"},
        name="leads-book-student-demo",
    ),
    path(
        "demo/agency/",
        views.book_demo,
        {"audience": "agency"},
        name="leads-book-agency-demo",
    ),
    path("demo/thanks/", views.demo_thanks, name="leads-demo-thanks"),
    path(
        "owner/demo-requests/<uuid:request_id>/contacted/",
        views.mark_contacted,
        name="leads-mark-contacted",
    ),
]

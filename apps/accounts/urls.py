from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import RateLimitedLoginView, profile

urlpatterns = [
    path("accounts/login/", RateLimitedLoginView.as_view(), name="accounts-login"),
    # POST only; the extension stays paired (owner, 2026-10-04).
    path("accounts/logout/", LogoutView.as_view(), name="accounts-logout"),
    path("student/profile/", profile, name="student-profile"),
]

from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import RateLimitedLoginView, budget_settings, password_change, profile

urlpatterns = [
    path("accounts/login/", RateLimitedLoginView.as_view(), name="accounts-login"),
    # POST only; the extension stays paired (owner, 2026-10-04).
    path("accounts/logout/", LogoutView.as_view(), name="accounts-logout"),
    path("accounts/password_change/", password_change, name="accounts-password-change"),
    path("student/profile/", profile, name="student-profile"),
    path("student/settings/budget/", budget_settings, name="student-settings-budget"),
]

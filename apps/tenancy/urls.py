from django.urls import path

from .views import mfa_setup

urlpatterns = [
    path("mfa/setup/", mfa_setup, name="tenancy-mfa-setup"),
]

from django.urls import path

from apps.privacy import views

urlpatterns = [
    path("signup/", views.signup, name="privacy-signup"),
    path("privacy/accept/", views.accept, name="privacy-accept"),
    path("privacy/stopped/", views.stopped, name="privacy-stopped"),
    path("legal/<str:kind>/", views.legal_document, name="privacy-legal"),
]

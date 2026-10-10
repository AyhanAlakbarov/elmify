from django.urls import path

from . import views

urlpatterns = [
    path("webhooks/firecrawl/", views.firecrawl_webhook, name="firecrawl-webhook"),
    path("platform/resolution/", views.resolution_queue, name="resolution-queue"),
    path(
        "platform/resolution/<uuid:item_id>/", views.resolution_item, name="resolution-item"
    ),
    path(
        "platform/resolution/<uuid:item_id>/decide/",
        views.resolution_decide,
        name="resolution-decide",
    ),
    path(
        "platform/resolution/<uuid:item_id>/park/",
        views.resolution_park,
        name="resolution-park",
    ),
    path("platform/gold/", views.gold_queue, name="gold-queue"),
    path("platform/gold/<uuid:item_id>/", views.gold_label, name="gold-label"),
]

from django.urls import path

from . import ext_api, views

urlpatterns = [
    path(
        "applications/<uuid:application_id>/kit",
        views.application_kit,
        name="portals-application-kit",
    ),
    path("api/extension/pairing-code", views.pairing_code, name="portals-extension-pairing-code"),
    path("ext/pair", ext_api.pair, name="portals-ext-pair"),
    path(
        "ext/applications/<uuid:application_id>/packet",
        ext_api.packet,
        name="portals-ext-packet",
    ),
    path(
        "ext/portal-forms/<uuid:portal_form_id>/snapshot",
        ext_api.snapshot,
        name="portals-ext-snapshot",
    ),
    path(
        "ext/applications/<uuid:application_id>/events",
        ext_api.events,
        name="portals-ext-events",
    ),
    path("ext/actions", ext_api.actions, name="portals-ext-actions"),
    path("ext/documents/<uuid:document_id>", ext_api.document, name="portals-ext-document"),
    path(
        "ext/actions/<uuid:action_id>/result",
        ext_api.action_result,
        name="portals-ext-action-result",
    ),
    path(
        "ext/applications/<uuid:application_id>/status",
        ext_api.application_status,
        name="portals-ext-status",
    ),
    path("ext/mailbox/check", ext_api.mailbox_check, name="portals-ext-mailbox-check"),
    path(
        "ext/applications/<uuid:application_id>/address",
        ext_api.address_report,
        name="portals-ext-address",
    ),
    path(
        "ext/applications/<uuid:application_id>/registration",
        ext_api.registration,
        name="portals-ext-registration",
    ),
    path(
        "student/settings/extension/",
        views.extension_settings,
        name="student-settings-extension",
    ),
    path(
        "student/settings/extension/<uuid:pairing_id>/disconnect/",
        views.extension_disconnect,
        name="student-settings-extension-disconnect",
    ),
    path(
        "student/applications/add/<uuid:candidate_id>/",
        views.application_add,
        name="student-application-add",
    ),
    path(
        "student/applications/<uuid:application_id>/start/",
        views.application_start,
        name="student-application-start",
    ),
    path(
        "student/applications/<uuid:application_id>/outcome/",
        views.application_outcome,
        name="student-application-outcome",
    ),
    path(
        "student/applications/<uuid:application_id>/remove/",
        views.application_remove,
        name="student-application-remove",
    ),
    path(
        "student/offers/<uuid:signal_id>/accept/",
        views.offer_accept,
        name="student-offer-accept",
    ),
    path(
        "student/offers/<uuid:signal_id>/ignore/",
        views.offer_ignore,
        name="student-offer-ignore",
    ),
]

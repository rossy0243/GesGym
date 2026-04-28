from django.urls import path

from .views import (
    create_member,
    delete_member,
    edit_member,
    member_app_manifest,
    member_app_service_worker,
    member_detail,
    member_portal,
    member_notification_read,
    member_portal_qr,
    member_subscription_request,
    member_qr,
    member_list,
    reactivate_member,
    suspend_member,
)
from .pre_registration_views import (
    cancel_pre_registration,
    confirm_pre_registration,
    pre_registration_list,
    public_pre_registration,
)

app_name = "members"
urlpatterns = [
    path("", member_list, name="member_list"),
    path("me/", member_portal, name="member_portal"),
    path("me/messages/<int:notification_id>/read/", member_notification_read, name="member_notification_read"),
    path("me/qr/", member_portal_qr, name="member_portal_qr"),
    path("me/subscription-request/", member_subscription_request, name="member_subscription_request"),
    path("app/manifest.json", member_app_manifest, name="member_app_manifest"),
    path("app/service-worker.js", member_app_service_worker, name="member_app_service_worker"),
    path("preinscriptions/", pre_registration_list, name="pre_registration_list"),
    path("preinscriptions/<int:pre_registration_id>/confirm/", confirm_pre_registration, name="confirm_pre_registration"),
    path("preinscriptions/<int:pre_registration_id>/cancel/", cancel_pre_registration, name="cancel_pre_registration"),
    path("preinscription/<uuid:token>/", public_pre_registration, name="public_pre_registration"),
    path("create/", create_member, name="create_member"),
    path('edit/<int:member_id>/', edit_member, name='edit_member'),
    path("<int:member_id>/delete/", delete_member, name="delete_member"),
    path('suspend/<int:member_id>/', suspend_member, name='suspend_member'),
    path("<int:member_id>/", member_detail, name="member_detail"),
    path("qr/<uuid:uuid>/", member_qr, name="member_qr"),
    path('reactivate/<int:member_id>/', reactivate_member, name='reactivate_member'),
]

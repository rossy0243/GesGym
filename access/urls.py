#access/urls.py
from django.urls import path
from . import device_views, enrollment_views, views
app_name = 'access'
urlpatterns = [
        path("access/<uuid:qr_code>/", views.member_access, name="member_access"),
        path("access-dashboard/", views.acces_dashboard, name="acces_dashboard"),
        path("access/realtime/", views.realtime_access),
        path("access/manual/entry/<int:member_id>/", views.manual_access_entry, name="manual_access_entry"),

        # Lecteurs physiques
        path("devices/", device_views.device_list, name="device_list"),
        path("devices/discover/", device_views.device_discover, name="device_discover"),
        path("devices/create/", device_views.device_create, name="device_create"),
        path("devices/<int:device_id>/test/", device_views.device_test, name="device_test"),
        path("devices/<int:device_id>/open/", device_views.device_open_door, name="device_open_door"),
        path("devices/<int:device_id>/update/", device_views.device_update, name="device_update"),
        path("devices/<int:device_id>/delete/", device_views.device_delete, name="device_delete"),
        path("devices/<int:device_id>/annoncer/", device_views.device_announce, name="device_announce"),
        path("devices/webhook/<uuid:token>/", device_views.device_webhook, name="device_webhook"),

        # Enrolement du visage, capture faite par le lecteur lui-meme.
        path("membres/<int:member_id>/visage/", enrollment_views.face_enrollment, name="face_enrollment"),
        path("membres/<int:member_id>/visage/capturer/", enrollment_views.face_capture, name="face_capture"),
        path("membres/<int:member_id>/visage/valider/", enrollment_views.face_confirm, name="face_confirm"),
        path("membres/<int:member_id>/visage/retirer/", enrollment_views.face_remove, name="face_remove"),

        # Messages affiches sur l'ecran du lecteur.
        path("devices/<int:device_id>/messages/", enrollment_views.device_messages, name="device_messages"),
]

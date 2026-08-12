#access/urls.py
from django.urls import path
from . import device_views, views
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
        path("devices/<int:device_id>/delete/", device_views.device_delete, name="device_delete"),
        path("devices/webhook/<uuid:token>/", device_views.device_webhook, name="device_webhook"),
]

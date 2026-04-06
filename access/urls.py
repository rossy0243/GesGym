#access/urls.py
from django.urls import path
from . import views
app_name = 'access'
urlpatterns = [
        path("access/<uuid:qr_code>/", views.member_access, name="member_access"),
        path("access-dashboard/", views.acces_dashboard, name="acces_dashboard"),
        path("access/realtime/", views.realtime_access),
        path("access/manual/entry/<int:member_id>/", views.manual_access_entry, name="manual_access_entry")
]
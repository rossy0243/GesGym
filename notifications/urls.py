from django.urls import path

from .views import notification_dashboard

app_name = "notifications"

urlpatterns = [
    path("", notification_dashboard, name="dashboard"),
]

from django.urls import path

from .views import cancel_message_batch, delete_message_batch, notification_dashboard

app_name = "notifications"

urlpatterns = [
    path("", notification_dashboard, name="dashboard"),
    path("envois/<uuid:batch_id>/annuler/", cancel_message_batch, name="cancel_message_batch"),
    path("envois/<uuid:batch_id>/supprimer/", delete_message_batch, name="delete_message_batch"),
]

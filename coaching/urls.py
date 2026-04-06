from django.urls import path
from . import views

app_name = "coaching"

urlpatterns = [
    path("", views.coach_list, name="coach_list"),
    path("create/", views.create_coach, name="create_coach"),
]
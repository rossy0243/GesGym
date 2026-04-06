from django.urls import path
from .views import dashboard, reports_dashboard

app_name = "core"

urlpatterns = [
    path('', dashboard, name='dashboard'),
    path('rapport/', reports_dashboard, name='rapport'),
]
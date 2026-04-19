from django.urls import path
from .views import (
    accounting_report_export,
    dashboard_redirect,
    gym_dashboard,
    reports_dashboard,
    select_gym,
    settings_dashboard,
    switch_gym,
)

app_name = "core"

urlpatterns = [
    path('dashboard/', dashboard_redirect, name='dashboard_redirect'),
    path('select-gym/', select_gym, name='select_gym'),
    path('gym/<int:gym_id>/dashboard/', gym_dashboard, name='gym_dashboard'),
    path('rapport/', reports_dashboard, name='rapport'),
    path('rapport/export/', accounting_report_export, name='rapport_export'),
    path('parametres/', settings_dashboard, name='settings'),
    path('switch-gym/<int:gym_id>/', switch_gym, name='switch_gym'),
]

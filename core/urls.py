from django.urls import path
from .views import  dashboard_redirect, reports_dashboard, gym_dashboard, organization_dashboard, select_gym

app_name = "core"

urlpatterns = [
    path('', dashboard_redirect, name='dashboard_redirect'),
    path('select-gym/', select_gym, name='select_gym'),
    # Dashboard par gym (existant)
    path('gym/<int:gym_id>/dashboard/', gym_dashboard, name='gym_dashboard'),
    
    # Dashboard organisation (NOUVEAU - pour Owner)
    path('organization/<int:org_id>/dashboard/', organization_dashboard, name='organization_dashboard'),
    
    path('rapport/', reports_dashboard, name='rapport'),
]
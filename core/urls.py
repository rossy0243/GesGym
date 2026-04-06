from django.urls import path
from .views import reports_dashboard, gym_dashboard, organization_dashboard

app_name = "core"

urlpatterns = [
    # Dashboard par gym (existant)
    path('gym/<int:gym_id>/dashboard/', gym_dashboard, name='gym_dashboard'),
    
    # Dashboard organisation (NOUVEAU - pour Owner)
    path('organization/<int:org_id>/dashboard/', organization_dashboard, name='organization_dashboard'),
    
    path('rapport/', reports_dashboard, name='rapport'),
]
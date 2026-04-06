from django.urls import path
from . import views

app_name = 'machines'

urlpatterns = [
    # Plus besoin de gym_id dans l'URL ! Le middleware le donne
    path('machines/', views.machine_list, name='list'),
    path('machines/create/', views.machine_create, name='create'),
    path('machines/<int:machine_id>/', views.machine_detail, name='detail'),
    path('machines/<int:machine_id>/update/', views.machine_update, name='update'),
    path('machines/<int:machine_id>/delete/', views.machine_delete, name='delete'),
    path('machines/<int:machine_id>/maintenances/add/', views.maintenance_log_create, name='add_maintenance'),
    
    # Maintenances
    path('maintenances/', views.maintenance_list, name='maintenance_list'),
    path('maintenances/dashboard/', views.maintenance_dashboard, name='maintenance_dashboard'),
]
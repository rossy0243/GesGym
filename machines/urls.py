from django.urls import path
from . import views

app_name = 'machines'

urlpatterns = [
    # Machines
    path('gym/<int:gym_id>/machines/', views.machine_list, name='list'),
    path('gym/<int:gym_id>/machines/create/', views.machine_create, name='create'),
    path('gym/<int:gym_id>/machines/<int:machine_id>/', views.machine_detail, name='detail'),
    path('gym/<int:gym_id>/machines/<int:machine_id>/update/', views.machine_update, name='update'),
    path('gym/<int:gym_id>/machines/<int:machine_id>/delete/', views.machine_delete, name='delete'),
    
    # Maintenances
    path('gym/<int:gym_id>/maintenances/', views.maintenance_list, name='maintenance_list'),
    path('gym/<int:gym_id>/maintenances/dashboard/', views.maintenance_dashboard, name='maintenance_dashboard'),
    path('gym/<int:gym_id>/machines/<int:machine_id>/maintenances/add/', 
         views.maintenance_log_create, name='add_maintenance'),
    path('gym/<int:gym_id>/maintenances/<int:maintenance_id>/delete/', 
         views.maintenance_delete, name='maintenance_delete'),
]
from django.urls import path
from . import views

app_name = 'rh'

urlpatterns = [
    # Employés
    path('gym/<int:gym_id>/employees/', views.employee_list, name='list'),
    path('gym/<int:gym_id>/employees/create/', views.employee_create, name='create'),
    path('gym/<int:gym_id>/employees/<int:employee_id>/', views.employee_detail, name='detail'),
    path('gym/<int:gym_id>/employees/<int:employee_id>/update/', views.employee_update, name='update'),
    path('gym/<int:gym_id>/employees/<int:employee_id>/delete/', views.employee_delete, name='delete'),
    
    # Présences
    path('gym/<int:gym_id>/attendances/', views.attendance_list, name='attendance_list'),
    path('gym/<int:gym_id>/attendances/create/', views.attendance_create, name='attendance_create'),
    path('gym/<int:gym_id>/attendances/bulk/', views.attendance_bulk, name='attendance_bulk'),
    
    # Paie
    path('gym/<int:gym_id>/payroll/', views.payroll_dashboard, name='payroll_dashboard'),
    path('gym/<int:gym_id>/payroll/<int:employee_id>/<int:year>/<int:month>/pay/', 
         views.process_payment, name='process_payment'),
]
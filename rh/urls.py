from django.urls import path
from . import views

app_name = 'rh'

urlpatterns = [
    path('employees/', views.employee_list, name='list'),
    path('employees/create/', views.employee_create, name='create'),
    path('employees/<int:employee_id>/', views.employee_detail, name='detail'),
    path('employees/<int:employee_id>/update/', views.employee_update, name='update'),
    path('employees/<int:employee_id>/delete/', views.employee_delete, name='delete'),
    path('attendances/', views.attendance_list, name='attendance_list'),
    path('attendances/create/', views.attendance_create, name='attendance_create'),
    path('attendances/bulk/', views.attendance_bulk, name='attendance_bulk'),
    path('payroll/', views.payroll_dashboard, name='payroll_dashboard'),
    path('payroll/<int:employee_id>/<int:year>/<int:month>/pay/',
         views.process_payment, name='process_payment'),
]

# core/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('superadmin/', views.superadmin_dashboard, name='superadmin_dashboard'),
    path('admin/<int:gym_id>/', views.admin_dashboard, name='admin_dashboard'),
    path('manager/<int:gym_id>/', views.manager_dashboard, name='manager_dashboard'),
    path('cashier/<int:gym_id>/', views.cashier_dashboard, name='cashier_dashboard'),
    path('reception/<int:gym_id>/', views.reception_dashboard, name='reception_dashboard'),
    path('member/', views.member_dashboard, name='member_dashboard'),
]
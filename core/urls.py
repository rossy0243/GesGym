# core/urls.py
from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('superadmin/', views.superadmin_dashboard, name='superadmin_dashboard'),
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('manager/dashboard/', views.manager_dashboard, name='manager_dashboard'),
    path('cashier/dashboard/', views.cashier_dashboard, name='cashier_dashboard'),
    path('reception/dashboard/', views.reception_dashboard, name='reception_dashboard'),
    path('member/', views.member_dashboard, name='member_dashboard'),
    path('create-member/', views.create_member, name='create_member'),
]
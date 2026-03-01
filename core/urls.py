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
    path('members/', views.member_list, name='member_list'),
    path('members/create/', views.create_member, name='create_member'),
    path('members/edit/<int:member_id>/', views.edit_member, name='edit_member'),
    path('members/delete/<int:member_id>/', views.delete_member, name='delete_member'),
    path('members/toggle/<int:member_id>/', views.toggle_member_status, name='toggle_member_status'),
    
]
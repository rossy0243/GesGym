# core/urls.py
from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('superadmin/', views.superadmin_dashboard, name='superadmin_dashboard'),
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('cashier/dashboard/', views.cashier_dashboard, name='cashier_dashboard'),
    path('reception/dashboard/', views.reception_dashboard, name='reception_dashboard'),
    path('member/', views.member_dashboard, name='member_dashboard'),
    path('members/', views.member_list, name='member_list'),
    path('members/create/', views.create_member, name='create_member'),
    path('members/edit/<int:member_id>/', views.edit_member, name='edit_member'),
    path('member/<int:member_id>/', views.member_detail, name='member_detail'),
    path('members/delete/<int:member_id>/', views.delete_member, name='delete_member'),
    path('members/toggle/<int:member_id>/', views.toggle_member_status, name='toggle_member_status'),
    
    path('subscription-plans/', views.plan_list, name='subscription_plan_list'),
    path('subscription-plans/create/', views.create_plan, name='create_subscription_plan'),
    path('subscription-plans/edit/<int:plan_id>/', views.edit_plan, name='edit_subscription_plan'),
    path('subscription-plans/delete/<int:plan_id>/', views.delete_plan, name='delete_subscription_plan'),
    
    path('open-cash-register/', views.open_register, name='open_cash_register'),
    path('close-cash-register/<int:register_id>/', views.close_register, name='close_register'),
    
    path("search-members/", views.search_members, name="search_members"),
    
    path(
    "register-history/",
    views.register_history,
    name="register_history"
),

    path(
        "register/<int:register_id>/",
        views.register_detail,
        name="register_detail"
    ),
    path("access/<uuid:qr_code>/", views.member_access, name="member_access"),
    path("access-dashboard/", views.acces_dashboard, name="acces_dashboard"),
    path("access/realtime/", views.realtime_access),
    path(
    "access/manual/entry/<int:member_id>/",
    views.manual_access_entry, name="manual_access_entry"
)
    
]
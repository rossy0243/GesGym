#pos/urs.py
from django.urls import path
from . import views 
app_name = "pos"
urlpatterns = [
    path("", views.cashier_dashboard, name="cashier_dashboard"),   
    path("search-members/", views.search_members, name="search_members"),
    path("open-register/", views.open_register, name="open_register"),
    path("close-register/<int:register_id>/", views.close_register, name="close_register"),
    path("register-history/", views.register_history, name="register_history"),
    path("decaissements/", views.expense_register, name="expense_register"),
    path("register-detail/<int:register_id>/", views.register_detail, name="register_detail"),
]
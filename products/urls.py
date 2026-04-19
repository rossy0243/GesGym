from django.urls import path
from . import views

app_name = 'products'

urlpatterns = [
    path('products/', views.product_list, name='list'),
    path('products/create/', views.product_create, name='create'),
    path('products/<int:product_id>/', views.product_detail, name='detail'),
    path('products/<int:product_id>/update/', views.product_update, name='update'),
    path('products/<int:product_id>/delete/', views.product_delete, name='delete'),
    path('products/<int:product_id>/movement/add/', views.stock_movement_create, name='add_movement'),
    path('movements/', views.stock_movement_list, name='movement_list'),
    path('stock/dashboard/', views.stock_dashboard, name='stock_dashboard'),
]

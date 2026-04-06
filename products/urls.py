from django.urls import path
from . import views

app_name = 'products'

urlpatterns = [
    # Produits
    path('gym/<int:gym_id>/products/', views.product_list, name='list'),
    path('gym/<int:gym_id>/products/create/', views.product_create, name='create'),
    path('gym/<int:gym_id>/products/<int:product_id>/', views.product_detail, name='detail'),
    path('gym/<int:gym_id>/products/<int:product_id>/update/', views.product_update, name='update'),
    path('gym/<int:gym_id>/products/<int:product_id>/delete/', views.product_delete, name='delete'),
    
    # Mouvements de stock
    path('gym/<int:gym_id>/products/<int:product_id>/movement/add/', views.stock_movement_create, name='add_movement'),
    path('gym/<int:gym_id>/movements/', views.stock_movement_list, name='movement_list'),
    
    # Dashboard
    path('gym/<int:gym_id>/stock/dashboard/', views.stock_dashboard, name='stock_dashboard'),
]
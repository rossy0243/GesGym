from django.urls import path
from . import views

app_name = 'coaching'

urlpatterns = [
    path('coaches/', views.coach_list, name='list'),
    path('coaches/create/', views.coach_create, name='create'),
    path('coaches/<int:coach_id>/', views.coach_detail, name='detail'),
    path('coaches/<int:coach_id>/update/', views.coach_update, name='update'),
    path('coaches/<int:coach_id>/delete/', views.coach_delete, name='delete'),
    path('coaches/<int:coach_id>/assign/', views.assign_member, name='assign_member'),
    path('coaches/<int:coach_id>/remove/<int:member_id>/', views.remove_member, name='remove_member'),
]

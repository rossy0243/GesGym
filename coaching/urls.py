from django.urls import path
from . import views

app_name = 'coaching'

urlpatterns = [
    path('gym/<int:gym_id>/coaches/', views.coach_list, name='list'),
    path('gym/<int:gym_id>/coaches/create/', views.coach_create, name='create'),
    path('gym/<int:gym_id>/coaches/<int:coach_id>/', views.coach_detail, name='detail'),
    path('gym/<int:gym_id>/coaches/<int:coach_id>/update/', views.coach_update, name='update'),
    path('gym/<int:gym_id>/coaches/<int:coach_id>/delete/', views.coach_delete, name='delete'),
    path('gym/<int:gym_id>/coaches/<int:coach_id>/assign/', views.assign_member, name='assign_member'),
    path('gym/<int:gym_id>/coaches/<int:coach_id>/remove/<int:member_id>/', views.remove_member, name='remove_member'),
]
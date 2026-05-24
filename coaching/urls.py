from django.urls import path
from . import views

app_name = 'coaching'

urlpatterns = [
    path('portal/', views.coach_portal, name='coach_portal'),
    path('portal/members/<int:member_id>/', views.coach_member_detail, name='coach_member_detail'),
    path('portal/members/<int:member_id>/weight/', views.coach_member_weight_measurement_create, name='coach_member_weight_measurement_create'),
    path('coaches/', views.coach_list, name='list'),
    path('coaches/create/', views.coach_create, name='create'),
    path('coaches/<int:coach_id>/', views.coach_detail, name='detail'),
    path('coaches/<int:coach_id>/update/', views.coach_update, name='update'),
    path('coaches/<int:coach_id>/delete/', views.coach_delete, name='delete'),
    path('coaches/<int:coach_id>/assign/', views.assign_member, name='assign_member'),
    path('coaches/<int:coach_id>/remove/<int:member_id>/', views.remove_member, name='remove_member'),
    path('programs/', views.group_program_list, name='group_program_list'),
    path('programs/create/', views.group_program_create, name='group_program_create'),
    path('programs/<int:program_id>/', views.group_program_detail, name='group_program_detail'),
    path('programs/<int:program_id>/update/', views.group_program_update, name='group_program_update'),
    path('programs/<int:program_id>/delete/', views.group_program_delete, name='group_program_delete'),
]

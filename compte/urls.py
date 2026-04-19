# compte/urls.py
from django.urls import path
from .views import CustomLoginView, activate_user, create_user_by_owner, deactivate_user, get_gyms_by_organization, logout_view, profile, reset_password, user_list

app_name = 'compte'

urlpatterns = [
    path('login/', CustomLoginView.as_view(), name='login'),
    path("profile/", profile, name="profile"),
    path("logout/", logout_view, name="logout"),
    path('admin/get-gyms/', get_gyms_by_organization, name='get_gyms_by_organization'),
    # Gestion des utilisateurs (Owner)
    path('users/', user_list, name='user_list'),
    path('users/create/', create_user_by_owner, name='create_user'),
    path('users/<int:user_id>/reset-password/', reset_password, name='reset_password'),
    path('users/<int:user_id>/deactivate/', deactivate_user, name='deactivate_user'),
    path('users/<int:user_id>/activate/', activate_user, name='activate_user'),
]

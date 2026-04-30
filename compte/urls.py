# compte/urls.py
from django.contrib.auth import views as auth_views
from django.urls import path
from django.urls import reverse_lazy

from .forms import StyledPasswordResetForm, StyledSetPasswordForm
from .views import CustomLoginView, activate_user, create_user_by_owner, deactivate_user, get_gyms_by_organization, logout_view, profile, reset_password, user_list, welcome

app_name = 'compte'

urlpatterns = [
    path('login/', CustomLoginView.as_view(), name='login'),
    path('welcome/', welcome, name='welcome'),
    path("profile/", profile, name="profile"),
    path("logout/", logout_view, name="logout"),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="compte/password_reset_form.html",
            email_template_name="compte/emails/password_reset_email.txt",
            subject_template_name="compte/emails/password_reset_subject.txt",
            form_class=StyledPasswordResetForm,
            success_url=reverse_lazy("compte:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="compte/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="compte/password_reset_confirm.html",
            form_class=StyledSetPasswordForm,
            success_url=reverse_lazy("compte:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="compte/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
    path('admin/get-gyms/', get_gyms_by_organization, name='get_gyms_by_organization'),
    # Gestion des utilisateurs (Owner)
    path('users/', user_list, name='user_list'),
    path('users/create/', create_user_by_owner, name='create_user'),
    path('users/<int:user_id>/reset-password/', reset_password, name='reset_password'),
    path('users/<int:user_id>/deactivate/', deactivate_user, name='deactivate_user'),
    path('users/<int:user_id>/activate/', activate_user, name='activate_user'),
]

from django.urls import path

from .views import create_member, delete_member, edit_member, member_detail, member_qr, member_list, reactivate_member, suspend_member
from .pre_registration_views import (
    cancel_pre_registration,
    confirm_pre_registration,
    pre_registration_list,
    public_pre_registration,
)

app_name = "members"
urlpatterns = [
    path("", member_list, name="member_list"),
    path("preinscriptions/", pre_registration_list, name="pre_registration_list"),
    path("preinscriptions/<int:pre_registration_id>/confirm/", confirm_pre_registration, name="confirm_pre_registration"),
    path("preinscriptions/<int:pre_registration_id>/cancel/", cancel_pre_registration, name="cancel_pre_registration"),
    path("preinscription/<uuid:token>/", public_pre_registration, name="public_pre_registration"),
    path("create/", create_member, name="create_member"),
    path('edit/<int:member_id>/', edit_member, name='edit_member'),
    path("<int:member_id>/delete/", delete_member, name="delete_member"),
    path('suspend/<int:member_id>/', suspend_member, name='suspend_member'),
    path("<int:member_id>/", member_detail, name="member_detail"),
    path("qr/<uuid:uuid>/", member_qr, name="member_qr"),
    path('reactivate/<int:member_id>/', reactivate_member, name='reactivate_member'),
]

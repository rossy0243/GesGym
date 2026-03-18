# compte/admin.py

from django.contrib import admin
from .models import User
from .models_roles import UserGymRole


@admin.register(User)
class UserAdmin(admin.ModelAdmin):

    list_display = ("username", "email", "is_saas_admin")


@admin.register(UserGymRole)
class UserGymRoleAdmin(admin.ModelAdmin):

    list_display = ("user", "gym", "role", "is_active")

    list_filter = ("role", "gym")
from django.contrib import admin
from .models import User, UserGymRole
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin



@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Utilise le vrai UserAdmin Django → mot de passe hashé automatiquement
    """

    list_display = ("username", "is_saas_admin", "is_staff", "is_active")

    fieldsets = BaseUserAdmin.fieldsets + (
        ("SaaS", {"fields": ("is_saas_admin",)}),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("SaaS", {"fields": ("is_saas_admin",)}),
    )

@admin.register(UserGymRole)
class UserGymRoleAdmin(admin.ModelAdmin):

    list_display = ("user", "gym", "organization", "role", "is_active")

    list_filter = ("gym", "role")

    def organization(self, obj):
        return obj.gym.organization

    organization.short_description = "Organization"
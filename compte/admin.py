# compte/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from compte.models import User

# Register your models here.
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ("username", "email", "role", "gym", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active", "gym")
    fieldsets = UserAdmin.fieldsets + (
        ("Informations supplémentaires", {
            "fields": ("role", "gym"),
        }),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Informations supplémentaires", {
            "fields": ("role", "gym"),
        }),
    )
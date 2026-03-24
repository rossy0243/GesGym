from django.contrib import admin
from .models import Organization, Gym


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")

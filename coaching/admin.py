from django.contrib import admin

from .models import Coach, CoachSpecialty


@admin.register(CoachSpecialty)
class CoachSpecialtyAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "gym", "is_active", "created_at")
    list_filter = ("is_active", "gym__organization", "gym")
    search_fields = ("name", "gym__name", "gym__organization__name")
    autocomplete_fields = ("gym",)
    list_editable = ("is_active",)
    ordering = ("gym__organization__name", "gym__name", "name")

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"


@admin.register(Coach)
class CoachAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "gym", "specialty", "phone", "is_active", "members_count", "created_at")
    list_filter = ("is_active", "specialty", "gym__organization", "gym")
    search_fields = ("name", "phone", "specialty", "gym__name", "gym__organization__name")
    autocomplete_fields = ("gym", "members")
    list_editable = ("is_active",)
    ordering = ("gym__organization__name", "gym__name", "name")

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"

    def members_count(self, obj):
        return obj.members.count()

    members_count.short_description = "Membres suivis"

from django.contrib import admin

from .models import Member, MemberPreRegistration, MemberPreRegistrationLink


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("full_name", "organization", "gym", "phone", "email", "computed_status", "is_active", "created_at")
    list_filter = ("status", "is_active", "gym__organization", "gym", "created_at")
    search_fields = ("first_name", "last_name", "phone", "email", "gym__name", "gym__organization__name")
    autocomplete_fields = ("gym", "user")
    date_hierarchy = "created_at"
    ordering = ("gym__organization__name", "gym__name", "-created_at")

    def full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"

    full_name.short_description = "Membre"

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"


@admin.register(MemberPreRegistrationLink)
class MemberPreRegistrationLinkAdmin(admin.ModelAdmin):
    list_display = ("organization", "gym", "token", "is_active", "created_at", "updated_at")
    list_filter = ("is_active", "gym__organization", "gym", "created_at")
    search_fields = ("gym__name", "gym__organization__name", "token")
    autocomplete_fields = ("gym",)
    readonly_fields = ("token", "created_at", "updated_at")

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"


@admin.register(MemberPreRegistration)
class MemberPreRegistrationAdmin(admin.ModelAdmin):
    list_display = ("full_name", "organization", "gym", "phone", "email", "status", "expires_at", "created_at")
    list_filter = ("status", "gym__organization", "gym", "created_at", "expires_at")
    search_fields = ("first_name", "last_name", "phone", "email", "gym__name", "gym__organization__name")
    autocomplete_fields = ("gym", "link", "member", "confirmed_by")
    readonly_fields = ("token", "created_at", "confirmed_at")

    def full_name(self, obj):
        return obj.full_name

    full_name.short_description = "Preinscrit"

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"

from django.contrib import admin

from .models import AccessLog


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = (
        "check_in_time",
        "organization",
        "gym",
        "member",
        "access_granted",
        "device_used",
        "scanned_by",
        "denial_reason",
    )
    list_filter = ("access_granted", "gym__organization", "gym", "device_used", "check_in_time")
    search_fields = (
        "member__first_name",
        "member__last_name",
        "member__phone",
        "gym__name",
        "gym__organization__name",
        "denial_reason",
    )
    autocomplete_fields = ("gym", "member", "scanned_by")
    readonly_fields = ("check_in_time",)
    date_hierarchy = "check_in_time"
    ordering = ("-check_in_time",)

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"

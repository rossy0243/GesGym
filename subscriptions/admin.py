from django.contrib import admin

from .models import MemberSubscription, SubscriptionPlan


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "gym", "duration_days", "price", "is_active", "created_at")
    list_filter = ("is_active", "gym__organization", "gym", "duration_days")
    search_fields = ("name", "gym__name", "gym__organization__name")
    autocomplete_fields = ("gym",)
    list_editable = ("is_active",)
    ordering = ("gym__organization__name", "gym__name", "name")

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"


@admin.register(MemberSubscription)
class MemberSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "member",
        "organization",
        "gym",
        "plan",
        "start_date",
        "end_date",
        "is_active",
        "is_paused",
        "auto_renew",
    )
    list_filter = ("is_active", "is_paused", "auto_renew", "gym__organization", "gym", "plan")
    search_fields = (
        "member__first_name",
        "member__last_name",
        "member__phone",
        "gym__name",
        "gym__organization__name",
        "plan__name",
    )
    autocomplete_fields = ("gym", "member", "plan")
    date_hierarchy = "start_date"
    ordering = ("-start_date", "gym__organization__name", "gym__name")

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"

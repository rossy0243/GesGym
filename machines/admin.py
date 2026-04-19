from django.contrib import admin

from .models import Machine, MaintenanceLog


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "gym", "status", "purchase_date", "created_at")
    list_filter = ("status", "gym__organization", "gym", "purchase_date")
    search_fields = ("name", "gym__name", "gym__organization__name")
    autocomplete_fields = ("gym",)
    date_hierarchy = "created_at"
    ordering = ("gym__organization__name", "gym__name", "name")

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"


@admin.register(MaintenanceLog)
class MaintenanceLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "organization", "gym", "machine", "cost", "pos_payment")
    list_filter = ("machine__gym__organization", "machine__gym", "created_at")
    search_fields = ("machine__name", "description", "machine__gym__name", "machine__gym__organization__name")
    autocomplete_fields = ("machine", "pos_payment")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def organization(self, obj):
        return obj.machine.gym.organization.name if obj.machine_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "machine__gym__organization__name"

    def gym(self, obj):
        return obj.machine.gym.name if obj.machine_id else "-"

    gym.short_description = "Gym"
    gym.admin_order_field = "machine__gym__name"

from django.contrib import admin

from .models import Attendance, Employee, PaymentRecord


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "gym", "role", "phone", "daily_salary", "is_active", "created_at")
    list_filter = ("role", "is_active", "gym__organization", "gym")
    search_fields = ("name", "phone", "gym__name", "gym__organization__name")
    autocomplete_fields = ("gym",)
    list_editable = ("is_active",)
    ordering = ("gym__organization__name", "gym__name", "name")

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("date", "organization", "gym", "employee", "status", "created_at")
    list_filter = ("status", "gym__organization", "gym", "date")
    search_fields = ("employee__name", "gym__name", "gym__organization__name")
    autocomplete_fields = ("gym", "employee")
    date_hierarchy = "date"
    ordering = ("-date", "gym__organization__name", "gym__name")

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = (
        "payment_date",
        "organization",
        "gym",
        "employee",
        "year",
        "month",
        "amount",
        "present_days",
        "is_paid",
    )
    list_filter = ("is_paid", "year", "month", "gym__organization", "gym", "payment_date")
    search_fields = ("employee__name", "reference", "gym__name", "gym__organization__name")
    autocomplete_fields = ("gym", "employee", "pos_payment")
    date_hierarchy = "payment_date"
    ordering = ("-year", "-month", "gym__organization__name", "gym__name")

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"

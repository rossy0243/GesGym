from django.contrib import admin

from .models import CashRegister, ExchangeRate, Payment


@admin.register(CashRegister)
class CashRegisterAdmin(admin.ModelAdmin):
    list_display = (
        "session_code",
        "organization",
        "gym",
        "opened_by",
        "opened_at",
        "is_closed",
        "exchange_rate",
        "opening_amount",
        "closing_amount",
        "difference",
    )
    list_filter = ("is_closed", "gym__organization", "gym", "opened_at")
    search_fields = ("session_code", "gym__name", "gym__organization__name", "opened_by__username")
    autocomplete_fields = ("gym", "opened_by", "closed_by")
    readonly_fields = ("session_code", "opened_at")
    date_hierarchy = "opened_at"
    ordering = ("-opened_at",)

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "organization",
        "gym",
        "type",
        "category",
        "member",
        "product",
        "amount",
        "currency",
        "amount_cdf",
        "status",
        "cash_register",
    )
    list_filter = ("status", "type", "category", "currency", "method", "gym__organization", "gym", "created_at")
    search_fields = (
        "description",
        "transaction_id",
        "member__first_name",
        "member__last_name",
        "member__phone",
        "product__name",
        "gym__name",
        "gym__organization__name",
    )
    autocomplete_fields = ("gym", "cash_register", "member", "subscription", "product", "created_by")
    readonly_fields = ("amount_cdf", "amount_usd", "exchange_rate", "created_at")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ("date", "organization", "gym", "rate", "created_at")
    list_filter = ("date", "gym__organization", "gym")
    search_fields = ("gym__name", "gym__organization__name")
    autocomplete_fields = ("gym",)
    date_hierarchy = "date"
    ordering = ("-date", "gym__organization__name", "gym__name")

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"

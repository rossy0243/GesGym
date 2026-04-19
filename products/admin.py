from django.contrib import admin

from .models import Product, StockMovement


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "gym", "price", "quantity", "is_active", "created_at")
    list_filter = ("is_active", "gym__organization", "gym", "created_at")
    search_fields = ("name", "gym__name", "gym__organization__name")
    autocomplete_fields = ("gym",)
    list_editable = ("is_active",)
    ordering = ("gym__organization__name", "gym__name", "name")

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "organization", "gym", "product", "movement_type", "quantity", "reason")
    list_filter = ("movement_type", "gym__organization", "gym", "created_at")
    search_fields = ("product__name", "reason", "gym__name", "gym__organization__name")
    autocomplete_fields = ("gym", "product")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"

from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("member", "gym", "channel", "status", "created_at", "read_at")
    list_filter = ("channel", "status", "gym", "read_at")
    search_fields = ("member__first_name", "member__last_name", "title", "message")
    readonly_fields = ("created_at",)

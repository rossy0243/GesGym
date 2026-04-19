from django.contrib import admin

from .models import Member, MemberPreRegistration, MemberPreRegistrationLink


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "phone", "email", "gym", "status", "created_at")
    list_filter = ("gym", "status", "created_at")
    search_fields = ("first_name", "last_name", "phone", "email")


@admin.register(MemberPreRegistrationLink)
class MemberPreRegistrationLinkAdmin(admin.ModelAdmin):
    list_display = ("gym", "token", "is_active", "created_at", "updated_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("gym__name", "token")
    readonly_fields = ("token", "created_at", "updated_at")


@admin.register(MemberPreRegistration)
class MemberPreRegistrationAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "phone", "gym", "status", "expires_at", "created_at")
    list_filter = ("gym", "status", "created_at", "expires_at")
    search_fields = ("first_name", "last_name", "phone", "email")
    readonly_fields = ("token", "created_at", "confirmed_at")

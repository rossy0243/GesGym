from django.contrib import admin, messages
from django.contrib.auth import get_user_model

from .models import Gym, GymModule, Module, Organization


DEFAULT_MODULE_CODES = [
    "MEMBERS",
    "SUBSCRIPTIONS",
    "POS",
    "ACCESS",
    "PRODUCTS",
    "MACHINES",
    "COACHING",
    "RH",
    "CORE",
    "COMPTE",
    "WEBSITE",
    "NOTIFICATIONS",
]


def ensure_default_gym_modules(gym):
    modules = Module.objects.filter(code__in=DEFAULT_MODULE_CODES)
    for module in modules:
        GymModule.objects.get_or_create(
            gym=gym,
            module=module,
            defaults={"is_active": True},
        )


class OwnerInline(admin.TabularInline):
    model = get_user_model()
    fk_name = "owned_organization"
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ("username", "first_name", "last_name", "email", "is_active")
    readonly_fields = ("username", "first_name", "last_name", "email", "is_active")
    verbose_name = "Owner"
    verbose_name_plural = "Owners de l'organisation"


class GymInline(admin.TabularInline):
    model = Gym
    extra = 1
    fields = ("name", "slug", "subdomain", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    show_change_link = True
    verbose_name = "Gym"
    verbose_name_plural = "Gyms de l'organisation"


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "description", "created_at")
    search_fields = ("code", "name", "description")
    readonly_fields = ("created_at",)
    ordering = ("code",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owners_count", "gyms_count", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "slug", "email", "phone")
    prepopulated_fields = {"slug": ("name",)}
    fields = ("name", "slug", "logo", "address", "phone", "email", "is_active")
    inlines = (OwnerInline, GymInline)
    readonly_fields = ("created_at",)

    def owners_count(self, obj):
        return obj.owners.count()

    owners_count.short_description = "Owners"

    def gyms_count(self, obj):
        return obj.gyms.count()

    gyms_count.short_description = "Gyms"

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        for gym in form.instance.gyms.all():
            ensure_default_gym_modules(gym)


class GymModuleInline(admin.TabularInline):
    model = GymModule
    extra = 0
    fields = ("module", "is_active")
    autocomplete_fields = ("module",)
    verbose_name = "Module actif"
    verbose_name_plural = "Modules actifs pour ce gym"


@admin.register(Gym)
class GymAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "slug", "subdomain", "active_modules_count", "is_active")
    list_filter = ("organization", "is_active", "modules__module")
    search_fields = ("name", "slug", "subdomain", "organization__name")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("organization",)
    inlines = (GymModuleInline,)
    actions = ("activate_all_modules", "deactivate_all_modules")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        ensure_default_gym_modules(obj)

    def active_modules_count(self, obj):
        return obj.modules.filter(is_active=True).count()

    active_modules_count.short_description = "Modules actifs"

    @admin.action(description="Activer tous les modules V1 sur les gyms selectionnes")
    def activate_all_modules(self, request, queryset):
        for gym in queryset:
            ensure_default_gym_modules(gym)
            gym.modules.update(is_active=True)
        self.message_user(request, "Tous les modules V1 ont ete actives.", messages.SUCCESS)

    @admin.action(description="Desactiver tous les modules sur les gyms selectionnes")
    def deactivate_all_modules(self, request, queryset):
        GymModule.objects.filter(gym__in=queryset).update(is_active=False)
        self.message_user(request, "Tous les modules ont ete desactives.", messages.WARNING)


@admin.register(GymModule)
class GymModuleAdmin(admin.ModelAdmin):
    list_display = ("organization_name", "gym_name", "module_code", "module", "is_active", "activated_at")
    list_editable = ("is_active",)
    list_filter = ("is_active", "module", "gym__organization", "gym")
    search_fields = ("gym__name", "gym__organization__name", "module__code", "module__name")
    autocomplete_fields = ("gym", "module")
    readonly_fields = ("activated_at",)
    ordering = ("gym__organization__name", "gym__name", "module__code")

    def organization_name(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization_name.short_description = "Organisation"
    organization_name.admin_order_field = "gym__organization__name"

    def gym_name(self, obj):
        return obj.gym.name if obj.gym_id else "-"

    gym_name.short_description = "Gym"
    gym_name.admin_order_field = "gym__name"

    def module_code(self, obj):
        return obj.module.code if obj.module_id else "-"

    module_code.short_description = "Code module"
    module_code.admin_order_field = "module__code"

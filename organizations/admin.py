# organizations/admin.py
from django.contrib import admin
from .models import Organization, Module, Gym, GymModule

@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'created_at']
    search_fields = ['code', 'name']
    readonly_fields = ['created_at']

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active', 'created_at']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    fields = ['name', 'slug', 'logo', 'is_active']

# Permet d'activer des modules directement depuis la page d'un Gym
class GymModuleInline(admin.TabularInline):
    model = GymModule
    extra = 1
    fields = ['module', 'is_active']
    autocomplete_fields = ['module']

@admin.register(Gym)
class GymAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'subdomain', 'is_active']
    list_filter = ['organization', 'is_active']
    search_fields = ['name', 'subdomain']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [GymModuleInline]  # ← Permet d'activer les modules ici

@admin.register(GymModule)
class GymModuleAdmin(admin.ModelAdmin):
    list_display = ('id','organization_name', 'gym_name',  'module', 'is_active', 'activated_at')
    list_filter = ('is_active', 'module', 'gym__organization')
    search_fields = ('gym__name', 'module__name', 'gym__organization__name')
    readonly_fields = ('is_active',)
    ordering = ('-activated_at',)

    def organization_name(self, obj):
        return obj.gym.organization.name if obj.gym and obj.gym.organization else "-"
    organization_name.short_description = "Organisation"
    organization_name.admin_order_field = 'gym__organization__name'   # permet de trier

    def gym_name(self, obj):
        return obj.gym.name if obj.gym else "-"
    gym_name.short_description = "Gym"
    gym_name.admin_order_field = 'gym__name'

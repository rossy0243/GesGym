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
    list_display = ['gym', 'module', 'is_active', 'activated_at']
    list_filter = ['is_active', 'module', 'gym__organization']
    search_fields = ['gym__name', 'module__name']
    readonly_fields = ['activated_at']
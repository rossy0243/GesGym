# compte/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import path
from django.template.response import TemplateResponse
from .models import User, UserGymRole
from organizations.models import Organization, Gym
from django.contrib.auth.hashers import make_password
from .utils import generate_username


class UserGymRoleInline(admin.TabularInline):
    """Afficher les rôles gym dans l'admin User"""
    model = UserGymRole
    extra = 0
    fields = ['gym', 'role', 'is_active']
    show_change_link = True
    can_delete = True


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "first_name", "last_name", "owned_organization", "is_saas_admin", "is_active")
    list_filter = ("is_saas_admin", "is_active", "owned_organization")
    search_fields = ("username", "first_name", "last_name", "email")
    
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Organisation (pour Owners)", {
            "fields": ("owned_organization",),
            "description": "Si l'utilisateur est Owner, sélectionnez son organisation. Il aura accès à TOUS les gyms de cette organisation."
        }),
        ("SaaS", {"fields": ("is_saas_admin",)}),
    )
    
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Organisation (pour Owners)", {
            "fields": ("owned_organization",),
        }),
        ("SaaS", {"fields": ("is_saas_admin",)}),
    )
    
    inlines = [UserGymRoleInline]
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('create-owner/', self.create_owner_view, name='create_owner_view'),
        ]
        return custom_urls + urls
    
    def create_owner_view(self, request):
        """Vue personnalisée pour créer un Owner facilement"""
        
        if request.method == 'POST':
            first_name = request.POST.get('first_name')
            last_name = request.POST.get('last_name')
            email = request.POST.get('email')
            organization_id = request.POST.get('organization')
            
            if not all([first_name, last_name, organization_id]):
                messages.error(request, "Le prénom, le nom et l'organisation sont requis")
                return redirect('admin:create_owner_view')
            
            organization = Organization.objects.get(id=organization_id)
            username = generate_username(first_name, last_name)
            
            # Créer l'utilisateur
            user = User.objects.create(
                username=username,
                first_name=first_name,
                last_name=last_name,
                email=email,
                password=make_password("12345"),
                is_active=True,
                is_staff=True,
                owned_organization=organization,
            )
            
            # CRUCIAL : Créer UserGymRole pour CHAQUE gym de l'organisation
            gyms = organization.gyms.filter(is_active=True)
            if gyms.exists():
                for gym in gyms:
                    UserGymRole.objects.get_or_create(
                        user=user,
                        gym=gym,
                        defaults={'role': 'owner', 'is_active': True}
                    )
                messages.success(
                    request, 
                    f'✅ Owner créé : {username} | Mot de passe : 12345\n'
                    f'📍 Organisation : {organization.name}\n'
                    f'🏋️ {gyms.count()} gym(s) accessible(s)'
                )
            else:
                messages.warning(
                    request,
                    f'⚠️ Owner créé mais aucun gym trouvé pour {organization.name}. '
                    f'Créez d\'abord des gyms.'
                )
            
            return redirect('admin:compte_user_changelist')
        
        # GET : afficher formulaire
        organizations = Organization.objects.filter(is_active=True)
        context = {
            'title': 'Créer un Owner (Propriétaire)',
            'organizations': organizations,
            'opts': self.model._meta,
        }
        return TemplateResponse(request, 'admin/create_owner.html', context)
    
    def save_model(self, request, obj, form, change):
        """Sécuriser la création : seul un superuser peut créer/modifier un Owner"""
        if 'owned_organization' in form.cleaned_data and form.cleaned_data['owned_organization']:
            if not request.user.is_superuser:
                messages.error(request, "Seul un superuser peut créer ou modifier un Owner")
                return
        super().save_model(request, obj, form, change)


@admin.register(UserGymRole)
class UserGymRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "gym", "organization", "role", "is_active")
    list_filter = ("gym", "role", "is_active")
    search_fields = ("user__username", "user__first_name", "user__last_name", "gym__name")
    
    def organization(self, obj):
        return obj.gym.organization
    organization.short_description = "Organization"
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "gym":
            if hasattr(request, 'gym') and request.gym:
                kwargs["queryset"] = Gym.objects.filter(organization=request.gym.organization)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
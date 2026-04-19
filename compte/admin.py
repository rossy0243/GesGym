from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.text import slugify

from organizations.admin import DEFAULT_MODULE_CODES, ensure_default_gym_modules
from organizations.models import Gym, GymModule, Module, Organization

from .models import User, UserGymRole
from .utils import generate_username


DEMO_DEFAULT_PASSWORD = "12345"


class OwnerCreationForm(forms.Form):
    first_name = forms.CharField(label="Prenom du Owner", max_length=150)
    last_name = forms.CharField(label="Nom du Owner", max_length=150)
    email = forms.EmailField(label="Email du Owner", required=False)
    organization = forms.ModelChoiceField(
        label="Organisation existante",
        queryset=Organization.objects.none(),
        required=False,
        help_text="Laisser vide pour creer une nouvelle organisation.",
    )
    organization_name = forms.CharField(label="Nom de la nouvelle organisation", max_length=255, required=False)
    organization_slug = forms.SlugField(label="Slug", max_length=255, required=False)
    organization_phone = forms.CharField(label="Telephone organisation", max_length=30, required=False)
    organization_email = forms.EmailField(label="Email organisation", required=False)
    organization_address = forms.CharField(
        label="Adresse organisation",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    gyms = forms.CharField(
        label="Gyms a creer",
        required=False,
        help_text="Un gym par ligne. Exemple: Gombe Premium",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    modules = forms.ModelMultipleChoiceField(
        label="Modules a activer sur les gyms",
        queryset=Module.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organization"].queryset = Organization.objects.order_by("name")
        self.fields["modules"].queryset = Module.objects.filter(code__in=DEFAULT_MODULE_CODES).order_by("code")
        self.fields["modules"].initial = list(self.fields["modules"].queryset)

    def clean(self):
        cleaned = super().clean()
        organization = cleaned.get("organization")
        organization_name = (cleaned.get("organization_name") or "").strip()
        gyms = self.gym_lines

        if not organization and not organization_name:
            raise forms.ValidationError("Choisissez une organisation existante ou renseignez une nouvelle organisation.")

        if not organization and not gyms:
            raise forms.ValidationError("Creez au moins un gym pour une nouvelle organisation.")

        return cleaned

    @property
    def gym_lines(self):
        raw = self.cleaned_data.get("gyms") if hasattr(self, "cleaned_data") else self.data.get("gyms")
        return [line.strip() for line in (raw or "").splitlines() if line.strip()]


class UserGymRoleInline(admin.TabularInline):
    model = UserGymRole
    extra = 0
    fields = ("gym", "role", "is_active")
    autocomplete_fields = ("gym",)
    show_change_link = True
    can_delete = True


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    change_list_template = "admin/compte/user/change_list.html"
    list_display = (
        "username",
        "full_name",
        "owner_organization",
        "gym_roles",
        "is_saas_admin",
        "is_active",
        "is_staff",
    )
    list_filter = ("is_saas_admin", "is_active", "is_staff", "owned_organization", "gym_roles__role")
    search_fields = (
        "username",
        "first_name",
        "last_name",
        "email",
        "owned_organization__name",
        "gym_roles__gym__name",
        "gym_roles__gym__organization__name",
    )
    autocomplete_fields = ("owned_organization",)
    ordering = ("username",)

    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Organisation Owner",
            {
                "fields": ("owned_organization",),
                "description": (
                    "Si ce champ est rempli, l'utilisateur est Owner et accede a tous les gyms "
                    "actifs de cette organisation dans l'application."
                ),
            },
        ),
        ("SaaS", {"fields": ("is_saas_admin",)}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Organisation Owner", {"fields": ("owned_organization",)}),
        ("SaaS", {"fields": ("is_saas_admin",)}),
    )
    inlines = (UserGymRoleInline,)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("create-owner/", self.admin_site.admin_view(self.create_owner_view), name="create_owner_view"),
        ]
        return custom_urls + urls

    def create_owner_view(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Seul un superuser peut creer un Owner.")
            return redirect("admin:compte_user_changelist")

        if request.method == "POST":
            form = OwnerCreationForm(request.POST)
            if form.is_valid():
                owner, organization, gyms, modules = self._create_owner_package(form)
                messages.success(
                    request,
                    (
                        f"Owner cree : {owner.username} | Mot de passe : {DEMO_DEFAULT_PASSWORD} | "
                        f"Organisation : {organization.name} | Gyms : {len(gyms)} | Modules : {len(modules)}"
                    ),
                )
                return redirect("admin:compte_user_changelist")
        else:
            form = OwnerCreationForm()

        context = {
            **self.admin_site.each_context(request),
            "title": "Creer un Owner + organisation + gyms",
            "form": form,
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/create_owner.html", context)

    def _create_owner_package(self, form):
        organization = form.cleaned_data["organization"]
        if not organization:
            organization_name = form.cleaned_data["organization_name"].strip()
            organization_slug = form.cleaned_data["organization_slug"] or slugify(organization_name)
            organization_slug = self._unique_organization_slug(organization_slug)
            organization = Organization.objects.create(
                name=organization_name,
                slug=organization_slug,
                phone=form.cleaned_data["organization_phone"],
                email=form.cleaned_data["organization_email"] or form.cleaned_data["email"],
                address=form.cleaned_data["organization_address"],
                is_active=True,
            )

        username = generate_username(form.cleaned_data["first_name"], form.cleaned_data["last_name"])
        owner = User.objects.create_user(
            username=username,
            password=DEMO_DEFAULT_PASSWORD,
            first_name=form.cleaned_data["first_name"],
            last_name=form.cleaned_data["last_name"],
            email=form.cleaned_data["email"] or "",
            owned_organization=organization,
            is_active=True,
            is_staff=False,
        )

        gyms = self._create_gyms(organization, form.gym_lines)
        if not gyms:
            gyms = list(organization.gyms.filter(is_active=True))

        modules = list(form.cleaned_data["modules"] or Module.objects.filter(code__in=DEFAULT_MODULE_CODES))
        for gym in gyms:
            if modules:
                for module in modules:
                    GymModule.objects.get_or_create(gym=gym, module=module, defaults={"is_active": True})
            else:
                ensure_default_gym_modules(gym)
            UserGymRole.objects.update_or_create(
                user=owner,
                gym=gym,
                defaults={"role": "owner", "is_active": True},
            )

        return owner, organization, gyms, modules

    def _create_gyms(self, organization, gym_names):
        gyms = []
        for name in gym_names:
            slug = self._unique_gym_slug(organization, slugify(name) or "gym")
            subdomain = self._unique_subdomain(f"{organization.slug}-{slug}")
            gym = Gym.objects.create(
                organization=organization,
                name=name,
                slug=slug,
                subdomain=subdomain,
                is_active=True,
            )
            ensure_default_gym_modules(gym)
            gyms.append(gym)
        return gyms

    def _unique_organization_slug(self, base_slug):
        slug = base_slug or "organisation"
        candidate = slug
        index = 2
        while Organization.objects.filter(slug=candidate).exists():
            candidate = f"{slug}-{index}"
            index += 1
        return candidate

    def _unique_gym_slug(self, organization, base_slug):
        slug = base_slug or "gym"
        candidate = slug
        index = 2
        while Gym.objects.filter(organization=organization, slug=candidate).exists():
            candidate = f"{slug}-{index}"
            index += 1
        return candidate

    def _unique_subdomain(self, base_subdomain):
        subdomain = slugify(base_subdomain)[:90] or "gym"
        candidate = subdomain
        index = 2
        while Gym.objects.filter(subdomain=candidate).exists():
            suffix = f"-{index}"
            candidate = f"{subdomain[:100 - len(suffix)]}{suffix}"
            index += 1
        return candidate

    def save_model(self, request, obj, form, change):
        if form.cleaned_data.get("owned_organization") and not request.user.is_superuser:
            messages.error(request, "Seul un superuser peut creer ou modifier un Owner.")
            return
        super().save_model(request, obj, form, change)

    def full_name(self, obj):
        return obj.get_full_name() or "-"

    full_name.short_description = "Nom complet"

    def owner_organization(self, obj):
        return obj.owned_organization.name if obj.owned_organization_id else "-"

    owner_organization.short_description = "Organisation Owner"
    owner_organization.admin_order_field = "owned_organization__name"

    def gym_roles(self, obj):
        roles = obj.gym_roles.select_related("gym", "gym__organization").all()[:4]
        labels = [f"{role.gym.organization.name} / {role.gym.name} : {role.get_role_display()}" for role in roles]
        return " | ".join(labels) if labels else "-"

    gym_roles.short_description = "Roles gyms"


@admin.register(UserGymRole)
class UserGymRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "user_full_name", "organization", "gym", "role", "is_active")
    list_filter = ("role", "is_active", "gym__organization", "gym")
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
        "gym__name",
        "gym__organization__name",
    )
    autocomplete_fields = ("user", "gym")
    list_editable = ("is_active",)
    ordering = ("gym__organization__name", "gym__name", "role", "user__username")

    def user_full_name(self, obj):
        return obj.user.get_full_name() or "-"

    user_full_name.short_description = "Nom complet"

    def organization(self, obj):
        return obj.gym.organization.name if obj.gym_id else "-"

    organization.short_description = "Organisation"
    organization.admin_order_field = "gym__organization__name"

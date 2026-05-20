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
from .utils import generate_temporary_password, generate_username


OWNER_CREATION_PREVIEW_SESSION_KEY = "admin_owner_creation_preview"
OWNER_CREATION_RESULT_SESSION_KEY = "admin_owner_creation_result"


class OwnerCreationForm(forms.Form):
    first_name = forms.CharField(label="Prenom du Owner", max_length=150)
    last_name = forms.CharField(label="Nom du Owner", max_length=150)
    email = forms.EmailField(label="Email du Owner", required=True)
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

    def clean_gyms(self):
        raw_value = self.cleaned_data.get("gyms", "")
        lines = []
        seen_names = set()

        for index, line in enumerate(raw_value.splitlines(), start=1):
            gym_name = " ".join(line.strip().split())
            if not gym_name:
                continue
            if len(gym_name) < 3:
                raise forms.ValidationError(f"Le gym ligne {index} est trop court.")
            normalized_name = gym_name.casefold()
            if normalized_name in seen_names:
                raise forms.ValidationError(f"Le gym '{gym_name}' est saisi plusieurs fois.")
            seen_names.add(normalized_name)
            lines.append(gym_name)

        return lines

    def clean(self):
        cleaned = super().clean()
        organization = cleaned.get("organization")
        organization_name = (cleaned.get("organization_name") or "").strip()
        gyms = cleaned.get("gyms") or []

        if not organization and not organization_name:
            raise forms.ValidationError("Choisissez une organisation existante ou renseignez une nouvelle organisation.")

        if organization and organization_name:
            raise forms.ValidationError("Choisissez une organisation existante ou creez-en une nouvelle, mais pas les deux.")

        if organization and any(
            cleaned.get(field_name)
            for field_name in ("organization_slug", "organization_phone", "organization_email", "organization_address")
        ):
            raise forms.ValidationError("Les champs de creation d'organisation doivent rester vides si vous selectionnez une organisation existante.")

        if not organization and not gyms:
            raise forms.ValidationError("Creez au moins un gym pour une nouvelle organisation.")

        if organization and not gyms and not organization.gyms.filter(is_active=True).exists():
            raise forms.ValidationError("Cette organisation n'a aucun gym actif. Ajoutez au moins un gym.")

        if User.objects.filter(email__iexact=cleaned.get("email", "").strip()).exists():
            self.add_error("email", "Un utilisateur existe deja avec cet email.")

        for gym_name in gyms:
            if organization and Gym.objects.filter(organization=organization, name__iexact=gym_name).exists():
                self.add_error("gyms", f"Le gym '{gym_name}' existe deja dans cette organisation.")

        return cleaned


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
                "fields": ("owned_organization", "force_password_change"),
                "description": (
                    "Si ce champ est rempli, l'utilisateur est Owner et accede a tous les gyms "
                    "actifs de cette organisation dans l'application."
                ),
            },
        ),
        ("SaaS", {"fields": ("is_saas_admin",)}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Organisation Owner", {"fields": ("owned_organization", "force_password_change")}),
        ("SaaS", {"fields": ("is_saas_admin",)}),
    )
    inlines = (UserGymRoleInline,)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("create-owner/", self.admin_site.admin_view(self.create_owner_view), name="create_owner_view"),
            path("create-owner/success/", self.admin_site.admin_view(self.create_owner_success_view), name="create_owner_success_view"),
        ]
        return custom_urls + urls

    def create_owner_view(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Seul un superuser peut creer un Owner.")
            return redirect("admin:compte_user_changelist")

        if request.method == "POST" and "_confirm_create" in request.POST:
            preview = request.session.get(OWNER_CREATION_PREVIEW_SESSION_KEY)
            if not preview:
                messages.error(request, "Le recapitulatif a expire. Recommencez la creation du client.")
                return redirect("admin:create_owner_view")

            owner, organization, gyms, modules, temporary_password = self._create_owner_package(preview)
            verification = self._build_creation_verification(owner, organization, gyms, modules)
            request.session.pop(OWNER_CREATION_PREVIEW_SESSION_KEY, None)
            request.session[OWNER_CREATION_RESULT_SESSION_KEY] = {
                "owner_username": owner.username,
                "owner_email": owner.email,
                "temporary_password": temporary_password,
                "organization_name": organization.name,
                "organization_slug": organization.slug,
                "gym_names": [gym.name for gym in gyms],
                "module_codes": [module.code for module in modules],
                "verification": verification,
            }
            return redirect("admin:create_owner_success_view")

        if request.method == "POST" and "_edit_draft" in request.POST:
            preview = request.session.get(OWNER_CREATION_PREVIEW_SESSION_KEY, {})
            form = OwnerCreationForm(initial=self._preview_to_form_initial(preview))
        elif request.method == "POST":
            form = OwnerCreationForm(request.POST)
            if form.is_valid():
                preview = self._build_preview_payload(form)
                request.session[OWNER_CREATION_PREVIEW_SESSION_KEY] = preview
                context = {
                    **self.admin_site.each_context(request),
                    "title": "Verifier le recapitulatif avant creation",
                    "preview": preview,
                    "opts": self.model._meta,
                }
                return TemplateResponse(request, "admin/create_owner_confirm.html", context)
        else:
            preview = request.session.get(OWNER_CREATION_PREVIEW_SESSION_KEY)
            initial = self._preview_to_form_initial(preview) if preview else None
            form = OwnerCreationForm(initial=initial)

        context = {
            **self.admin_site.each_context(request),
            "title": "Creer un Owner + organisation + gyms",
            "form": form,
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/create_owner.html", context)

    def create_owner_success_view(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Seul un superuser peut consulter ce recapitulatif.")
            return redirect("admin:compte_user_changelist")

        result = request.session.pop(OWNER_CREATION_RESULT_SESSION_KEY, None)
        if not result:
            messages.info(request, "Aucun recapitulatif recent a afficher.")
            return redirect("admin:create_owner_view")

        context = {
            **self.admin_site.each_context(request),
            "title": "Client cree et verifie",
            "result": result,
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/create_owner_success.html", context)

    def _build_preview_payload(self, form):
        organization = form.cleaned_data["organization"]
        gym_names = form.cleaned_data["gyms"]
        modules = list(form.cleaned_data["modules"] or Module.objects.filter(code__in=DEFAULT_MODULE_CODES).order_by("code"))
        return {
            "first_name": form.cleaned_data["first_name"].strip(),
            "last_name": form.cleaned_data["last_name"].strip(),
            "email": form.cleaned_data["email"].strip(),
            "organization_id": organization.id if organization else None,
            "organization_name": organization.name if organization else form.cleaned_data["organization_name"].strip(),
            "organization_slug": organization.slug if organization else (form.cleaned_data["organization_slug"] or slugify(form.cleaned_data["organization_name"])).strip(),
            "organization_phone": organization.phone if organization else (form.cleaned_data["organization_phone"] or "").strip(),
            "organization_email": organization.email if organization else (form.cleaned_data["organization_email"] or form.cleaned_data["email"]).strip(),
            "organization_address": organization.address if organization else (form.cleaned_data["organization_address"] or "").strip(),
            "gym_names": gym_names,
            "module_ids": [module.id for module in modules],
            "module_codes": [module.code for module in modules],
            "uses_existing_organization": bool(organization),
            "existing_active_gym_names": list(organization.gyms.filter(is_active=True).order_by("name").values_list("name", flat=True))
            if organization
            else [],
        }

    def _preview_to_form_initial(self, preview):
        if not preview:
            return None
        return {
            "first_name": preview.get("first_name", ""),
            "last_name": preview.get("last_name", ""),
            "email": preview.get("email", ""),
            "organization": preview.get("organization_id"),
            "organization_name": "" if preview.get("organization_id") else preview.get("organization_name", ""),
            "organization_slug": "" if preview.get("organization_id") else preview.get("organization_slug", ""),
            "organization_phone": "" if preview.get("organization_id") else preview.get("organization_phone", ""),
            "organization_email": "" if preview.get("organization_id") else preview.get("organization_email", ""),
            "organization_address": "" if preview.get("organization_id") else preview.get("organization_address", ""),
            "gyms": "\n".join(preview.get("gym_names", [])),
            "modules": preview.get("module_ids", []),
        }

    def _create_owner_package(self, preview):
        organization = Organization.objects.filter(id=preview["organization_id"]).first()
        if not organization:
            organization_name = preview["organization_name"].strip()
            organization_slug = preview["organization_slug"] or slugify(organization_name)
            organization_slug = self._unique_organization_slug(organization_slug)
            organization = Organization.objects.create(
                name=organization_name,
                slug=organization_slug,
                phone=preview["organization_phone"],
                email=preview["organization_email"] or preview["email"],
                address=preview["organization_address"],
                is_active=True,
            )

        username = generate_username(preview["first_name"], preview["last_name"])
        temporary_password = generate_temporary_password()
        owner = User.objects.create_user(
            username=username,
            password=temporary_password,
            first_name=preview["first_name"],
            last_name=preview["last_name"],
            email=preview["email"],
            owned_organization=organization,
            force_password_change=True,
            is_active=True,
            is_staff=False,
        )

        gyms = self._create_gyms(organization, preview["gym_names"])
        if not gyms:
            gyms = list(organization.gyms.filter(is_active=True))

        modules = list(Module.objects.filter(id__in=preview["module_ids"]).order_by("code"))
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

        return owner, organization, gyms, modules, temporary_password

    def _create_gyms(self, organization, gym_names):
        gyms = []
        for name in gym_names:
            if Gym.objects.filter(organization=organization, name__iexact=name).exists():
                continue
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

    def _build_creation_verification(self, owner, organization, gyms, modules):
        return {
            "organization_active": organization.is_active,
            "owner_active": owner.is_active,
            "owner_must_change_password": owner.force_password_change,
            "gyms_created_count": len(gyms),
            "gyms_active_count": sum(1 for gym in gyms if gym.is_active),
            "modules_active_count": GymModule.objects.filter(
                gym__in=gyms,
                module__in=modules,
                is_active=True,
            ).count(),
            "expected_modules_active_count": len(gyms) * len(modules),
            "login_ready": bool(owner.is_active and organization.is_active and gyms),
        }

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

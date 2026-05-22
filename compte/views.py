# compte/views.py
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.contrib.auth.views import LoginView
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy

from compte.utils import generate_temporary_password, generate_username, has_other_active_access
from organizations.models import Gym

from .forms import (
    CreateUserForm,
    CustomAuthenticationForm,
    ForcedPasswordChangeForm,
    UserPasswordChangeForm,
    UserProfileForm,
)
from .models import User, UserGymRole


def _scoped_identity_change_blocked(user, role):
    return has_other_active_access(user, exclude_role_ids=[role.id])


def _resolve_login_success_url(request):
    user = request.user

    if user.is_saas_admin:
        return reverse_lazy("admin:index")

    if user.owned_organization and user.owned_organization.is_active:
        return reverse_lazy("core:dashboard_redirect")

    member_profile = getattr(user, "member_profile", None)
    if member_profile:
        return reverse_lazy("members:member_portal")

    role = UserGymRole.objects.filter(
        user=user,
        is_active=True,
        gym__is_active=True,
        gym__organization__is_active=True,
    ).select_related("gym").first()

    if not role:
        logout(request)
        messages.error(
            request,
            "Aucun acces actif n'est associe a ces identifiants."
        )
        return reverse_lazy("compte:login")

    if role.role == "coach":
        return reverse_lazy("coaching:coach_portal")

    return reverse_lazy("core:dashboard_redirect")


def _welcome_context_for_user(request):
    user = request.user
    organization = getattr(request, "organization", None) or getattr(user, "owned_organization", None)
    role = UserGymRole.objects.filter(
        user=user,
        is_active=True,
        gym__is_active=True,
        gym__organization__is_active=True,
    ).select_related("gym", "gym__organization").first()
    gym = getattr(request, "gym", None) or (role.gym if role else None)
    if not organization and gym:
        organization = gym.organization

    is_owner = bool(user.owned_organization_id)
    subtitle = "Proprietaire"
    if not is_owner and gym:
        subtitle = gym.name
    elif not is_owner and role:
        subtitle = role.get_role_display()

    return {
        "organization": organization,
        "gym": gym,
        "is_owner": is_owner,
        "subtitle": subtitle,
        "welcome_target": request.session.get("post_login_target", reverse_lazy("core:dashboard_redirect")),
    }


class CustomLoginView(LoginView):
    template_name = "compte/login.html"
    authentication_form = CustomAuthenticationForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["social_links"] = [link for link in settings.SOCIAL_LINKS if link.get("url")]
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        if form.cleaned_data.get("remember_me"):
            self.request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        else:
            self.request.session.set_expiry(0)
        self.request.session["post_login_target"] = str(_resolve_login_success_url(self.request))
        self.request.session.modified = True
        if self.request.user.force_password_change:
            messages.warning(
                self.request,
                "Votre mot de passe temporaire doit etre remplace avant d'acceder a l'application.",
            )
            return redirect("compte:profile")
        return redirect("compte:welcome")

    def get_success_url(self):
        return _resolve_login_success_url(self.request)


@login_required
def welcome(request):
    context = _welcome_context_for_user(request)
    return render(request, "compte/welcome.html", context)


def logout_view(request):
    logout(request)
    return redirect("compte:login")


@login_required
def profile(request):
    force_password_change = bool(request.user.force_password_change)
    profile_form = UserProfileForm(instance=request.user)
    password_form = (
        ForcedPasswordChangeForm(request.user)
        if force_password_change
        else UserPasswordChangeForm(request.user)
    )

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "profile" and not force_password_change:
            profile_form = UserProfileForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profil mis a jour avec succes.")
                return redirect("compte:profile")
            messages.error(request, "Impossible de mettre a jour le profil. Verifiez les champs.")

        elif action == "password":
            password_form = (
                ForcedPasswordChangeForm(request.user, request.POST)
                if force_password_change
                else UserPasswordChangeForm(request.user, request.POST)
            )
            if password_form.is_valid():
                user = password_form.save()
                if user.force_password_change:
                    user.force_password_change = False
                    user.save(update_fields=["force_password_change"])
                update_session_auth_hash(request, user)
                messages.success(
                    request,
                    "Mot de passe defini avec succes."
                    if force_password_change
                    else "Mot de passe modifie avec succes.",
                )
                return redirect(request.session.get("post_login_target", reverse_lazy("compte:profile")))
            messages.error(request, "Mot de passe non modifie. Verifiez les informations saisies.")

    active_roles = UserGymRole.objects.filter(
        user=request.user,
        is_active=True,
        gym__is_active=True,
        gym__organization__is_active=True,
    ).select_related("gym", "gym__organization")

    context = {
        "profile_form": profile_form,
        "password_form": password_form,
        "active_roles": active_roles,
        "page_title": "Mon profil",
        "nav_active": "profile",
        "force_password_change": force_password_change,
        "breadcrumbs": [
            {"label": "Accueil", "url": reverse_lazy("core:dashboard_redirect")},
            {"label": "Mon profil", "url": ""},
        ],
    }
    return render(request, "compte/profile.html", context)


@staff_member_required
def get_gyms_by_organization(request):
    organization_id = request.GET.get("organization_id")
    if organization_id:
        gyms = Gym.objects.filter(
            organization_id=organization_id,
            is_active=True
        ).values("id", "name")
        return JsonResponse({"gyms": list(gyms)})
    return JsonResponse({"gyms": []})


@login_required
def create_user_by_owner(request):
    gym = request.gym
    user_role = UserGymRole.objects.filter(user=request.user, gym=gym, is_active=True).first()

    if not user_role or user_role.role != "owner":
        messages.error(request, "Vous n'avez pas les permissions necessaires")
        return redirect("core:dashboard_redirect")

    if request.method == "POST":
        form = CreateUserForm(request.POST)
        if form.is_valid():
            username = generate_username(
                form.cleaned_data["first_name"],
                form.cleaned_data["last_name"]
            )

            user = User.objects.create(
                username=username,
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                email=form.cleaned_data["email"],
                password=make_password(generate_temporary_password()),
                force_password_change=True,
                is_active=True,
                is_staff=False,
            )

            UserGymRole.objects.create(
                user=user,
                gym=gym,
                role=form.cleaned_data["role"],
                is_active=True
            )

            messages.success(
                request,
                f"Utilisateur '{username}' cree avec succes. Un mot de passe temporaire fort a ete genere et devra etre change a la premiere connexion."
            )
            return redirect("compte:user_list")
    else:
        form = CreateUserForm()

    context = {
        "form": form,
        "gym": gym,
        "available_roles": ["manager", "coach", "reception", "cashier"],
    }
    return render(request, "compte/create_user.html", context)


@login_required
def user_list(request):
    gym = request.gym
    users_with_roles = UserGymRole.objects.filter(
        gym=gym,
        is_active=True
    ).select_related("user")

    context = {
        "users": users_with_roles,
        "gym": gym,
    }
    return render(request, "compte/user_list.html", context)


@login_required
def reset_password(request, user_id):
    gym = request.gym
    user_role = UserGymRole.objects.filter(user=request.user, gym=gym, is_active=True).first()

    if not user_role or user_role.role != "owner":
        messages.error(request, "Permission non accordee")
        return redirect("core:dashboard_redirect")

    target_user = get_object_or_404(User, id=user_id)

    target_role = UserGymRole.objects.filter(user=target_user, gym=gym).first()
    if not target_role:
        messages.error(request, "Utilisateur non trouve dans ce gym")
        return redirect("compte:user_list")
    if _scoped_identity_change_blocked(target_user, target_role):
        messages.error(
            request,
            "Ce compte est partage avec un autre acces actif. Utilisez une reinitialisation globale supervisee.",
        )
        return redirect("compte:user_list")

    target_user.password = make_password(generate_temporary_password())
    target_user.force_password_change = True
    target_user.save(update_fields=["password", "force_password_change"])

    messages.success(
        request,
        f"Mot de passe reinitialise pour {target_user.username}. Un nouveau mot de passe temporaire fort a ete genere et devra etre change a la prochaine connexion."
    )
    return redirect("compte:user_list")


@login_required
def deactivate_user(request, user_id):
    gym = request.gym
    user_role = UserGymRole.objects.filter(user=request.user, gym=gym, is_active=True).first()

    if not user_role or user_role.role != "owner":
        messages.error(request, "Permission non accordee")
        return redirect("core:dashboard_redirect")

    target_user = get_object_or_404(User, id=user_id)

    if target_user.id == request.user.id:
        messages.error(request, "Vous ne pouvez pas vous desactiver vous-meme")
        return redirect("compte:user_list")

    target_role = UserGymRole.objects.filter(user=target_user, gym=gym).first()
    if not target_role:
        messages.error(request, "Utilisateur non trouve dans ce gym")
        return redirect("compte:user_list")

    target_role.is_active = False
    target_role.save(update_fields=["is_active"])

    if not has_other_active_access(target_user, exclude_role_ids=[target_role.id]):
        target_user.is_active = False
        target_user.save(update_fields=["is_active"])

    messages.success(request, f"Utilisateur {target_user.username} desactive")
    return redirect("compte:user_list")


@login_required
def activate_user(request, user_id):
    gym = request.gym
    user_role = UserGymRole.objects.filter(user=request.user, gym=gym, is_active=True).first()

    if not user_role or user_role.role != "owner":
        messages.error(request, "Permission non accordee")
        return redirect("core:dashboard_redirect")

    target_user = get_object_or_404(User, id=user_id)
    target_role = UserGymRole.objects.filter(user=target_user, gym=gym).first()

    if not target_role:
        messages.error(request, "Utilisateur non trouve dans ce gym")
        return redirect("compte:user_list")

    target_role.is_active = True
    target_role.save(update_fields=["is_active"])

    if not target_user.is_active:
        target_user.is_active = True
        target_user.save(update_fields=["is_active"])

    messages.success(request, f"Utilisateur {target_user.username} reactive")
    return redirect("compte:user_list")

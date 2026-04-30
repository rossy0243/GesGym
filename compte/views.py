# compte/views.py
from django.conf import settings
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.views import LoginView
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.contrib.auth.hashers import make_password
from compte.utils import generate_username
from .forms import CreateUserForm, CustomAuthenticationForm, UserPasswordChangeForm, UserProfileForm
from .models import User, UserGymRole
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.admin.views.decorators import staff_member_required
from organizations.models import Gym


def _resolve_login_success_url(request):
    user = request.user

    if user.is_saas_admin:
        return reverse_lazy("admin:index")

    if user.owned_organization and user.owned_organization.is_active:
        return reverse_lazy("core:dashboard_redirect")

    member_profile = getattr(user, "member_profile", None)
    if member_profile:
        has_staff_role = UserGymRole.objects.filter(
            user=user,
            is_active=True,
            gym__is_active=True,
            gym__organization__is_active=True,
        ).exclude(role="accountant").exists()
        if not has_staff_role:
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
    template_name = 'compte/login.html'
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
        return redirect("compte:welcome")

    def get_success_url(self):
        return _resolve_login_success_url(self.request)


@login_required
def welcome(request):
    context = _welcome_context_for_user(request)
    return render(request, "compte/welcome.html", context)
        

def logout_view(request):
    """
    Déconnexion propre de l'utilisateur
    """
    logout(request)
    return redirect("compte:login")


@login_required
def profile(request):
    profile_form = UserProfileForm(instance=request.user)
    password_form = UserPasswordChangeForm(request.user)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "profile":
            profile_form = UserProfileForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profil mis a jour avec succes.")
                return redirect("compte:profile")
            messages.error(request, "Impossible de mettre a jour le profil. Verifiez les champs.")

        elif action == "password":
            password_form = UserPasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Mot de passe modifie avec succes.")
                return redirect("compte:profile")
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
        "breadcrumbs": [
            {"label": "Accueil", "url": reverse_lazy("core:dashboard_redirect")},
            {"label": "Mon profil", "url": ""},
        ],
    }
    return render(request, "compte/profile.html", context)


@staff_member_required
def get_gyms_by_organization(request):
    """API pour récupérer les gyms d'une organisation (utilisé dans l'admin)"""
    organization_id = request.GET.get('organization_id')
    if organization_id:
        gyms = Gym.objects.filter(
            organization_id=organization_id,
            is_active=True
        ).values('id', 'name')
        return JsonResponse({'gyms': list(gyms)})
    return JsonResponse({'gyms': []})


@login_required
def create_user_by_owner(request):
    """
    Vue pour permettre au Owner de créer des utilisateurs.
    Ne permet PAS de créer un autre Owner.
    """
    # Vérifier que l'utilisateur est Owner
    gym = request.gym
    user_role = UserGymRole.objects.filter(user=request.user, gym=gym, is_active=True).first()
    
    if not user_role or user_role.role != 'owner':
        messages.error(request, "Vous n'avez pas les permissions nécessaires")
        return redirect('core:dashboard_redirect')
    
    if request.method == 'POST':
        form = CreateUserForm(request.POST)
        if form.is_valid():
            # Créer l'utilisateur
            username = generate_username(
                form.cleaned_data['first_name'],
                form.cleaned_data['last_name']
            )
            
            user = User.objects.create(
                username=username,
                first_name=form.cleaned_data['first_name'],
                last_name=form.cleaned_data['last_name'],
                email=form.cleaned_data['email'],
                password=make_password("12345"),
                is_active=True,
                is_staff=False,  # Seuls les Owners ont accès admin
            )
            
            # Assigner le rôle (jamais Owner)
            UserGymRole.objects.create(
                user=user,
                gym=gym,
                role=form.cleaned_data['role'],
                is_active=True
            )
            
            messages.success(
                request,
                f"Utilisateur '{username}' créé avec succès. Mot de passe: 12345"
            )
            return redirect('compte:user_list')
    else:
        form = CreateUserForm()
    
    context = {
        'form': form,
        'gym': gym,
        'available_roles': ['manager', 'coach', 'reception', 'cashier', 'accountant'],
    }
    return render(request, 'compte/create_user.html', context)

@login_required
def user_list(request):
    """Liste des utilisateurs du gym (pour Owner)"""
    gym = request.gym
    users_with_roles = UserGymRole.objects.filter(
        gym=gym,
        is_active=True
    ).select_related('user')
    
    context = {
        'users': users_with_roles,
        'gym': gym,
    }
    return render(request, 'compte/user_list.html', context)

@login_required
def reset_password(request, user_id):
    """Réinitialiser le mot de passe d'un utilisateur"""
    # Vérifier que l'utilisateur connecté est Owner
    gym = request.gym
    user_role = UserGymRole.objects.filter(user=request.user, gym=gym, is_active=True).first()
    
    if not user_role or user_role.role != 'owner':
        messages.error(request, "Permission non accordée")
        return redirect('core:dashboard_redirect')
    
    # Récupérer l'utilisateur cible
    target_user = get_object_or_404(User, id=user_id)
    
    # Vérifier que l'utilisateur appartient bien au gym
    target_role = UserGymRole.objects.filter(user=target_user, gym=gym).first()
    if not target_role:
        messages.error(request, "Utilisateur non trouvé dans ce gym")
        return redirect('compte:user_list')
    
    # Réinitialiser le mot de passe
    target_user.password = make_password("12345")
    target_user.save()
    
    messages.success(request, f"Mot de passe réinitialisé pour {target_user.username} (12345)")
    return redirect('compte:user_list')


@login_required
def deactivate_user(request, user_id):
    """Désactiver un utilisateur"""
    # Vérifier que l'utilisateur connecté est Owner
    gym = request.gym
    user_role = UserGymRole.objects.filter(user=request.user, gym=gym, is_active=True).first()
    
    if not user_role or user_role.role != 'owner':
        messages.error(request, "Permission non accordée")
        return redirect('core:dashboard_redirect')
    
    # Récupérer l'utilisateur cible
    target_user = get_object_or_404(User, id=user_id)
    
    # Ne pas se désactiver soi-même
    if target_user.id == request.user.id:
        messages.error(request, "Vous ne pouvez pas vous désactiver vous-même")
        return redirect('compte:user_list')
    
    # Vérifier que l'utilisateur appartient bien au gym
    target_role = UserGymRole.objects.filter(user=target_user, gym=gym).first()
    if not target_role:
        messages.error(request, "Utilisateur non trouvé dans ce gym")
        return redirect('compte:user_list')
    
    # Désactiver le rôle (pas l'utilisateur complet)
    target_role.is_active = False
    target_role.save()
    
    # Optionnel : aussi désactiver l'utilisateur
    target_user.is_active = False
    target_user.save()
    
    messages.success(request, f"Utilisateur {target_user.username} désactivé")
    return redirect('compte:user_list')


@login_required
def activate_user(request, user_id):
    """Réactiver un utilisateur"""
    gym = request.gym
    user_role = UserGymRole.objects.filter(user=request.user, gym=gym, is_active=True).first()
    
    if not user_role or user_role.role != 'owner':
        messages.error(request, "Permission non accordée")
        return redirect('core:dashboard_redirect')
    
    target_user = get_object_or_404(User, id=user_id)
    target_role = UserGymRole.objects.filter(user=target_user, gym=gym).first()
    
    if not target_role:
        messages.error(request, "Utilisateur non trouvé dans ce gym")
        return redirect('compte:user_list')
    
    target_role.is_active = True
    target_role.save()
    
    target_user.is_active = True
    target_user.save()
    
    messages.success(request, f"Utilisateur {target_user.username} réactivé")
    return redirect('compte:user_list')

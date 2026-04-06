# compte/views.py
from django.contrib.auth import logout
from django.contrib.auth.views import LoginView
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.contrib.auth.hashers import make_password
from compte.utils import generate_username
from .forms import CreateUserForm, CustomAuthenticationForm
from .models import User, UserGymRole
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.admin.views.decorators import staff_member_required
from organizations.models import Gym

class CustomLoginView(LoginView):
    template_name = 'compte/login.html'
    authentication_form = CustomAuthenticationForm

    from compte.models import UserGymRole


    def get_success_url(self):

        user = self.request.user

        # SaaS admin (global)
        if user.is_saas_admin:
            return reverse_lazy("admin:index")  # ou futur dashboard SaaS

        # récupérer le rôle actif
        role = UserGymRole.objects.filter(
            user=user,
            is_active=True
        ).select_related("gym").first()

        if not role:
            return reverse_lazy("compte:login")

        return reverse_lazy("core:dashboard_redirect")
        

def logout_view(request):
    """
    Déconnexion propre de l'utilisateur
    """
    logout(request)
    return redirect("compte:login")


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

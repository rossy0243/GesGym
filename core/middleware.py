# core/middleware.py
from organizations.models import Gym
from compte.models import UserGymRole

class GymMiddleware:
    """
    Middleware principal pour gérer le contexte multi-tenant :
    - Owner → organisation + ses gyms
    - Autres rôles → gym spécifique
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Initialisation par défaut
        request.gym = None
        request.organization = None
        request.is_owner = False
        request.role = None
        request.owned_gyms = []

        if not request.user.is_authenticated:
            return self.get_response(request)

        user = request.user

        # ====================== CAS OWNER ======================
        if hasattr(user, 'owned_organization') and user.owned_organization:
            request.is_owner = True
            request.organization = user.owned_organization
            request.role = 'owner'

            # Récupérer tous les gyms actifs de son organisation
            request.owned_gyms = list(
                user.owned_organization.gyms.filter(is_active=True)
            )

            # Définir le gym actuel (priorité à la session)
            current_gym_id = request.session.get('current_gym_id')
            if current_gym_id:
                try:
                    request.gym = Gym.objects.get(
                        id=current_gym_id,
                        organization=request.organization
                    )
                except Gym.DoesNotExist:
                    request.gym = request.owned_gyms[0] if request.owned_gyms else None
            elif request.owned_gyms:
                request.gym = request.owned_gyms[0]  # gym par défaut

        # ====================== CAS UTILISATEUR NORMAL ======================
        else:
            role_entry = UserGymRole.objects.filter(
                user=user,
                is_active=True
            ).select_related('gym__organization').first()

            if role_entry:
                request.gym = role_entry.gym
                request.organization = role_entry.gym.organization
                request.role = role_entry.role
                request.is_owner = False

        return self.get_response(request)
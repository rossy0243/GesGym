# core/middleware.py
from compte.models import UserGymRole
from organizations.models import Gym

class GymMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Initialisation des attributs
        request.gym = None
        request.organization = None
        request.is_owner = False
        request.role = None  # ← AJOUTER CETTE LIGNE
        request.owned_gyms = []

        if request.user.is_authenticated:
            # Cas 1 : Owner (lié à une organisation)
            if hasattr(request.user, 'owned_organization') and request.user.owned_organization:
                request.is_owner = True
                request.organization = request.user.owned_organization
                request.role = 'owner'  # ← AJOUTER
                request.gym = None
                # Récupérer les gyms de l'organisation
                request.owned_gyms = list(request.organization.gyms.filter(is_active=True))
            
            # Cas 2 : Autres rôles (Manager, Coach, etc.)
            else:
                role = UserGymRole.objects.filter(
                    user=request.user,
                    is_active=True
                ).select_related("gym__organization").first()

                if role:
                    request.gym = role.gym
                    request.organization = role.gym.organization
                    request.role = role.role  # ← AJOUTER
                    request.is_owner = False

        return self.get_response(request)
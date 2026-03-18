# core/middleware/tenant_middleware.py

from organizations.models.gym import Gym


class TenantMiddleware:
    """
    Middleware responsable de déterminer le gym actif
    pour chaque requête.

    Il injecte automatiquement :
    - request.gym
    - request.organization
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        request.gym = None
        request.organization = None

        # Cas 1 : utilisateur connecté
        if request.user.is_authenticated:

            # si utilisateur possède un gym
            if hasattr(request.user, "gym") and request.user.gym:

                request.gym = request.user.gym
                request.organization = request.user.gym.organization

        # Cas 2 : fallback via sous-domaine
        if not request.gym:

            host = request.get_host().split(":")[0]

            subdomain = host.split(".")[0]

            try:
                gym = Gym.objects.select_related("organization").get(
                    subdomain=subdomain
                )

                request.gym = gym
                request.organization = gym.organization

            except Gym.DoesNotExist:
                pass

        response = self.get_response(request)

        return response
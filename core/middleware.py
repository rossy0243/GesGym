from django.core.exceptions import PermissionDenied
from django.urls import resolve

class GymIsolationMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        # Pages publiques autorisées
        public_paths = [
            '/',
            '/compte/login/',
            '/compte/logout/',
            '/admin/login/',
        ]

        if request.path.startswith('/admin'):
            return self.get_response(request)

        if request.path in public_paths:
            return self.get_response(request)

        # Si non connecté → laisser passer
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Superadmin → accès global
        if request.user.role == "superadmin":
            request.gym = None
            return self.get_response(request)

        # Utilisateur normal → doit avoir une gym
        if not request.user.gym:
            raise PermissionDenied("Aucune salle associée.")

        request.gym = request.user.gym

        return self.get_response(request)
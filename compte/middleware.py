from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """
    Tant que le mot de passe temporaire n'a pas ete remplace, l'utilisateur
    reste redirige vers son profil.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and getattr(user, "force_password_change", False):
            allowed_paths = {
                reverse("compte:profile"),
                reverse("compte:logout"),
            }
            if request.path not in allowed_paths:
                return redirect(f"{reverse('compte:profile')}?force_password_change=1")

        return self.get_response(request)

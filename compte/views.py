# compte/views.py
from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy

from .forms import CustomAuthenticationForm
from .models import User, UserGymRole
from django.contrib.auth.decorators import login_required

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

        return reverse_lazy("core:dashboard")
        

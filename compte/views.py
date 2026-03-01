# compte/views.py
from django.contrib.auth.views import LoginView
from django.shortcuts import render
from django.urls import reverse_lazy
from .forms import CustomAuthenticationForm, StaffCreationForm
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

class CustomLoginView(LoginView):
    template_name = 'compte/login.html'
    authentication_form = CustomAuthenticationForm

    def get_success_url(self):
        user = self.request.user

        if user.role == 'superadmin':
            return reverse_lazy('superadmin_dashboard')

        role_dashboard_map = {
            'admin': 'core:admin_dashboard',
            'manager': 'core:manager_dashboard',
            'cashier': 'core:cashier_dashboard',
            'reception': 'core:reception_dashboard',
            'member': 'core:member_dashboard',
        }

        return reverse_lazy(role_dashboard_map.get(user.role, 'compte:login'))
    
    
@login_required
def create_staff(request):

    if request.user.role != "admin":
        raise PermissionDenied("Seul l'admin peut créer du staff.")

    if request.method == "POST":
        form = StaffCreationForm(request.POST)
        if form.is_valid():
            form.save(gym=request.user.gym)
            return redirect("admin_dashboard")
    else:
        form = StaffCreationForm()

    return render(request, "compte/create_staff.html", {"form": form})
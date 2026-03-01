# compte/views.py
from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
from .forms import CustomAuthenticationForm

class CustomLoginView(LoginView):
    template_name = 'compte/login.html'
    authentication_form = CustomAuthenticationForm

    def get_success_url(self):
        user = self.request.user
        if user.role == 'superadmin':
            return reverse_lazy('superadmin_dashboard')
        elif user.role == 'admin':
            return reverse_lazy('admin_dashboard', kwargs={'gym_id': user.gym.id})
        elif user.role == 'manager':
            return reverse_lazy('manager_dashboard', kwargs={'gym_id': user.gym.id})
        elif user.role == 'cashier':
            return reverse_lazy('cashier_dashboard', kwargs={'gym_id': user.gym.id})
        elif user.role == 'reception':
            return reverse_lazy('reception_dashboard', kwargs={'gym_id': user.gym.id})
        elif user.role == 'member':
            return reverse_lazy('member_dashboard', kwargs={'gym_id': user.gym.id})
        return reverse_lazy('login')
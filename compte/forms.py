# accounts/forms.py
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from .models import User
import random

class CustomAuthenticationForm(AuthenticationForm):

    username = forms.CharField(
        label="Nom d'utilisateur",
        widget=forms.TextInput(attrs={
            'autofocus': True,
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#004e92]'
        })
    )

    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#004e92]'
        })
    )

    error_messages = {
        'invalid_login': "Nom d'utilisateur ou mot de passe incorrect.",
        'inactive': "Ce compte est inactif.",
    }

class StaffCreationForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'role']

    def save(self, commit=True, gym=None):
        user = super().save(commit=False)

        # Générer username
        random_digits = random.randint(1000, 9999)
        username = f"{user.first_name.lower()}{user.last_name.lower()}{random_digits}"

        while User.objects.filter(username=username).exists():
            random_digits = random.randint(1000, 9999)
            username = f"{user.first_name.lower()}{user.last_name.lower()}{random_digits}"

        user.username = username
        user.set_password("12345")
        user.gym = gym

        if commit:
            user.save()

        return user
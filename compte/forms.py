from django import forms
from django.contrib.auth.forms import AuthenticationForm


class CustomAuthenticationForm(AuthenticationForm):

    username = forms.CharField(
        widget=forms.TextInput(attrs={
            "class": "w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#004e92] ",
            "placeholder": "Nom d'utilisateur"
        })
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#004e92]",
            "placeholder": "Mot de passe"
        })
    )
    
    
class CreateUserForm(forms.Form):
    first_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    
    ROLE_CHOICES = (
        ('manager', 'Manager'),
        ('coach', 'Coach'),
        ('reception', 'Réceptionniste'),
        ('cashier', 'Caissier'),
        ('accountant', 'Comptable'),
    )
    role = forms.ChoiceField(choices=ROLE_CHOICES, widget=forms.Select(attrs={'class': 'form-control'}))
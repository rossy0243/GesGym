from django import forms

from coaching.models import CoachSpecialty
from compte.models import UserGymRole
from organizations.models import Gym, Organization


INTERNAL_ROLE_CHOICES = [
    (value, label)
    for value, label in UserGymRole.ROLE_CHOICES
    if value != "owner"
]


class OrganizationSettingsForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "logo", "address", "phone", "email"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "logo": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
        }
        labels = {
            "name": "Nom de l'organisation",
            "logo": "Logo",
            "address": "Adresse",
            "phone": "Telephone",
            "email": "Email",
        }


class InternalEmployeeForm(forms.Form):
    first_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control"}),
        label="Prenom",
    )
    last_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control"}),
        label="Nom",
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
        label="Email",
    )
    gym = forms.ModelChoiceField(
        queryset=Gym.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Gym",
    )
    role = forms.ChoiceField(
        choices=INTERNAL_ROLE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Role",
    )
    is_active = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Actif",
    )

    def __init__(self, *args, organization=None, gyms=None, **kwargs):
        super().__init__(*args, **kwargs)
        if gyms is not None:
            self.fields["gym"].queryset = gyms
        elif organization:
            self.fields["gym"].queryset = organization.gyms.filter(is_active=True).order_by("name")
        else:
            self.fields["gym"].queryset = Gym.objects.none()

    def clean_role(self):
        role = self.cleaned_data["role"]
        if role == "owner":
            raise forms.ValidationError("Impossible de creer un autre Owner depuis les parametres.")
        return role


class CoachSpecialtyForm(forms.ModelForm):
    class Meta:
        model = CoachSpecialty
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex: Musculation, Crossfit, Yoga...",
                }
            )
        }
        labels = {
            "name": "Specialite",
        }

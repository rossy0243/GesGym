from django import forms

from coaching.models import CoachSpecialty
from compte.models import UserGymRole
from core.validators import validate_safe_image_upload
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

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        validate_safe_image_upload(logo)
        return logo


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

    def __init__(
        self,
        *args,
        organization=None,
        gyms=None,
        allowed_roles=None,
        locked_gym=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if gyms is not None:
            self.fields["gym"].queryset = gyms
        elif organization:
            self.fields["gym"].queryset = organization.gyms.filter(is_active=True).order_by("name")
        else:
            self.fields["gym"].queryset = Gym.objects.none()
        self.locked_gym = locked_gym
        if locked_gym is not None:
            self.fields["gym"].queryset = Gym.objects.filter(id=locked_gym.id)
            self.fields["gym"].initial = locked_gym
            self.fields["gym"].widget = forms.HiddenInput()
        if allowed_roles is not None:
            allowed_roles = set(allowed_roles)
            self.fields["role"].choices = [
                (value, label)
                for value, label in INTERNAL_ROLE_CHOICES
                if value in allowed_roles
            ]

    def clean_role(self):
        role = self.cleaned_data["role"]
        if role == "owner":
            raise forms.ValidationError("Impossible de creer un autre Owner depuis les parametres.")
        return role


class InternalEmployeeProfileForm(InternalEmployeeForm):
    def __init__(self, *args, role_instance=None, **kwargs):
        self.role_instance = role_instance
        if role_instance is not None and "initial" not in kwargs:
            kwargs["initial"] = {
                "first_name": role_instance.user.first_name,
                "last_name": role_instance.user.last_name,
                "email": role_instance.user.email,
                "gym": role_instance.gym,
                "role": role_instance.role,
                "is_active": role_instance.is_active and role_instance.user.is_active,
            }
        super().__init__(*args, **kwargs)

    def clean_gym(self):
        gym = self.cleaned_data["gym"]
        if self.role_instance and UserGymRole.objects.filter(
            user=self.role_instance.user,
            gym=gym,
        ).exclude(id=self.role_instance.id).exists():
            raise forms.ValidationError("Cet employe a deja un acces dans cette salle.")
        return gym


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

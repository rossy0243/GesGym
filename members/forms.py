from django import forms
from django.utils import timezone

from .models import Member, MemberPreRegistration


class MemberCreationForm(forms.ModelForm):
    """
    Formulaire de création / modification membre
    """

    class Meta:
        model = Member
        fields = [
            "first_name",
            "last_name",
            "phone",
            "email",
            "address",
            "photo",
        ]

        widgets = {
            "first_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Prénom"
            }),
            "last_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Nom"
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Téléphone"
            }),
            "email": forms.EmailInput(attrs={
                "class": "form-control",
                "placeholder": "Email"
            }),
            "address": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Adresse"
            }),
            "photo": forms.FileInput(attrs={
                "class": "form-control"
            }),
        }


class MemberPreRegistrationForm(forms.ModelForm):
    """
    Formulaire public de preinscription. Le gym est fourni par le lien public
    afin de valider les doublons sans exposer le multi-tenant.
    """

    class Meta:
        model = MemberPreRegistration
        fields = [
            "first_name",
            "last_name",
            "phone",
            "email",
            "address",
        ]
        widgets = {
            "first_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Prenom",
            }),
            "last_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Nom",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Telephone",
            }),
            "email": forms.EmailInput(attrs={
                "class": "form-control",
                "placeholder": "Email",
            }),
            "address": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Adresse",
            }),
        }

    def __init__(self, *args, gym=None, **kwargs):
        self.gym = gym
        super().__init__(*args, **kwargs)

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        if not phone:
            return phone

        if self.gym and Member.objects.filter(gym=self.gym, phone=phone).exists():
            raise forms.ValidationError("Un membre existe deja avec ce telephone.")

        pending_exists = MemberPreRegistration.objects.filter(
            gym=self.gym,
            phone=phone,
            status=MemberPreRegistration.STATUS_PENDING,
            expires_at__gt=timezone.now(),
        ).exists()
        if pending_exists:
            raise forms.ValidationError("Une preinscription active existe deja avec ce telephone.")

        return phone

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        if not email:
            return None

        if self.gym and Member.objects.filter(gym=self.gym, email=email).exists():
            raise forms.ValidationError("Un membre existe deja avec cet email.")

        pending_exists = MemberPreRegistration.objects.filter(
            gym=self.gym,
            email=email,
            status=MemberPreRegistration.STATUS_PENDING,
            expires_at__gt=timezone.now(),
        ).exists()
        if pending_exists:
            raise forms.ValidationError("Une preinscription active existe deja avec cet email.")

        return email

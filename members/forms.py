from django import forms
from django.utils import timezone

from core.validators import validate_safe_image_upload

from .models import Member, MemberGoal, MemberPreRegistration, MemberWeightMeasurement


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

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        validate_safe_image_upload(photo)
        return photo


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
        self.fields["phone"].required = True
        self.fields["email"].required = True
        self.fields["phone"].widget.attrs["required"] = "required"
        self.fields["email"].widget.attrs["required"] = "required"

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
            raise forms.ValidationError("L'email est obligatoire.")

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


class MemberGoalForm(forms.ModelForm):
    class Meta:
        model = MemberGoal
        fields = [
            "goal_type",
            "target_weight",
            "target_date",
            "measurement_starter",
            "note",
        ]
        widgets = {
            "goal_type": forms.Select(attrs={"class": "form-control"}),
            "target_weight": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.1",
                    "min": "1",
                    "placeholder": "Ex: 78.5",
                }
            ),
            "target_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "measurement_starter": forms.Select(attrs={"class": "form-control"}),
            "note": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Ex: prise de masse propre avant aout",
                }
            ),
        }
        labels = {
            "goal_type": "Type d'objectif",
            "target_weight": "Poids cible (kg)",
            "target_date": "Date cible",
            "measurement_starter": "Qui commence les releves ?",
            "note": "Note",
        }


class MemberWeightMeasurementForm(forms.ModelForm):
    class Meta:
        model = MemberWeightMeasurement
        fields = ["weight", "measured_at", "note"]
        widgets = {
            "weight": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.1",
                    "min": "1",
                    "placeholder": "Ex: 82.4",
                }
            ),
            "measured_at": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "note": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": "Commentaire optionnel sur la pesee",
                }
            ),
        }
        labels = {
            "weight": "Poids releve (kg)",
            "measured_at": "Date de mesure",
            "note": "Commentaire",
        }

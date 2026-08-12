from datetime import timedelta

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

        # Repris dans les messages d'erreur affiches a l'utilisateur.
        labels = {
            "first_name": "Prenom",
            "last_name": "Nom",
            "phone": "Telephone",
            "email": "E-mail",
            "address": "Adresse",
            "photo": "Photo",
        }

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

    def __init__(self, *args, gym=None, **kwargs):
        # La salle n'est pas un champ du formulaire : sans elle, Django ne peut
        # pas verifier les contraintes d'unicite (gym, telephone) et
        # (gym, email), et la base rejetait l'ecriture par une erreur 500.
        self.gym = gym
        super().__init__(*args, **kwargs)

    def _duplicate_exists(self, field_name, value):
        if not value or self.gym is None:
            return False

        others = Member.objects.filter(gym=self.gym, **{field_name: value})
        if self.instance and self.instance.pk:
            others = others.exclude(pk=self.instance.pk)
        return others.exists()

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        if self._duplicate_exists("phone", phone):
            raise forms.ValidationError(
                "Un membre de cette salle utilise deja ce numero de telephone."
            )
        return phone

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        if not email:
            # Stocker None plutot qu'une chaine vide : deux membres sans email
            # violeraient sinon la contrainte d'unicite (gym, email).
            return None
        if self._duplicate_exists("email", email):
            raise forms.ValidationError(
                "Un membre de cette salle utilise deja cette adresse e-mail."
            )
        return email

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

    # Nombre de demandes tolerees par heure. Le formulaire etant public, il
    # faut empecher qu'un robot noie la liste des prospects.
    MAX_PER_IP_PER_HOUR = 3
    MAX_PER_LINK_PER_HOUR = 30

    RATE_LIMIT_MESSAGE = (
        "Trop de demandes envoyees depuis cet appareil. "
        "Merci de reessayer dans une heure ou de contacter la salle directement."
    )
    LINK_SATURATED_MESSAGE = (
        "Ce formulaire recoit trop de demandes en ce moment. "
        "Merci de reessayer plus tard ou de contacter la salle directement."
    )

    # Champ piege : invisible pour un humain, souvent rempli par les robots.
    website = forms.CharField(
        required=False,
        label="",
        widget=forms.TextInput(attrs={
            "autocomplete": "off",
            "tabindex": "-1",
            "aria-hidden": "true",
        }),
    )

    def __init__(self, *args, gym=None, link=None, ip_address=None, **kwargs):
        self.gym = gym
        self.link = link
        self.ip_address = ip_address
        super().__init__(*args, **kwargs)
        self.fields["phone"].required = True
        self.fields["email"].required = True
        self.fields["phone"].widget.attrs["required"] = "required"
        self.fields["email"].widget.attrs["required"] = "required"

    def clean_website(self):
        # Un humain ne voit pas ce champ : s'il est rempli, c'est un robot.
        if (self.cleaned_data.get("website") or "").strip():
            raise forms.ValidationError("Envoi refuse.")
        return ""

    def clean(self):
        cleaned = super().clean()
        self._check_rate_limits()
        return cleaned

    def _check_rate_limits(self):
        since = timezone.now() - timedelta(hours=1)

        if self.ip_address:
            recent_from_ip = MemberPreRegistration.objects.filter(
                ip_address=self.ip_address,
                created_at__gte=since,
            ).count()
            if recent_from_ip >= self.MAX_PER_IP_PER_HOUR:
                raise forms.ValidationError(self.RATE_LIMIT_MESSAGE)

        if self.link is not None:
            recent_for_link = MemberPreRegistration.objects.filter(
                link=self.link,
                created_at__gte=since,
            ).count()
            if recent_for_link >= self.MAX_PER_LINK_PER_HOUR:
                raise forms.ValidationError(self.LINK_SATURATED_MESSAGE)

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

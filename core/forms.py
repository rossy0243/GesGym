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
    """
    Identite de l'organisation, reprise sur le site vitrine.

    Ces coordonnees alimentent le pied de page public et la destination du
    formulaire de contact : elles etaient ecrites en dur dans le gabarit, avec
    des mentions "a confirmer" que les visiteurs pouvaient lire.
    """

    class Meta:
        model = Organization
        fields = [
            "name",
            "logo",
            "address",
            "phone",
            "email",
            "city",
            "whatsapp_number",
            "opening_hours",
            "footer_services",
            "facebook_url",
            "instagram_url",
            "tiktok_url",
            "landing_kicker",
            "landing_title",
            "landing_intro",
            "seo_description",
            "seo_keywords",
            "landing_hero_image",
            "landing_image_1",
            "landing_image_2",
            "landing_image_3",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "logo": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "whatsapp_number": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "243810000000",
            }),
            "opening_hours": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Lundi au samedi : 06h - 21h\nDimanche : ferme",
            }),
            "footer_services": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Musculation\nCardio-training\nCours collectifs\nCoaching personnel",
            }),
            "facebook_url": forms.URLInput(attrs={
                "class": "form-control",
                "placeholder": "https://facebook.com/...",
            }),
            "instagram_url": forms.URLInput(attrs={
                "class": "form-control",
                "placeholder": "https://instagram.com/...",
            }),
            "tiktok_url": forms.URLInput(attrs={
                "class": "form-control",
                "placeholder": "https://tiktok.com/@...",
            }),
            "city": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Kinshasa",
            }),
            "landing_kicker": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Salle de sport premium a Kinshasa",
            }),
            "landing_title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Entrainez-vous comme un roi",
            }),
            "landing_intro": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Musculation, cardio-training, cours collectifs...",
            }),
            "seo_description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Environ 160 caracteres.",
            }),
            "seo_keywords": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "salle de sport Kinshasa, musculation, fitness",
            }),
            "landing_hero_image": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "landing_image_1": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "landing_image_2": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "landing_image_3": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }
        labels = {
            "name": "Nom de l'organisation",
            "logo": "Logo",
            "address": "Adresse",
            "phone": "Telephone",
            "email": "Email",
            "whatsapp_number": "Numero WhatsApp",
            "opening_hours": "Horaires affiches sur le site public",
            "footer_services": "Services listes en pied de page",
            "facebook_url": "Page Facebook",
            "instagram_url": "Compte Instagram",
            "tiktok_url": "Compte TikTok",
            "city": "Ville",
            "landing_kicker": "Petite accroche",
            "landing_title": "Titre principal",
            "landing_intro": "Phrase d'introduction",
            "seo_description": "Description pour les moteurs de recherche",
            "seo_keywords": "Mots-cles",
            "landing_hero_image": "Photo principale",
            "landing_image_1": "Photo espace 1",
            "landing_image_2": "Photo espace 2",
            "landing_image_3": "Photo espace 3",
        }
        help_texts = {
            "address": "Affichee dans le pied de page du site public.",
            "phone": "Affiche dans le pied de page du site public.",
            "email": "Affiche en pied de page, et destinataire du formulaire de contact.",
            "whatsapp_number": "Indicatif et numero, sans + ni espaces. Ex : 243810000000",
            "opening_hours": "Affiches dans le bloc \"Horaires & localisation\" de la page d'accueil.",
            "footer_services": "Un service par ligne. Laisser vide pour la liste par defaut.",
            "city": "Reprise dans les accroches et la fiche etablissement.",
            "landing_kicker": "Petit texte au-dessus du titre. Sert aussi de sous-titre a l'onglet.",
            "landing_title": "Affiche sous le nom de l'organisation.",
            "landing_intro": "Le paragraphe sous le titre principal.",
            "seo_description": "Environ 160 caracteres. Reprise lors d'un partage sur les reseaux.",
            "seo_keywords": "Separes par des virgules.",
            "landing_hero_image": "Grande photo a droite du titre.",
            "landing_image_1": "Vignette de la section \"Nos espaces\".",
            "landing_image_2": "Vignette de la section \"Nos espaces\".",
            "landing_image_3": "Vignette de la section \"Nos espaces\".",
        }

    # Toute image televersee passe par le meme controle que le logo : un
    # fichier deguise en image reste un fichier execute par le serveur.
    def clean_logo(self):
        return self._image_verifiee("logo")

    def clean_landing_hero_image(self):
        return self._image_verifiee("landing_hero_image")

    def clean_landing_image_1(self):
        return self._image_verifiee("landing_image_1")

    def clean_landing_image_2(self):
        return self._image_verifiee("landing_image_2")

    def clean_landing_image_3(self):
        return self._image_verifiee("landing_image_3")

    def _image_verifiee(self, nom):
        image = self.cleaned_data.get(nom)
        validate_safe_image_upload(image)
        return image

    def clean_whatsapp_number(self):
        # wa.me n'accepte que des chiffres : un "+" ou des espaces produisent
        # un lien mort, et rien ne le signale au visiteur.
        brut = (self.cleaned_data.get("whatsapp_number") or "").strip()
        if not brut:
            return ""

        chiffres = "".join(c for c in brut if c.isdigit())
        if len(chiffres) < 8:
            raise forms.ValidationError(
                "Numero WhatsApp incomplet : indiquez l'indicatif et le numero, "
                "par exemple 243810000000."
            )
        return chiffres


class GymContactForm(forms.ModelForm):
    """
    Coordonnees de la salle, telles que le membre les verra.

    Une organisation peut exploiter plusieurs sites : l'adresse du siege
    envoie a la mauvaise porte un membre inscrit ailleurs. Les champs laisses
    vides retombent sur les coordonnees de l'organisation.
    """

    class Meta:
        model = Gym
        fields = ["address", "phone", "email", "opening_hours"]
        widgets = {
            "address": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Ex : 12 avenue de la Justice, Gombe, Kinshasa",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ex : +243 81 000 00 00",
            }),
            "email": forms.EmailInput(attrs={
                "class": "form-control",
                "placeholder": "Ex : kinshasa@royalgym.cd",
            }),
            "opening_hours": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Lundi au vendredi : 06h - 21h\nSamedi : 08h - 18h\nDimanche : ferme",
            }),
        }
        labels = {
            "address": "Adresse",
            "phone": "Telephone",
            "email": "E-mail",
            "opening_hours": "Horaires d'ouverture",
        }
        help_texts = {
            "address": "Laisser vide pour reprendre l'adresse de l'organisation.",
            "phone": "Laisser vide pour reprendre le telephone de l'organisation.",
            "email": "Laisser vide pour reprendre l'e-mail de l'organisation.",
            "opening_hours": "Texte libre, une ligne par plage. Propre a cette salle.",
        }

    def clean_phone(self):
        return (self.cleaned_data.get("phone") or "").strip()

    def clean_address(self):
        return (self.cleaned_data.get("address") or "").strip()

    def clean_opening_hours(self):
        return (self.cleaned_data.get("opening_hours") or "").strip()


class GymMaintenanceSettingsForm(forms.ModelForm):
    """
    Delai de prevenance des maintenances, propre a chaque salle.

    Une salle qui commande ses pieces a l'etranger a besoin de plus d'avance
    qu'une salle servie par un atelier voisin : le delai ne peut pas etre fige
    dans le code.
    """

    class Meta:
        model = Gym
        fields = ["maintenance_alert_lead_days"]
        widgets = {
            "maintenance_alert_lead_days": forms.NumberInput(attrs={
                "class": "form-control",
                "min": "1",
                "max": "365",
            }),
        }
        labels = {
            "maintenance_alert_lead_days": "Prevenir combien de jours a l'avance",
        }

    def clean_maintenance_alert_lead_days(self):
        jours = self.cleaned_data.get("maintenance_alert_lead_days")
        if jours is None or jours < 1:
            raise forms.ValidationError("Le delai doit valoir au moins un jour.")
        if jours > 365:
            raise forms.ValidationError("Un delai de plus d'un an n'a pas de sens.")
        return jours


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
        self.allowed_roles = set(allowed_roles) if allowed_roles is not None else None
        if self.allowed_roles is not None:
            self.fields["role"].choices = [
                (value, label)
                for value, label in INTERNAL_ROLE_CHOICES
                if value in self.allowed_roles
            ]
            # Sans ce message, forcer un role interdit renvoyait la phrase brute
            # de Django (« Selectionnez un choix valide. manager n'en fait pas
            # partie. »), qui ressemble a une panne plutot qu'a une regle.
            self.fields["role"].error_messages["invalid_choice"] = (
                "Vous ne pouvez pas attribuer ce role. Votre niveau d'acces permet "
                "d'affecter : %(roles)s."
            ) % {"roles": self._readable_roles()}

    def _readable_roles(self):
        labels = dict(INTERNAL_ROLE_CHOICES)
        return ", ".join(
            str(labels.get(value, value))
            for value, _ in INTERNAL_ROLE_CHOICES
            if self.allowed_roles is None or value in self.allowed_roles
        )

    def clean_role(self):
        role = self.cleaned_data["role"]
        if role == "owner":
            raise forms.ValidationError(
                "Seul un proprietaire peut exister par organisation : ce role ne "
                "s'attribue pas depuis les parametres."
            )
        if self.allowed_roles is not None and role not in self.allowed_roles:
            raise forms.ValidationError(
                "Vous ne pouvez pas attribuer ce role. Votre niveau d'acces permet "
                f"d'affecter : {self._readable_roles()}."
            )
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

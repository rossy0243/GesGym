# organizations/models.py
from django.db import models
# Create your models here.
class Organization(models.Model):
    """
    Représente une entreprise cliente du SaaS.
    Une organisation peut posséder plusieurs gyms.
    """

    PACK_CLUB = "club"
    PACK_PREMIUM = "premium"
    PACK_CHOICES = (
        (PACK_CLUB, "Pack Club"),
        (PACK_PREMIUM, "Pack Premium"),
    )

    name = models.CharField(max_length=255)

    slug = models.SlugField(unique=True)

    logo = models.ImageField(
        upload_to="organizations/logos/",
        blank=True,
        null=True
    )

    address = models.TextField(blank=True, null=True)

    phone = models.CharField(max_length=30, blank=True, null=True)

    email = models.EmailField(blank=True, null=True)

    # --- Ce que le public lit sur le site vitrine --------------------------
    # Ces informations etaient ecrites en dur dans le gabarit, avec des
    # marqueurs "a confirmer" visibles par les visiteurs. Elles appartiennent
    # a l'organisation : elle doit pouvoir les corriger sans toucher au code.

    whatsapp_number = models.CharField(
        max_length=20,
        blank=True,
        default="",
        verbose_name="Numero WhatsApp",
        help_text="Indicatif et numero, sans + ni espaces. Ex : 243810000000",
    )

    facebook_url = models.URLField(blank=True, default="", verbose_name="Page Facebook")

    instagram_url = models.URLField(blank=True, default="", verbose_name="Compte Instagram")

    tiktok_url = models.URLField(blank=True, default="", verbose_name="Compte TikTok")

    footer_services = models.TextField(
        blank=True,
        default="",
        verbose_name="Services listes en pied de page",
        help_text="Un service par ligne. Ex : Musculation",
    )

    opening_hours = models.TextField(
        blank=True,
        default="",
        verbose_name="Horaires affiches sur le site public",
        help_text="Texte libre. Ex : Lundi au samedi, 06h - 21h",
    )

    subscription_pack = models.CharField(
        max_length=20,
        choices=PACK_CHOICES,
        default=PACK_PREMIUM,
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["slug"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def services_list(self):
        """Services du pied de page, une entree par ligne non vide."""
        return [
            ligne.strip()
            for ligne in (self.footer_services or "").splitlines()
            if ligne.strip()
        ]

    @property
    def whatsapp_url(self):
        """Lien wa.me, ou chaine vide si aucun numero n'est declare."""
        numero = "".join(c for c in (self.whatsapp_number or "") if c.isdigit())
        return f"https://wa.me/{numero}" if numero else ""

    @property
    def social_links(self):
        """Reseaux renseignes, prets a afficher : (libelle, icone, url)."""
        candidats = (
            ("WhatsApp", "fab fa-whatsapp", self.whatsapp_url),
            ("Facebook", "fab fa-facebook", (self.facebook_url or "").strip()),
            ("Instagram", "fab fa-instagram", (self.instagram_url or "").strip()),
            ("TikTok", "fab fa-tiktok", (self.tiktok_url or "").strip()),
        )
        return [
            {"label": libelle, "icon": icone, "url": url}
            for libelle, icone, url in candidats
            if url
        ]


class SensitiveActivityLog(models.Model):
    """
    Journal des actions sensibles visibles par le proprietaire de l'organisation.
    """

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="sensitive_logs",
        db_index=True,
    )

    gym = models.ForeignKey(
        "Gym",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sensitive_logs",
    )

    actor = models.ForeignKey(
        "compte.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sensitive_actions",
    )

    action = models.CharField(max_length=120)

    target_type = models.CharField(max_length=80, blank=True)

    target_label = models.CharField(max_length=255, blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "created_at"]),
            models.Index(fields=["gym", "created_at"]),
            models.Index(fields=["actor", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} - {self.target_label or self.organization}"
    
class Module(models.Model):
    """
    Modules activables du SaaS.
    Exemple : POS, STOCK, COACHING
    """

    code = models.CharField(max_length=50, unique=True, db_index=True)

    name = models.CharField(max_length=255)

    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"
    
class Gym(models.Model):
    """
    Une salle de sport appartenant à une organisation.
    Toutes les données métier seront liées au Gym.
    """

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="gyms"
    )

    name = models.CharField(max_length=255)

    slug = models.SlugField()

    subdomain = models.CharField(
        max_length=100,
        unique=True
    )

    custom_domain = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    is_active = models.BooleanField(default=True)

    # Coordonnees propres a la salle. Une organisation peut exploiter
    # plusieurs sites : afficher l'adresse du siege a un membre inscrit
    # ailleurs l'envoie a la mauvaise porte. Vide, on retombe sur celles de
    # l'organisation, qui restent le point de contact par defaut.
    address = models.TextField(
        blank=True,
        default="",
        verbose_name="Adresse de la salle",
    )

    phone = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="Telephone de la salle",
    )

    email = models.EmailField(
        blank=True,
        default="",
        verbose_name="E-mail de la salle",
    )

    opening_hours = models.TextField(
        blank=True,
        default="",
        verbose_name="Horaires d'ouverture",
        help_text="Texte libre, une ligne par plage. Ex : Lundi au vendredi 06h - 21h",
    )

    # Combien de jours a l'avance signaler une maintenance a venir. Deux
    # semaines laissent le temps de commander une piece ou de reserver un
    # technicien avant que la machine ne soit immobilisee.
    MAINTENANCE_ALERT_DEFAULT_DAYS = 14

    maintenance_alert_lead_days = models.PositiveIntegerField(
        default=MAINTENANCE_ALERT_DEFAULT_DAYS,
        verbose_name="Prevenance maintenance (jours)",
        help_text="Nombre de jours avant l'echeance ou l'alerte apparait.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("organization", "slug")
        indexes = [
            models.Index(fields=["organization"]),
            models.Index(fields=["subdomain"]),
            models.Index(fields=["organization", "created_at"])
        ]

    def __str__(self):
        return self.name

    # --- Coordonnees a montrer au membre -----------------------------------
    # La salle prime sur l'organisation : c'est la porte que le membre pousse.
    # Sans coordonnee propre, celles de l'organisation valent mieux que rien.

    def _repli(self, valeur, champ_organisation):
        propre = (valeur or "").strip()
        if propre:
            return propre
        return (getattr(self.organization, champ_organisation, "") or "").strip()

    @property
    def contact_address(self):
        return self._repli(self.address, "address")

    @property
    def contact_phone(self):
        return self._repli(self.phone, "phone")

    @property
    def contact_email(self):
        return self._repli(self.email, "email")

    @property
    def contact_hours(self):
        """Horaires propres a la salle : l'organisation n'en porte pas."""
        return (self.opening_hours or "").strip()

    @property
    def has_public_contact(self):
        """Vrai des qu'une coordonnee est affichable au membre."""
        return any(
            (
                self.contact_address,
                self.contact_phone,
                self.contact_email,
                self.contact_hours,
            )
        )


class GymModule(models.Model):
    """
    Permet d'activer un module pour un gym spécifique.
    """

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="modules"
    )

    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name="gym_modules"
    )

    is_active = models.BooleanField(default=True)

    activated_at = models.DateTimeField(auto_now_add=True)

    class Meta:

        unique_together = ("gym", "module")

        indexes = [
            models.Index(fields=["gym"]),
            models.Index(fields=["gym", "is_active"])
        ]

    def __str__(self):
        return f"{self.gym} - {self.module}"

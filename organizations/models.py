# organizations/models.py
from django.db import models
# Create your models here.
class Organization(models.Model):
    """
    Représente une entreprise cliente du SaaS.
    Une organisation peut posséder plusieurs gyms.
    """

    name = models.CharField(max_length=255)

    slug = models.SlugField(unique=True)

    logo = models.ImageField(
        upload_to="organizations/logos/",
        blank=True,
        null=True
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
        return self.name
    
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

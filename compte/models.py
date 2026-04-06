#compte/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from organizations.models import Gym, Organization
from smartclub import settings
from .utils import generate_username
from django.contrib.auth.hashers import make_password


class User(AbstractUser):
    """
    Utilisateur du système SMARTCLUB.
    Le rôle et le gym sont gérés dans le modèle UserGymRole
    afin de permettre plusieurs rôles par utilisateur.
    """

    is_saas_admin = models.BooleanField(
        default=False,
        help_text="Administrateur global du SaaS"
    )
    owned_organization = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owners",
        help_text="Si l'utilisateur est Owner d'une organisation"
    )
    def get_owned_gyms(self):
        """Récupère tous les gyms de l'organisation dont il est Owner"""
        if self.owned_organization:
            return self.owned_organization.gyms.filter(is_active=True)
        return Gym.objects.none()
    def is_owner(self):
        """Vérifie si l'utilisateur est un Owner"""
        return self.owned_organization is not None
    def clean(self):
        super().clean()
        # Empêcher qu'un utilisateur non superuser se donne is_saas_admin
        if self.is_saas_admin and not self.pk:
            # À la création, seul un superuser peut créer un saas_admin
            pass
    def save(self, *args, **kwargs):

        # Générer username automatiquement si vide
        if not self.username:
            self.username = generate_username(
                self.first_name,
                self.last_name
            )

        # Mot de passe par défaut si vide
        if not self.password:
            self.password = make_password("12345")

        super().save(*args, **kwargs)

    def __str__(self):
        return self.username
    
class UserGymRole(models.Model):
    """
    Assigne un rôle à un utilisateur dans un gym
    """

    ROLE_CHOICES = (
        ("owner", "Owner"),
        ("manager", "Manager"),
        ("coach", "Coach"),
        ("reception", "Receptionist"),
        ("cashier", "Cashier"),
        ("accountant", "Accountant"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gym_roles"
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="user_roles"
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "gym")

        indexes = [
            models.Index(fields=["gym"]),
            models.Index(fields=["user"]),
            models.Index(fields=["user", "gym"])
        ]

    def __str__(self):
        return f"{self.user} - {self.role} ({self.gym})"
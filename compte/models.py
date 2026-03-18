from django.contrib.auth.models import AbstractUser
from django.db import models
from .models_roles import UserGymRole

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

    def __str__(self):
        return self.username
from django.db import models
from django.conf import settings
from organizations.models.gym import Gym


class UserGymRole(models.Model):
    """
    Associe un utilisateur à un gym avec un rôle spécifique.
    """

    ROLE_CHOICES = (
        ("owner", "Propriétaire"),
        ("manager", "Manager"),
        ("coach", "Coach"),
        ("receptionist", "Agent Accueil"),
        ("accountant", "Comptable"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gym_roles"
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="staff"
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:

        unique_together = ("user", "gym", "role")

        indexes = [
            models.Index(fields=["gym"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.role} - {self.gym}"
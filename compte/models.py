# compte/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from core.models import Gym

class User(AbstractUser):
    ROLE_CHOICES = (
        ("superadmin", "Super Admin SaaS"),
        ("admin", "Propriétaire Salle"),
        ("manager", "Gérant"),
        ("cashier", "Caissier"),
        ("reception", "Agent Accueil"),
        ("member", "Member Client"),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f"{self.username} ({self.role})"
    


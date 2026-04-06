from django.db import models
from members.models import Member
from organizations.models import Gym



class Coach(models.Model):
    """
    Coach du gym (version simple V1)
    """

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="coaches",
        db_index=True
    )

    name = models.CharField(max_length=255)

    phone = models.CharField(max_length=20, blank=True, null=True)

    specialty = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )
    # RELATION COACH ↔ MEMBERS
    members = models.ManyToManyField(
        Member,
        related_name="coaches",
        blank=True
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["gym"]),
        ]

    def __str__(self):
        return self.name
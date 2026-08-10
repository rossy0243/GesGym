import uuid

from django.db import models
from organizations.models import Gym
from members.models import Member
from django.core.exceptions import ValidationError


class AccessDevice(models.Model):
    """
    Lecteur physique de controle d'acces (borne QR / badge) rattache a un gym.

    Le lecteur pousse ses evenements de scan vers l'endpoint webhook identifie
    par ``webhook_token``; l'application repond en autorisant ou refusant.
    """

    BRAND_HIKVISION = "hikvision"
    BRAND_CHOICES = [
        (BRAND_HIKVISION, "Hikvision (ISAPI)"),
    ]

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="access_devices",
        db_index=True,
    )

    name = models.CharField(max_length=100)

    brand = models.CharField(
        max_length=30,
        choices=BRAND_CHOICES,
        default=BRAND_HIKVISION,
    )

    host = models.GenericIPAddressField(protocol="IPv4")
    port = models.PositiveIntegerField(default=80)
    use_https = models.BooleanField(default=False)

    username = models.CharField(max_length=64, default="admin")
    # Stocke en clair : le lecteur exige les identifiants a chaque appel ISAPI.
    # A n'exposer ni dans l'admin en liste, ni dans les reponses JSON.
    password = models.CharField(max_length=128, blank=True)

    door_number = models.PositiveSmallIntegerField(default=1)

    open_on_granted = models.BooleanField(
        default=True,
        verbose_name="Ouvrir la porte sur acces autorise",
        help_text=(
            "Declenche le relais de ce lecteur quand un QR code valide est "
            "reconnu par l'application."
        ),
    )

    # Renseignes automatiquement lors du test de connexion.
    model_name = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)
    firmware = models.CharField(max_length=100, blank=True)
    mac_address = models.CharField(max_length=32, blank=True)

    webhook_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    is_active = models.BooleanField(default=True)

    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lecteur d'acces"
        verbose_name_plural = "Lecteurs d'acces"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["gym", "host"],
                name="unique_access_device_host_per_gym",
            ),
        ]
        indexes = [
            models.Index(fields=["gym", "is_active"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.host})"

    @property
    def is_online(self):
        return bool(self.last_seen_at) and not self.last_error


class AccessLog(models.Model):
    """
    Historique des accès des membres (scan QR, entrée gym).
    """

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="access_logs",
        db_index=True
    )

    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="access_logs"
    )

    check_in_time = models.DateTimeField(auto_now_add=True)

    access_granted = models.BooleanField(default=True)

    device_used = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    device = models.ForeignKey(
        "access.AccessDevice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="access_logs",
    )

    denial_reason = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    scanned_by = models.ForeignKey(
        "compte.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="access_scans"
    )

    class Meta:

        indexes = [
            models.Index(fields=["gym"]),
            models.Index(fields=["member"]),
            models.Index(fields=["check_in_time"]),
            models.Index(fields=["member", "check_in_time"]),
        ]

        ordering = ["-check_in_time"]

    def clean(self):
        if self.member_id and not self.gym_id:
            self.gym = self.member.gym

        if self.member_id and self.gym_id and self.member.gym_id != self.gym_id:
            raise ValidationError("Le membre n'appartient pas a ce gym.")

    def save(self, *args, **kwargs):
        if self.member_id and not self.gym_id:
            self.gym = self.member.gym
        self.full_clean()
        return super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.member} - {self.check_in_time}"

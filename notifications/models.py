from django.core.exceptions import ValidationError
from django.db import models

from members.models import Member
from organizations.models import Gym


class Notification(models.Model):
    """
    Notifications envoyees aux membres.
    La V1 utilise le canal in-app; SMS, Email et WhatsApp restent disponibles
    pour les integrations futures.
    """

    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
    )

    CHANNEL_IN_APP = "in_app"
    CHANNEL_SMS = "sms"
    CHANNEL_WHATSAPP = "whatsapp"
    CHANNEL_EMAIL = "email"

    CHANNEL_CHOICES = (
        (CHANNEL_IN_APP, "In-app"),
        (CHANNEL_SMS, "SMS"),
        (CHANNEL_WHATSAPP, "WhatsApp"),
        (CHANNEL_EMAIL, "Email"),
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
    )

    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    title = models.CharField(max_length=120, blank=True)

    message = models.TextField()

    channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    sent_at = models.DateTimeField(null=True, blank=True)

    read_at = models.DateTimeField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)

    sent_by = models.ForeignKey(
        "compte.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_notifications",
    )

    error_message = models.TextField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["gym"]),
            models.Index(fields=["member"]),
            models.Index(fields=["status"]),
            models.Index(fields=["gym", "status"]),
            models.Index(fields=["gym", "member", "read_at"]),
            models.Index(fields=["created_at"]),
        ]
        ordering = ["-created_at"]

    def clean(self):
        if self.member_id and self.gym_id and self.member.gym_id != self.gym_id:
            raise ValidationError("Le membre n'appartient pas a ce gym.")

    @property
    def is_read(self):
        return self.read_at is not None

    def __str__(self):
        return f"{self.member} - {self.channel}"

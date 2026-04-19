from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import uuid
from organizations.models import Gym
from core.managers import GymManager


def default_pre_registration_expiry():
    return timezone.now() + timedelta(days=7)


class Member(models.Model):
    """
    Représente un membre d’un gym.
    Toutes les données sont isolées par gym (multi-tenant).
    """

    STATUS_CHOICES = (
        ("active", "Active"),
        ("expired", "Expired"),
        ("suspended", "Suspended"),
    )

    # 🔐 Multi-tenant obligatoire
    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="members",
        db_index=True
    )

    # 🔐 Manager sécurisé
    objects = GymManager()

    # lien optionnel avec User
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="member_profile",
        null=True,
        blank=True
    )

    # QR code (SANS IMAGE STOCKÉE)
    qr_code = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True
    )

    # infos personnelles
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    photo = models.ImageField(
        upload_to="members/",
        blank=True,
        null=True
    )
    

    coach_notes = models.TextField(
        blank=True,
        null=True
    )
    address = models.TextField(blank=True, null=True)

    phone = models.CharField(max_length=20, db_index=True)

    email = models.EmailField(blank=True, null=True, db_index=True)
    
    is_active = models.BooleanField(default=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    
    @property
    def active_subscription(self):
        return self.subscriptions.filter(
            is_active=True
        ).select_related("plan").first()

    @property
    def expiration_date(self):
        sub = self.active_subscription
        return sub.end_date if sub else None

    @property
    def subscription_type(self):
        sub = self.active_subscription
        return sub.plan.name if sub else "Aucun"

    @property
    def last_access(self):
        log = self.access_logs.order_by("-check_in_time").first()
        return log.check_in_time if log else None

    @property
    def computed_status(self):
        if self.status == "suspended":
            return "suspended"

        today = timezone.now().date()

        active_subscription = self.subscriptions.filter(
            end_date__gte=today,
            is_active=True
        ).exists()

        if active_subscription:
            return "active"

        return "expired"

    @property
    def days_remaining(self):
        if not self.expiration_date:
            return None

        return (self.expiration_date - timezone.now().date()).days

    def get_qr_data(self):
        """Données qui seront encodées dans le QR Code"""
        return str(self.qr_code)
    
    class Meta:
        unique_together = ("gym", "qr_code"), ("gym", "phone"), ("gym", "email")
        indexes = [

            # 🔥 performance multi-tenant
            models.Index(fields=["gym"]),

            models.Index(fields=["gym", "status"]),

            models.Index(fields=["gym", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        gym_name = self.gym.name if self.gym_id else "Sans gym"
        return f"{self.first_name} {self.last_name} - {gym_name}"


class MemberPreRegistrationLink(models.Model):
    """
    Lien public permanent de preinscription pour une salle precise.
    Les demandes creees via ce lien expirent separement apres 7 jours.
    """

    gym = models.OneToOneField(
        Gym,
        on_delete=models.CASCADE,
        related_name="member_pre_registration_link",
    )

    token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["gym", "is_active"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Lien preinscription - {self.gym}"


class MemberPreRegistration(models.Model):
    """
    Demande de preinscription publique. Elle ne devient un vrai membre
    qu'apres confirmation interne par un Owner ou Manager du gym.
    """

    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = (
        (STATUS_PENDING, "En attente"),
        (STATUS_CONFIRMED, "Confirmee"),
        (STATUS_CANCELLED, "Annulee"),
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="member_pre_registrations",
        db_index=True,
    )

    link = models.ForeignKey(
        MemberPreRegistrationLink,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pre_registrations",
    )

    member = models.OneToOneField(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pre_registration",
    )

    token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
    )

    first_name = models.CharField(max_length=100)

    last_name = models.CharField(max_length=100)

    phone = models.CharField(max_length=20, db_index=True)

    email = models.EmailField(blank=True, null=True, db_index=True)

    address = models.TextField(blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    expires_at = models.DateTimeField(default=default_pre_registration_expiry)

    confirmed_at = models.DateTimeField(blank=True, null=True)

    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_member_pre_registrations",
    )

    objects = GymManager()

    class Meta:
        indexes = [
            models.Index(fields=["gym", "status"]),
            models.Index(fields=["gym", "expires_at"]),
            models.Index(fields=["status", "expires_at"]),
            models.Index(fields=["gym", "phone"]),
            models.Index(fields=["gym", "email"]),
        ]
        ordering = ["-created_at"]

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_expired(self):
        return self.status == self.STATUS_PENDING and self.expires_at <= timezone.now()

    @classmethod
    def delete_expired_pending(cls):
        return cls.objects.filter(
            status=cls.STATUS_PENDING,
            expires_at__lte=timezone.now(),
        ).delete()

    def confirm(self, confirmed_by):
        if self.is_expired:
            raise ValueError("Cette preinscription a expire.")
        if self.status != self.STATUS_PENDING:
            raise ValueError("Cette preinscription n'est plus en attente.")

        member = Member.objects.create(
            gym=self.gym,
            first_name=self.first_name,
            last_name=self.last_name,
            phone=self.phone,
            email=self.email,
            address=self.address,
        )

        self.member = member
        self.status = self.STATUS_CONFIRMED
        self.confirmed_at = timezone.now()
        self.confirmed_by = confirmed_by
        self.save(update_fields=["member", "status", "confirmed_at", "confirmed_by"])
        return member

    def __str__(self):
        return f"{self.full_name} - {self.gym}"



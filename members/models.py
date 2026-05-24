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

    def _current_subscription_queryset(self):
        today = timezone.localdate()
        return self.subscriptions.filter(
            is_active=True,
            is_paused=False,
            start_date__lte=today,
            end_date__gte=today,
        ).select_related("plan")

    def _latest_active_subscription_queryset(self):
        return self.subscriptions.filter(
            is_active=True
        ).select_related("plan")
    
    @property
    def active_subscription(self):
        return self._current_subscription_queryset().first()

    @property
    def latest_active_subscription(self):
        return self._latest_active_subscription_queryset().first()

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

        if self._current_subscription_queryset().exists():
            return "active"

        return "expired"

    @property
    def days_remaining(self):
        if not self.expiration_date:
            return None

        return (self.expiration_date - timezone.now().date()).days

    @property
    def has_coaching_access(self):
        subscription = self.active_subscription
        return bool(
            self.is_active
            and subscription
            and subscription.plan
            and (
                subscription.plan.allows_individual_coaching
                or subscription.plan.allows_group_coaching
            )
        )

    @property
    def has_individual_coaching_access(self):
        subscription = self.active_subscription
        return bool(
            self.is_active
            and subscription
            and subscription.plan
            and subscription.plan.allows_individual_coaching
        )

    @property
    def has_group_coaching_access(self):
        subscription = self.active_subscription
        return bool(
            self.is_active
            and subscription
            and subscription.plan
            and subscription.plan.allows_group_coaching
        )

    def get_qr_data(self):
        """Données qui seront encodées dans le QR Code"""
        return str(self.qr_code)

    @property
    def active_goal(self):
        return self.goals.filter(status=MemberGoal.STATUS_ACTIVE).prefetch_related("measurements").first()
    
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


class MemberGoal(models.Model):
    GOAL_LOSE_WEIGHT = "lose_weight"
    GOAL_GAIN_WEIGHT = "gain_weight"

    GOAL_TYPE_CHOICES = (
        (GOAL_LOSE_WEIGHT, "Perte de poids"),
        (GOAL_GAIN_WEIGHT, "Prise de poids"),
    )

    STARTER_MEMBER = "member"
    STARTER_COACH = "coach"

    STARTER_CHOICES = (
        (STARTER_MEMBER, "Le membre commence les releves"),
        (STARTER_COACH, "Le coach commence les releves"),
    )

    STATUS_ACTIVE = "active"
    STATUS_ACHIEVED = "achieved"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Actif"),
        (STATUS_ACHIEVED, "Atteint"),
        (STATUS_CANCELLED, "Annule"),
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="member_goals",
        db_index=True,
    )
    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="goals",
    )
    goal_type = models.CharField(max_length=20, choices=GOAL_TYPE_CHOICES)
    target_weight = models.DecimalField(max_digits=5, decimal_places=2)
    target_date = models.DateField(blank=True, null=True)
    measurement_starter = models.CharField(
        max_length=10,
        choices=STARTER_CHOICES,
        default=STARTER_MEMBER,
    )
    note = models.TextField(blank=True)
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_member_goals",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["gym", "status"]),
            models.Index(fields=["member", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["member"],
                condition=models.Q(status="active"),
                name="unique_active_goal_per_member",
            ),
        ]
        ordering = ["-created_at"]

    def clean(self):
        super().clean()
        if self.gym_id and self.member_id and self.member.gym_id != self.gym_id:
            raise models.ValidationError("L'objectif doit appartenir au meme gym que le membre.")
        if self.target_weight and self.target_weight <= 0:
            raise models.ValidationError("Le poids cible doit etre superieur a zero.")
        if self.note:
            self.note = self.note.strip()

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def measurements_ordered(self):
        return self.measurements.order_by("measured_at", "created_at")

    @property
    def initial_measurement(self):
        return self.measurements_ordered.first()

    @property
    def latest_measurement(self):
        return self.measurements.order_by("-measured_at", "-created_at").first()

    @property
    def is_started(self):
        return self.initial_measurement is not None

    @property
    def initial_weight(self):
        measurement = self.initial_measurement
        return measurement.weight if measurement else None

    @property
    def current_weight(self):
        measurement = self.latest_measurement
        return measurement.weight if measurement else None

    @property
    def remaining_weight(self):
        if self.current_weight is None:
            return None
        if self.goal_type == self.GOAL_GAIN_WEIGHT:
            return max(self.target_weight - self.current_weight, 0)
        return max(self.current_weight - self.target_weight, 0)

    @property
    def progress_percent(self):
        if self.initial_weight is None or self.current_weight is None:
            return 0
        if self.goal_type == self.GOAL_GAIN_WEIGHT:
            total = self.target_weight - self.initial_weight
            progressed = self.current_weight - self.initial_weight
        else:
            total = self.initial_weight - self.target_weight
            progressed = self.initial_weight - self.current_weight
        if total <= 0:
            return 100 if self.reached_target else 0
        return min(max(round((progressed / total) * 100), 0), 100)

    @property
    def reached_target(self):
        if self.current_weight is None:
            return False
        if self.goal_type == self.GOAL_GAIN_WEIGHT:
            return self.current_weight >= self.target_weight
        return self.current_weight <= self.target_weight

    def refresh_status_from_progress(self, save=True):
        next_status = self.STATUS_ACHIEVED if self.reached_target else self.STATUS_ACTIVE
        if self.status != next_status:
            self.status = next_status
            if save:
                self.save(update_fields=["status", "updated_at"])
        return self.status

    def __str__(self):
        return f"{self.member} - {self.get_goal_type_display()}"


class MemberWeightMeasurement(models.Model):
    SOURCE_MEMBER = "member"
    SOURCE_COACH = "coach"

    SOURCE_CHOICES = (
        (SOURCE_MEMBER, "Membre"),
        (SOURCE_COACH, "Coach"),
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="member_weight_measurements",
        db_index=True,
    )
    goal = models.ForeignKey(
        MemberGoal,
        on_delete=models.CASCADE,
        related_name="measurements",
    )
    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="weight_measurements",
    )
    weight = models.DecimalField(max_digits=5, decimal_places=2)
    measured_at = models.DateField(default=timezone.localdate)
    note = models.TextField(blank=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_weight_measurements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["gym", "measured_at"]),
            models.Index(fields=["member", "measured_at"]),
            models.Index(fields=["goal", "measured_at"]),
        ]
        ordering = ["-measured_at", "-created_at"]

    def clean(self):
        super().clean()
        if self.gym_id and self.member_id and self.member.gym_id != self.gym_id:
            raise models.ValidationError("La mesure doit appartenir au meme gym que le membre.")
        if self.goal_id and self.member_id and self.goal.member_id != self.member_id:
            raise models.ValidationError("La mesure doit viser le meme membre que l'objectif.")
        if self.goal_id and self.gym_id and self.goal.gym_id != self.gym_id:
            raise models.ValidationError("La mesure doit appartenir au meme gym que l'objectif.")
        if self.weight and self.weight <= 0:
            raise models.ValidationError("Le poids releve doit etre superieur a zero.")
        if self.note:
            self.note = self.note.strip()

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.member} - {self.weight} kg"


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



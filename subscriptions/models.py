from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from members.models import Member
from organizations.models import Gym
from django.core.exceptions import ValidationError
from django.utils.text import slugify

# Create your models here.
class SubscriptionOffer(models.Model):
    CATEGORY_ACCESS = "access"
    CATEGORY_COACHING = "coaching"
    CATEGORY_CLASS = "class"
    CATEGORY_OTHER = "other"

    CATEGORY_CHOICES = (
        (CATEGORY_ACCESS, "Acces"),
        (CATEGORY_COACHING, "Coaching"),
        (CATEGORY_CLASS, "Cours"),
        (CATEGORY_OTHER, "Autre"),
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="subscription_offers",
        db_index=True,
    )
    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=140, editable=False)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=CATEGORY_ACCESS)
    grants_individual_coaching = models.BooleanField(default=False)
    grants_group_coaching = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["gym", "name"], name="unique_subscription_offer_name_per_gym"),
            models.UniqueConstraint(fields=["gym", "code"], name="unique_subscription_offer_code_per_gym"),
        ]
        indexes = [
            models.Index(fields=["gym", "is_active"]),
            models.Index(fields=["gym", "category"]),
        ]
        ordering = ["name"]

    def clean(self):
        super().clean()
        if self.name:
            self.name = self.name.strip()
        if self.description:
            self.description = self.description.strip()

    def save(self, *args, **kwargs):
        self.full_clean()
        if not self.code:
            base_code = slugify(self.name) or "offre"
            candidate = base_code
            suffix = 2
            while SubscriptionOffer.objects.filter(gym=self.gym, code=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base_code}-{suffix}"
                suffix += 1
            self.code = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        gym_name = self.gym.name if self.gym_id else "Sans gym"
        return f"{self.name} - {gym_name}"


class SubscriptionPlan(models.Model):
    COACHING_MODE_NONE = "none"
    COACHING_MODE_INDIVIDUAL = "individual"
    COACHING_MODE_GROUP = "group"
    COACHING_MODE_BOTH = "both"

    COACHING_MODE_CHOICES = (
        (COACHING_MODE_NONE, "Aucun coaching"),
        (COACHING_MODE_INDIVIDUAL, "Coaching individuel"),
        (COACHING_MODE_GROUP, "Programme groupe"),
        (COACHING_MODE_BOTH, "Coaching individuel et groupe"),
    )

    COACHING_LEVEL_STANDARD = "standard"
    COACHING_LEVEL_PREMIUM = "premium"
    COACHING_LEVEL_INTENSIVE = "intensive"

    COACHING_LEVEL_CHOICES = (
        (COACHING_LEVEL_STANDARD, "Standard"),
        (COACHING_LEVEL_PREMIUM, "Premium"),
        (COACHING_LEVEL_INTENSIVE, "Intensif"),
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="subscription_plans",
        db_index=True
    )
    name = models.CharField(max_length=100)
    duration_days = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)
    offers = models.ManyToManyField(
        SubscriptionOffer,
        blank=True,
        related_name="plans",
    )
    coaching_mode = models.CharField(
        max_length=20,
        choices=COACHING_MODE_CHOICES,
        default=COACHING_MODE_NONE,
    )
    coaching_level = models.CharField(
        max_length=20,
        choices=COACHING_LEVEL_CHOICES,
        default=COACHING_LEVEL_STANDARD,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:

        constraints = [
            models.UniqueConstraint(
                fields=['gym', 'name'],
                name='unique_plan_name_per_gym'
            )
        ]
        indexes = [
            models.Index(fields=["gym"]),
            models.Index(fields=["gym", "is_active"]),
        ]

        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.gym})"

    @property
    def allows_individual_coaching(self):
        if self.coaching_mode in {self.COACHING_MODE_INDIVIDUAL, self.COACHING_MODE_BOTH}:
            return True
        return self.offers.filter(is_active=True, grants_individual_coaching=True).exists()

    @property
    def allows_group_coaching(self):
        if self.coaching_mode in {self.COACHING_MODE_GROUP, self.COACHING_MODE_BOTH}:
            return True
        return self.offers.filter(is_active=True, grants_group_coaching=True).exists()

    @property
    def active_offers(self):
        return self.offers.filter(is_active=True).order_by("name")

    def coaching_rights_payload(self):
        return {
            "mode": self.coaching_mode,
            "mode_label": self.get_coaching_mode_display(),
            "level": self.coaching_level,
            "level_label": self.get_coaching_level_display(),
            "allows_individual": self.allows_individual_coaching,
            "allows_group": self.allows_group_coaching,
            "has_any_access": self.allows_individual_coaching or self.allows_group_coaching,
            "offers": [
                {
                    "id": offer.id,
                    "name": offer.name,
                    "category": offer.category,
                    "category_label": offer.get_category_display(),
                }
                for offer in self.active_offers
            ],
        }


class MemberSubscription(models.Model):

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="subscriptions",
        db_index=True
    )

    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="subscriptions"
    )

    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        null=True,
        related_name="subscriptions"
    )

    start_date = models.DateField()

    end_date = models.DateField()

    is_active = models.BooleanField(default=True)

    auto_renew = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    
    is_paused = models.BooleanField(default=False, verbose_name="Abonnement en pause")
    paused_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de mise en pause")

    class Meta:

        ordering = ["-start_date"]

        indexes = [
            models.Index(fields=["gym"]),
            models.Index(fields=["member"]),
            models.Index(fields=["gym", "is_active"]),
        ]

    def clean(self):
        """
        Validation métier :
        - start_date < end_date
        - un seul abonnement actif par membre
        """

        if self.member_id and not self.gym_id:
            self.gym = self.member.gym

        if self.member_id and self.gym_id and self.member.gym_id != self.gym_id:
            raise ValidationError("Le membre n'appartient pas au gym de cet abonnement.")

        if self.plan_id and self.gym_id and self.plan.gym_id != self.gym_id:
            raise ValidationError("La formule n'appartient pas au gym de cet abonnement.")

        if self.member_id and self.plan_id and self.member.gym_id != self.plan.gym_id:
            raise ValidationError("Le membre et la formule doivent appartenir au meme gym.")

        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValidationError("La date de fin doit être après la date de début.")

        if self.is_active and self.member_id and self.gym_id and not getattr(self, "_skip_active_collision_validation", False):
            exists = MemberSubscription.objects.filter(
                member=self.member,
                gym=self.gym,
                is_active=True
            ).exclude(pk=self.pk).exists()

            if exists:
                raise ValidationError("Ce membre a déjà un abonnement actif.")
            
    def save(self, *args, **kwargs):
        if self.member_id and not self.gym_id:
            self.gym = self.member.gym
        self.full_clean()
        return super().save(*args, **kwargs)

    def resume_subscription(self):
        """Reprend l'abonnement après une pause"""
        if self.is_paused and self.paused_at:
            paused_duration = (timezone.now() - self.paused_at).days
            self.end_date += timedelta(days=paused_duration)
            self.is_paused = False
            self.paused_at = None
            self.save()
    
    def __str__(self):
        return f"{self.member} - {self.plan}"


class SubscriptionRequest(models.Model):
    """
    Intention de souscription creee depuis l'espace membre.
    L'abonnement actif sera cree plus tard apres validation du paiement.
    """

    STATUS_PENDING = "pending"
    STATUS_AWAITING_PAYMENT = "awaiting_payment"
    STATUS_PAID = "paid"
    STATUS_CANCELLED = "cancelled"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = (
        (STATUS_PENDING, "En attente"),
        (STATUS_AWAITING_PAYMENT, "Paiement en cours"),
        (STATUS_PAID, "Payee"),
        (STATUS_CANCELLED, "Annulee"),
        (STATUS_FAILED, "Echec"),
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="subscription_requests",
        db_index=True,
    )

    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="subscription_requests",
    )

    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="subscription_requests",
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscription_requests",
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )

    price_usd = models.DecimalField(max_digits=10, decimal_places=2)

    aggregator_reference = models.CharField(max_length=160, blank=True)

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["gym", "member", "status"]),
            models.Index(fields=["gym", "created_at"]),
            models.Index(fields=["status", "created_at"]),
        ]
        ordering = ["-created_at"]

    def clean(self):
        super().clean()
        if self.member_id and not self.gym_id:
            self.gym = self.member.gym
        if self.member_id and self.gym_id and self.member.gym_id != self.gym_id:
            raise ValidationError("Le membre n'appartient pas au gym de la demande.")
        if self.plan_id and self.gym_id and self.plan.gym_id != self.gym_id:
            raise ValidationError("La formule n'appartient pas au gym de la demande.")
        if self.price_usd is not None and self.price_usd < 0:
            raise ValidationError({"price_usd": "Le prix ne peut pas etre negatif."})

    def save(self, *args, **kwargs):
        if self.member_id and not self.gym_id:
            self.gym = self.member.gym
        if self.plan_id and self.price_usd is None:
            self.price_usd = self.plan.price
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.member} - {self.plan} - {self.get_status_display()}"

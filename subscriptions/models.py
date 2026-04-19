from datetime import timedelta

from django.db import models
from django.utils import timezone
from members.models import Member
from organizations.models import Gym
from django.core.exceptions import ValidationError

# Create your models here.
class SubscriptionPlan(models.Model):
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

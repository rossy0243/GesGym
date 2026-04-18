from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
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

    def clean(self):
        super().clean()
        if self.name:
            self.name = self.name.strip()
        if self.phone:
            self.phone = self.phone.strip()
        if self.specialty:
            self.specialty = self.specialty.strip()

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def assign_member(self, member):
        if member.gym_id != self.gym_id:
            raise ValidationError("Le membre doit appartenir au meme gym que le coach.")
        self.members.add(member)

    def remove_member(self, member):
        if member.gym_id != self.gym_id:
            raise ValidationError("Le membre doit appartenir au meme gym que le coach.")
        self.members.remove(member)


@receiver(m2m_changed, sender=Coach.members.through)
def validate_coach_members(sender, instance, action, pk_set, **kwargs):
    if action != "pre_add" or not pk_set:
        return

    invalid_members = Member.objects.filter(id__in=pk_set).exclude(gym=instance.gym)
    if invalid_members.exists():
        raise ValidationError("Un coach ne peut suivre que les membres de son gym.")

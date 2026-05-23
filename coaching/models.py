from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from members.models import Member
from organizations.models import Gym


class CoachSpecialty(models.Model):
    """
    Specialite configurable par gym pour standardiser les fiches coach.
    """

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="coach_specialties",
        db_index=True,
    )

    name = models.CharField(max_length=120)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["gym", "name"],
                name="unique_coach_specialty_per_gym",
            )
        ]
        indexes = [
            models.Index(fields=["gym", "is_active"]),
        ]
        ordering = ["name"]

    def clean(self):
        super().clean()
        if self.name:
            self.name = self.name.strip()

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        gym_name = self.gym.name if self.gym_id else "Sans gym"
        return f"{self.name} - {gym_name}"


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

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="coach_profile",
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
        if not member.has_individual_coaching_access:
            raise ValidationError("Le membre doit avoir un abonnement actif avec coaching individuel.")
        self.members.add(member)

    def remove_member(self, member):
        if member.gym_id != self.gym_id:
            raise ValidationError("Le membre doit appartenir au meme gym que le coach.")
        self.members.remove(member)


class GroupCoachingProgram(models.Model):
    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="group_coaching_programs",
        db_index=True,
    )

    coach = models.ForeignKey(
        Coach,
        on_delete=models.PROTECT,
        related_name="group_programs",
    )

    name = models.CharField(max_length=140)

    objective = models.CharField(max_length=180, blank=True)

    description = models.TextField(blank=True)

    capacity = models.PositiveIntegerField(default=12)

    participants = models.ManyToManyField(
        Member,
        related_name="group_coaching_programs",
        blank=True,
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["gym", "name"],
                name="unique_group_coaching_program_per_gym",
            )
        ]
        indexes = [
            models.Index(fields=["gym", "is_active"]),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def participant_count(self):
        return self.participants.count()

    @property
    def available_slots(self):
        return max(self.capacity - self.participant_count, 0)

    @property
    def is_full(self):
        return self.participant_count >= self.capacity

    def clean(self):
        super().clean()
        if self.name:
            self.name = self.name.strip()
        if self.objective:
            self.objective = self.objective.strip()
        if self.coach_id and self.gym_id and self.coach.gym_id != self.gym_id:
            raise ValidationError("Le coach du programme doit appartenir au meme gym.")
        if self.capacity < 1:
            raise ValidationError("La capacite doit etre superieure a zero.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def join_member(self, member):
        if member.gym_id != self.gym_id:
            raise ValidationError("Le membre doit appartenir au meme gym que le programme.")
        if not member.has_group_coaching_access:
            raise ValidationError("Le membre doit avoir un abonnement actif avec acces au coaching groupe.")
        if self.is_full and not self.participants.filter(id=member.id).exists():
            raise ValidationError("Ce programme groupe est deja complet.")
        self.participants.add(member)

    def remove_member(self, member):
        if member.gym_id != self.gym_id:
            raise ValidationError("Le membre doit appartenir au meme gym que le programme.")
        self.participants.remove(member)


class CoachAssignment(models.Model):
    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="coach_assignments",
        db_index=True,
    )

    coach = models.ForeignKey(
        Coach,
        on_delete=models.CASCADE,
        related_name="assignments",
    )

    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="coach_assignments",
    )

    started_at = models.DateTimeField(auto_now_add=True)

    ended_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["gym", "started_at"]),
            models.Index(fields=["coach", "started_at"]),
            models.Index(fields=["member", "started_at"]),
            models.Index(fields=["gym", "ended_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["member"],
                condition=Q(ended_at__isnull=True),
                name="unique_active_coach_assignment_per_member",
            ),
        ]
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.member} -> {self.coach}"

    def clean(self):
        super().clean()
        if self.gym_id and self.member_id and self.member.gym_id != self.gym_id:
            raise ValidationError("Le membre de l'affectation doit appartenir au meme gym.")
        if self.gym_id and self.coach_id and self.coach.gym_id != self.gym_id:
            raise ValidationError("Le coach de l'affectation doit appartenir au meme gym.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class CoachingFollowUp(models.Model):
    INTERACTION_CALL = "call"
    INTERACTION_MESSAGE = "message"
    INTERACTION_ASSESSMENT = "assessment"
    INTERACTION_SESSION = "session"
    INTERACTION_FOLLOW_UP = "follow_up"

    INTERACTION_CHOICES = (
        (INTERACTION_CALL, "Appel"),
        (INTERACTION_MESSAGE, "Message"),
        (INTERACTION_ASSESSMENT, "Bilan"),
        (INTERACTION_SESSION, "Seance"),
        (INTERACTION_FOLLOW_UP, "Relance"),
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="coaching_follow_ups",
        db_index=True,
    )

    coach = models.ForeignKey(
        Coach,
        on_delete=models.CASCADE,
        related_name="follow_ups",
    )

    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="coaching_follow_ups",
    )

    interaction_type = models.CharField(
        max_length=20,
        choices=INTERACTION_CHOICES,
        default=INTERACTION_FOLLOW_UP,
    )

    summary = models.TextField()

    next_action = models.CharField(max_length=255, blank=True)

    next_follow_up_at = models.DateField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["gym", "created_at"]),
            models.Index(fields=["coach", "created_at"]),
            models.Index(fields=["member", "created_at"]),
            models.Index(fields=["gym", "next_follow_up_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        member_name = f"{self.member.first_name} {self.member.last_name}".strip() if self.member_id else "Membre"
        return f"{member_name} - {self.get_interaction_type_display()}"

    def clean(self):
        super().clean()
        if self.summary:
            self.summary = self.summary.strip()
        if self.next_action:
            self.next_action = self.next_action.strip()
        if self.gym_id and self.coach_id and self.coach.gym_id != self.gym_id:
            raise ValidationError("Le coach du suivi doit appartenir au meme gym.")
        if self.gym_id and self.member_id and self.member.gym_id != self.gym_id:
            raise ValidationError("Le membre du suivi doit appartenir au meme gym.")
        if self.coach_id and self.member_id and not self.coach.members.filter(id=self.member_id).exists():
            raise ValidationError("Le coach doit suivre ce membre avant d'enregistrer un suivi.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class CoachingFeedback(models.Model):
    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="coaching_feedbacks",
        db_index=True,
    )

    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="coaching_feedbacks",
    )

    coach = models.ForeignKey(
        Coach,
        on_delete=models.CASCADE,
        related_name="feedbacks",
    )

    group_program = models.ForeignKey(
        GroupCoachingProgram,
        on_delete=models.CASCADE,
        related_name="feedbacks",
        null=True,
        blank=True,
    )

    overall_rating = models.PositiveSmallIntegerField()
    listening_rating = models.PositiveSmallIntegerField()
    clarity_rating = models.PositiveSmallIntegerField()
    motivation_rating = models.PositiveSmallIntegerField()
    availability_rating = models.PositiveSmallIntegerField()

    comment = models.TextField(blank=True)

    wants_contact = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["gym", "created_at"]),
            models.Index(fields=["coach", "created_at"]),
            models.Index(fields=["member", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        member_name = f"{self.member.first_name} {self.member.last_name}".strip() if self.member_id else "Membre"
        return f"Avis coaching - {member_name}"

    def clean(self):
        super().clean()
        if self.comment:
            self.comment = self.comment.strip()
        if self.gym_id and self.member_id and self.member.gym_id != self.gym_id:
            raise ValidationError("Le membre de l'avis doit appartenir au meme gym.")
        if self.gym_id and self.coach_id and self.coach.gym_id != self.gym_id:
            raise ValidationError("Le coach de l'avis doit appartenir au meme gym.")
        if self.coach_id and self.member_id and not self.coach.members.filter(id=self.member_id).exists():
            raise ValidationError("Le membre doit etre rattache a ce coach pour laisser un avis.")
        if self.group_program_id:
            if self.group_program.gym_id != self.gym_id:
                raise ValidationError("Le programme groupe de l'avis doit appartenir au meme gym.")
            if self.group_program.coach_id != self.coach_id:
                raise ValidationError("Le programme groupe doit etre relie au meme coach.")
            if not self.group_program.participants.filter(id=self.member_id).exists():
                raise ValidationError("Le membre doit participer au programme pour laisser un avis.")

        ratings = [
            self.overall_rating,
            self.listening_rating,
            self.clarity_rating,
            self.motivation_rating,
            self.availability_rating,
        ]
        for rating in ratings:
            if rating < 1 or rating > 5:
                raise ValidationError("Les notes doivent etre comprises entre 1 et 5.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


@receiver(m2m_changed, sender=Coach.members.through)
def validate_coach_members(sender, instance, action, pk_set, **kwargs):
    if action == "pre_add" and pk_set:
        invalid_members = Member.objects.filter(id__in=pk_set).exclude(gym=instance.gym)
        if invalid_members.exists():
            raise ValidationError("Un coach ne peut suivre que les membres de son gym.")

    if action == "post_add" and pk_set:
        active_assignments = CoachAssignment.objects.filter(
            member_id__in=pk_set,
            ended_at__isnull=True,
        ).exclude(coach=instance)
        active_assignments.update(ended_at=models.functions.Now())

        for member_id in pk_set:
            existing_assignment = CoachAssignment.objects.filter(
                coach=instance,
                member_id=member_id,
                ended_at__isnull=True,
            ).first()
            if not existing_assignment:
                CoachAssignment.objects.create(
                    gym=instance.gym,
                    coach=instance,
                    member_id=member_id,
                )

    if action == "post_remove" and pk_set:
        CoachAssignment.objects.filter(
            coach=instance,
            member_id__in=pk_set,
            ended_at__isnull=True,
        ).update(ended_at=models.functions.Now())


@receiver(m2m_changed, sender=GroupCoachingProgram.participants.through)
def validate_group_program_participants(sender, instance, action, pk_set, **kwargs):
    if action != "pre_add" or not pk_set:
        return

    invalid_members = Member.objects.filter(id__in=pk_set).exclude(gym=instance.gym)
    if invalid_members.exists():
        raise ValidationError("Un programme groupe ne peut contenir que les membres de son gym.")

    current_count = instance.participants.count()
    new_members_count = len(set(pk_set) - set(instance.participants.values_list("id", flat=True)))
    if current_count + new_members_count > instance.capacity:
        raise ValidationError("La capacite du programme groupe serait depassee.")

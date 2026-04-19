import random
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

from compte.models import UserGymRole
from organizations.models import Gym
from .models import Member, MemberPreRegistrationLink

User = get_user_model()


def generate_username(first_name, last_name):
    random_digits = random.randint(1000, 9999)
    base_username = f"{first_name.lower()}{last_name.lower()}{random_digits}"
    return base_username


@receiver(post_save, sender=Member)
def create_user_for_member(sender, instance, created, **kwargs):
    if created and not instance.user:
        username = generate_username(instance.first_name, instance.last_name)

        while User.objects.filter(username=username).exists():
            username = generate_username(instance.first_name, instance.last_name)

        user = User.objects.create_user(
            username=username,
            password="12345",
            first_name=instance.first_name,
            last_name=instance.last_name,
            email=instance.email or "",
        )

        UserGymRole.objects.create(
            user=user,
            gym=instance.gym,
            role="accountant",
            is_active=True,
        )

        instance.user = user
        instance.save(update_fields=["user"])


@receiver(post_save, sender=Gym)
def create_pre_registration_link_for_gym(sender, instance, created, **kwargs):
    if created:
        MemberPreRegistrationLink.objects.get_or_create(gym=instance)

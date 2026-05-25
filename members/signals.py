from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

from compte.utils import generate_temporary_password, generate_username
from organizations.models import Gym
from .models import Member, MemberPreRegistrationLink

User = get_user_model()


@receiver(post_save, sender=Member)
def create_user_for_member(sender, instance, created, **kwargs):
    if created and not instance.user:
        username = generate_username(instance.first_name, instance.last_name)

        while User.objects.filter(username=username).exists():
            username = generate_username(instance.first_name, instance.last_name)

        temporary_password = generate_temporary_password()
        user = User.objects.create_user(
            username=username,
            password=temporary_password,
            first_name=instance.first_name,
            last_name=instance.last_name,
            email=instance.email or "",
            force_password_change=True,
        )

        instance.user = user
        instance._temporary_password = temporary_password
        instance.save(update_fields=["user"])


@receiver(post_save, sender=Gym)
def create_pre_registration_link_for_gym(sender, instance, created, **kwargs):
    if created:
        MemberPreRegistrationLink.objects.get_or_create(gym=instance)

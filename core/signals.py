import random
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from core.models import Member

User = get_user_model()


def generate_username(first_name, last_name):
    random_digits = random.randint(1000, 9999)
    base_username = f"{first_name.lower()}{last_name.lower()}{random_digits}"
    return base_username


@receiver(post_save, sender=Member)
def create_user_for_member(sender, instance, created, **kwargs):

    if created and not instance.user:

        username = generate_username(instance.first_name, instance.last_name)

        # S'assurer que le username est unique
        while User.objects.filter(username=username).exists():
            username = generate_username(instance.first_name, instance.last_name)

        user = User.objects.create_user(
            username=username,
            password="12345",
            role="member",
            gym=instance.gym
        )

        instance.user = user
        instance.save()
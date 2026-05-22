import random
import secrets
import string

from django.contrib.auth import get_user_model


def generate_username(first_name, last_name):
        User = get_user_model()

        while True:
            username = f"{last_name.lower()}_{first_name.lower()}_{random.randint(1000,9999)}"
            if not User.objects.filter(username=username).exists():
                return username


def generate_temporary_password(length=14):
        alphabet = string.ascii_letters + string.digits + "@#$%!"
        while True:
            password = "".join(secrets.choice(alphabet) for _ in range(length))
            if (
                any(character.islower() for character in password)
                and any(character.isupper() for character in password)
                and any(character.isdigit() for character in password)
                and any(character in "@#$%!" for character in password)
            ):
                return password


def has_other_active_access(user, *, exclude_role_ids=None):
        from .models import UserGymRole

        role_ids = [role_id for role_id in (exclude_role_ids or []) if role_id]
        other_active_roles = UserGymRole.objects.filter(
            user=user,
            is_active=True,
            gym__is_active=True,
            gym__organization__is_active=True,
        )
        if role_ids:
            other_active_roles = other_active_roles.exclude(id__in=role_ids)
        if other_active_roles.exists():
            return True

        if getattr(user, "owned_organization_id", None):
            return True
        if getattr(user, "is_saas_admin", False) or getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True

        member_profile = getattr(user, "member_profile", None)
        if member_profile and member_profile.is_active and member_profile.gym.is_active and member_profile.gym.organization.is_active:
            return True

        coach_profile = getattr(user, "coach_profile", None)
        if coach_profile and coach_profile.is_active and coach_profile.gym.is_active and coach_profile.gym.organization.is_active:
            return True

        return False

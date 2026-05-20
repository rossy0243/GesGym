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

import random
from django.contrib.auth import get_user_model


def generate_username(first_name, last_name):
        User = get_user_model()

        while True:
            username = f"{last_name.lower()}_{first_name.lower()}_{random.randint(1000,9999)}"
            if not User.objects.filter(username=username).exists():
                return username
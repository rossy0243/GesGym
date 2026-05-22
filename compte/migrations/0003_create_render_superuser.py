import os

from django.contrib.auth.hashers import make_password
from django.db import migrations


def _env(name, default=""):
    return os.environ.get(name, default).strip()


def create_render_superuser(apps, schema_editor):
    if os.environ.get("DJANGO_ENV", "development").lower() != "production":
        return

    User = apps.get_model("compte", "User")
    username = _env("DJANGO_BOOTSTRAP_SUPERUSER_USERNAME")
    raw_password = _env("DJANGO_BOOTSTRAP_SUPERUSER_PASSWORD")
    email = _env("DJANGO_BOOTSTRAP_SUPERUSER_EMAIL")
    password_hash = make_password(raw_password) if raw_password else None

    if not username:
        return

    if not User.objects.filter(username=username).exists() and not password_hash:
        return

    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "password": password_hash or "",
            "email": email,
            "is_superuser": True,
            "is_staff": True,
            "is_active": True,
        },
    )

    update_fields = []
    if not user.is_superuser:
        user.is_superuser = True
        update_fields.append("is_superuser")
    if not user.is_staff:
        user.is_staff = True
        update_fields.append("is_staff")
    if not user.is_active:
        user.is_active = True
        update_fields.append("is_active")
    if created and password_hash and user.password != password_hash:
        user.password = password_hash
        update_fields.append("password")
    if created and email and user.email != email:
        user.email = email
        update_fields.append("email")

    if update_fields:
        user.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ("compte", "0002_user_owned_organization"),
    ]

    operations = [
        migrations.RunPython(create_render_superuser, migrations.RunPython.noop),
    ]

from django.db import migrations

from members.models import default_member_qr_expiry


def extend_qr_validity(apps, schema_editor):
    """
    Repousse l'echeance des QR codes existants.

    Ils avaient ete emis avec sept jours de validite, heritage d'un
    fonctionnement ou le code tournait automatiquement. Les QR etant desormais
    imprimes sur les cartes membres, une carte deviendrait inutilisable au bout
    d'une semaine. On aligne donc les codes deja emis sur la nouvelle duree,
    sans changer les codes eux-memes : les cartes deja imprimees restent
    valables.
    """
    Member = apps.get_model("members", "Member")
    Member.objects.all().update(qr_code_expires_at=default_member_qr_expiry())


def noop(apps, schema_editor):
    """Sens inverse volontairement neutre : on ne raccourcit pas une validite."""


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0008_alter_memberpreregistration_status"),
    ]

    operations = [
        migrations.RunPython(extend_qr_validity, noop),
    ]

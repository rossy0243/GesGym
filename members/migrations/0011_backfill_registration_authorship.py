"""
Reporte l'auteur connu sur les fiches deja creees.

Les preinscriptions confirmees portaient deja le nom de qui les a validees.
Cette information existait donc en base sans etre lisible sur la fiche du
membre : on la recopie plutot que de laisser ces fiches sans auteur.

Les membres saisis a la main avant ce changement restent sans auteur : le
journal sensible garde la trace de l'action, mais rien ne permet de rattacher
une ligne de journal a une fiche avec certitude. Mieux vaut "Inconnu" qu'une
attribution devinee.
"""

from django.db import migrations


def reporter_les_auteurs(apps, schema_editor):
    MemberPreRegistration = apps.get_model("members", "MemberPreRegistration")

    confirmees = MemberPreRegistration.objects.filter(
        status="confirmed",
        member__isnull=False,
        confirmed_by__isnull=False,
    ).select_related("member")

    for demande in confirmees:
        membre = demande.member
        membre.created_by_id = demande.confirmed_by_id
        membre.registration_source = "pre_registration"
        membre.save(update_fields=["created_by", "registration_source"])


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0010_member_created_by_member_registration_source_and_more"),
    ]

    operations = [
        # Retour arriere sans effet : effacer les auteurs supprimerait aussi
        # ceux enregistres depuis, alors qu'annuler cette migration seule
        # n'est pas une raison de perdre l'information. Revenir avant la 0010
        # retire les colonnes de toute facon.
        migrations.RunPython(reporter_les_auteurs, migrations.RunPython.noop),
    ]

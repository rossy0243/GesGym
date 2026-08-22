"""
Retire le masque de sous-reseau ajoute lors du changement de type du champ.

Le champ host etait un GenericIPAddressField, stocke par PostgreSQL dans le
type `inet`. Le convertir en texte a rendu les adresses sous leur forme
reseau : "172.20.10.3" est devenu "172.20.10.3/32". La fiche ne passait plus
la validation, et l'application ne joignait plus le lecteur.

On retire donc le suffixe des adresses simples. Une adresse portant un vrai
masque autre que /32 n'aurait aucun sens ici : le champ designe une machine,
pas un reseau.
"""

from django.db import migrations


def retirer_le_masque(apps, schema_editor):
    AccessDevice = apps.get_model("access", "AccessDevice")

    for device in AccessDevice.objects.exclude(host=""):
        if "/" not in device.host:
            continue
        adresse, _, masque = device.host.partition("/")
        if masque == "32":
            device.host = adresse
            device.save(update_fields=["host"])


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0008_accesslog_device_event_id_and_more"),
    ]

    operations = [
        # Retour arriere sans effet : reajouter un masque casserait de nouveau
        # la validation, et revenir avant la 0007 retablit le type inet.
        migrations.RunPython(retirer_le_masque, migrations.RunPython.noop),
    ]

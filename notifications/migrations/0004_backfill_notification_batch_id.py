import uuid

from django.db import migrations


def assign_batch_ids(apps, schema_editor):
    """
    Rattache les notifications deja envoyees a un identifiant d'envoi.

    Elles ont ete creees avant l'existence du champ. On reconstitue les lots
    comme le tableau de bord le faisait a l'affichage : meme salle, meme titre,
    meme message, meme horodatage et meme expediteur. Sans cela, aucun envoi
    passe ne pourrait etre annule ni supprime.
    """
    Notification = apps.get_model("notifications", "Notification")

    batches = {}
    to_update = []

    for notification in Notification.objects.filter(batch_id__isnull=True).iterator():
        sent_on = notification.sent_at or notification.created_at
        key = (
            notification.gym_id,
            notification.title or "",
            notification.message,
            sent_on.isoformat() if sent_on else "",
            notification.sent_by_id,
        )
        if key not in batches:
            batches[key] = uuid.uuid4()
        notification.batch_id = batches[key]
        to_update.append(notification)

        if len(to_update) >= 500:
            Notification.objects.bulk_update(to_update, ["batch_id"])
            to_update = []

    if to_update:
        Notification.objects.bulk_update(to_update, ["batch_id"])


def clear_batch_ids(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")
    Notification.objects.update(batch_id=None)


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0003_notification_batch_id_notification_cancelled_at_and_more"),
    ]

    operations = [
        migrations.RunPython(assign_batch_ids, clear_batch_ids),
    ]

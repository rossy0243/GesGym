"""
La presence du personnel, etablie a la porte.

Un employe qui passe devant le lecteur est la : le pointer une seconde fois a
la main n'apprend rien a personne. La saisie manuelle garde pourtant le
dernier mot - badge oublie, journee passee en course, employe envoye ailleurs.

Rien ici ne doit empecher une porte de s'ouvrir : un incident de pointage est
journalise, jamais propage.
"""

import logging

from django.utils import timezone

from .models import Attendance

logger = logging.getLogger(__name__)


def noter_passage(employee, moment=None):
    """
    Marque l'employe present le jour de son passage.

    Renvoie la presence, ou None si rien n'a ete touche - une presence saisie a
    la main n'est jamais recouverte.
    """
    if employee is None:
        return None

    moment = moment or timezone.now()
    local = timezone.localtime(moment)

    try:
        presence = Attendance.objects.filter(employee=employee, date=local.date()).first()

        if presence is None:
            return Attendance.objects.create(
                gym=employee.gym,
                employee=employee,
                date=local.date(),
                status="present",
                source=Attendance.SOURCE_LECTEUR,
                heure_arrivee=local.time(),
            )

        if presence.source != Attendance.SOURCE_LECTEUR:
            # Quelqu'un a tranche a la main : c'est cette decision qui compte.
            return None

        # Plusieurs passages dans la journee : l'heure d'arrivee est la premiere.
        if presence.heure_arrivee is None or local.time() < presence.heure_arrivee:
            presence.status = "present"
            presence.heure_arrivee = local.time()
            presence.save(update_fields=["status", "heure_arrivee", "updated_at"])
        return presence
    except Exception as exc:  # pragma: no cover - garde-fou
        logger.warning("Pointage de %s impossible : %s", employee, exc)
        return None

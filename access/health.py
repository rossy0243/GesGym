"""
Sante des lecteurs : lesquels ne donnent plus signe de vie.

Une panne franche se voit : la porte ne s'ouvre plus, quelqu'un appelle. Le
danger est la panne silencieuse — le tunnel qui ne remonte pas apres une
coupure, le PC qu'on a eteint le soir. Le lecteur continue d'ouvrir la porte
tout seul, personne ne remarque rien, et pendant ce temps les passages ne sont
plus journalises et les abonnements encaisses ne lui parviennent plus.

On signale donc l'absence de nouvelles, avant qu'un membre ne s'en plaigne.
"""

from datetime import timedelta

from django.utils import timezone

from .models import AccessDevice

# Au-dela de ce delai sans nouvelles, on considere le lecteur hors ligne.
# Trois heures laissent passer une coupure courte sans alarmer l'equipe, et
# restent assez courtes pour qu'une panne du matin soit vue avant midi.
SILENCE_TOLERE = timedelta(hours=3)


def lecteurs_hors_ligne(gym, maintenant=None):
    """Lecteurs actifs sans nouvelles depuis trop longtemps."""
    maintenant = maintenant or timezone.now()
    limite = maintenant - SILENCE_TOLERE

    silencieux = []
    for device in AccessDevice.objects.filter(gym=gym, is_active=True):
        # Jamais contacte : la fiche vient d'etre creee, on ne crie pas encore.
        if device.last_seen_at is None:
            continue
        if device.last_seen_at < limite:
            silencieux.append(device)
    return silencieux


def resume_hors_ligne(gym, maintenant=None):
    """
    Resume affichable, ou None quand tout va bien.

    Renvoyer None plutot qu'une structure vide permet au gabarit de poser une
    seule condition.
    """
    maintenant = maintenant or timezone.now()
    silencieux = lecteurs_hors_ligne(gym, maintenant)
    if not silencieux:
        return None

    plus_ancien = min(silencieux, key=lambda d: d.last_seen_at)
    heures = int((maintenant - plus_ancien.last_seen_at).total_seconds() // 3600)

    return {
        "total": len(silencieux),
        "devices": silencieux,
        "plus_ancien": plus_ancien,
        "heures": heures,
        "erreur": plus_ancien.last_error,
    }

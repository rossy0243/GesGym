"""
Le lecteur lit parfois deux fois la meme personne en quelques secondes.

Une personne ne franchit la porte qu'une fois : deux lignes a la meme minute
ne racontent pas deux visites, mais une lecture repetee. On rend alors le
passage deja enregistre au lieu d'en creer un second - sinon la frequentation
gonfle, et un carnet d'invitation perd une seance pour rien.

La regle ne vaut que pour les passages accordes. Un refus repete, lui, doit se
voir : c'est meme ce qui nourrit l'alerte "refuse trois fois".
"""

from datetime import timedelta

from django.utils import timezone

from .models import AccessLog

# Assez long pour couvrir une rafale du lecteur, assez court pour qu'un vrai
# aller-retour - sortir, revenir - reste deux passages distincts.
FENETRE = timedelta(seconds=60)

# Ce que lit l'equipe quand le passage etait deja enregistre.
RELECTURE_REASON = "Passage deja enregistre"


def passage_recent(gym, *, member=None, employee=None, guest_pass=None,
                   terminal_label="", moment=None, sens=None):
    """
    Le passage accorde de cette personne juste avant, s'il existe.

    ``moment`` sert au rattrapage, qui recree des passages anciens : la fenetre
    se calcule alors autour de l'heure de l'evenement, pas de maintenant.
    """
    if member is not None:
        cible = {"member": member}
    elif employee is not None:
        cible = {"employee": employee}
    elif guest_pass is not None:
        cible = {"guest_pass": guest_pass}
    elif terminal_label:
        cible = {"terminal_label": terminal_label}
    else:
        # Ouverture manuelle : aucune personne a reconnaitre, rien a regrouper.
        return None

    moment = moment or timezone.now()
    # Entrer puis sortir dans la minute, c'est possible - un employe qui a
    # oublie quelque chose. Seules deux lectures de meme sens se regroupent.
    if sens:
        cible["sens"] = sens

    return (
        AccessLog.objects.filter(
            gym=gym,
            access_granted=True,
            check_in_time__gte=moment - FENETRE,
            check_in_time__lte=moment + FENETRE,
            **cible,
        )
        .order_by("-check_in_time")
        .first()
    )

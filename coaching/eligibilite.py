"""
Qui a droit au coaching.

Le droit appartient a la formule vendue : un membre n'est suivi que si son
abonnement en cours y donne acces, soit par le mode de la formule, soit par une
offre active attachee a cette formule.

La regle etait ecrite deux fois - dans le formulaire d'affectation et dans le
portail du coach - et nulle part dans les compteurs. "Membres sans coach"
retranchait donc les membres suivis de toute la salle, et presentait des
membres Standard comme des membres a repartir entre les coaches.

Elle est ecrite ici une seule fois.
"""

from django.db.models import Q
from django.utils import timezone

from members.models import Member
from subscriptions.models import SubscriptionPlan


def filtre_individuel():
    """Les abonnements dont la formule donne acces au coaching individuel."""
    return Q(
        subscriptions__plan__coaching_mode__in=[
            SubscriptionPlan.COACHING_MODE_INDIVIDUAL,
            SubscriptionPlan.COACHING_MODE_BOTH,
        ]
    ) | Q(
        subscriptions__plan__offers__is_active=True,
        subscriptions__plan__offers__grants_individual_coaching=True,
    )


def filtre_groupe():
    """Les abonnements dont la formule donne acces au programme groupe."""
    return Q(
        subscriptions__plan__coaching_mode__in=[
            SubscriptionPlan.COACHING_MODE_GROUP,
            SubscriptionPlan.COACHING_MODE_BOTH,
        ]
    ) | Q(
        subscriptions__plan__offers__is_active=True,
        subscriptions__plan__offers__grants_group_coaching=True,
    )


def filtre_abonnement_en_cours(today=None):
    """L'abonnement paye, actif, non suspendu, dont la periode couvre le jour."""
    today = today or timezone.localdate()
    return Q(
        subscriptions__is_active=True,
        subscriptions__is_paused=False,
        subscriptions__start_date__lte=today,
        subscriptions__end_date__gte=today,
    )


def membres_avec_droit(gym, individuel=True, groupe=False, today=None):
    """
    Les membres dont l'abonnement en cours donne droit au coaching demande.

    Les trois conditions - le membre, la periode, le droit - tiennent dans un
    seul filtre. Les enchainer en plusieurs appels laisserait Django les
    satisfaire avec des abonnements differents : un abonnement Premium termine
    l'an dernier et un abonnement Standard en cours suffiraient alors a faire
    passer le membre pour un abonne au coaching.
    """
    droit = Q()
    if individuel:
        droit |= filtre_individuel()
    if groupe:
        droit |= filtre_groupe()
    if not droit:
        return Member.objects.none()

    return Member.objects.filter(
        Q(gym=gym, is_active=True, status="active")
        & filtre_abonnement_en_cours(today)
        & droit
    ).distinct()

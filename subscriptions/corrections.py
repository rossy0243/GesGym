"""
Correction de la periode d'un abonnement mal saisi.

Une receptionniste peut vendre une periode deja terminee : le membre paie et
n'a aucun acces. Corriger les dates repare l'acces sans toucher a l'argent -
la recette, elle, a bien eu lieu.

Ce module ne connait qu'un geste : **corriger une periode**. Annuler une vente
en est un autre, ou l'argent doit suivre ; les confondre ferait disparaitre des
recettes reellement encaissees.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import MemberSubscription, SubscriptionCorrection


def periode_close(start_date, plan, aujourd_hui=None):
    """
    La periode vendue est-elle deja terminee ?

    C'est le seul cas qu'il faut attraper a la saisie. Une date passee est
    souvent legitime - on enregistre la vente d'hier, ou un abonnement commence
    lundi. Interdire toutes les dates passees a deja casse le renouvellement
    anticipe dans ce projet.
    """
    if not start_date or plan is None:
        return False

    aujourd_hui = aujourd_hui or timezone.localdate()
    return start_date + timedelta(days=plan.duration_days) < aujourd_hui


def restantes(subscription):
    """Corrections encore possibles sur cet abonnement."""
    deja = subscription.corrections.count()
    return max(SubscriptionCorrection.MAXIMUM_PAR_ABONNEMENT - deja, 0)


def _chevauchement(subscription, debut, fin):
    """Un autre abonnement du membre occupe-t-il deja cette periode ?"""
    return (
        MemberSubscription.objects.filter(
            gym=subscription.gym,
            member=subscription.member,
            is_active=True,
        )
        .exclude(pk=subscription.pk)
        .filter(Q(start_date__lt=fin) & Q(end_date__gt=debut))
        .first()
    )


@transaction.atomic
def corriger(subscription, nouveau_debut, motif, par, acquitte=False):
    """
    Repose la periode d'un abonnement, et garde trace du geste.

    La date de fin se recalcule sur la duree de la formule : une correction ne
    doit pas pouvoir allonger discretement un abonnement. Le paiement n'est
    jamais touche.

    ``acquitte`` vaut vrai quand c'est le proprietaire qui corrige : il n'a pas
    a s'accuser reception a lui-meme.
    """
    motif = (motif or "").strip()
    if not motif:
        raise ValidationError(
            "Le motif est obligatoire : c'est ce que le proprietaire lira."
        )

    if nouveau_debut is None:
        raise ValidationError("La nouvelle date de debut est obligatoire.")

    if subscription.plan is None:
        raise ValidationError(
            "Cet abonnement n'a plus de formule : sa duree est inconnue."
        )

    if restantes(subscription) == 0:
        raise ValidationError(
            f"Cet abonnement a deja ete corrige "
            f"{SubscriptionCorrection.MAXIMUM_PAR_ABONNEMENT} fois. "
            "Au-dela, c'est la vente elle-meme qu'il faut revoir."
        )

    nouvelle_fin = nouveau_debut + timedelta(days=subscription.plan.duration_days)

    if (nouveau_debut, nouvelle_fin) == (subscription.start_date, subscription.end_date):
        raise ValidationError(
            "Cette date est deja celle de l'abonnement : rien a corriger."
        )

    voisin = _chevauchement(subscription, nouveau_debut, nouvelle_fin)
    if voisin is not None:
        raise ValidationError(
            f"Cette periode chevauche un autre abonnement du membre, "
            f"du {voisin.start_date:%d/%m/%Y} au {voisin.end_date:%d/%m/%Y}."
        )

    trace = SubscriptionCorrection(
        gym=subscription.gym,
        subscription=subscription,
        previous_start=subscription.start_date,
        previous_end=subscription.end_date,
        new_start=nouveau_debut,
        new_end=nouvelle_fin,
        reason=motif,
        corrected_by=par,
    )
    if acquitte:
        trace.acknowledged_by = par
        trace.acknowledged_at = timezone.now()

    subscription.start_date = nouveau_debut
    subscription.end_date = nouvelle_fin
    # La correction prend effet sur-le-champ : le membre retrouve son acces
    # sans attendre que quiconque valide.
    subscription.is_active = True
    subscription.save(update_fields=["start_date", "end_date", "is_active"])

    trace.save()
    return trace


def en_attente(gym):
    """
    Corrections qu'aucun proprietaire n'a encore declare avoir vues.

    Elles alimentent son bandeau : une correction n'est pas une ligne de
    journal qu'on peut ne jamais lire.
    """
    return (
        SubscriptionCorrection.objects.filter(gym=gym, acknowledged_at__isnull=True)
        .select_related("subscription__member", "corrected_by")
        .order_by("-corrected_at")
    )


@transaction.atomic
def accuser_reception(correction, par):
    """Le proprietaire declare avoir vu. La correction quitte son bandeau."""
    if correction.is_acknowledged:
        return correction

    correction.acknowledged_by = par
    correction.acknowledged_at = timezone.now()
    correction.save(update_fields=["acknowledged_by", "acknowledged_at"])
    return correction

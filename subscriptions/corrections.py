"""
Correction d'un abonnement mal saisi : sa periode, ou sa formule.

Une receptionniste peut vendre une periode deja terminee : le membre paie et
n'a aucun acces. Corriger les dates repare l'acces sans toucher a l'argent -
la recette, elle, a bien eu lieu.

La formule, elle, porte un prix. Un gerant qui vend une annuelle a la place
d'une mensuelle a inscrit une recette que personne n'a versee : le montant
n'est pas saisi, il vient de la formule. Corriger la formule demande donc de
corriger aussi les comptes, sans jamais reecrire la vente d'origine - elle a
ete comptee dans sa journee, et cette journee a peut-etre ete contre-signee.

Ce module ne connait donc que deux gestes : **corriger une periode** et
**corriger une formule**. Annuler une vente en est un troisieme, ou l'argent
doit revenir ; les confondre ferait disparaitre des recettes reellement
encaissees.
"""

from datetime import timedelta
from decimal import Decimal

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

    # Pas de plafond. Il protegeait contre un gerant qui deplacerait une periode
    # a repetition ; la correction est desormais reservee au proprietaire, qui
    # ne se controle pas lui-meme, et ce risque a disparu avec le geste.

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


def _ventes_de(subscription):
    """
    Les recettes rattachees a cet abonnement.

    Un geste offert n'en fait pas partie : il vaut zero et ne se corrige pas
    en argent.
    """
    return subscription.payments.recettes().filter(
        category="subscription"
    ).order_by("created_at")


def ecart_de_prix(subscription, nouveau_plan):
    """
    Ce que la correction de formule change aux comptes, en francs.

    Positif : la salle a inscrit plus qu'elle n'a recu, il faut retirer la
    difference. Negatif : la bonne formule coute plus cher, et il reste a
    encaisser. Aucune vente rattachee : rien a corriger.

    Le prix juste est calcule au taux de la vente d'origine, jamais a celui du
    jour : au taux d'aujourd'hui, les deux lignes ne s'annuleraient pas.
    """
    ventes = list(_ventes_de(subscription))
    if not ventes:
        return None, Decimal("0.00")

    vente = ventes[-1]
    paye = sum((v.amount_cdf for v in ventes), Decimal("0.00"))
    taux = vente.exchange_rate or Decimal("1")
    juste = (Decimal(nouveau_plan.price) * taux).quantize(Decimal("0.01"))
    return vente, (paye - juste).quantize(Decimal("0.01"))


def _corriger_les_comptes(subscription, vente, ecart, motif, par):
    """
    Retire des comptes une recette que personne n'a versee.

    Une seule ligne, du montant de l'ecart, rattachee a la vente d'origine.
    Elle porte la methode de la vente : en especes elle corrige l'attendu du
    tiroir, en mobile money elle n'y touche pas.

    Elle va dans la caisse de la vente si celle-ci est encore ouverte - meme
    journee, tout se neutralise - et sinon dans celle du jour, ou elle devient
    une contre-ecriture assumee.

    Rien n'est cree quand la bonne formule coute plus cher : la salle
    encaissera un vrai paiement le jour ou le membre versera la difference. On
    n'inscrit pas une recette que personne n'a remise.
    """
    from pos.services import caisse_cible, record_payment

    caisse = vente.cash_register
    if caisse is None or caisse.is_closed:
        caisse = caisse_cible(subscription.gym, par)

    return record_payment(
        gym=subscription.gym,
        register=caisse,
        amount=ecart,
        currency="CDF",
        method=vente.method,
        transaction_type="out",
        category="sale_correction",
        member=subscription.member,
        subscription=subscription,
        vente_corrigee=vente,
        description=f"Correction de formule : {motif}"[:255],
        created_by=par,
        source_app="subscriptions",
        source_model="SubscriptionCorrection",
    )


@transaction.atomic
def corriger_formule(subscription, nouveau_plan, motif, par, acquitte=False):
    """
    Repose la formule d'un abonnement, sa fin et les comptes.

    La fin se recalcule sur la duree de la nouvelle formule, depuis le meme
    debut : une correction ne deplace pas la vente dans le temps, elle repare
    ce qui a ete vendu.
    """
    motif = (motif or "").strip()
    if not motif:
        raise ValidationError(
            "Le motif est obligatoire : c'est ce que le proprietaire lira."
        )

    if nouveau_plan is None:
        raise ValidationError("La nouvelle formule est obligatoire.")

    if nouveau_plan.gym_id != subscription.gym_id:
        raise ValidationError("Cette formule appartient a une autre salle.")

    if subscription.plan_id == nouveau_plan.id:
        raise ValidationError(
            "C'est deja la formule de cet abonnement : rien a corriger."
        )

    nouvelle_fin = subscription.start_date + timedelta(days=nouveau_plan.duration_days)

    voisin = _chevauchement(subscription, subscription.start_date, nouvelle_fin)
    if voisin is not None:
        raise ValidationError(
            f"Cette periode chevauche un autre abonnement du membre, "
            f"du {voisin.start_date:%d/%m/%Y} au {voisin.end_date:%d/%m/%Y}."
        )

    vente, ecart = ecart_de_prix(subscription, nouveau_plan)
    correction = None
    reste_a_encaisser = Decimal("0.00")
    if vente is not None and ecart > 0:
        correction = _corriger_les_comptes(subscription, vente, ecart, motif, par)
    elif vente is not None and ecart < 0:
        reste_a_encaisser = -ecart

    trace = SubscriptionCorrection(
        gym=subscription.gym,
        subscription=subscription,
        previous_plan=subscription.plan,
        new_plan=nouveau_plan,
        previous_start=subscription.start_date,
        previous_end=subscription.end_date,
        new_start=subscription.start_date,
        new_end=nouvelle_fin,
        reason=motif,
        corrected_by=par,
    )
    if acquitte:
        trace.acknowledged_by = par
        trace.acknowledged_at = timezone.now()

    subscription.plan = nouveau_plan
    subscription.end_date = nouvelle_fin
    subscription.save(update_fields=["plan", "end_date"])
    trace.save()

    # Le lecteur porte ses propres dates : sans cela, une formule raccourcie
    # ouvrirait encore la porte jusqu'a la prochaine synchronisation.
    from access import enrollment

    enrollment.propager(subscription.member)

    trace.correction_de_caisse = correction
    trace.reste_a_encaisser = reste_a_encaisser
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

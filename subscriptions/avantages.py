"""
Les articles offerts avec une formule.

Un membre qui paie sa formule Premium recoit un kit : une serviette, quelques
bouteilles d'eau, tout article du stock que la salle a decide d'offrir. Ce
module ne connait que trois gestes - crediter a chaque paiement, remettre au
comptoir, annuler une erreur de saisie le jour meme - et deux lectures : ce qui
reste a un membre, et ce qui a ete offert sur une periode.

Le solde n'est pas un compteur qu'on modifie : c'est la somme d'un journal.
Rien ne s'efface. Le report d'un kit sur le suivant se fait donc tout seul, et
une annulation est une ligne de plus, pas une suppression.

Aucun paiement n'est jamais cree ici. Un article offert sort du stock sans
entrer dans la caisse : l'enregistrer comme une vente a zero ferait apparaitre
une fausse vente dans les encaissements.
"""

from collections import OrderedDict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from products.models import Product

from .models import BenefitMovement, OfferItem

MOTIF_STOCK_REMISE = "Avantage abonne"
MOTIF_STOCK_ANNULATION = "Annulation d'avantage abonne"


def _nom_membre(member):
    nom = f"{member.first_name} {member.last_name}".strip()
    return nom or member.phone or f"Membre #{member.id}"


# ---------------------------------------------------------------------------
# Le parametrage
# ---------------------------------------------------------------------------


@transaction.atomic
def definir_articles(offer, lignes):
    """
    Remplace les articles d'une offre.

    N'agit que sur les paiements futurs : les soldes deja credites appartiennent
    aux membres, et ne bougent pas quand le kit change.
    """
    propres = OrderedDict()
    for product_id, quantite in lignes:
        if not product_id:
            continue
        try:
            quantite = int(quantite)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Une quantite du kit est invalide.") from exc
        if quantite < 1:
            raise ValidationError("Chaque article du kit compte au moins une unite.")
        try:
            produit = Product.objects.get(id=product_id, gym=offer.gym)
        except (Product.DoesNotExist, ValueError) as exc:
            raise ValidationError("Un article du kit n'appartient pas a cette salle.") from exc
        propres[produit] = propres.get(produit, 0) + quantite

    offer.items.all().delete()
    for produit, quantite in propres.items():
        OfferItem.objects.create(offer=offer, product=produit, quantity=quantite)
    return list(offer.items.select_related("product"))


# ---------------------------------------------------------------------------
# Les gestes
# ---------------------------------------------------------------------------


def crediter(subscription, par=None):
    """
    Credite le kit de la formule, a chaque paiement - renouvellement compris.

    Un meme article present dans deux offres de la formule s'additionne en un
    seul credit. Un article retire du stock actif n'est pas credite : il ne
    pourrait pas etre remis.
    """
    plan = subscription.plan
    if plan is None:
        return []

    quantites = OrderedDict()
    articles = (
        OfferItem.objects.filter(
            offer__in=plan.offers.filter(is_active=True),
            offer__gym=subscription.gym,
            product__gym=subscription.gym,
            product__is_active=True,
        )
        .select_related("product")
        .order_by("product__name")
    )
    for article in articles:
        quantites[article.product] = quantites.get(article.product, 0) + article.quantity

    return [
        BenefitMovement.objects.create(
            gym=subscription.gym,
            member=subscription.member,
            product=produit,
            quantity=quantite,
            kind=BenefitMovement.KIND_CREDIT,
            subscription=subscription,
            created_by=par,
        )
        for produit, quantite in quantites.items()
        if quantite > 0
    ]


@transaction.atomic
def reprendre_kit(subscription, motif="", par=None):
    """
    Reprend le kit credite par une vente annulee.

    Un article deja remis ne se reprend pas : la salle a livre la marchandise,
    et ce qui est pris ne se reprend plus. L'annulation est alors refusee -
    mieux vaut un geste qui reste qu'un solde qui ment.
    """
    deja_remis = BenefitMovement.objects.filter(
        subscription=subscription, kind=BenefitMovement.KIND_REMISE
    ).exists()
    if deja_remis:
        raise ValidationError(
            "Des articles de ce kit ont deja ete remis au membre : ce geste ne "
            "peut plus etre annule."
        )

    credits = BenefitMovement.objects.filter(
        subscription=subscription, kind=BenefitMovement.KIND_CREDIT, cancellations__isnull=True
    ).select_related("product", "member", "gym")

    return [
        BenefitMovement.objects.create(
            gym=credit.gym,
            member=credit.member,
            product=credit.product,
            quantity=-credit.quantity,
            kind=BenefitMovement.KIND_ANNULATION,
            subscription=subscription,
            cancels=credit,
            reason=(motif or "")[:255],
            created_by=par,
        )
        for credit in credits
    ]


def solde(member, product):
    """Ce qu'il reste de cet article au membre : la somme de son journal."""
    return (
        BenefitMovement.objects.filter(gym=member.gym, member=member, product=product)
        .aggregate(total=Sum("quantity"))["total"]
        or 0
    )


@transaction.atomic
def remettre(member, product_id, quantite, par=None):
    """
    Remet au comptoir un article du solde.

    Ce qui est pris ne se recredite pas avant le prochain paiement. Un solde
    sans abonnement actif, ou un article en rupture, est conserve intact : le
    membre ne perd rien parce qu'on ne peut pas le servir aujourd'hui.
    """
    try:
        quantite = int(quantite)
    except (TypeError, ValueError) as exc:
        raise ValidationError("La quantite est invalide.") from exc
    if quantite < 1:
        raise ValidationError("La quantite doit etre d'au moins un article.")

    abonnement = member.active_subscription
    if abonnement is None:
        raise ValidationError(
            "Ce membre n'a pas d'abonnement actif : son solde est conserve et "
            "redeviendra utilisable a son prochain paiement."
        )

    try:
        # Le verrou sur l'article serialise deux remises simultanees : sans lui,
        # deux clics rapides pourraient chacun lire le meme solde.
        produit = Product.objects.select_for_update().get(id=product_id, gym=member.gym)
    except (Product.DoesNotExist, ValueError) as exc:
        raise ValidationError("Article introuvable dans cette salle.") from exc

    disponible = solde(member, produit)
    if quantite > disponible:
        raise ValidationError(
            f"Il ne reste que {disponible} {produit.name} au solde de ce membre."
        )

    if produit.quantity < quantite:
        raise ValidationError(
            f"Stock insuffisant : {produit.quantity} {produit.name} en stock. "
            "Le solde du membre n'est pas touche."
        )

    produit.update_stock(quantite, "out", f"{MOTIF_STOCK_REMISE} : {_nom_membre(member)}")

    return BenefitMovement.objects.create(
        gym=member.gym,
        member=member,
        product=produit,
        quantity=-quantite,
        kind=BenefitMovement.KIND_REMISE,
        subscription=abonnement,
        created_by=par,
    )


@transaction.atomic
def annuler(remise, motif, par=None):
    """
    Corrige une remise saisie par erreur : le jour meme, et avec un motif.

    L'article revient en stock et au solde. La remise et son annulation restent
    toutes deux au journal. Passe le jour, les comptes sont clos : une remise
    d'hier ne s'annule plus.
    """
    remise = BenefitMovement.objects.select_for_update().select_related(
        "member", "product", "gym"
    ).get(pk=remise.pk)

    if remise.kind != BenefitMovement.KIND_REMISE:
        raise ValidationError("Seule une remise peut etre annulee.")

    motif = (motif or "").strip()
    if not motif:
        raise ValidationError(
            "Le motif est obligatoire : une annulation corrige une erreur de "
            "saisie, elle doit dire laquelle."
        )

    if timezone.localtime(remise.created_at).date() != timezone.localdate():
        raise ValidationError(
            "Une remise ne s'annule que le jour meme : passe ce delai, les "
            "comptes du jour sont clos."
        )

    if remise.cancellations.exists():
        raise ValidationError("Cette remise a deja ete annulee.")

    produit = Product.objects.select_for_update().get(pk=remise.product_id)
    quantite = -remise.quantity
    produit.update_stock(
        quantite, "in", f"{MOTIF_STOCK_ANNULATION} : {_nom_membre(remise.member)}"
    )

    return BenefitMovement.objects.create(
        gym=remise.gym,
        member=remise.member,
        product=produit,
        quantity=quantite,
        kind=BenefitMovement.KIND_ANNULATION,
        subscription=remise.subscription,
        cancels=remise,
        reason=motif[:255],
        created_by=par,
    )


# ---------------------------------------------------------------------------
# Les lectures
# ---------------------------------------------------------------------------


def etat(member):
    """
    Ce que montrent le scan et la fiche : les soldes, et les remises du jour.

    Une remise du jour porte son adresse d'annulation ; au-dela, elle n'est
    plus annulable et n'apparait plus ici.
    """
    abonne = member.active_subscription is not None

    lignes = (
        BenefitMovement.objects.filter(gym=member.gym, member=member)
        .values("product_id", "product__name", "product__quantity")
        .annotate(solde=Sum("quantity"))
        .order_by("product__name")
    )
    soldes = [
        {
            "product_id": ligne["product_id"],
            "nom": ligne["product__name"],
            "solde": ligne["solde"],
            "en_stock": ligne["product__quantity"],
            "remettable": abonne and ligne["product__quantity"] > 0,
        }
        for ligne in lignes
        if ligne["solde"] > 0
    ]

    remises = (
        BenefitMovement.objects.filter(
            gym=member.gym,
            member=member,
            kind=BenefitMovement.KIND_REMISE,
            created_at__date=timezone.localdate(),
        )
        .select_related("product", "created_by")
        .prefetch_related("cancellations")
        .order_by("-created_at")
    )
    remises_du_jour = []
    for remise in remises:
        auteur = remise.created_by
        remises_du_jour.append({
            "id": remise.id,
            "nom": remise.product.name,
            "quantite": -remise.quantity,
            "heure": timezone.localtime(remise.created_at).strftime("%H:%M"),
            "par": (auteur.get_full_name() or auteur.username) if auteur else "",
            "annulee": bool(list(remise.cancellations.all())),
            "url_annuler": reverse("subscriptions:annuler_avantage", args=[remise.id]),
        })

    return {
        "abonnement_actif": abonne,
        "soldes": soldes,
        "remises_du_jour": remises_du_jour,
        "url_remettre": reverse("subscriptions:remettre_avantage", args=[member.id]),
    }


def offerts_sur_periode(gym, debut, fin):
    """
    Ce que les avantages ont fait sortir du stock sur la periode.

    Ni une recette ni une depense : c'est ce que l'avantage coute en
    marchandise. Valorise au prix de vente - le stock ne connait pas de prix
    d'achat. Un article en dollars sans taux de change connu est compte en
    quantite, et la valeur le signale comme incomplete plutot que de l'ignorer
    en silence.
    """
    from pos.models import ExchangeRate

    lignes = list(
        BenefitMovement.objects.filter(
            gym=gym,
            kind__in=[BenefitMovement.KIND_REMISE, BenefitMovement.KIND_ANNULATION],
            created_at__date__range=(debut, fin),
        )
        .values("product_id", "product__name")
        .annotate(total=Sum("quantity"))
        .order_by("product__name")
    )
    produits = Product.objects.in_bulk([ligne["product_id"] for ligne in lignes])
    taux = ExchangeRate.objects.filter(gym=gym).order_by("-date", "-created_at").first()

    articles = []
    valeur = Decimal("0.00")
    valeur_complete = True
    for ligne in lignes:
        # Remises negatives, annulations positives : leur somme retournee donne
        # ce qui est reellement sorti.
        quantite = -(ligne["total"] or 0)
        if quantite <= 0:
            continue
        articles.append({"nom": ligne["product__name"], "quantite": quantite})
        try:
            prix = produits[ligne["product_id"]].price_in("CDF", taux.rate if taux else None)
        except (ValueError, KeyError):
            valeur_complete = False
            continue
        valeur += prix * quantite

    return {
        "articles": articles,
        "valeur_cdf": valeur,
        "valeur_complete": valeur_complete,
    }

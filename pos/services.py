from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from products.models import Product
from subscriptions.models import MemberSubscription

from .models import CashRegister, Payment, _money


# Un abonnement se paie d'avance, mais pas indefiniment : au-dela, une date
# est plus probablement une faute de frappe qu'une intention.
DELAI_DEBUT_FUTUR_MAX = 90


def _to_decimal(value, field_label="Montant"):
    try:
        return Decimal(str(value or "0"))
    except Exception as exc:
        raise ValidationError(f"{field_label} invalide.") from exc


def get_open_register(gym, user=None):
    registers = CashRegister.objects.filter(gym=gym, is_closed=False)
    if user is not None:
        registers = registers.filter(opened_by=user)
    register = registers.first()
    if not register:
        if user is not None:
            raise ValidationError("Aucune caisse ouverte pour cet utilisateur. Ouvrez votre session POS avant tout mouvement financier.")
        raise ValidationError("Aucune caisse ouverte. Ouvrez une session POS avant tout mouvement financier.")
    if not register.exchange_rate or register.exchange_rate <= 0:
        raise ValidationError("La caisse ouverte n'a pas de taux USD-CDF valide.")
    return register


def _caisse_cible(gym, utilisateur):
    """
    La caisse dans laquelle cet argent va physiquement entrer.

    Celui qui tient un tiroir y remet ce qu'il n'a pas depense. Mais un gerant
    qui apporte des fonds n'a pas de caisse a lui : l'argent va dans celle qui
    est ouverte. Quand plusieurs le sont, personne ne peut deviner laquelle -
    on demande alors de choisir plutot que d'en tirer une au hasard.
    """
    sienne = CashRegister.objects.filter(
        gym=gym, is_closed=False, opened_by=utilisateur
    ).first()
    if sienne is not None:
        return sienne

    ouvertes = list(CashRegister.objects.filter(gym=gym, is_closed=False)[:2])
    if not ouvertes:
        raise ValidationError(
            "Aucune caisse ouverte. Ouvrez une session avant tout mouvement."
        )
    if len(ouvertes) > 1:
        raise ValidationError(
            "Plusieurs caisses sont ouvertes : precisez celle qui recoit "
            "l'argent."
        )
    return ouvertes[0]


def record_payment(
    *,
    gym,
    amount,
    currency,
    method,
    transaction_type,
    category,
    register=None,
    member=None,
    subscription=None,
    product=None,
    description="",
    amount_usd=None,
    created_by=None,
    source_app="",
    source_model="",
    source_id=None,
    status="success",
    refund_of=None,
):
    register = register or get_open_register(gym, created_by)
    if register.gym_id != gym.id:
        raise ValidationError("La caisse n'appartient pas a ce gym.")
    if register.is_closed:
        raise ValidationError("Impossible d'enregistrer un mouvement sur une caisse fermee.")

    return Payment.objects.create(
        gym=gym,
        cash_register=register,
        refund_of=refund_of,
        member=member,
        subscription=subscription,
        product=product,
        amount=_to_decimal(amount),
        amount_usd=_to_decimal(amount_usd, "Montant USD") if amount_usd is not None else None,
        currency=currency,
        exchange_rate=register.exchange_rate,
        method=method,
        type=transaction_type,
        category=category,
        status=status,
        description=description,
        source_app=source_app,
        source_model=source_model,
        source_id=source_id,
        created_by=created_by,
    )


def record_subscription_payment(
    *,
    gym,
    member,
    plan,
    currency,
    method,
    start_date=None,
    auto_renew=False,
    confirm_closed_period=False,
    created_by=None,
):
    if member.gym_id != gym.id:
        raise ValidationError("Le membre n'appartient pas a ce gym.")
    if plan.gym_id != gym.id:
        raise ValidationError("La formule d'abonnement n'appartient pas a ce gym.")
    if not member.is_active:
        raise ValidationError("Le membre doit etre actif pour acheter un abonnement.")

    register = get_open_register(gym, created_by)
    today = timezone.localdate()
    start = start_date or today

    # Un abonnement peut se payer d'avance pour demarrer plus tard. La borne
    # attrape les fautes de frappe : une annee erronee creerait un abonnement
    # fantome que personne ne remarquerait avant des mois.
    if start > today + timedelta(days=DELAI_DEBUT_FUTUR_MAX):
        raise ValidationError(
            "La date de debut ne peut pas depasser "
            f"{DELAI_DEBUT_FUTUR_MAX // 30} mois. Verifiez l'annee saisie."
        )

    en_cours = (
        MemberSubscription.objects.filter(
            gym=gym,
            member=member,
            is_active=True,
            end_date__gte=today,
        )
        .order_by("-end_date")
        .first()
    )

    # Une date choisie dans le futur, mais tombant au milieu de l'abonnement en
    # cours, ferait payer deux fois les memes jours. On refuse en indiquant la
    # premiere date libre plutot que de laisser le caissier deviner.
    #
    # Un debut aujourd'hui n'est pas concerne : c'est le renouvellement
    # anticipe, ou les jours restants sont reportes. Le formulaire preremplit
    # d'ailleurs ce champ a la date du jour.
    if start > today and en_cours and start <= en_cours.end_date:
        libre = en_cours.end_date + timedelta(days=1)
        raise ValidationError(
            f"Cet abonnement court jusqu'au {en_cours.end_date.strftime('%d/%m/%Y')}. "
            f"Choisissez le {libre.strftime('%d/%m/%Y')}, ou laissez la date vide "
            "pour prolonger l'abonnement en cours."
        )

    # Renouvellement anticipe sans date imposee : le nouvel abonnement
    # prolonge le temps qui restait au lieu de l'effacer. Le membre ne perd
    # aucun jour deja paye.
    absorbe = en_cours if (en_cours and start <= en_cours.end_date) else None
    carried_over_days = (absorbe.end_date - start).days if absorbe else 0
    end = start + timedelta(days=plan.duration_days + carried_over_days)

    # Une periode deja terminee au moment de la vente est presque toujours une
    # faute de saisie : le membre paie et n'a aucun acces, sans que rien ne le
    # signale. On ne la refuse pas - regulariser une vente ancienne est
    # legitime - mais elle doit etre assumee.
    #
    # Seule la periode close alerte : une date passee est souvent normale, et
    # interdire toutes les dates passees a deja casse le renouvellement
    # anticipe dans ce projet.
    if end < today and not confirm_closed_period:
        raise ValidationError(
            f"Cette periode s'est terminee le {end:%d/%m/%Y} : le membre "
            "n'aura aucun acces. Cochez la confirmation s'il s'agit d'une "
            "regularisation.",
            code="periode_close",
        )

    amount_usd = _money(plan.price)
    amount = amount_usd if currency == "USD" else _money(amount_usd * register.exchange_rate)

    with transaction.atomic():
        # On clot ce que le nouvel abonnement remplace : les periodes qui le
        # chevauchent, et celles deja terminees qui trainaient encore marquees
        # actives. Un abonnement qui demarre apres celui-ci est preserve : le
        # desactiver laisserait le membre a la porte d'ici la.
        MemberSubscription.objects.filter(
            gym=gym, member=member, is_active=True
        ).filter(
            Q(start_date__lte=end, end_date__gte=start) | Q(end_date__lt=today)
        ).update(is_active=False)

        subscription = MemberSubscription.objects.create(
            gym=gym,
            member=member,
            plan=plan,
            start_date=start,
            end_date=end,
            auto_renew=auto_renew,
            is_active=True,
        )

        payment = record_payment(
            gym=gym,
            register=register,
            member=member,
            subscription=subscription,
            amount=amount,
            amount_usd=amount_usd,
            currency=currency,
            method=method,
            transaction_type="in",
            category="subscription",
            description=f"Abonnement: {plan.name}",
            created_by=created_by,
            source_app="subscriptions",
            source_model="MemberSubscription",
            source_id=subscription.id,
        )

        # Le kit de la formule, credite dans la meme transaction que la vente :
        # un paiement sans son kit, ou un kit sans paiement, ne doit pas pouvoir
        # exister. Renouvellements compris.
        from subscriptions import avantages

        avantages.crediter(subscription, par=created_by)

        # Une demande faite depuis le portail pour cette formule est reglee.
        # Rien ne la marquait comme payee : apres la vente au comptoir, le
        # membre continuait de la voir en attente.
        from subscriptions.models import SubscriptionRequest

        SubscriptionRequest.objects.filter(
            gym=gym,
            member=member,
            plan=plan,
            status__in=[
                SubscriptionRequest.STATUS_PENDING,
                SubscriptionRequest.STATUS_AWAITING_PAYMENT,
            ],
        ).update(status=SubscriptionRequest.STATUS_PAID, updated_at=timezone.now())

    # Le lecteur porte ses propres dates de validite : il doit apprendre la
    # nouvelle echeance tout de suite. propager() ne leve jamais, un lecteur
    # debranche ne doit pas empecher d'encaisser.
    from access import enrollment

    enrollment.propager(member)

    return subscription, payment


def record_product_sale(*, gym, product, quantity, currency, method, created_by=None, member=None):
    try:
        quantity = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValidationError("La quantite vendue est invalide.") from exc
    if quantity <= 0:
        raise ValidationError("La quantite vendue doit etre superieure a zero.")

    register = get_open_register(gym, created_by)

    with transaction.atomic():
        try:
            product = Product.objects.select_for_update().get(
                id=product.id,
                gym=gym,
                is_active=True,
            )
        except Product.DoesNotExist as exc:
            raise ValidationError("Produit introuvable pour ce gym.") from exc

        # Le prix du produit peut etre fixe en francs : on part de sa propre
        # devise et on convertit vers celle de l'encaissement, au taux de la
        # session. Supposer le dollar facturait un prix faux aux produits CDF.
        try:
            amount = _money(product.price_in(currency, register.exchange_rate) * quantity)
            amount_usd = _money(product.price_usd(register.exchange_rate) * quantity)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        try:
            product.update_stock(quantity, "out", "Vente POS")
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        payment = record_payment(
            gym=gym,
            register=register,
            member=member,
            product=product,
            amount=amount,
            amount_usd=amount_usd,
            currency=currency,
            method=method,
            transaction_type="in",
            category="product",
            description=f"Vente produit: {product.name} x{quantity}",
            created_by=created_by,
            source_app="products",
            source_model="Product",
            source_id=product.id,
        )

    return payment


def record_expense(
    *,
    gym,
    amount,
    currency="CDF",
    method="cash",
    category="expense",
    description="",
    created_by=None,
    source_app="",
    source_model="",
    source_id=None,
):
    """
    Sortie de caisse, saisie dans la devise reellement decaissee.

    Le tiroir contient les deux devises : obliger a convertir avant la saisie
    faisait porter au caissier une conversion que le logiciel sait faire, et
    l'ecart de conversion se retrouvait dans l'ecart de cloture. Le montant en
    CDF est recalcule par le modele a partir du taux de la session.
    """
    if currency not in {"CDF", "USD"}:
        raise ValidationError("Devise de decaissement invalide.")

    return record_payment(
        gym=gym,
        amount=amount,
        currency=currency,
        method=method,
        transaction_type="out",
        category=category,
        description=description,
        created_by=created_by,
        source_app=source_app,
        source_model=source_model,
        source_id=source_id,
    )


def record_expense_refund(
    *,
    gym,
    expense,
    amount,
    currency,
    method="cash",
    description="",
    created_by=None,
):
    """
    Remet dans le tiroir l'argent d'un decaissement qui n'a pas abouti.

    La course n'a pas eu lieu, ou elle a coute moins cher que prevu. La sortie
    d'origine n'est pas corrigee : elle a bien eu lieu, et un comptage
    intermediaire deja contre-signe la retrouverait. Le retour s'y rattache.

    Ce mouvement remplit la caisse **sans etre une recette** : la salle n'a
    rien gagne, elle recupere ce qu'elle avait avance.
    """
    if expense.gym_id != gym.id:
        raise ValidationError("Ce decaissement n'appartient pas a ce gym.")
    if expense.type != "out":
        raise ValidationError("On ne rend que de l'argent sorti de la caisse.")
    if expense.status != "success":
        raise ValidationError("Ce decaissement n'a pas abouti.")

    amount = _money(amount)
    if amount <= 0:
        raise ValidationError("Le montant rendu doit etre superieur a zero.")

    register = _caisse_cible(gym, created_by)

    montant_cdf = (
        amount if currency == "CDF" else _money(amount * register.exchange_rate)
    )
    reste = expense.reste_a_rendre
    # On ne rend pas plus qu'on n'a pris : au-dela, ce n'est plus un retour,
    # c'est un apport - et il ne se justifie pas de la meme facon.
    if montant_cdf > reste:
        raise ValidationError(
            f"Ce decaissement de {expense.amount_cdf:.0f} CDF n'a plus que "
            f"{reste:.0f} CDF a rendre. Pour ajouter de l'argent au-dela, "
            "utilisez un apport en caisse."
        )

    motif = (description or "").strip() or (
        f'Retour sur : {expense.description or "decaissement"}'
    )

    return record_payment(
        gym=gym,
        register=register,
        amount=amount,
        currency=currency,
        method=method,
        transaction_type="in",
        category="expense_refund",
        description=motif,
        created_by=created_by,
        source_app="pos",
        source_model="ExpenseRefund",
        source_id=expense.id,
        refund_of=expense,
    )


def record_cash_injection(
    *,
    gym,
    amount,
    currency,
    method="cash",
    description="",
    created_by=None,
):
    """
    Fait entrer de l'argent neuf dans la caisse.

    Un renfort de fonds en cours de journee, quand le tiroir ne suffit plus a
    rendre la monnaie. Ce n'est ni une vente ni un retour : la salle n'a rien
    gagne, elle a mis de l'argent dedans. Le solde theorique augmente donc, et
    le chiffre d'affaires ne bouge pas.
    """
    amount = _money(amount)
    if amount <= 0:
        raise ValidationError("Le montant apporte doit etre superieur a zero.")

    motif = (description or "").strip()
    if not motif:
        raise ValidationError(
            "Le motif est obligatoire : un apport augmente le montant que le "
            "caissier devra retrouver dans le tiroir."
        )

    register = _caisse_cible(gym, created_by)

    return record_payment(
        gym=gym,
        register=register,
        amount=amount,
        currency=currency,
        method=method,
        transaction_type="in",
        category="cash_injection",
        description=motif,
        created_by=created_by,
        source_app="pos",
        source_model="CashInjection",
    )

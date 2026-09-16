from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone

from members.models import Member
from products.models import Product
from subscriptions.models import SubscriptionPlan
from smartclub.access_control import (
    POS_CASHIER_ROLES,
    POS_HISTORY_ROLES,
    SETTINGS_ORGANIZATION_ROLES,
    has_role,
)
from smartclub.decorators import module_required, role_required
from core.audit import log_sensitive_action

from .models import CashRegister, ExchangeRate, Payment
from . import validation
from .services import (
    annuler_geste_offert,
    record_cash_injection,
    record_expense,
    record_expense_refund,
    record_product_sale,
    record_subscription_payment,
)


# Assez pour lire un mois d'un coup d'oeil, assez peu pour que la page reste
# legere sur un telephone.
DECAISSEMENTS_PAR_PAGE = 50

# Une session de caisse tient sur une ligne large : cinquante par page suffisent
# a couvrir un mois de trois caissiers.
CAISSES_PAR_PAGE = 50


def _media_url(request, file_field, fallback=""):
    if not file_field:
        return fallback
    try:
        return request.build_absolute_uri(file_field.url)
    except ValueError:
        return fallback


def _to_decimal(value, field_label):
    try:
        return Decimal(str(value or "0"))
    except Exception as exc:
        raise ValidationError(f"{field_label} invalide.") from exc


# Nombre de clients renvoyes par la recherche du caissier. Assez pour
# choisir sans faire defiler, assez peu pour rester lisible au comptoir.
MEMBER_SEARCH_LIMIT = 12


def _validation_message(exc):
    return exc.messages[0] if getattr(exc, "messages", None) else str(exc)


@login_required
@role_required(POS_CASHIER_ROLES)
@module_required("POS")
def search_members(request):
    """
    Clients correspondant a la saisie du caissier.

    La liste complete n'est plus rendue dans la page : une salle qui grandit
    ferait grossir la caisse a chaque chargement. On interroge ici a la
    frappe, et on ne renvoie qu'une poignee de resultats.

    ``total`` permet a l'ecran de dire qu'il en existe d'autres, plutot que de
    laisser croire que la recherche a tout trouve.
    """
    query = (request.GET.get("q") or "").strip()

    resultats = Member.objects.filter(gym=request.gym, is_active=True)
    if query:
        resultats = resultats.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(phone__icontains=query)
        )

    total = resultats.count()
    # Un nom trop court ramenerait la moitie du fichier : on borne, et on
    # ordonne pour que deux recherches identiques donnent le meme ordre.
    members = resultats.order_by("first_name", "last_name", "id")[:MEMBER_SEARCH_LIMIT]

    data = [
        {
            "id": member.id,
            "name": f"{member.first_name} {member.last_name}",
            "phone": member.phone,
            "status": member.computed_status,
            "photo": _media_url(request, member.photo, "/static/avatar/1.png"),
        }
        for member in members
    ]

    return JsonResponse({
        "members": data,
        "total": total,
        "tronque": total > len(data),
    })


@login_required
@role_required(POS_CASHIER_ROLES)
@module_required("POS")
def cashier_dashboard(request):
    gym = request.gym
    register = CashRegister.objects.filter(gym=gym, is_closed=False, opened_by=request.user).first()

    if request.method == "POST":
        # Offrir : aucun argent ne change de main, mais un abonnement ou une
        # marchandise part. Le proprietaire seul en decide, et il n'a pas
        # forcement de caisse a lui : le service prend alors celle qui est
        # ouverte dans la salle, comme pour un apport de fonds.
        offert = request.POST.get("offert") == "on"
        if offert and not has_role(request, SETTINGS_ORGANIZATION_ROLES):
            raise PermissionDenied

        if not register and not offert:
            messages.error(request, "Aucune caisse ouverte.")
            return redirect("pos:cashier_dashboard")

        if register and not register.exchange_rate:
            messages.error(
                request,
                "Cette session de caisse n'a pas de taux USD-CDF. Fermez-la puis ouvrez une nouvelle session.",
            )
            return redirect("pos:cashier_dashboard")

        transaction_type = request.POST.get("type", "in")
        method = request.POST.get("method", "cash")

        if transaction_type == "out":
            expense_currency = request.POST.get("expense_currency", "CDF")
            if expense_currency not in {"USD", "CDF"}:
                messages.error(request, "Devise invalide.")
                return redirect("pos:cashier_dashboard")

            try:
                montant = _to_decimal(request.POST.get("amount"), "Montant")
                if montant <= 0:
                    raise ValidationError("Le montant doit etre superieur a zero.")

                depense = record_expense(
                    gym=gym,
                    amount=montant,
                    currency=expense_currency,
                    method="cash",
                    category="expense",
                    description=request.POST.get("description") or "Decaissement",
                    created_by=request.user,
                    source_app="pos",
                    source_model="ManualExpense",
                )
                log_sensitive_action(
                    request,
                    "pos.expense_recorded",
                    "CashRegister",
                    register.session_code or f"register-{register.id}",
                    metadata={
                        "montant_saisi": str(montant),
                        "devise": expense_currency,
                        "amount_cdf": str(depense.amount_cdf),
                        "method": "cash",
                    },
                )
            except ValidationError as exc:
                messages.error(request, _validation_message(exc))
                return redirect("pos:cashier_dashboard")

            messages.success(request, "Decaissement enregistre.")
            return redirect("pos:cashier_dashboard")

        sale_type = request.POST.get("sale_type", "subscription")
        motif_offert = (request.POST.get("motif_offert") or "").strip()
        beneficiaire = (request.POST.get("beneficiaire") or "").strip()
        currency = request.POST.get("currency", "USD")
        if currency not in {"USD", "CDF"}:
            messages.error(request, "Devise invalide.")
            return redirect("pos:cashier_dashboard")

        try:
            if sale_type == "product":
                product = get_object_or_404(
                    Product,
                    id=request.POST.get("product"),
                    gym=gym,
                    is_active=True,
                )
                payment = record_product_sale(
                    gym=gym,
                    product=product,
                    quantity=request.POST.get("quantity"),
                    currency=currency,
                    method=method,
                    created_by=request.user,
                    offert=offert,
                    motif=motif_offert,
                    beneficiaire=beneficiaire,
                )
                log_sensitive_action(
                    request,
                    "pos.product_sale_recorded",
                    "Product",
                    product.name,
                    metadata={
                        "payment_id": payment.id,
                        "product_id": product.id,
                        "currency": payment.currency,
                        "amount": str(payment.amount),
                        "offert": offert,
                        "motif": motif_offert,
                        "beneficiaire": beneficiaire,
                    },
                )
                if offert:
                    messages.success(
                        request,
                        f"Produit offert : {product.name}. Aucun encaissement, "
                        f"valeur {payment.valeur_offerte_cdf} CDF.",
                    )
                else:
                    messages.success(
                        request,
                        f"Vente produit enregistree: {payment.amount} {payment.currency}.",
                    )
            else:
                member = get_object_or_404(Member, id=request.POST.get("member"), gym=gym, is_active=True)
                plan = get_object_or_404(SubscriptionPlan, id=request.POST.get("plan"), gym=gym)
                start_date_raw = request.POST.get("start_date")
                start_date = None
                if start_date_raw:
                    try:
                        start_date = datetime.strptime(start_date_raw, "%Y-%m-%d").date()
                    except ValueError as exc:
                        raise ValidationError("La date de debut est invalide.") from exc
                subscription, payment = record_subscription_payment(
                    gym=gym,
                    member=member,
                    plan=plan,
                    currency=currency,
                    method=method,
                    start_date=start_date,
                    auto_renew=request.POST.get("auto_renew") == "on",
                    confirm_closed_period=(
                        request.POST.get("confirm_closed_period") == "on"
                    ),
                    created_by=request.user,
                    offert=offert,
                    motif=motif_offert,
                )
                log_sensitive_action(
                    request,
                    "pos.subscription_payment_recorded",
                    "Member",
                    f"{member.first_name} {member.last_name}".strip(),
                    metadata={
                        "payment_id": payment.id,
                        "plan_id": plan.id,
                        "currency": payment.currency,
                        "amount": str(payment.amount),
                        "offert": offert,
                        "motif": motif_offert,
                    },
                )
                if offert:
                    messages.success(
                        request,
                        f"Abonnement offert a {member.first_name} {member.last_name} : "
                        f"{plan.name}. Aucun encaissement, valeur "
                        f"{payment.valeur_offerte_cdf} CDF.",
                    )
                else:
                    messages.success(
                        request,
                        f"Paiement abonnement enregistre: {payment.amount} {payment.currency}.",
                    )
        except ValidationError as exc:
            messages.error(request, _validation_message(exc))
            return redirect("pos:cashier_dashboard")

        return redirect("pos:cashier_dashboard")

    # Les clients ne sont plus rendus dans la page : le champ de recherche du
    # nouveau paiement interroge search_members a la frappe. Les charger ici
    # ferait grossir la caisse a chaque ouverture sans que rien ne s'en serve.
    plans = SubscriptionPlan.objects.filter(gym=gym, is_active=True)
    products = Product.objects.filter(gym=gym, is_active=True, quantity__gt=0).order_by("name")
    latest_exchange_rate = ExchangeRate.objects.filter(gym=gym).order_by("-date", "-created_at").first()

    if register:
        payments = (
            Payment.objects.filter(gym=gym, cash_register=register)
            .select_related("member", "subscription", "subscription__plan", "product")
            .order_by("-created_at")[:20]
        )
        entries_today = register.total_entries()
        exits_today = register.total_exits()
        cash_total = register.expected_total()
        non_cash_balance = register.non_cash_balance()
        has_negative_cash = register.has_negative_cash()
    else:
        payments = []
        entries_today = 0
        exits_today = 0
        cash_total = 0
        non_cash_balance = 0
        has_negative_cash = False

    peut_offrir = has_role(request, SETTINGS_ORGANIZATION_ROLES)
    # Les gestes du jour, toutes caisses confondues : celui qui offre n'a pas
    # forcement de caisse a lui, et doit pouvoir se relire - et se corriger.
    gestes_offerts = (
        Payment.objects.filter(
            gym=gym, offert=True, status="success",
            created_at__date=timezone.localdate(),
        )
        .select_related("member", "product")
        .order_by("-created_at")
        if peut_offrir
        else []
    )

    return render(
        request,
        "pos/cashier.html",
        {
            "gestes_offerts": gestes_offerts,
            "plans": plans,
            "products": products,
            "payments": payments,
            "register": register,
            "today_total": cash_total,
            "today_entries": entries_today,
            "today_exits": exits_today,
            "non_cash_balance": non_cash_balance,
            "has_negative_cash": has_negative_cash,
            "latest_exchange_rate": latest_exchange_rate,
            "peut_offrir": peut_offrir,
        },
    )


@login_required
@role_required(POS_CASHIER_ROLES)
@module_required("POS")
@require_POST
def annuler_offert(request, payment_id):
    """Annule un geste offert du jour. Proprietaire seul, motif obligatoire."""
    if not has_role(request, SETTINGS_ORGANIZATION_ROLES):
        raise PermissionDenied

    paiement = get_object_or_404(Payment, id=payment_id, gym=request.gym, offert=True)
    motif = (request.POST.get("motif") or "").strip()

    try:
        annuler_geste_offert(paiement, motif, par=request.user)
    except ValidationError as exc:
        messages.error(request, _validation_message(exc))
        return redirect("pos:cashier_dashboard")

    log_sensitive_action(
        request,
        "pos.gift_cancelled",
        "Payment",
        paiement.description or f"paiement-{paiement.id}",
        metadata={
            "payment_id": paiement.id,
            "motif": motif,
            "valeur": str(paiement.valeur_offerte_cdf),
        },
    )
    messages.success(request, "Geste offert annule.")
    return redirect("pos:cashier_dashboard")


@login_required
@role_required(POS_CASHIER_ROLES)
@module_required("POS")
def open_register(request):
    if request.method != "POST":
        return redirect("pos:cashier_dashboard")

    existing = CashRegister.objects.filter(gym=request.gym, is_closed=False, opened_by=request.user).first()
    if existing:
        messages.warning(request, "Vous avez deja une caisse ouverte.")
        return redirect("pos:cashier_dashboard")

    try:
        opening_amount = _to_decimal(request.POST.get("opening_amount"), "Fonds d'ouverture")
        exchange_rate = _to_decimal(request.POST.get("exchange_rate"), "Taux USD-CDF")
        if opening_amount < 0:
            raise ValidationError("Le fonds d'ouverture ne peut pas etre negatif.")
        if exchange_rate <= 0:
            raise ValidationError("Le taux USD-CDF doit etre superieur a zero.")
    except ValidationError as exc:
        messages.error(request, _validation_message(exc))
        return redirect("pos:cashier_dashboard")

    try:
        ExchangeRate.objects.update_or_create(
            gym=request.gym,
            date=timezone.localdate(),
            defaults={"rate": exchange_rate},
        )
        register = CashRegister.objects.create(
            gym=request.gym,
            opened_by=request.user,
            opening_amount=opening_amount,
            exchange_rate=exchange_rate,
        )
        log_sensitive_action(
            request,
            "pos.register_opened",
            "CashRegister",
            register.session_code or f"register-{register.id}",
            metadata={
                "opening_amount": str(opening_amount),
                "exchange_rate": str(exchange_rate),
            },
        )
    except ValidationError as exc:
        messages.error(request, _validation_message(exc))
        return redirect("pos:cashier_dashboard")

    messages.success(request, "Caisse ouverte avec succes.")
    return redirect("pos:cashier_dashboard")


@login_required
@role_required(POS_CASHIER_ROLES)
@module_required("POS")
def close_register(request, register_id):
    # Un caissier ne ferme que sa propre caisse. Gerants et proprietaires
    # peuvent forcer la cloture : sans cela, une caisse laissee ouverte par
    # quelqu'un qui a quitte son poste restait bloquee indefiniment, et son
    # titulaire ne pouvait plus en ouvrir une nouvelle.
    can_force_close = has_role(request, POS_HISTORY_ROLES)

    lookup = {
        "id": register_id,
        "gym": request.gym,
        "is_closed": False,
    }
    if not can_force_close:
        lookup["opened_by"] = request.user

    register = get_object_or_404(CashRegister, **lookup)
    is_forced = register.opened_by_id != request.user.id

    entries = register.total_entries()
    exits = register.total_exits()
    expected_total = register.expected_total()
    non_cash_entries = register.non_cash_entries()
    non_cash_exits = register.non_cash_exits()

    if request.method == "POST":
        try:
            real_amount = _to_decimal(request.POST.get("real_amount"), "Montant reel")
            if real_amount < 0:
                raise ValidationError("Le montant reel ne peut pas etre negatif.")
        except ValidationError as exc:
            messages.error(request, _validation_message(exc))
            return redirect("pos:close_register", register_id=register.id)

        difference = real_amount - expected_total
        register.closing_amount = real_amount
        register.closed_by = request.user
        register.closed_at = timezone.now()
        register.is_closed = True
        register.difference = difference
        register.save()
        log_sensitive_action(
            request,
            "pos.register_closed",
            "CashRegister",
            register.session_code or f"register-{register.id}",
            metadata={
                "real_amount": str(real_amount),
                "difference": str(difference),
                "forced": is_forced,
                "opened_by": register.opened_by.username if register.opened_by else "",
            },
        )

        if is_forced:
            titulaire = (
                register.opened_by.get_full_name() or register.opened_by.username
                if register.opened_by
                else "un utilisateur supprime"
            )
            messages.success(
                request,
                f"Caisse de {titulaire} cloturee d'autorite. "
                f"Difference : {difference} CDF. L'ecart reste attribue a son titulaire.",
            )
        else:
            messages.success(request, f"Caisse fermee. Difference : {difference} CDF")
        return redirect("pos:cashier_dashboard")

    return render(
        request,
        "pos/close_register.html",
        {
            "register": register,
            "expected_total": expected_total,
            "entries": entries,
            "exits": exits,
            "cash_entries": register.cash_entries(),
            "cash_exits": register.cash_exits(),
            "non_cash_entries": non_cash_entries,
            "non_cash_exits": non_cash_exits,
            "non_cash_balance": register.non_cash_balance(),
            "has_negative_cash": register.has_negative_cash(),
            "is_forced_closure": is_forced,
        },
    )


@login_required
@role_required(POS_HISTORY_ROLES)
@module_required("POS")
def register_history(request):
    registers = CashRegister.objects.filter(gym=request.gym, is_closed=True)

    search = request.GET.get("search", "").strip()
    status = request.GET.get("status", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    sort = request.GET.get("sort", "recent").strip()

    if status == "open":
        registers = CashRegister.objects.filter(gym=request.gym, is_closed=False)
    elif status == "closed":
        registers = registers.filter(is_closed=True)

    if search:
        registers = registers.filter(
            Q(session_code__icontains=search)
            | Q(opened_by__username__icontains=search)
            | Q(opened_by__first_name__icontains=search)
            | Q(opened_by__last_name__icontains=search)
        )

    if date_from:
        registers = registers.filter(opened_at__date__gte=date_from)
    if date_to:
        registers = registers.filter(opened_at__date__lte=date_to)

    if sort == "oldest":
        registers = registers.order_by("closed_at")
    elif sort == "difference_desc":
        registers = registers.order_by("-difference", "-closed_at")
    elif sort == "difference_asc":
        registers = registers.order_by("difference", "-closed_at")
    else:
        registers = registers.order_by("-closed_at")

    all_registers = CashRegister.objects.filter(gym=request.gym)

    # Une a trois sessions par jour : au bout d'un an, la page en deroulait des
    # centaines, chacune sur onze colonnes.
    pages = Paginator(registers, CAISSES_PAR_PAGE)
    page = pages.get_page(request.GET.get("page"))

    parametres = request.GET.copy()
    parametres.pop("page", None)

    return render(
        request,
        "pos/register_history.html",
        {
            "registers": page,
            "page": page,
            "filtres_conserves": parametres.urlencode(),
            "sessions_trouvees": pages.count,
            "search": search,
            "status": status,
            "date_from": date_from,
            "date_to": date_to,
            "sort": sort,
            "positive_count": all_registers.filter(difference__gt=0).count(),
            "negative_count": all_registers.filter(difference__lt=0).count(),
            "open_count": all_registers.filter(is_closed=False).count(),
        },
    )


@login_required
@role_required(POS_HISTORY_ROLES)
@module_required("POS")
def register_detail(request, register_id):
    register = get_object_or_404(CashRegister, id=register_id, gym=request.gym)
    payments = (
        Payment.objects.filter(gym=request.gym, cash_register=register)
        .select_related("member", "subscription", "subscription__plan", "product", "created_by")
        .order_by("-created_at")
    )

    return render(
        request,
        "pos/register_detail.html",
        {
            "register": register,
            "payments": payments,
        },
    )


# ---------------------------------------------------------------------------
# Registre des decaissements
# ---------------------------------------------------------------------------


# Les trois portes par lesquelles l'argent sort : une depense saisie au
# comptoir, un salaire verse, une maintenance payee. Les autres categories
# n'existent qu'en entree.
CATEGORIES_SORTIE = ("expense", "salary", "maintenance", "other")


@login_required
@role_required(POS_HISTORY_ROLES)
@module_required("POS")
def expense_register(request):
    """
    Toutes les sorties d'argent de la salle, au meme endroit.

    Elles etaient jusqu'ici dispersees : melees aux encaissements dans la
    table de la caisse, reparties session par session, et agregees en totaux
    dans les rapports. Relire les depenses d'un mois demandait de les repErer
    a l'oeil, une session apres l'autre.
    """
    aujourd_hui = timezone.localdate()
    defaut_debut = aujourd_hui.replace(day=1)

    depuis = (request.GET.get("date_from") or defaut_debut.isoformat()).strip()
    jusqu_a = (request.GET.get("date_to") or aujourd_hui.isoformat()).strip()
    categorie = (request.GET.get("category") or "").strip()
    methode = (request.GET.get("method") or "").strip()
    recherche = (request.GET.get("search") or "").strip()

    depenses = (
        Payment.objects.filter(gym=request.gym, type="out")
        .select_related("created_by", "cash_register")
        .order_by("-created_at")
    )

    if depuis:
        depenses = depenses.filter(created_at__date__gte=depuis)
    if jusqu_a:
        depenses = depenses.filter(created_at__date__lte=jusqu_a)
    if categorie:
        depenses = depenses.filter(category=categorie)
    if methode:
        depenses = depenses.filter(method=methode)
    if recherche:
        # Le motif est le seul texte libre d'un decaissement : c'est par lui
        # qu'on retrouve une depense dont on ne se rappelle que l'objet.
        depenses = depenses.filter(
            Q(description__icontains=recherche)
            | Q(created_by__username__icontains=recherche)
            | Q(created_by__first_name__icontains=recherche)
            | Q(created_by__last_name__icontains=recherche)
        )

    # Ce que la salle a reellement depense : une sortie de 50 000 dont 20 000
    # sont revenus a coute 30 000. Le brut resterait lisible ligne a ligne,
    # mais un total qui l'ignore surestime les depenses du mois.
    brut = depenses.aggregate(total=Sum("amount_cdf"))["total"] or Decimal("0.00")
    rendu_total = Payment.objects.filter(
        gym=request.gym, refund_of__in=depenses, status="success"
    ).aggregate(total=Sum("amount_cdf"))["total"] or Decimal("0.00")
    total = brut - rendu_total

    # Le detail par categorie repond a la premiere question du gerant : ou est
    # parti l'argent, avant meme de savoir a qui.
    # Deux passes plutot qu'une jointure : additionner les depenses et leurs
    # retours dans la meme requete duplique chaque depense autant de fois
    # qu'elle a de retours, et gonfle le brut. Sum(distinct=True) ne sauve
    # rien - il additionnerait les montants *distincts*, effacant deux
    # depenses de meme valeur.
    rendu_par_categorie = {
        ligne["refund_of__category"]: ligne["total"] or Decimal("0.00")
        for ligne in Payment.objects.filter(
            gym=request.gym, refund_of__in=depenses, status="success"
        )
        .values("refund_of__category")
        .annotate(total=Sum("amount_cdf"))
    }

    par_categorie = [
        {
            "code": ligne["category"],
            "libelle": dict(Payment.CATEGORY_CHOICES).get(
                ligne["category"], ligne["category"] or "Non classe"
            ),
            "nombre": ligne["nombre"],
            "total": (ligne["total"] or Decimal("0.00"))
            - rendu_par_categorie.get(ligne["category"], Decimal("0.00")),
        }
        for ligne in depenses.values("category")
        .annotate(nombre=Count("id"), total=Sum("amount_cdf"))
        .order_by("-total")
    ]

    # Une salle qui tourne sort de l'argent tous les jours : au bout de
    # quelques mois, la liste se compte en centaines de lignes. Elle etait
    # coupee aux 300 plus recentes, et les plus anciennes n'etaient atteignables
    # qu'en resserrant les dates a l'aveugle.
    pages = Paginator(depenses, DECAISSEMENTS_PAR_PAGE)
    page = pages.get_page(request.GET.get("page"))

    # Les liens de pagination gardent les filtres : tourner la page ne doit pas
    # renvoyer au mois en cours.
    parametres = request.GET.copy()
    parametres.pop("page", None)
    filtres_conserves = parametres.urlencode()

    return render(
        request,
        "pos/expense_register.html",
        {
            "expenses": page,
            "page": page,
            "filtres_conserves": filtres_conserves,
            "total_count": pages.count,
            "total_cdf": total,
            "total_brut_cdf": brut,
            "total_rendu_cdf": rendu_total,
            "by_category": par_categorie,
            "categories": [
                (code, libelle)
                for code, libelle in Payment.CATEGORY_CHOICES
                if code in CATEGORIES_SORTIE
            ],
            "methods": Payment.PAYMENT_METHODS,
            "filtre": {
                "date_from": depuis,
                "date_to": jusqu_a,
                "category": categorie,
                "method": methode,
                "search": recherche,
            },
        },
    )


@login_required
@role_required(POS_HISTORY_ROLES)
@module_required("POS")
@require_POST
def validate_register(request, register_id):
    """
    Contre-signature d'une clôture de caisse.

    Clôturer, c'est compter le tiroir ; valider, c'est qu'une seconde personne
    l'ait regarde. Un caissier qui compte seul et signe seul n'est controle
    par personne - et c'est justement ce que le proprietaire demandait.

    Celui qui a clôture ne peut donc pas valider : la signature perdrait son
    objet. Le proprietaire reste libre de valider la clôture d'un gerant, et
    l'inverse.
    """
    registre = get_object_or_404(
        CashRegister, id=register_id, gym=request.gym, is_closed=True
    )

    retour = request.POST.get("next") or "pos:register_history"

    autorise, raison = validation.peut_signer(registre, request.user)
    if not autorise:
        messages.error(request, raison)
        return _retour_validation(request, retour)

    motif = (request.POST.get("validation_note") or "").strip()
    # Un ecart signe sans explication ne vaut rien : dans six mois, personne ne
    # saura s'il s'agissait d'un rendu de monnaie ou d'autre chose. Une caisse
    # juste, elle, se signe d'un clic - et cela vaut pour le gerant comme pour
    # le caissier.
    if validation.motif_requis(registre) and not motif:
        messages.error(
            request,
            "Cette caisse presente un ecart : indiquez ce qui l'explique "
            "avant de signer.",
        )
        return _retour_validation(request, retour)

    besoin = validation.regime(registre)
    registre.validated_by = request.user
    registre.validated_at = timezone.now()
    registre.validation_note = motif
    registre.save(
        update_fields=["validated_by", "validated_at", "validation_note"]
    )

    log_sensitive_action(
        request,
        "pos.register_validated",
        "CashRegister",
        registre.session_code or f"register-{registre.id}",
        metadata={
            "closed_by": (
                registre.closed_by.username if registre.closed_by else ""
            ),
            "regime": besoin,
            "difference": str(registre.difference or 0),
            "note": motif,
        },
    )

    geste = "signalee comme vue" if besoin == validation.ACQUITTEMENT else "validee"
    messages.success(
        request,
        f"Clôture du {timezone.localtime(registre.closed_at):%d/%m/%Y} {geste}.",
    )
    return _retour_validation(request, retour)


def _retour_validation(request, retour):
    """
    La ou l'utilisateur etait.

    Le bandeau du proprietaire s'affiche sur tous les ecrans : le renvoyer a
    l'historique des caisses l'arracherait a ce qu'il faisait.
    """
    if retour.startswith("/"):
        return redirect(retour)
    return redirect(retour)


@login_required
@role_required(POS_CASHIER_ROLES)
@module_required("POS")
@require_POST
def refund_expense(request, payment_id):
    """
    Remet dans la caisse l'argent d'un decaissement qui n'a pas abouti.

    C'est le geste de celui qui tient le tiroir : il est parti avec 50 000, la
    course a coute 30 000, il rend 20 000. Le decaissement d'origine n'est pas
    touche - il a bien eu lieu.
    """
    depense = get_object_or_404(
        Payment, id=payment_id, gym=request.gym, type="out"
    )

    try:
        montant = _to_decimal(request.POST.get("amount"), "Montant")
        devise = request.POST.get("currency", "CDF")
        if devise not in {"USD", "CDF"}:
            raise ValidationError("Devise invalide.")

        retour = record_expense_refund(
            gym=request.gym,
            expense=depense,
            amount=montant,
            currency=devise,
            description=request.POST.get("description") or "",
            created_by=request.user,
        )
    except ValidationError as exc:
        messages.error(request, _validation_message(exc))
        return redirect("pos:expense_register")

    log_sensitive_action(
        request,
        "pos.expense_refunded",
        "Payment",
        depense.description or f"decaissement-{depense.id}",
        metadata={
            "decaissement_id": depense.id,
            "montant_rendu": str(retour.amount_cdf),
            "reste_a_rendre": str(depense.reste_a_rendre),
        },
    )

    messages.success(
        request,
        f"{retour.amount_cdf:.0f} CDF remis en caisse. Cette depense revient a "
        f"{depense.montant_net:.0f} CDF.",
    )
    return redirect("pos:expense_register")


@login_required
@role_required(POS_HISTORY_ROLES)
@module_required("POS")
@require_POST
def inject_cash(request):
    """
    Fait entrer de l'argent neuf dans la caisse.

    Un renfort de fonds quand le tiroir ne suffit plus a rendre la monnaie.
    Reserve au gerant et au proprietaire : cet argent augmente le montant que
    le caissier devra retrouver a la clôture, et engage la salle.
    """
    try:
        montant = _to_decimal(request.POST.get("amount"), "Montant")
        devise = request.POST.get("currency", "CDF")
        if devise not in {"USD", "CDF"}:
            raise ValidationError("Devise invalide.")

        apport = record_cash_injection(
            gym=request.gym,
            amount=montant,
            currency=devise,
            description=request.POST.get("description") or "",
            created_by=request.user,
        )
    except ValidationError as exc:
        messages.error(request, _validation_message(exc))
        return redirect("pos:cashier_dashboard")

    log_sensitive_action(
        request,
        "pos.cash_injected",
        "CashRegister",
        apport.cash_register.session_code if apport.cash_register else "",
        metadata={
            "montant": str(apport.amount_cdf),
            "motif": apport.description,
        },
    )

    messages.success(
        request,
        f"{apport.amount_cdf:.0f} CDF ajoutes en caisse. Le solde theorique "
        "augmente d'autant.",
    )
    return redirect("pos:cashier_dashboard")

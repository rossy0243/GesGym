from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from members.models import Member
from products.models import Product
from subscriptions.models import SubscriptionPlan
from smartclub.access_control import POS_CASHIER_ROLES, POS_HISTORY_ROLES
from smartclub.decorators import role_required

from .models import CashRegister, ExchangeRate, Payment
from .services import record_expense, record_product_sale, record_subscription_payment


def _to_decimal(value, field_label):
    try:
        return Decimal(str(value or "0"))
    except Exception as exc:
        raise ValidationError(f"{field_label} invalide.") from exc


def _validation_message(exc):
    return exc.messages[0] if getattr(exc, "messages", None) else str(exc)


@login_required
@role_required(POS_CASHIER_ROLES)
def search_members(request):
    query = request.GET.get("q", "")
    members = Member.objects.filter(gym=request.gym).filter(
        Q(first_name__icontains=query)
        | Q(last_name__icontains=query)
        | Q(phone__icontains=query)
    )[:10]

    data = [
        {
            "id": member.id,
            "name": f"{member.first_name} {member.last_name}",
            "phone": member.phone,
            "status": member.computed_status,
            "photo": member.photo.url if member.photo else "/static/avatar/1.png",
        }
        for member in members
    ]

    return JsonResponse({"members": data})


@login_required
@role_required(POS_CASHIER_ROLES)
def cashier_dashboard(request):
    gym = request.gym
    register = CashRegister.objects.filter(gym=gym, is_closed=False).first()

    if request.method == "POST":
        if not register:
            messages.error(request, "Aucune caisse ouverte.")
            return redirect("pos:cashier_dashboard")

        if not register.exchange_rate:
            messages.error(
                request,
                "Cette session de caisse n'a pas de taux USD-CDF. Fermez-la puis ouvrez une nouvelle session.",
            )
            return redirect("pos:cashier_dashboard")

        transaction_type = request.POST.get("type", "in")
        method = request.POST.get("method", "cash")

        if transaction_type == "out":
            try:
                amount_cdf = _to_decimal(request.POST.get("amount"), "Montant")
                if amount_cdf <= 0:
                    raise ValidationError("Le montant doit etre superieur a zero.")

                record_expense(
                    gym=gym,
                    amount_cdf=amount_cdf,
                    method="cash",
                    category="expense",
                    description=request.POST.get("description") or "Decaissement",
                    created_by=request.user,
                    source_app="pos",
                    source_model="ManualExpense",
                )
            except ValidationError as exc:
                messages.error(request, _validation_message(exc))
                return redirect("pos:cashier_dashboard")

            messages.success(request, "Decaissement enregistre.")
            return redirect("pos:cashier_dashboard")

        sale_type = request.POST.get("sale_type", "subscription")
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
                )
                messages.success(
                    request,
                    f"Vente produit enregistree: {payment.amount} {payment.currency}.",
                )
            else:
                member = get_object_or_404(Member, id=request.POST.get("member"), gym=gym)
                plan = get_object_or_404(SubscriptionPlan, id=request.POST.get("plan"), gym=gym)
                subscription, payment = record_subscription_payment(
                    gym=gym,
                    member=member,
                    plan=plan,
                    currency=currency,
                    method=method,
                    created_by=request.user,
                )
                messages.success(
                    request,
                    f"Paiement abonnement enregistre: {payment.amount} {payment.currency}.",
                )
        except ValidationError as exc:
            messages.error(request, _validation_message(exc))
            return redirect("pos:cashier_dashboard")

        return redirect("pos:cashier_dashboard")

    members = Member.objects.filter(gym=gym)
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
    else:
        payments = []
        entries_today = 0
        exits_today = 0
        cash_total = 0

    return render(
        request,
        "pos/cashier.html",
        {
            "members": members,
            "plans": plans,
            "products": products,
            "payments": payments,
            "register": register,
            "today_total": cash_total,
            "today_entries": entries_today,
            "today_exits": exits_today,
            "latest_exchange_rate": latest_exchange_rate,
        },
    )


@login_required
@role_required(POS_CASHIER_ROLES)
def open_register(request):
    if request.method != "POST":
        return redirect("pos:cashier_dashboard")

    existing = CashRegister.objects.filter(gym=request.gym, is_closed=False).first()
    if existing:
        messages.warning(request, "Une caisse est deja ouverte.")
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
        CashRegister.objects.create(
            gym=request.gym,
            opened_by=request.user,
            opening_amount=opening_amount,
            exchange_rate=exchange_rate,
        )
    except ValidationError as exc:
        messages.error(request, _validation_message(exc))
        return redirect("pos:cashier_dashboard")

    messages.success(request, "Caisse ouverte avec succes.")
    return redirect("pos:cashier_dashboard")


@login_required
@role_required(POS_CASHIER_ROLES)
def close_register(request, register_id):
    register = get_object_or_404(
        CashRegister,
        id=register_id,
        gym=request.gym,
        is_closed=False,
    )

    entries = register.total_entries()
    exits = register.total_exits()
    expected_total = register.expected_total()

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
        },
    )


@login_required
@role_required(POS_HISTORY_ROLES)
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
    return render(
        request,
        "pos/register_history.html",
        {
            "registers": registers,
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
def register_detail(request, register_id):
    register = get_object_or_404(CashRegister, id=register_id, gym=request.gym)
    payments = (
        Payment.objects.filter(gym=request.gym, cash_register=register)
        .select_related("member", "subscription", "subscription__plan", "product")
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

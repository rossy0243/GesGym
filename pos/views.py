from datetime import timedelta
from django.utils import timezone
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from members.models import Member
from subscriptions.models import MemberSubscription, SubscriptionPlan
from .models import CashRegister, ExchangeRate, Payment
from django.db.models import Q
from django.db import transaction
from django.contrib import messages


def _to_decimal(value, field_label):
    try:
        return Decimal(str(value or "0"))
    except Exception:
        raise ValidationError(f"{field_label} invalide.")

    
@login_required
def search_members(request):

    query = request.GET.get("q", "")

    members = Member.objects.filter(
        gym=request.gym
    ).filter(
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query) |
        Q(phone__icontains=query)
    )[:10]

    data = []

    for m in members:
        data.append({
            "id": m.id,
            "name": f"{m.first_name} {m.last_name}",
            "phone": m.phone,
            "status": m.computed_status,
            "photo": m.photo.url if m.photo else "/static/avatar/1.png"
        })

    return JsonResponse({"members": data})

#APPLICATION DE LA CAISSE

#vue du dashboard de la caisse
@login_required
def cashier_dashboard(request):
    
    gym = request.gym
    register = CashRegister.objects.filter(
        gym=gym,
        is_closed=False
    ).first()

    if request.method == "POST":

        if not register:
            messages.error(request, "Aucune caisse ouverte.")
            return redirect("pos:cashier_dashboard")

        if not register.exchange_rate:
            messages.error(
                request,
                "Cette session de caisse n'a pas de taux USD-CDF. Fermez-la puis ouvrez une nouvelle session."
            )
            return redirect("pos:cashier_dashboard")

        transaction_type = request.POST.get("type", "in")

        method = request.POST.get("method", "cash")

        # ----------------------
        # DECAISSEMENT
        # ----------------------
        if transaction_type == "out":
            try:
                amount_cdf = _to_decimal(request.POST.get("amount"), "Montant")
                if amount_cdf <= 0:
                    raise ValidationError("Le montant doit etre superieur a zero.")
            except ValidationError as exc:
                messages.error(request, exc.message)
                return redirect("pos:cashier_dashboard")

            Payment.objects.create(
                gym=gym,
                cash_register=register,
                amount=amount_cdf,
                currency="CDF",
                exchange_rate=register.exchange_rate,
                method="cash",
                type="out",
                status="success",
                description=request.POST.get("description") or "Decaissement"
            )

            messages.success(request, "Décaissement enregistré.")

            return redirect("pos:cashier_dashboard")

        # ----------------------
        # ENCAISSEMENT
        # ----------------------

        member_id = request.POST.get("member")
        plan_id = request.POST.get("plan")

        member = get_object_or_404(Member, id=member_id, gym=gym)
        plan = get_object_or_404(SubscriptionPlan, id=plan_id, gym=gym)

        start = timezone.now().date()
        end = start + timedelta(days=plan.duration_days)
        
        currency = request.POST.get("currency", "USD")
        if currency not in {"USD", "CDF"}:
            messages.error(request, "Devise invalide.")
            return redirect("pos:cashier_dashboard")

        amount_usd = plan.price
        amount = amount_usd if currency == "USD" else amount_usd * register.exchange_rate

        with transaction.atomic():
            MemberSubscription.objects.filter(
                gym=gym,
                member=member,
                is_active=True
            ).update(is_active=False)

            subscription = MemberSubscription.objects.create(
                gym=gym,
                member=member,
                plan=plan,
                start_date=start,
                end_date=end,
                is_active=True
            )

            Payment.objects.create(
                gym=gym,
                member=member,
                subscription=subscription,
                cash_register=register,
                amount=amount,
                amount_usd=amount_usd,
                currency=currency,
                exchange_rate=register.exchange_rate,
                method=method,
                type="in",
                status="success"
            )

        messages.success(request, f"Paiement de {amount} {currency} enregistré avec succès.")

        return redirect("pos:cashier_dashboard")

    members = Member.objects.filter(gym=gym)

    plans = SubscriptionPlan.objects.filter(
        gym=gym,
        is_active=True
    )
    latest_exchange_rate = ExchangeRate.objects.filter(
        gym=gym
    ).order_by("-date", "-created_at").first()

    if register:

        payments = Payment.objects.filter(
            gym=gym,
            cash_register=register
        ).select_related("member","subscription").order_by("-created_at")[:20]

        entries_today = register.total_entries()
        exits_today = register.total_exits()
        cash_total = register.expected_total()

    else:

        payments = []
        entries_today = 0
        exits_today = 0
        cash_total = 0
    return render(request, "pos/cashier.html", {
        "members": members,
        "plans": plans,
        "payments": payments,
        "register": register,
        "today_total": cash_total,
        "today_entries": entries_today,
        "today_exits": exits_today,
        "latest_exchange_rate": latest_exchange_rate,
        
    })


#vue ouverture de la caisse
@login_required
def open_register(request):

    if request.method != "POST":
        return redirect("pos:cashier_dashboard")

    existing = CashRegister.objects.filter(
        gym=request.gym,
        is_closed=False
    ).first()

    if existing:
        messages.warning(request, "Une caisse est déjà ouverte.")
        return redirect("pos:cashier_dashboard")

    try:
        opening_amount = _to_decimal(request.POST.get("opening_amount"), "Fonds d'ouverture")
        exchange_rate = _to_decimal(request.POST.get("exchange_rate"), "Taux USD-CDF")
        if opening_amount < 0:
            raise ValidationError("Le fonds d'ouverture ne peut pas etre negatif.")
        if exchange_rate <= 0:
            raise ValidationError("Le taux USD-CDF doit etre superieur a zero.")
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("pos:cashier_dashboard")

    try:
        with transaction.atomic():
            ExchangeRate.objects.update_or_create(
                gym=request.gym,
                date=timezone.now().date(),
                defaults={"rate": exchange_rate}
            )

            CashRegister.objects.create(
                gym=request.gym,
                opened_by=request.user,
                opening_amount=opening_amount,
                exchange_rate=exchange_rate
            )
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("pos:cashier_dashboard")

    messages.success(request, "Caisse ouverte avec succès.")

    return redirect("pos:cashier_dashboard")


#vue fermeture de la caisse
@login_required
def close_register(request, register_id):

    register = get_object_or_404(
        CashRegister,
        id=register_id,
        gym=request.gym,
        is_closed=False
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
            messages.error(request, exc.message)
            return redirect("pos:close_register", register_id=register.id)

        difference = real_amount - expected_total

        register.closing_amount = real_amount
        register.closed_by = request.user
        register.closed_at = timezone.now()
        register.is_closed = True
        register.difference = difference
        register.save()

        messages.success(
            request,
            f"Caisse fermée. Différence : {difference} CDF"
        )

        return redirect("pos:cashier_dashboard")

    return render(request, "pos/close_register.html", {
        "register": register,
        "expected_total": expected_total,
        "entries": entries,
        "exits": exits
    })

#vue historique des caisses
@login_required
def register_history(request):
    registers = CashRegister.objects.filter(
        gym=request.gym,
        is_closed=True
    )

    # --- filtres ---
    search = request.GET.get("search", "").strip()
    status = request.GET.get("status", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    sort = request.GET.get("sort", "recent").strip()

    if search:
        registers = registers.filter(
            Q(session_code__icontains=search) |
            Q(opened_by__username__icontains=search) |
            Q(opened_by__first_name__icontains=search) |
            Q(opened_by__last_name__icontains=search)
        )

    # même si ta requête de base est déjà is_closed=True,
    # on garde ce filtre pour coller au template premium sans casser la logique
    if status == "open":
        registers = CashRegister.objects.filter(
            gym=request.gym,
            is_closed=False
        )
        if search:
            registers = registers.filter(
                Q(session_code__icontains=search) |
                Q(opened_by__username__icontains=search) |
                Q(opened_by__first_name__icontains=search) |
                Q(opened_by__last_name__icontains=search)
            )
    elif status == "closed":
        registers = registers.filter(is_closed=True)

    if date_from:
        registers = registers.filter(opened_at__date__gte=date_from)

    if date_to:
        registers = registers.filter(opened_at__date__lte=date_to)

    # --- tri ---
    if sort == "oldest":
        registers = registers.order_by("closed_at")
    elif sort == "difference_desc":
        registers = registers.order_by("-difference", "-closed_at")
    elif sort == "difference_asc":
        registers = registers.order_by("difference", "-closed_at")
    else:
        registers = registers.order_by("-closed_at")

    # --- stats ---
    all_registers = CashRegister.objects.filter(gym=request.gym)

    positive_count = all_registers.filter(difference__gt=0).count()
    negative_count = all_registers.filter(difference__lt=0).count()
    open_count = all_registers.filter(is_closed=False).count()

    return render(request, "pos/register_history.html", {
        "registers": registers,
        "search": search,
        "status": status,
        "date_from": date_from,
        "date_to": date_to,
        "sort": sort,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "open_count": open_count,
    })

#vue détail d'une session de caisse
@login_required
def register_detail(request, register_id):

    register = get_object_or_404(
        CashRegister,
        id=register_id,
        gym=request.gym
    )

    payments = Payment.objects.filter(
        gym=request.gym,
        cash_register=register
    ).select_related("member", "subscription")

    return render(request, "pos/register_detail.html", {
        "register": register,
        "payments": payments
    })

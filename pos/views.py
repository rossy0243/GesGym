from datetime import timedelta
from django.utils import timezone
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from members.models import Member
from subscriptions.models import MemberSubscription, SubscriptionPlan
from .models import CashRegister, Payment
from django.db.models import Q, Sum
from django.contrib import messages

    
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

        transaction_type = request.POST.get("type", "in")

        amount = request.POST.get("amount")
        method = request.POST.get("method", "cash")

        # ----------------------
        # DECAISSEMENT
        # ----------------------
        if transaction_type == "out":

            Payment.objects.create(
                gym=gym,
                cash_register=register,
                amount=amount,
                method="cash",
                type="out",
                status="success"
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

        MemberSubscription.objects.filter(
            member=member,
            is_active=True
        ).update(is_active=False)

        start = timezone.now().date()
        end = start + timedelta(days=plan.duration_days)

        subscription = MemberSubscription.objects.create(
            gym=gym,
            member=member,
            plan=plan,
            start_date=start,
            end_date=end,
            is_active=True
        )
        
        amount = Decimal(request.POST.get("amount"))
        currency = request.POST.get("currency", "CDF")
        exchange_rate = request.POST.get("exchange_rate")

        if currency == "USD":
            if not exchange_rate:
                messages.error(request, "Le taux de change est requis pour les paiements en USD.")
                return redirect("pos:cashier_dashboard")
            exchange_rate = Decimal(exchange_rate)
        else:
            exchange_rate = None

        Payment.objects.create(
            gym=gym,
            member=member,
            subscription=subscription,
            cash_register=register,
            amount=plan.price,
            currency=currency,
            exchange_rate=exchange_rate,
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
    if register:

        payments = Payment.objects.filter(
            gym=gym,
            cash_register=register
        ).select_related("member","subscription").order_by("-created_at")[:20]

        entries_today = Payment.objects.filter(
            gym=gym,
            cash_register=register,
            type="in",
            status="success"
        ).aggregate(total=Sum("amount"))["total"] or 0

        exits_today = Payment.objects.filter(
            gym=gym,
            cash_register=register,
            type="out",
            status="success"
        ).aggregate(total=Sum("amount"))["total"] or 0

        cash_total = entries_today - exits_today

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

    CashRegister.objects.create(
        gym=request.gym,
        opened_by=request.user
    )

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

        real_amount = Decimal(request.POST.get("real_amount"))
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
    ).order_by("-closed_at")

    return render(request, "pos/register_history.html", {
        "registers": registers
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
        cash_register=register
    ).select_related("member", "subscription")

    return render(request, "pos/register_detail.html", {
        "register": register,
        "payments": payments
    })
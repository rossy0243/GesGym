#core/views.py
from datetime import timedelta
from decimal import Decimal
from django.utils.timezone import localtime, now
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.contrib import messages
from core.decorators import role_required
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from .forms import MemberCreationForm, SubscriptionForm, SubscriptionPlanForm
from .models import AccessLog, CashRegister, Member, Payment, Subscription, SubscriptionPlan
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.db.models import Q, Count, Sum
from django.core.paginator import Paginator
from django.db.models.functions import ExtractMonth


#######   MEMBRE  ######
#CREATION MEMBRE (avec signal pour créer User automatiquement)
@login_required
@role_required(["admin", "reception"])
def create_member(request):

    allowed_roles = ["admin", "reception"]
    
    if not request.user.is_authenticated or request.user.role not in allowed_roles:
        raise PermissionDenied("Accès refusé – rôle non autorisé.")
    
    
    if request.method == "POST":
        form = MemberCreationForm(request.POST, request.FILES)
        if form.is_valid():
            member = form.save(commit=False)
            member.gym = request.user.gym
            member.save()  # déclenche signal → crée User automatiquement

            messages.success(
                request,
                f"Membre créé avec succès | Mot de passe par défaut : 12345"
            )

            
            return redirect("core:member_list")
            
    else:
        form = MemberCreationForm()

    return render(request, "core/create_member.html", {"form": form})

#LISTE DES MEMBRES
@login_required
@role_required(["admin", "reception", "manager"])
def member_list(request):

    if request.user.role not in ["admin", "reception", "manager"]:
        raise PermissionDenied
    today = timezone.now().date()
    limit = today + timedelta(days=7)
    
    members = Member.objects.filter(gym=request.user.gym).select_related("user").prefetch_related("subscription_set__plan")


    search = request.GET.get("search")
    status = request.GET.get("status")
    plan = request.GET.get("plan")
    # Recherche texte
    if search:

        members = members.filter(

            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(phone__icontains=search) |
            Q(email__icontains=search)

        )

    # Filtre statut
    if status == "active":

        members = members.filter(
            subscription__is_active=True,
            subscription__end_date__gte=timezone.now().date()
        )

    elif status == "expired":

        members = members.filter(
            subscription__end_date__lt=timezone.now().date()
        )

    elif status == "suspended":

        members = members.filter(status="suspended")

    elif status == "expiring":

        today = timezone.now().date()
        limit = today + timedelta(days=7)

        members = members.filter(
            subscription__is_active=True,
            subscription__end_date__range=(today, limit)
        )

    # Filtre plan
    if plan:

        members = members.filter(
            subscription__plan_id=plan,
            subscription__is_active=True
        )
        
    paginator = Paginator(members, 10)  # 10 membres par page

    page_number = request.GET.get("page")
    
    page_obj = paginator.get_page(page_number)
    
    plans = SubscriptionPlan.objects.filter(gym=request.user.gym, is_active=True)
    
    form = MemberCreationForm()
    members = members.distinct()  # éviter doublons si plusieurs abonnements
    
    return render(request, "core/member_list.html", {"form": form, "page_obj": page_obj, "plans": plans})

#DETAIL D'UN MEMBRE
@login_required
@role_required(["admin", "reception", "manager"])
def member_detail(request, member_id):

    member = get_object_or_404(
        Member.objects.select_related("user"),
        id=member_id,
        gym=request.user.gym
    )
    subscription = member.active_subscription
    
    payments = Payment.objects.filter(
        member=member
    ).order_by("-created_at")[:5]
    
    payments_data = []
    
    for p in payments:
        payments_data.append({
            "date": p.created_at.strftime("%d/%m/%Y"),
            "amount": float(p.amount),
            "method": p.method,
            "status": p.status
        })
        
    access_logs = AccessLog.objects.filter(
        member=member
    ).order_by("-check_in_time")[:5]

    access_data = []

    for log in access_logs:
        access_data.append({
            "date": log.check_in_time.strftime("%d/%m/%Y"),
            "time": log.check_in_time.strftime("%H:%M"),
            "device": log.device_used,
            "status": log.access_granted
        })
        
    data = {
        "id": member.id,
        "first_name": member.first_name,
        "last_name": member.last_name,
        "phone": member.phone,
        "email": member.email,
        "status": member.computed_status,
        "qr_code": member.qr_code,
        # abonnement
        "subscription_type": member.subscription_type,
        "start_date": subscription.start_date.strftime("%d/%m/%Y") if subscription else None,
        "expiration_date": member.expiration_date.strftime("%d/%m/%Y") if member.expiration_date else None,
        "price": subscription.plan.price if subscription else 0,

        # paiements
        "paid": member.amount_paid if hasattr(member, "amount_paid") else 0,
        "remaining": member.amount_remaining if hasattr(member, "amount_remaining") else 0,
        
        "payments": payments_data,
        "access_logs": access_data,
        
        "qr_image": member.qr_image.url if member.qr_image else None,
        
    }

    return JsonResponse(data)


@login_required
@role_required(["admin", "manager"])
def reports_dashboard(request):

    gym = request.user.gym
    today = now().date()
    section = request.GET.get("section", "journalier")
    # =========================
    # CA du jour
    # =========================
    payments_today = Payment.objects.filter(
        gym=gym,
        created_at__date=today
    )

    daily_revenue = payments_today.aggregate(
        total=Sum("amount")
    )["total"] or 0

    daily_transactions = payments_today.count()

    # =========================
    # Nouveaux membres
    # =========================
    daily_new_clients = Member.objects.filter(
        gym=gym,
        created_at__date=today
    ).count()
    
    # =========================
    # Fréquentation
    # =========================
    daily_visits = AccessLog.objects.filter(
        member__gym=gym,
        check_in_time__date=today,
        access_granted=True
    ).count()

    denied_access = AccessLog.objects.filter(
        member__gym=gym,
        check_in_time__date=today,
        access_granted=False
    ).count()

    # =========================
    # Transactions détaillées
    # =========================
    transactions = payments_today.select_related(
        "member"
    ).order_by("-created_at")[:50]

    # =========================
    # KPI MENSUELS
    # =========================

    today = now().date()
    current_year = today.year
    current_month = today.month

    payments_month = Payment.objects.filter(
        gym=gym,
        created_at__year=current_year,
        created_at__month=current_month
    )

    monthly_revenue = payments_month.aggregate(
        total=Sum("amount")
    )["total"] or 0

    monthly_transactions = payments_month.count()


    # nouveaux membres ce mois
    monthly_new_members = Member.objects.filter(
        gym=gym,
        created_at__year=current_year,
        created_at__month=current_month
    ).count()


    # renouvellements abonnement
    monthly_renewals = Subscription.objects.filter(
        member__gym=gym,
        start_date__year=current_year,
        start_date__month=current_month
    ).count()


    # visites
    monthly_visits = AccessLog.objects.filter(
        member__gym=gym,
        check_in_time__year=current_year,
        check_in_time__month=current_month,
        access_granted=True
    ).count()
    
    plans_stats = Subscription.objects.filter(
        member__gym=gym,
        start_date__year=current_year,
        start_date__month=current_month
        ).values(
            "plan__name"
        ).annotate(
            subscriptions=Count("id"),
            revenue=Sum("payment__amount")
        ).order_by("-revenue")
    
    monthly_sales = Payment.objects.filter(
        gym=gym,
        created_at__year=current_year
        ).annotate(
            month=ExtractMonth("created_at")
        ).values("month").annotate(
            total=Sum("amount")
        ).order_by("month")
    
    sales_labels = []
    sales_values = []

    for m in monthly_sales:
        sales_labels.append(m["month"])
        sales_values.append(float(m["total"]))
    context = {
        "section": section,
            # journalier
        "daily_revenue": daily_revenue,
        "daily_transactions": daily_transactions,
        "daily_new_clients": daily_new_clients,
        "daily_visits": daily_visits,
        "denied_access": denied_access,
        "transactions": transactions,

        # mensuel
        "monthly_revenue": monthly_revenue,
        "monthly_new_members": monthly_new_members,
        "monthly_renewals": monthly_renewals,
        "monthly_visits": monthly_visits,
        "plans_stats": plans_stats,
        "sales_labels": sales_labels,
        "sales_values": sales_values,
        "monthly_transactions": monthly_transactions
        }

    return render(request, "core/rapports.html", context)

@login_required
@role_required(["admin"])
def admin_dashboard(request):
    gym = request.gym
    return render(request, 'core/admin.html', {'gym': gym})


#vue (scanner + pointage manuel)
@login_required
@role_required(["admin", "manager", "reception"])
def acces_dashboard(request):

    gym = request.gym

    query = request.GET.get("q")
    member_id = request.GET.get("member")
    section = request.GET.get("section", "scan")

    members = []
    selected_member = None

    # recherche membre (pointage manuel)
    if query:

        members = Member.objects.filter(
            gym=gym
        ).filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(phone__icontains=query)
        ).order_by("first_name")[:10]


    # membre sélectionné
    if member_id:

        selected_member = get_object_or_404(
            Member,
            id=member_id,
            gym=gym
        )


    # statistiques du jour pour le scanner
    today = now().date()

    today_entries = AccessLog.objects.filter(
        member__gym=gym,
        check_in_time__date=today,
        access_granted=True
    ).count()

    today_denied = AccessLog.objects.filter(
        member__gym=gym,
        check_in_time__date=today,
        access_granted=False
    ).count()


    return render(request, "core/acces.html", {
        "members": members,
        "selected_member": selected_member,
        "today_entries": today_entries,
        "today_denied": today_denied,
        "section": section
    })

def realtime_access(request):

    logs = AccessLog.objects.select_related("member").order_by("-check_in_time")[:10]

    data = []

    for log in logs:

        data.append({
            "member": f"{log.member.first_name} {log.member.last_name}",
            "time": localtime(log.check_in_time).strftime("%H:%M"),
            "status": "success" if log.access_granted else "denied",
            "method": log.device_used
        })

    return JsonResponse(data, safe=False)


@login_required
def manual_access_entry(request, member_id):

    member = get_object_or_404(
        Member,
        id=member_id,
        gym=request.user.gym
    )

    access_granted = True
    reason = ""

    if not member.active_subscription:
        access_granted = False
        reason = "Aucun abonnement actif"

    AccessLog.objects.create(
        member=member,
        access_granted=access_granted,
        device_used="Manuel"
    )

    today = now().date()

    today_entries = AccessLog.objects.filter(
        check_in_time__date=today,
        access_granted=True
    ).count()

    today_denied = AccessLog.objects.filter(
        check_in_time__date=today,
        access_granted=False
    ).count()

    return JsonResponse({
        "member": f"{member.first_name} {member.last_name}",
        "access": access_granted,
        "reason": reason,
        "stats":{
            "entries":today_entries,
            "denied":today_denied
        }
    })

def member_access(request, qr_code):

    member = get_object_or_404(Member, qr_code=qr_code)

    access_granted = True
    reason = ""
    
    subscription = member.active_subscription

    if not subscription:
        access_granted = False
        reason = "Abonnement expiré"

    AccessLog.objects.create(
        member=member,
        access_granted=access_granted,
        device_used="QR Scanner"
    )
    today = now().date()

    today_entries = AccessLog.objects.filter(
        check_in_time__date=today,
        access_granted=True
    ).count()

    today_denied = AccessLog.objects.filter(
        check_in_time__date=today,
        access_granted=False
    ).count()

    return JsonResponse({
        "member": f"{member.first_name} {member.last_name}",
        "access": access_granted,
        "reason": reason,
        "stats": {
            "entries": today_entries,
            "denied": today_denied
        }
    })

@login_required
@role_required(["reception"])
def reception_dashboard(request):
    gym = request.gym
    return render(request, 'core/reception.html', {'gym': gym})

@login_required
@role_required(["member"])
def member_dashboard(request):
    member = request.user.member_profile
    return render(request, 'core/member.html', {
        'member': member,
        'gym': member.gym
    })


@login_required
@role_required(["admin", "reception"])
def edit_member(request, member_id):

    if request.user.role not in ["admin", "reception"]:
        raise PermissionDenied

    member = get_object_or_404(
        Member,
        id=member_id,
        gym=request.user.gym
    )

    form = MemberCreationForm(request.POST or None, request.FILES or None, instance=member)

    if form.is_valid():
        form.save()
        messages.success(request, "Membre modifié avec succès.")
        return redirect("core:member_list")

    return render(request, "core/edit_member.html", {"form": form})


@login_required
@role_required(["admin"])
def delete_member(request, member_id):

    if request.user.role not in ["admin"]:
        raise PermissionDenied

    member = get_object_or_404(
        Member,
        id=member_id,
        gym=request.user.gym
    )

    if request.method == "POST":
        member.delete()
        messages.success(request, "Membre supprimé avec succès.")
        return redirect("core:member_list")

    return render(request, "core/delete_member.html", {"member": member})

@login_required
@role_required(["admin", "reception"])
def toggle_member_status(request, member_id):

    if request.user.role not in ["admin", "reception"]:
        raise PermissionDenied

    member = get_object_or_404(
        Member,
        id=member_id,
        gym=request.user.gym
    )

    if member.status == "suspended":
        member.status = "active"
    else:
        member.status = "suspended"

    member.save()

    return redirect("member_list")



def create_subscription(member, plan):

    start_date = timezone.now().date()

    end_date = start_date + timedelta(days=plan.duration_days)

    # désactiver anciennes subscriptions
    Subscription.objects.filter(
        member=member,
        is_active=True
    ).update(is_active=False)

    subscription = Subscription.objects.create(
        member=member,
        plan=plan,
        start_date=start_date,
        end_date=end_date,
        is_active=True
    )

    return subscription


@login_required
@role_required(["admin","manager"])
def plan_list(request):

    plans = SubscriptionPlan.objects.filter(gym=request.user.gym)
    form = SubscriptionPlanForm()
    return render(
        request,
        "core/subscription_plan_list.html",
        {"plans": plans, "form": form}
    )

@login_required
@role_required(["admin","manager"])
def create_plan(request):

    if request.method == "POST":

        form = SubscriptionPlanForm(request.POST)

        if form.is_valid():

            plan = form.save(commit=False)
            plan.gym = request.user.gym
            plan.save()

            messages.success(request,"Plan créé avec succès")

            return redirect("core:subscription_plan_list")

    else:
        form = SubscriptionPlanForm()

    return render(request,"core/create_plan.html",{"form":form})


@login_required
@role_required(["admin","manager"])
def edit_plan(request, plan_id):

    plan = get_object_or_404(
        SubscriptionPlan,
        id=plan_id,
        gym=request.user.gym
    )

    form = SubscriptionPlanForm(
        request.POST or None,
        instance=plan
    )
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Formule modifiée avec succès")
            return redirect("core:subscription_plan_list")  # ou JsonResponse si tu veux rester sur la page
        # Si erreur → on continue pour renvoyer le form avec erreurs

    # GET ou POST invalide → renvoyer le fragment du modal
    context = {
        'form': form,
        'plan': plan,                   # pour afficher le nom dans le titre
        'is_edit': True,
    }

    html = render_to_string(
        'core/partials/subscription_plan_form.html',  # ← nouveau partial
        context,
        request=request
    )

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return HttpResponse(html)

    # Fallback si accès direct (rare)
    return render(request, 'core/subscription_plan_edit_full.html', context)



@login_required
@role_required(["admin","manager"])
def delete_plan(request, plan_id):

    plan = get_object_or_404(
        SubscriptionPlan,
        id=plan_id,
        gym=request.user.gym
    )

    if request.method == "POST":
        plan.delete()
        messages.success(request,"Plan supprimé")
        return redirect("core:subscription_plan_list")

    return render(request,"core/delete_plan.html",{"plan":plan})


@login_required
@role_required(["admin","manager","reception"])
def create_subscription(request):

    if request.method == "POST":

        form = SubscriptionForm(request.POST)

        if form.is_valid():

            subscription = form.save(commit=False)

            plan = subscription.plan

            subscription.end_date = (
                subscription.start_date
                + timedelta(days=plan.duration_days)
            )

            # désactiver abonnement actif
            Subscription.objects.filter(
                member=subscription.member,
                is_active=True
            ).update(is_active=False)

            subscription.save()

            messages.success(
                request,
                "Abonnement enregistré avec succès"
            )

            return redirect("core:member_list")

    else:
        form = SubscriptionForm()

    return render(
        request,
        "core/create_subscription.html",
        {"form": form}
    )
    
    
@login_required
@role_required(["admin","manager","cashier","reception"])
def payments_dashboard(request):

    gym = request.user.gym

    register = CashRegister.objects.filter(
        gym=gym,
        is_closed=False
    ).first()

    payments = Payment.objects.filter(
        gym=gym
    ).select_related("member","subscription")

    today = timezone.now().date()

    today_payments = payments.filter(
        created_at__date=today,
        status="success"
    )
    plans = SubscriptionPlan.objects.filter(
    gym=request.user.gym,
    is_active=True
)

    total_cash = today_payments.aggregate(
        total=Sum("amount")
    )["total"] or 0

    context = {
        "register": register,
        "payments": payments.order_by("-created_at")[:20],
        "today_total": total_cash,
        "plans": plans
    }

    return render(
        request,
        "core/cashier.html",
        context
    )
    
@login_required
def search_members(request):

    query = request.GET.get("q", "")

    members = Member.objects.filter(
        gym=request.user.gym
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
    
    gym = request.user.gym
    register = CashRegister.objects.filter(
        gym=gym,
        is_closed=False
    ).first()

    if request.method == "POST":

        if not register:
            messages.error(request, "Aucune caisse ouverte.")
            return redirect("core:cashier_dashboard")

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

            return redirect("core:cashier_dashboard")

        # ----------------------
        # ENCAISSEMENT
        # ----------------------

        member_id = request.POST.get("member")
        plan_id = request.POST.get("plan")

        member = get_object_or_404(Member, id=member_id, gym=gym)
        plan = get_object_or_404(SubscriptionPlan, id=plan_id, gym=gym)

        Subscription.objects.filter(
            member=member,
            is_active=True
        ).update(is_active=False)

        start = timezone.now().date()
        end = start + timedelta(days=plan.duration_days)

        subscription = Subscription.objects.create(
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
            amount=plan.price,
            method=method,
            type="in",
            status="success"
        )

        messages.success(request, "Paiement enregistré.")

        return redirect("core:cashier_dashboard")

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
    return render(request, "core/cashier.html", {
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
@role_required(["cashier", "admin"])
def open_register(request):

    if request.method != "POST":
        return redirect("core:cashier_dashboard")

    existing = CashRegister.objects.filter(
        gym=request.user.gym,
        is_closed=False
    ).first()

    if existing:
        messages.warning(request, "Une caisse est déjà ouverte.")
        return redirect("core:cashier_dashboard")

    CashRegister.objects.create(
        gym=request.user.gym,
        opened_by=request.user
    )

    messages.success(request, "Caisse ouverte avec succès.")

    return redirect("core:cashier_dashboard")


#vue fermeture de la caisse
@login_required
@role_required(["cashier", "admin"])
def close_register(request, register_id):

    register = get_object_or_404(
        CashRegister,
        id=register_id,
        gym=request.user.gym,
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

        return redirect("core:cashier_dashboard")

    return render(request, "core/close_register.html", {
        "register": register,
        "expected_total": expected_total,
        "entries": entries,
        "exits": exits
    })

#vue historique des caisses
@login_required
@role_required(["admin", "manager"])
def register_history(request):

    registers = CashRegister.objects.filter(
        gym=request.user.gym,
        is_closed=True
    ).order_by("-closed_at")

    return render(request, "core/register_history.html", {
        "registers": registers
    })

#vue détail d'une session de caisse
@login_required
@role_required(["admin", "manager"])
def register_detail(request, register_id):

    register = get_object_or_404(
        CashRegister,
        id=register_id,
        gym=request.user.gym
    )

    payments = Payment.objects.filter(
        cash_register=register
    ).select_related("member", "subscription")

    return render(request, "core/register_detail.html", {
        "register": register,
        "payments": payments
    })
    
    

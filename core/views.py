from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponseForbidden
from django.db.models import Q, Count, Sum
from django.db.models.functions import ExtractMonth, TruncDate
from django.utils.timezone import now
from datetime import timedelta
import calendar
from access.models import AccessLog
from members.models import Member
from organizations.models import GymModule
from pos.models import Payment
from services.dashboard_service import OrganizationDashboardService
from subscriptions.models import MemberSubscription

@login_required
def gym_dashboard(request, gym_id):

    if not request.gym:
        return HttpResponseForbidden()

    if not request.role:
        return HttpResponseForbidden()
    
    gym = request.gym
    today = now().date()
    view = request.GET.get("view", "dashboard")
    # Récupérer les modules actifs
    active_modules = GymModule.objects.filter(
        gym=gym,
        is_active=True
    ).values_list('module__code', flat=True)

    
    # ======================
    # MEMBRES
    # ======================

    total_members = Member.objects.filter(gym=gym).count()

    active_members = Member.objects.filter(
        gym=gym,
        subscriptions__is_active=True
    ).distinct().count()

    expired_members = Member.objects.filter(
    gym=gym
    ).filter(
        Q(subscriptions__is_active=False) | Q(subscriptions__isnull=True)
    ).distinct().count()

    # nouveaux ce mois
    current_month = today.month
    current_year = today.year

    new_members_month = Member.objects.filter(
        gym=gym,
        created_at__year=current_year,
        created_at__month=current_month
    ).count()

    # ======================
    # REVENUS
    # ======================

    payments_today = Payment.objects.filter(
        gym=gym,
        created_at__date=today
    )

    daily_revenue = payments_today.aggregate(
        total=Sum("amount")
    )["total"] or 0

    monthly_revenue = Payment.objects.filter(
        gym=gym,
        created_at__year=current_year,
        created_at__month=current_month
    ).aggregate(
        total=Sum("amount")
    )["total"] or 0

    # ======================
    # ACCES
    # ======================

    today_checkins = AccessLog.objects.filter(
        member__gym=gym,
        check_in_time__date=today,
        access_granted=True
    ).count()

    # ======================
    # EXPIRATIONS
    # ======================

    expiry_soon = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date__gte=today,
        end_date__lte=today + timedelta(days=15)
    ).count()
    
    # ======================
    # REPARTITION FORMULES
    # ======================

    plans_stats = MemberSubscription.objects.filter(
        member__gym=gym,
        is_active=True
    ).values(
        "plan__name"
    ).annotate(
        total=Count("id")
    ).order_by("-total")

    total_subscriptions = MemberSubscription.objects.filter(
        member__gym=gym,
        is_active=True
    ).count()


    # ======================
    # FREQUENTATION SEMAINE
    # ======================

    start_week = today - timedelta(days=today.weekday())

    attendance_week = []

    days = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]

    attendance_qs = AccessLog.objects.filter(
    member__gym=gym,
    check_in_time__gte=start_week,
    access_granted=True
    ).annotate(
        day=TruncDate("check_in_time")
    ).values("day").annotate(
        count=Count("id")
    )

    attendance_map = {a["day"]: a["count"] for a in attendance_qs}

    attendance_week = []

    for i in range(7):
        day = start_week + timedelta(days=i)

        attendance_week.append({
            "day": days[i],
            "count": attendance_map.get(day, 0)
        })


    # ======================
    # DERNIERS PAIEMENTS
    # ======================

    recent_payments = Payment.objects.filter(
        gym=gym
    ).select_related(
        "member"
    ).order_by("-created_at")[:5]
    
    # ======================
    # ALERTES EXPIRATION
    # ======================

    expiry_7_days = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date=today + timedelta(days=7),
        is_active=True
    ).count()

    expiry_3_days = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date=today + timedelta(days=3),
        is_active=True
    ).count()

    expiry_1_day = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date=today + timedelta(days=1),
        is_active=True
    ).count()


    # ======================
    # PAIEMENTS EN ATTENTE
    # ======================

    pending_payments = Payment.objects.filter(
        gym=gym,
        status="pending"
    )

    pending_count = pending_payments.count()

    pending_total = pending_payments.aggregate(
        total=Sum("amount")
    )["total"] or 0


    # ======================
    # DERNIERS ACCES
    # ======================

    recent_access = AccessLog.objects.filter(
        member__gym=gym
    ).select_related(
        "member"
    ).order_by("-check_in_time")[:5]
    
    # ======================
    # FREQUENTATION SEMAINE (graph)
    # ======================

    week_labels = []
    week_values = []

    for day in attendance_week:
        week_labels.append(day["day"])
        week_values.append(day["count"])


    # ======================
    # REVENUS PAR MOIS (graph)
    # ======================

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
        sales_labels.append(calendar.month_abbr[m["month"]])
        sales_values.append(float(m["total"]))


    # ======================
    # REPARTITION ABONNEMENTS (graph)
    # ======================

    plan_labels = []
    plan_values = []

    for p in plans_stats:
        plan_labels.append(p["plan__name"])
        plan_values.append(p["total"])

    context = {
        "active_modules": active_modules,
        "gym": gym,
        "context_view": view,

        "total_members": total_members,
        "active_members": active_members,
        "expired_members": expired_members,

        "daily_revenue": daily_revenue,
        "monthly_revenue": monthly_revenue,

        "new_members_month": new_members_month,

        "today_checkins": today_checkins,

        "expiry_soon": expiry_soon,
        "plans_stats": plans_stats,
        "total_subscriptions": total_subscriptions,
        "attendance_week": attendance_week,
        "recent_payments": recent_payments,
        
        "expiry_7_days": expiry_7_days,
        "expiry_3_days": expiry_3_days,
        "expiry_1_day": expiry_1_day,

        "pending_count": pending_count,
        "pending_total": pending_total,

        "recent_access": recent_access,
        
        "week_labels": week_labels,
        "week_values": week_values,

        "sales_labels": sales_labels,
        "sales_values": sales_values,

        "plan_labels": plan_labels,
        "plan_values": plan_values,
    }

    return render(request, "core/dashboard.html", context)

@login_required
def reports_dashboard(request):
    gym = request.gym
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
    monthly_renewals = MemberSubscription.objects.filter(
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
    
    plans_stats = MemberSubscription.objects.filter(
        member__gym=gym,
        start_date__year=current_year,
        start_date__month=current_month
        ).values(
            "plan__name"
        ).annotate(
            subscriptions=Count("id"),
            revenue=Sum("payments__amount")
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
def organization_dashboard(request, org_id):
    """Dashboard pour le role Owner (vue consolidée)"""
    service = OrganizationDashboardService(org_id)
    
    context = {
        'organization': service.org,
        'gyms': service.gyms,
        'machines': service.get_machines_summary(),
        'coaching': service.get_coaching_summary(),
        # ... autres modules
    }
    return render(request, 'dashboard/organization_dashboard.html', context)
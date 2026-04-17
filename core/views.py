from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseForbidden
from django.db.models import Q, Count, Sum, Exists, OuterRef
from django.db.models.functions import ExtractMonth, TruncDate
from django.utils.timezone import now
from datetime import timedelta
import calendar
import json
from access.models import AccessLog
from compte.models import UserGymRole
from members.models import Member
from organizations.models import Gym, GymModule
from pos.models import Payment
from subscriptions.models import MemberSubscription


PERIOD_LABELS = {
    "day": "Jour",
    "week": "Semaine",
    "month": "Mois",
    "year": "Année",
}

MONTH_LABELS = ["", "Jan", "Fev", "Mar", "Avr", "Mai", "Juin", "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"]


def _to_json(value):
    return json.dumps(value, ensure_ascii=False)


def _get_period_window(period_key, reference_date):
    period_key = period_key if period_key in PERIOD_LABELS else "month"

    if period_key == "day":
        start_date = end_date = reference_date
    elif period_key == "week":
        start_date = reference_date - timedelta(days=reference_date.weekday())
        end_date = start_date + timedelta(days=6)
    elif period_key == "year":
        start_date = reference_date.replace(month=1, day=1)
        end_date = reference_date.replace(month=12, day=31)
    else:
        start_date = reference_date.replace(day=1)
        if start_date.month == 12:
            next_month = start_date.replace(year=start_date.year + 1, month=1, day=1)
        else:
            next_month = start_date.replace(month=start_date.month + 1, day=1)
        end_date = next_month - timedelta(days=1)

    period_days = (end_date - start_date).days + 1
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=period_days - 1)

    return {
        "key": period_key,
        "label": PERIOD_LABELS[period_key],
        "start_date": start_date,
        "end_date": end_date,
        "previous_start": previous_start,
        "previous_end": previous_end,
        "days": period_days,
    }


def _format_period_range(start_date, end_date):
    if start_date == end_date:
        return start_date.strftime("%d/%m/%Y")
    return f"{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}"


def _build_trend(current_value, previous_value):
    delta = current_value - previous_value
    if previous_value:
        percent = round((delta / previous_value) * 100, 1)
    elif current_value:
        percent = 100.0
    else:
        percent = 0.0

    if delta > 0:
        direction = "up"
        badge_class = "success"
        prefix = "+"
    elif delta < 0:
        direction = "down"
        badge_class = "danger"
        prefix = ""
    else:
        direction = "flat"
        badge_class = "secondary"
        prefix = ""

    return {
        "delta": delta,
        "percent": percent,
        "direction": direction,
        "badge_class": badge_class,
        "display": f"{prefix}{percent:.1f}%",
    }


def _build_attendance_rows(gym, period_data):
    access_logs = AccessLog.objects.filter(
        gym=gym,
        access_granted=True,
        check_in_time__date__range=(period_data["start_date"], period_data["end_date"]),
    )
    period_key = period_data["key"]
    rows = []

    if period_key == "day":
        counts_by_slot = {}
        for hour in access_logs.values_list("check_in_time__hour", flat=True):
            slot_start = (hour // 4) * 4
            counts_by_slot[slot_start] = counts_by_slot.get(slot_start, 0) + 1

        for slot_start in range(0, 24, 4):
            slot_end = slot_start + 3
            label = f"{slot_start:02d}h-{slot_end:02d}h"
            rows.append({"label": label, "count": counts_by_slot.get(slot_start, 0)})

    elif period_key == "week":
        counts_by_day = {
            item["day"]: item["count"]
            for item in access_logs.annotate(day=TruncDate("check_in_time"))
            .values("day")
            .annotate(count=Count("id"))
        }
        weekdays = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        for index in range(7):
            current_day = period_data["start_date"] + timedelta(days=index)
            rows.append({"label": weekdays[index], "count": counts_by_day.get(current_day, 0)})

    elif period_key == "month":
        counts_by_day = {
            item["day"]: item["count"]
            for item in access_logs.annotate(day=TruncDate("check_in_time"))
            .values("day")
            .annotate(count=Count("id"))
        }
        week_start = period_data["start_date"]
        week_index = 1
        while week_start <= period_data["end_date"]:
            week_end = min(week_start + timedelta(days=6), period_data["end_date"])
            total = 0
            current_day = week_start
            while current_day <= week_end:
                total += counts_by_day.get(current_day, 0)
                current_day += timedelta(days=1)
            rows.append({"label": f"Semaine {week_index}", "count": total})
            week_start = week_end + timedelta(days=1)
            week_index += 1

    else:
        counts_by_month = {
            item["month"]: item["count"]
            for item in access_logs.annotate(month=ExtractMonth("check_in_time"))
            .values("month")
            .annotate(count=Count("id"))
        }
        for month_number in range(1, 13):
            rows.append({
                "label": calendar.month_abbr[month_number],
                "count": counts_by_month.get(month_number, 0),
            })

    max_count = max((row["count"] for row in rows), default=0)
    for row in rows:
        row["percent"] = round((row["count"] / max_count) * 100, 1) if max_count else 0

    return rows


def _build_member_growth_rows(members_qs, period_data):
    created_members = members_qs.filter(
        created_at__date__range=(period_data["start_date"], period_data["end_date"])
    )
    period_key = period_data["key"]
    rows = []

    if period_key == "day":
        counts_by_slot = {}
        for hour in created_members.values_list("created_at__hour", flat=True):
            slot_start = (hour // 4) * 4
            counts_by_slot[slot_start] = counts_by_slot.get(slot_start, 0) + 1

        for slot_start in range(0, 24, 4):
            slot_end = slot_start + 3
            rows.append({
                "label": f"{slot_start:02d}h-{slot_end:02d}h",
                "count": counts_by_slot.get(slot_start, 0),
            })

    elif period_key == "week":
        counts_by_day = {
            item["day"]: item["count"]
            for item in created_members.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=Count("id"))
        }
        weekdays = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        for index in range(7):
            current_day = period_data["start_date"] + timedelta(days=index)
            rows.append({"label": weekdays[index], "count": counts_by_day.get(current_day, 0)})

    elif period_key == "month":
        counts_by_day = {
            item["day"]: item["count"]
            for item in created_members.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=Count("id"))
        }
        week_start = period_data["start_date"]
        week_index = 1
        while week_start <= period_data["end_date"]:
            week_end = min(week_start + timedelta(days=6), period_data["end_date"])
            total = 0
            current_day = week_start
            while current_day <= week_end:
                total += counts_by_day.get(current_day, 0)
                current_day += timedelta(days=1)
            rows.append({"label": f"Semaine {week_index}", "count": total})
            week_start = week_end + timedelta(days=1)
            week_index += 1

    else:
        counts_by_month = {
            item["month"]: item["count"]
            for item in created_members.annotate(month=ExtractMonth("created_at"))
            .values("month")
            .annotate(count=Count("id"))
        }
        for month_number in range(1, 13):
            rows.append({
                "label": MONTH_LABELS[month_number],
                "count": counts_by_month.get(month_number, 0),
            })

    return rows


@login_required
def dashboard_redirect(request):
    """Redirige vers le bon dashboard après connexion"""
    
    if not request.user.is_authenticated:
        return redirect('login')

    # === CAS OWNER ===
    if hasattr(request, 'is_owner') and request.is_owner:
        # Si l'Owner a plusieurs gyms → on le redirige vers la sélection
        if len(getattr(request, 'owned_gyms', [])) > 1:
            return redirect('core:select_gym')
        
        # Si l'Owner n'a qu'un seul gym → on va directement sur son dashboard
        elif len(getattr(request, 'owned_gyms', [])) == 1:
            gym = request.owned_gyms[0]
            request.session['current_gym_id'] = gym.id
            return redirect('core:gym_dashboard', gym_id=gym.id)
        
        # Fallback
        else:
            return redirect('core:select_gym')

    # === CAS UTILISATEUR NORMAL (Manager, Coach, etc.) ===
    if hasattr(request, 'gym') and request.gym:
        return redirect('core:gym_dashboard', gym_id=request.gym.id)

    # Fallback général
    return redirect('core:select_gym')

@login_required
def select_gym(request):
    """Page pour sélectionner un gym (Owner avec plusieurs gyms)"""
    
    # Récupérer tous les gyms accessibles
    if hasattr(request, 'is_owner') and request.is_owner:
        gyms = request.owned_gyms if hasattr(request, 'owned_gyms') else []
    else:
        gyms = Gym.objects.filter(
            user_roles__user=request.user,
            user_roles__is_active=True
        )
    
    if request.method == 'POST':
        gym_id = request.POST.get('gym_id')
        gym = get_object_or_404(Gym, id=gym_id)
        
        # Vérifier l'accès
        if gym in gyms or (request.user.is_superuser):
            request.session['current_gym_id'] = gym_id
            return redirect('core:gym_dashboard', gym_id=gym_id)
    
    context = {
        'gyms': gyms,
    }
    return render(request, 'core/select_gym.html', context)

@login_required
def switch_gym(request, gym_id):
    """
    Permet à un Owner de changer de gym actif.
    Version robuste avec vérifications de sécurité.
    """
    user = request.user

    # Vérification 1 : L'utilisateur doit être Owner
    if not getattr(user, 'is_owner', False) or not user.owned_organization:
        messages.error(request, "Vous n'avez pas le droit de changer de gym.")
        return redirect('core:dashboard_redirect')

    # Vérification 2 : Le gym doit appartenir à son organisation
    gym = get_object_or_404(
        Gym,
        id=gym_id,
        organization=user.owned_organization,
        is_active=True
    )

    # Vérification 3 : Optionnel - Vérifier que l'utilisateur a bien accès à ce gym
    if gym not in request.owned_gyms:   # si tu as la propriété owned_gyms dans le middleware
        messages.error(request, "Accès refusé à ce gym.")
        return redirect('core:select_gym')

    # Tout est OK → on change le gym actif en session
    request.session['current_gym_id'] = gym.id
    request.session.modified = True  # Force la sauvegarde de la session

    messages.success(
        request, 
        f"Vous travaillez maintenant sur : <strong>{gym.name}</strong>",
        extra_tags='safe'
    )

    # Redirection vers le dashboard du gym
    return redirect('core:gym_dashboard', gym_id=gym.id)

@login_required
def gym_dashboard(request, gym_id):
    """Dashboard pour une salle spécifique - Vérifie les accès par rôle"""
    
    # Récupérer le gym avec son organisation
    gym = get_object_or_404(Gym.objects.select_related('organization'), id=gym_id)
    
    # ======================
    # VÉRIFICATION DES ACCÈS
    # ======================
    
    user_role = None
    is_owner = hasattr(request, 'is_owner') and request.is_owner
    
    # Owner : vérifier que le gym appartient à son organisation
    if is_owner and request.user.owned_organization:
        if gym.organization_id != request.user.owned_organization_id:
            return HttpResponseForbidden("Accès non autorisé")
        user_role = 'owner'
    
    # Non-Owner : utiliser request.role du middleware
    elif hasattr(request, 'role') and request.role:
        # Vérifier que l'utilisateur a bien un rôle dans ce gym
        user_role_obj = UserGymRole.objects.filter(
            user=request.user, 
            gym=gym, 
            is_active=True
        ).first()
        if not user_role_obj:
            return HttpResponseForbidden("Accès non autorisé")
        user_role = request.role
    
    else:
        # Fallback : vérifier dans la base de données
        user_role_obj = UserGymRole.objects.filter(
            user=request.user, 
            gym=gym, 
            is_active=True
        ).first()
        if not user_role_obj:
            return HttpResponseForbidden("Accès non autorisé")
        user_role = user_role_obj.role
    
    today = now().date()
    view = request.GET.get("view", "dashboard")
    period_data = _get_period_window(request.GET.get("period", "month"), today)
    
    # Récupérer les modules actifs
    active_modules = GymModule.objects.filter(
        gym=gym,
        is_active=True
    ).values_list('module__code', flat=True)

    current_month = today.month
    current_year = today.year

    members_qs = Member.objects.filter(gym=gym)
    active_subscriptions_qs = MemberSubscription.objects.filter(
        member__gym=gym,
        is_active=True,
        end_date__gte=today,
        is_paused=False,
    )

    total_members = members_qs.count()
    active_members = members_qs.filter(
        status="active",
        subscriptions__in=active_subscriptions_qs,
    ).distinct().count()
    suspended_members = members_qs.filter(status="suspended").count()
    expired_members = max(total_members - active_members - suspended_members, 0)
    active_member_rate = round((active_members / total_members) * 100, 1) if total_members else 0

    new_members_month = members_qs.filter(
        created_at__year=current_year,
        created_at__month=current_month,
    ).count()
    new_members_period = members_qs.filter(
        created_at__date__range=(period_data["start_date"], period_data["end_date"])
    ).count()
    new_members_previous = members_qs.filter(
        created_at__date__range=(period_data["previous_start"], period_data["previous_end"])
    ).count()

    subscriptions_in_period = MemberSubscription.objects.filter(
        member__gym=gym,
        start_date__range=(period_data["start_date"], period_data["end_date"]),
    )
    subscriptions_previous_period = MemberSubscription.objects.filter(
        member__gym=gym,
        start_date__range=(period_data["previous_start"], period_data["previous_end"]),
    )
    previous_subscription_exists = MemberSubscription.objects.filter(
        member=OuterRef("member"),
        start_date__lt=OuterRef("start_date"),
    )
    renewals_period = subscriptions_in_period.annotate(
        has_previous=Exists(previous_subscription_exists)
    ).filter(has_previous=True).count()
    renewals_previous = subscriptions_previous_period.annotate(
        has_previous=Exists(previous_subscription_exists)
    ).filter(has_previous=True).count()

    expirations_period = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date__range=(period_data["start_date"], period_data["end_date"]),
    ).count()
    expirations_previous = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date__range=(period_data["previous_start"], period_data["previous_end"]),
    ).count()
    expiry_soon = MemberSubscription.objects.filter(
        member__gym=gym,
        is_active=True,
        end_date__gte=today,
        end_date__lte=today + timedelta(days=15),
    ).count()
    expiry_7_days = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date=today + timedelta(days=7),
        is_active=True,
    ).count()
    expiry_3_days = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date=today + timedelta(days=3),
        is_active=True,
    ).count()
    expiry_1_day = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date=today + timedelta(days=1),
        is_active=True,
    ).count()

    access_period_qs = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date__range=(period_data["start_date"], period_data["end_date"]),
    )
    access_previous_qs = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date__range=(period_data["previous_start"], period_data["previous_end"]),
    )
    visits_period = access_period_qs.filter(access_granted=True).count()
    visits_previous = access_previous_qs.filter(access_granted=True).count()
    unique_visitors_period = access_period_qs.filter(
        access_granted=True
    ).values("member_id").distinct().count()
    denied_period = access_period_qs.filter(access_granted=False).count()
    today_checkins = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date=today,
        access_granted=True,
    ).count()
    denied_today = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date=today,
        access_granted=False,
    ).count()
    engagement_rate = round((unique_visitors_period / active_members) * 100, 1) if active_members else 0
    average_daily_visits = round(visits_period / period_data["days"], 1) if period_data["days"] else 0
    attendance_rows = _build_attendance_rows(gym, period_data)
    week_labels = [row["label"] for row in attendance_rows]
    week_values = [row["count"] for row in attendance_rows]
    member_growth_rows = _build_member_growth_rows(members_qs, period_data)
    member_growth_labels = [row["label"] for row in member_growth_rows]
    member_growth_values = [row["count"] for row in member_growth_rows]

    daily_revenue = 0
    monthly_revenue = 0
    period_revenue = 0
    previous_period_revenue = 0
    sales_labels = []
    sales_values = []
    if user_role in ["owner", "manager", "accountant", "cashier"]:
        successful_incoming_payments = Payment.objects.filter(
            gym=gym,
            status="success",
            type="in",
        )
        daily_revenue = successful_incoming_payments.filter(
            created_at__date=today
        ).aggregate(total=Sum("amount_cdf"))["total"] or 0
        monthly_revenue = successful_incoming_payments.filter(
            created_at__year=current_year,
            created_at__month=current_month,
        ).aggregate(total=Sum("amount_cdf"))["total"] or 0
        period_revenue = successful_incoming_payments.filter(
            created_at__date__range=(period_data["start_date"], period_data["end_date"])
        ).aggregate(total=Sum("amount_cdf"))["total"] or 0
        previous_period_revenue = successful_incoming_payments.filter(
            created_at__date__range=(period_data["previous_start"], period_data["previous_end"])
        ).aggregate(total=Sum("amount_cdf"))["total"] or 0

        monthly_sales = successful_incoming_payments.filter(
            created_at__year=current_year
        ).annotate(
            month=ExtractMonth("created_at")
        ).values("month").annotate(
            total=Sum("amount_cdf")
        ).order_by("month")

        for item in monthly_sales:
            sales_labels.append(calendar.month_abbr[item["month"]])
            sales_values.append(float(item["total"]))

    new_members_trend = _build_trend(new_members_period, new_members_previous)
    renewals_trend = _build_trend(renewals_period, renewals_previous)
    visits_trend = _build_trend(visits_period, visits_previous)
    revenue_trend = _build_trend(period_revenue, previous_period_revenue)
    expirations_trend = _build_trend(expirations_period, expirations_previous)

    plans_stats = MemberSubscription.objects.filter(
        member__gym=gym,
        is_active=True,
        end_date__gte=today,
    ).values("plan__name").annotate(total=Count("id")).order_by("-total")
    total_subscriptions = MemberSubscription.objects.filter(
        member__gym=gym,
        is_active=True,
        end_date__gte=today,
    ).count()
    plan_labels = [plan["plan__name"] or "Sans nom" for plan in plans_stats]
    plan_values = [plan["total"] for plan in plans_stats]
    status_chart_labels = ["Actifs", "Expires", "Suspendus"]
    status_chart_values = [active_members, expired_members, suspended_members]

    recent_payments = []
    if user_role in ["owner", "manager", "accountant", "cashier"]:
        recent_payments = Payment.objects.filter(gym=gym).select_related("member").order_by("-created_at")[:5]

    pending_count = 0
    pending_total = 0
    if user_role in ["owner", "manager", "accountant", "cashier"]:
        pending_payments = Payment.objects.filter(
            gym=gym,
            status="pending",
        )
        pending_count = pending_payments.count()
        pending_total = pending_payments.aggregate(total=Sum("amount_cdf"))["total"] or 0

    recent_access = []
    if user_role in ["owner", "manager", "reception"]:
        recent_access = AccessLog.objects.filter(gym=gym).select_related("member").order_by("-check_in_time")[:5]

    my_members = []
    coach_name = None
    if user_role == "coach":
        from coaching.models import Coach

        coach = Coach.objects.filter(
            gym=gym,
            is_active=True,
        ).filter(
            Q(name__icontains=request.user.first_name) |
            Q(user=request.user)
        ).first()

        if coach:
            my_members = coach.members.filter(is_active=True)
            coach_name = coach.name
        else:
            coach_name = request.user.first_name

    checkins_today = today_checkins if user_role == "reception" else 0
    sales_today = daily_revenue if user_role == "cashier" else 0

    machine_kpis = {
        "total_machines": 0,
        "machines_ok": 0,
        "machines_maintenance": 0,
        "machines_broken": 0,
        "machines_ok_percent": 0,
        "machines_maintenance_percent": 0,
        "machines_broken_percent": 0,
        "availability_rate": 0,
        "attention_count": 0,
        "total_maintenances": 0,
        "total_maintenance_cost": 0,
        "period_maintenances": 0,
        "period_maintenance_cost": 0,
        "monthly_maintenance_cost": 0,
        "average_maintenance_cost": 0,
        "top_costly_machine": "-",
    }
    if "MACHINES" in active_modules:
        from machines.kpis import build_machine_kpis

        machine_kpis = build_machine_kpis(gym, period_data)

    total_maintenance_cost = machine_kpis["total_maintenance_cost"]
    total_revenue = monthly_revenue

    context = {
        "active_modules": active_modules,
        "gym": gym,
        "organization": gym.organization,
        "context_view": view,
        "user_role": user_role,
        "is_owner": is_owner,
        "my_members": my_members,
        "coach_name": coach_name,
        "checkins_today": checkins_today,
        "sales_today": sales_today,
        "total_maintenance_cost": total_maintenance_cost,
        "total_revenue": total_revenue,
        "selected_period": period_data["key"],
        "period_label": period_data["label"],
        "period_label_lower": period_data["label"].lower(),
        "period_range_label": _format_period_range(period_data["start_date"], period_data["end_date"]),
        "period_days": period_data["days"],
        "total_members": total_members,
        "active_members": active_members,
        "active_member_rate": active_member_rate,
        "expired_members": expired_members,
        "suspended_members": suspended_members,
        "new_members_month": new_members_month,
        "new_members_period": new_members_period,
        "renewals_period": renewals_period,
        "expirations_period": expirations_period,
        "unique_visitors_period": unique_visitors_period,
        "engagement_rate": engagement_rate,
        "average_daily_visits": average_daily_visits,
        "new_members_trend": new_members_trend,
        "renewals_trend": renewals_trend,
        "visits_trend": visits_trend,
        "revenue_trend": revenue_trend,
        "expirations_trend": expirations_trend,
        "daily_revenue": daily_revenue,
        "monthly_revenue": monthly_revenue,
        "period_revenue": period_revenue,
        "today_checkins": today_checkins,
        "visits_period": visits_period,
        "denied_period": denied_period,
        "denied_today": denied_today,
        "expiry_soon": expiry_soon,
        "expiry_7_days": expiry_7_days,
        "expiry_3_days": expiry_3_days,
        "expiry_1_day": expiry_1_day,
        "plans_stats": plans_stats,
        "total_subscriptions": total_subscriptions,
        "plan_labels": plan_labels,
        "plan_values": plan_values,
        "attendance_rows": attendance_rows,
        "week_labels": week_labels,
        "week_values": week_values,
        "member_growth_rows": member_growth_rows,
        "status_chart_labels": _to_json(status_chart_labels),
        "status_chart_values": _to_json(status_chart_values),
        "member_growth_labels": _to_json(member_growth_labels),
        "member_growth_values": _to_json(member_growth_values),
        "plan_chart_labels": _to_json(plan_labels),
        "plan_chart_values": _to_json(plan_values),
        "attendance_chart_labels": _to_json(week_labels),
        "attendance_chart_values": _to_json(week_values),
        "sales_chart_labels": _to_json(sales_labels),
        "sales_chart_values": _to_json(sales_values),
        "recent_payments": recent_payments,
        "pending_count": pending_count,
        "pending_total": pending_total,
        "recent_access": recent_access,
        "sales_labels": sales_labels,
        "sales_values": sales_values,
    }
    context.update(machine_kpis)

    return render(request, "core/dashboard_members.html", context)

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
        created_at__date=today,
        status="success",
        type="in",
    )

    daily_revenue = payments_today.aggregate(
        total=Sum("amount_cdf")
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
        created_at__month=current_month,
        status="success",
        type="in",
    )

    monthly_revenue = payments_month.aggregate(
        total=Sum("amount_cdf")
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
            subscriptions=Count("id", distinct=True),
            revenue=Sum(
                "payments__amount_cdf",
                filter=Q(payments__status="success", payments__type="in")
            )
        ).order_by("-revenue")
    
    monthly_sales = Payment.objects.filter(
        gym=gym,
        created_at__year=current_year,
        status="success",
        type="in",
        ).annotate(
            month=ExtractMonth("created_at")
        ).values("month").annotate(
            total=Sum("amount_cdf")
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

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.db.models import Q, Count, Sum, Exists, OuterRef
from django.db.models.functions import ExtractMonth, TruncDate
from django.utils.timezone import now
from datetime import timedelta
import calendar
import json
from access.models import AccessLog
from compte.models import UserGymRole
from compte.models import User
from compte.utils import generate_username
from coaching.models import CoachSpecialty
from organizations.models import SensitiveActivityLog
from .forms import CoachSpecialtyForm, InternalEmployeeForm, OrganizationSettingsForm
from members.models import Member
from organizations.models import Gym, GymModule
from pos.models import Payment
from subscriptions.models import MemberSubscription
from .accounting_reports import (
    accounting_filename,
    build_accounting_report,
    build_csv_export,
    build_custom_csv_export,
    build_custom_report,
    build_custom_xlsx_export,
    build_xlsx_export,
    get_report_period,
    get_report_section,
)


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
    """Redirige vers le bon dashboard apres connexion."""
    if not request.user.is_authenticated:
        return redirect('login')

    if getattr(request, 'is_owner', False):
        owned_gyms = list(getattr(request, 'owned_gyms', []))
        current_gym_id = request.session.get('current_gym_id')

        if len(owned_gyms) == 1:
            gym = owned_gyms[0]
            request.session['current_gym_id'] = gym.id
            return redirect('core:gym_dashboard', gym_id=gym.id)

        if len(owned_gyms) > 1:
            current_gym = next(
                (gym for gym in owned_gyms if str(gym.id) == str(current_gym_id)),
                None,
            )
            if current_gym:
                return redirect('core:gym_dashboard', gym_id=current_gym.id)
            return redirect('core:select_gym')

        return redirect('core:select_gym')

    if getattr(request, 'gym', None):
        return redirect('core:gym_dashboard', gym_id=request.gym.id)

    return redirect('core:select_gym')

@login_required
def select_gym(request):
    """Page de selection d'une salle accessible."""
    if getattr(request, 'is_owner', False):
        gyms = Gym.objects.filter(
            organization=request.organization,
            is_active=True,
        )
    else:
        gyms = Gym.objects.filter(
            user_roles__user=request.user,
            user_roles__is_active=True,
            is_active=True,
            organization__is_active=True,
        )

    gyms = (
        gyms.annotate(
            members_count=Count("members", distinct=True),
            machines_count=Count("machines", distinct=True),
            coaches_count=Count("coaches", distinct=True),
        )
        .select_related("organization")
        .distinct()
        .order_by("name")
    )

    if request.method == 'POST':
        gym_id = request.POST.get('gym_id')
        gym = gyms.filter(id=gym_id).first()
        if request.user.is_superuser and not gym:
            gym = Gym.objects.filter(
                id=gym_id,
                is_active=True,
                organization__is_active=True,
            ).first()
        if gym:
            request.session['current_gym_id'] = gym.id
            request.session.modified = True
            return redirect('core:gym_dashboard', gym_id=gym.id)
        messages.error(request, "Acces refuse a cette salle.")
        return redirect('core:select_gym')

    context = {
        'gyms': gyms,
    }
    return render(request, 'core/select_gym.html', context)

@login_required
@require_POST
def switch_gym(request, gym_id):
    """
    Permet a un Owner de changer de salle active.
    Le changement est volontairement limite au POST + CSRF.
    """
    if not getattr(request, 'is_owner', False) or not getattr(request, 'organization', None):
        messages.error(request, "Vous n'avez pas le droit de changer de gym.")
        return redirect('core:dashboard_redirect')

    gym = Gym.objects.filter(
        id=gym_id,
        organization=request.organization,
        is_active=True,
    ).first()
    if not gym:
        messages.error(request, "Acces refuse a ce gym.")
        return redirect('core:select_gym')

    request.session['current_gym_id'] = gym.id
    request.session.modified = True

    messages.success(
        request, 
        f"Vous travaillez maintenant sur : <strong>{gym.name}</strong>",
        extra_tags='safe'
    )

    return redirect('core:gym_dashboard', gym_id=gym.id)


def _owner_settings_allowed(request):
    return bool(
        request.user.is_authenticated
        and getattr(request, "is_owner", False)
        and getattr(request, "organization", None)
    )


def _log_sensitive_action(request, action, target_type="", target_label="", metadata=None, gym=None):
    if not getattr(request, "organization", None):
        return

    SensitiveActivityLog.objects.create(
        organization=request.organization,
        gym=gym or getattr(request, "gym", None),
        actor=request.user if request.user.is_authenticated else None,
        action=action,
        target_type=target_type,
        target_label=target_label,
        metadata={
            "ip": request.META.get("REMOTE_ADDR", ""),
            **(metadata or {}),
        },
    )


@login_required
def settings_dashboard(request):
    if not _owner_settings_allowed(request):
        return HttpResponseForbidden("Acces non autorise")

    organization = request.organization
    gym = request.gym
    if not gym:
        return redirect("core:select_gym")

    active_tab = request.GET.get("tab", "organization")
    organization_form = OrganizationSettingsForm(instance=organization)
    employee_form = InternalEmployeeForm(organization=organization)
    specialty_form = CoachSpecialtyForm()

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "organization":
            active_tab = "organization"
            organization_form = OrganizationSettingsForm(request.POST, request.FILES, instance=organization)
            if organization_form.is_valid():
                organization_form.save()
                _log_sensitive_action(
                    request,
                    "organization.updated",
                    "Organization",
                    organization.name,
                )
                messages.success(request, "Informations de l'organisation mises a jour.")
                return redirect("core:settings")

        elif action == "employee_create":
            active_tab = "employees"
            employee_form = InternalEmployeeForm(request.POST, organization=organization)
            if employee_form.is_valid():
                selected_gym = employee_form.cleaned_data["gym"]
                username = generate_username(
                    employee_form.cleaned_data["first_name"],
                    employee_form.cleaned_data["last_name"],
                )
                employee = User.objects.create(
                    username=username,
                    first_name=employee_form.cleaned_data["first_name"],
                    last_name=employee_form.cleaned_data["last_name"],
                    email=employee_form.cleaned_data["email"],
                    password=make_password("12345"),
                    is_active=employee_form.cleaned_data["is_active"],
                    is_staff=False,
                )
                role = UserGymRole.objects.create(
                    user=employee,
                    gym=selected_gym,
                    role=employee_form.cleaned_data["role"],
                    is_active=employee_form.cleaned_data["is_active"],
                )
                _log_sensitive_action(
                    request,
                    "employee.created",
                    "UserGymRole",
                    f"{employee.username} - {role.get_role_display()} ({selected_gym.name})",
                    metadata={"role": role.role, "employee_id": employee.id},
                    gym=selected_gym,
                )
                messages.success(
                    request,
                    f"Employe cree : {username}. Mot de passe par defaut : 12345",
                )
                return redirect("core:settings")

        elif action in ["employee_activate", "employee_deactivate", "employee_reset_password"]:
            active_tab = "employees"
            role = get_object_or_404(
                UserGymRole.objects.select_related("user", "gym"),
                id=request.POST.get("role_id"),
                gym__organization=organization,
            )
            if role.role == "owner":
                return HttpResponseForbidden("Impossible de modifier un Owner ici.")

            if action == "employee_reset_password":
                role.user.password = make_password("12345")
                role.user.save(update_fields=["password"])
                _log_sensitive_action(
                    request,
                    "employee.password_reset",
                    "User",
                    role.user.username,
                    metadata={"employee_id": role.user_id},
                    gym=role.gym,
                )
                messages.success(request, f"Mot de passe reinitialise pour {role.user.username} : 12345")
                return redirect("core:settings")

            if role.user_id == request.user.id:
                messages.error(request, "Vous ne pouvez pas vous desactiver vous-meme.")
                return redirect("core:settings")

            should_activate = action == "employee_activate"
            role.is_active = should_activate
            role.save(update_fields=["is_active"])
            role.user.is_active = should_activate
            role.user.save(update_fields=["is_active"])
            _log_sensitive_action(
                request,
                "employee.activated" if should_activate else "employee.deactivated",
                "UserGymRole",
                role.user.username,
                metadata={"employee_id": role.user_id, "role": role.role},
                gym=role.gym,
            )
            status_label = "active" if should_activate else "desactive"
            messages.success(request, f"Employe {role.user.username} {status_label}.")
            return redirect("core:settings")

        elif action == "specialty_create":
            active_tab = "specialties"
            specialty_form = CoachSpecialtyForm(request.POST)
            if specialty_form.is_valid():
                name = specialty_form.cleaned_data["name"].strip()
                specialty, created = CoachSpecialty.objects.get_or_create(
                    gym=gym,
                    name=name,
                    defaults={"is_active": True},
                )
                if not created and not specialty.is_active:
                    specialty.is_active = True
                    specialty.save(update_fields=["is_active"])
                _log_sensitive_action(
                    request,
                    "coach_specialty.created" if created else "coach_specialty.reactivated",
                    "CoachSpecialty",
                    specialty.name,
                    gym=gym,
                )
                messages.success(request, f"Specialite coach enregistree : {specialty.name}")
                return redirect("core:settings")

        elif action in ["specialty_activate", "specialty_deactivate"]:
            active_tab = "specialties"
            specialty = get_object_or_404(CoachSpecialty, id=request.POST.get("specialty_id"), gym=gym)
            specialty.is_active = action == "specialty_activate"
            specialty.save(update_fields=["is_active"])
            _log_sensitive_action(
                request,
                "coach_specialty.activated" if specialty.is_active else "coach_specialty.deactivated",
                "CoachSpecialty",
                specialty.name,
                gym=gym,
            )
            messages.success(request, f"Specialite {specialty.name} mise a jour.")
            return redirect("core:settings")

    employee_roles = (
        UserGymRole.objects.filter(gym__organization=organization)
        .exclude(role="owner")
        .select_related("user", "gym")
        .order_by("gym__name", "user__first_name", "user__last_name")
    )
    specialties = CoachSpecialty.objects.filter(gym=gym).order_by("name")
    activity_logs = (
        SensitiveActivityLog.objects.filter(organization=organization)
        .select_related("actor", "gym")
        .order_by("-created_at")[:50]
    )

    context = {
        "organization": organization,
        "gym": gym,
        "organization_form": organization_form,
        "employee_form": employee_form,
        "specialty_form": specialty_form,
        "employee_roles": employee_roles,
        "specialties": specialties,
        "activity_logs": activity_logs,
        "active_tab": active_tab,
        "nav_active": "parametres",
    }
    return render(request, "core/settings.html", context)


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

        coach_lookup = Q()
        for value in [request.user.get_full_name(), request.user.first_name, getattr(request.user, "phone", "")]:
            if value:
                coach_lookup |= Q(name__icontains=value) | Q(phone=value)
        coach = Coach.objects.filter(gym=gym, is_active=True).filter(coach_lookup).first() if coach_lookup else None

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

    rh_kpis = {
        "total_employees": 0,
        "active_employees": 0,
        "inactive_employees": 0,
        "attendance_today_present": 0,
        "attendance_today_absent": 0,
        "attendance_today_rate": 0,
        "attendance_period_present": 0,
        "attendance_period_absent": 0,
        "attendance_period_rate": 0,
        "monthly_payroll": 0,
        "monthly_payroll_paid": 0,
        "monthly_payroll_pending": 0,
        "monthly_payroll_pending_count": 0,
        "salary_paid_period": 0,
        "salary_payments_period": 0,
        "employee_role_breakdown": [],
    }
    if "RH" in active_modules:
        from rh.kpis import build_rh_kpis

        rh_kpis = build_rh_kpis(gym, period_data)

    product_kpis = {
        "total_products": 0,
        "all_products_count": 0,
        "inactive_products": 0,
        "stock_value_total": 0,
        "stock_ok_count": 0,
        "low_stock_count": 0,
        "out_of_stock_count": 0,
        "stock_movements_period": 0,
        "stock_in_period": 0,
        "stock_out_period": 0,
        "top_value_products": [],
        "recent_stock_movements": [],
        "stock_status_chart_labels": [],
        "stock_status_chart_values": [],
        "stock_value_chart_labels": [],
        "stock_value_chart_values": [],
    }
    if "PRODUCTS" in active_modules:
        from products.kpis import build_product_kpis

        product_kpis = build_product_kpis(gym, period_data)

    coaching_kpis = {
        "total_coaches": 0,
        "active_coaches": 0,
        "inactive_coaches": 0,
        "assigned_members_count": 0,
        "unassigned_members_count": 0,
        "average_members_per_coach": 0,
        "new_coaches_period": 0,
        "top_coaches": [],
        "coaching_status_chart_labels": [],
        "coaching_status_chart_values": [],
        "coaching_workload_chart_labels": [],
        "coaching_workload_chart_values": [],
    }
    if "COACHING" in active_modules:
        from coaching.kpis import build_coaching_kpis

        coaching_kpis = build_coaching_kpis(gym, period_data)

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
        "stock_status_chart_labels_json": _to_json(product_kpis["stock_status_chart_labels"]),
        "stock_status_chart_values_json": _to_json(product_kpis["stock_status_chart_values"]),
        "stock_value_chart_labels_json": _to_json(product_kpis["stock_value_chart_labels"]),
        "stock_value_chart_values_json": _to_json(product_kpis["stock_value_chart_values"]),
        "coaching_status_chart_labels_json": _to_json(coaching_kpis["coaching_status_chart_labels"]),
        "coaching_status_chart_values_json": _to_json(coaching_kpis["coaching_status_chart_values"]),
        "coaching_workload_chart_labels_json": _to_json(coaching_kpis["coaching_workload_chart_labels"]),
        "coaching_workload_chart_values_json": _to_json(coaching_kpis["coaching_workload_chart_values"]),
        "recent_payments": recent_payments,
        "pending_count": pending_count,
        "pending_total": pending_total,
        "recent_access": recent_access,
        "sales_labels": sales_labels,
        "sales_values": sales_values,
    }
    context.update(machine_kpis)
    context.update(rh_kpis)
    context.update(product_kpis)
    context.update(coaching_kpis)

    return render(request, "core/dashboard_members.html", context)

@login_required
def _legacy_reports_dashboard(request):
    gym = getattr(request, "gym", None)
    if not gym:
        return redirect("core:select_gym")

    user_role = getattr(request, "role", None)
    if user_role not in ["owner", "manager", "accountant", "cashier"]:
        return HttpResponseForbidden("Acces non autorise")

    today = now().date()
    section = request.GET.get("section", "journalier")
    period_data = get_report_period(request.GET)
    accounting_report = build_accounting_report(gym, period_data)
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
        "selected_period": period_data["key"],
        "date_from": period_data["date_from"],
        "date_to": period_data["date_to"],
        "report_period_label": period_data["label"],
        "accounting_report": accounting_report,
        "can_export_accounting": user_role in ["owner", "manager", "accountant"],
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
def reports_dashboard(request):
    gym = getattr(request, "gym", None)
    if not gym:
        return redirect("core:select_gym")

    user_role = getattr(request, "role", None)
    if user_role not in ["owner", "manager", "accountant", "cashier"]:
        return HttpResponseForbidden("Acces non autorise")

    section = get_report_section(request.GET)
    default_period_by_section = {
        "journalier": "today",
        "mensuel": "month",
        "personnalise": "custom",
    }
    period_data = get_report_period(
        request.GET,
        default_period=default_period_by_section.get(section, "month"),
    )
    accounting_report = build_accounting_report(gym, period_data)

    payments_period = Payment.objects.filter(
        gym=gym,
        created_at__date__range=(period_data["start_date"], period_data["end_date"]),
        status="success",
    )
    incoming_period = payments_period.filter(type="in")

    daily_revenue = incoming_period.aggregate(total=Sum("amount_cdf"))["total"] or 0
    daily_transactions = payments_period.count()
    daily_new_clients = Member.objects.filter(
        gym=gym,
        created_at__date__range=(period_data["start_date"], period_data["end_date"]),
    ).count()
    daily_visits = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date__range=(period_data["start_date"], period_data["end_date"]),
        access_granted=True,
    ).count()
    denied_access = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date__range=(period_data["start_date"], period_data["end_date"]),
        access_granted=False,
    ).count()
    transactions = payments_period.select_related("member", "cash_register").order_by("-created_at")[:50]

    monthly_revenue = daily_revenue
    monthly_transactions = daily_transactions
    monthly_new_members = daily_new_clients
    monthly_renewals = MemberSubscription.objects.filter(
        member__gym=gym,
        start_date__range=(period_data["start_date"], period_data["end_date"]),
    ).count()
    monthly_visits = daily_visits

    plans_stats = MemberSubscription.objects.filter(
        member__gym=gym,
        start_date__range=(period_data["start_date"], period_data["end_date"]),
    ).values("plan__name").annotate(
        subscriptions=Count("id", distinct=True),
        revenue=Sum(
            "payments__amount_cdf",
            filter=Q(payments__status="success", payments__type="in"),
        ),
    ).order_by("-revenue")

    monthly_sales = incoming_period.annotate(
        month=ExtractMonth("created_at")
    ).values("month").annotate(
        total=Sum("amount_cdf")
    ).order_by("month")

    sales_labels = []
    sales_values = []
    for item in monthly_sales:
        sales_labels.append(calendar.month_abbr[item["month"]])
        sales_values.append(float(item["total"]))

    custom_report = build_custom_report(gym, request.GET, period_data, limit=50)

    context = {
        "section": section,
        "selected_period": period_data["key"],
        "date_from": period_data["date_from"],
        "date_to": period_data["date_to"],
        "report_period_label": period_data["label"],
        "accounting_report": accounting_report,
        "can_export_accounting": user_role in ["owner", "manager", "accountant"],
        "custom_report": custom_report,
        "daily_revenue": daily_revenue,
        "daily_transactions": daily_transactions,
        "daily_new_clients": daily_new_clients,
        "daily_visits": daily_visits,
        "denied_access": denied_access,
        "transactions": transactions,
        "monthly_revenue": monthly_revenue,
        "monthly_new_members": monthly_new_members,
        "monthly_renewals": monthly_renewals,
        "monthly_visits": monthly_visits,
        "plans_stats": plans_stats,
        "sales_labels": sales_labels,
        "sales_values": sales_values,
        "monthly_transactions": monthly_transactions,
    }

    return render(request, "core/rapports.html", context)


@login_required
def accounting_report_export(request):
    gym = getattr(request, "gym", None)
    if not gym:
        return redirect("core:select_gym")

    user_role = getattr(request, "role", None)
    if user_role not in ["owner", "manager", "accountant"]:
        return HttpResponseForbidden("Acces non autorise")

    export_format = request.GET.get("format", "xlsx").lower()
    if export_format == "excel":
        export_format = "xlsx"
    if export_format not in ["csv", "xlsx"]:
        return HttpResponseBadRequest("Format d'export non supporte.")

    section = get_report_section(request.GET)
    default_period = "custom" if section == "personnalise" else "month"
    period_data = get_report_period(request.GET, default_period=default_period)

    if section == "personnalise":
        custom_report = build_custom_report(gym, request.GET, period_data)
        if export_format == "csv":
            content = build_custom_csv_export(custom_report)
            content_type = "text/csv; charset=utf-8"
        else:
            content = build_custom_xlsx_export(custom_report)
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = (
            f'attachment; filename="{accounting_filename(gym, period_data, export_format)}"'
        )
        return response

    report = build_accounting_report(gym, period_data)

    if export_format == "csv":
        content = build_csv_export(report)
        content_type = "text/csv; charset=utf-8"
    else:
        content = build_xlsx_export(report)
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = (
        f'attachment; filename="{accounting_filename(gym, period_data, export_format)}"'
    )
    return response

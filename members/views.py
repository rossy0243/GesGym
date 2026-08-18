#members/views.py
import json
import mimetypes
from datetime import date, timedelta
from decimal import Decimal
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.db.models import Model, Subquery
from django.db.models import Q, Exists, OuterRef, Count
from django.core.paginator import Paginator
from django.urls import reverse
from django.utils.html import format_html
from django.utils.text import slugify
from django.templatetags.static import static
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_http_methods
from access.models import AccessLog
from coaching.forms import CoachingFeedbackForm
from coaching.models import Coach, CoachingFeedback, GroupCoachingProgram
from compte.utils import generate_temporary_password
from core.audit import log_sensitive_action
from core.creation_emails import (
    notify_creation_email_failure,
    send_member_creation_email,
    send_member_password_reset_email,
)
from smartclub.access_control import (
    MEMBER_DELETE_ROLES,
    MEMBER_ROLES,
    MEMBER_STATUS_ROLES,
    MEMBER_WRITE_ROLES,
    has_role,
)
from smartclub.public_links import build_public_url
from .forms import MemberCreationForm, MemberGoalForm, MemberWeightMeasurementForm
from .models import Member, MemberGoal, MemberPreRegistration, MemberPreRegistrationLink, MemberWeightMeasurement
from notifications.models import Notification
from organizations.models import Organization
from pos.models import Payment
from subscriptions.models import MemberSubscription, SubscriptionPlan, SubscriptionRequest


#######   MEMBRE  ######


def _cleanup_expired_pre_registrations():
    MemberPreRegistration.mark_expired_pending()


def _member_management_allowed(request):
    return has_role(request, MEMBER_ROLES) and request.gym


def _member_write_allowed(request):
    return has_role(request, MEMBER_WRITE_ROLES) and request.gym


def _member_qr_admin_allowed(request):
    # Regenerer un QR invalide la carte imprimee du membre : reserve aux
    # proprietaires et gerants.
    # bool() explicite : cette valeur est serialisee telle quelle dans la fiche
    # membre, elle ne doit pas y arriver sous forme d'objet Gym.
    return bool(has_role(request, MEMBER_STATUS_ROLES) and request.gym)


def _get_pre_registration_public_url(request, link):
    return request.build_absolute_uri(
        reverse("members:public_pre_registration", args=[link.token])
    )


def _get_current_member(user):
    return getattr(user, "member_profile", None)


def _member_code(member):
    return f"MEM-{member.id:05d}"


SUSPENDED_MEMBER_MESSAGE = (
    "Votre compte est suspendu. Contactez la salle pour le reactiver."
)


def _member_filename(member, prefix, extension="png"):
    """Nom de fichier lisible pour un telechargement."""
    slug = slugify(f"{member.first_name}-{member.last_name}") or f"membre-{member.id}"
    return f"{prefix}_{slug}.{extension}"


def _image_response(content, filename, as_attachment):
    """
    Reponse image, telechargee ou affichee selon le contexte.

    L'en-tete n'est pose que sur demande explicite : la meme URL sert aussi
    d'apercu dans l'interface, ou une piece jointe serait genante.
    """
    response = HttpResponse(content, content_type="image/png")
    response["Cache-Control"] = "private, no-store"
    if as_attachment:
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _wants_download(request):
    return request.GET.get("download") in {"1", "true", "yes"}


def _member_is_suspended(member):
    return getattr(member, "status", "") == "suspended"


def _block_suspended_member(request, member):
    """
    Coupe les actions engageantes d'un membre suspendu.

    Masquer les boutons ne suffit pas : un formulaire deja ouvert ou un appel
    direct passerait au travers. Le refus doit venir du serveur.
    Renvoie une redirection si le membre est suspendu, sinon None.
    """
    if not _member_is_suspended(member):
        return None

    messages.error(request, SUSPENDED_MEMBER_MESSAGE)
    return redirect("members:member_portal")


def _api_block_suspended_member(member):
    """Equivalent pour l'application mobile."""
    if not _member_is_suspended(member):
        return None
    return _json_error(SUSPENDED_MEMBER_MESSAGE, status=403)


def _json_safe_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Model):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    return value


def _subscription_progress(subscription):
    if not subscription:
        return 0

    total_days = max((subscription.end_date - subscription.start_date).days, 1)
    elapsed_days = (timezone.localdate() - subscription.start_date).days
    progress = round((elapsed_days / total_days) * 100)
    return min(max(progress, 0), 100)


def _status_label(status):
    return {
        "active": "Actif",
        "expired": "Expire",
        "suspended": "Suspendu",
    }.get(status, "Inconnu")


def _status_class(status):
    return {
        "active": "is-active",
        "expired": "is-expired",
        "suspended": "is-suspended",
    }.get(status, "is-unknown")


def _member_coaching_rights(subscription):
    if subscription and subscription.plan:
        return subscription.plan.coaching_rights_payload()

    return {
        "mode": "none",
        "mode_label": "Aucun coaching",
        "level": "standard",
        "level_label": "Standard",
        "allows_individual": False,
        "allows_group": False,
        "has_any_access": False,
    }


def _member_can_choose_individual_coach(member, subscription):
    return member.has_individual_coaching_access


def _member_can_choose_group_program(member, subscription):
    return member.has_group_coaching_access


def _member_tab_config(unread_notification_count):
    badge = str(unread_notification_count) if unread_notification_count else ""
    return [
        {"key": "home", "label": "Accueil", "icon": "home"},
        {"key": "goal", "label": "Objectif", "icon": "goal"},
        {"key": "messages", "label": "Messages", "icon": "mail", "badge": badge},
        {"key": "plans", "label": "Formules", "icon": "plans"},
    ]


def _build_feedback_form(prefix):
    return CoachingFeedbackForm(prefix=prefix)


def _member_goal_access(goal):
    if not goal:
        return {
            "can_member_record": False,
            "can_coach_record": False,
            "waiting_for": "",
        }

    if not goal.is_started:
        if goal.measurement_starter == MemberGoal.STARTER_MEMBER:
            return {
                "can_member_record": True,
                "can_coach_record": False,
                "waiting_for": "member",
            }
        return {
            "can_member_record": False,
            "can_coach_record": True,
            "waiting_for": "coach",
        }

    return {
        "can_member_record": True,
        "can_coach_record": True,
        "waiting_for": "",
    }


def _goal_direction_label(goal):
    if not goal:
        return ""
    return "Encore a gagner" if goal.goal_type == MemberGoal.GOAL_GAIN_WEIGHT else "Encore a perdre"


def _json_error(message, status=400, errors=None):
    payload = {"ok": False, "error": message}
    if errors:
        payload["errors"] = errors
    return JsonResponse(payload, status=status)


def _json_success(data=None, status=200):
    payload = {"ok": True}
    if data:
        payload.update(data)
    return JsonResponse(payload, status=status)


def _json_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("JSON invalide.")


def _form_errors(form):
    return {
        field: [str(error) for error in errors]
        for field, errors in form.errors.items()
    }


def _api_current_member(request):
    if not request.user.is_authenticated:
        return None, _json_error("Authentification requise.", status=401)
    member = _get_current_member(request.user)
    if not member:
        return None, _json_error("Ce compte n'est pas un compte membre.", status=403)
    member = get_object_or_404(
        Member.objects.select_related("user", "gym", "gym__organization"),
        id=member.id,
        user=request.user,
    )
    return member, None


def _absolute_media_url(request, file_field):
    if not file_field:
        return ""
    try:
        return request.build_absolute_uri(file_field.url)
    except ValueError:
        return ""


def _subscription_payload(subscription):
    if not subscription:
        return None
    plan = subscription.plan
    return {
        "id": subscription.id,
        "start_date": subscription.start_date.isoformat(),
        "end_date": subscription.end_date.isoformat(),
        "progress": _subscription_progress(subscription),
        "plan": {
            "id": plan.id if plan else None,
            "name": plan.name if plan else "-",
            "price": float(plan.price) if plan else 0,
            "duration_days": plan.duration_days if plan else 0,
            "offers": [
                {
                    "id": offer.id,
                    "name": offer.name,
                    "category": offer.category,
                    "category_label": offer.get_category_display(),
                }
                for offer in plan.active_offers
            ] if plan else [],
        },
    }


def _payment_payload(payment):
    return {
        "id": payment.id,
        "description": payment.description or "Paiement",
        "amount_cdf": float(payment.amount_cdf or 0),
        "amount_usd": float(payment.amount_usd or payment.amount or 0),
        "currency": payment.currency,
        "method": payment.method,
        "method_label": payment.get_method_display(),
        "status": payment.status,
        "status_label": payment.get_status_display(),
        "category": payment.category,
        "category_label": payment.get_category_display(),
        "created_at": payment.created_at.isoformat(),
    }


def _access_log_payload(log):
    return {
        "id": log.id,
        "access_granted": log.access_granted,
        "status_label": "Autorise" if log.access_granted else "Refuse",
        "denial_reason": log.denial_reason or "",
        "device_used": log.device_used or "",
        "check_in_time": log.check_in_time.isoformat(),
    }


def _notification_payload(notification):
    return {
        "id": notification.id,
        "title": notification.title or "Message de la salle",
        "message": notification.message,
        "is_read": bool(notification.read_at),
        "created_at": notification.created_at.isoformat(),
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
    }


def _plan_payload(plan, current_plan_id, pending_plan_ids, top_plan_sales_count):
    return {
        "id": plan.id,
        "name": plan.name,
        "description": plan.description or "",
        "duration_days": plan.duration_days,
        "price": float(plan.price),
        "is_current": plan.id == current_plan_id,
        "is_pending": plan.id in pending_plan_ids,
        "is_featured": bool(top_plan_sales_count and plan.total_sales_count == top_plan_sales_count),
        "sales_count": plan.total_sales_count,
        "coaching_rights": plan.coaching_rights_payload(),
        "offers": [
            {
                "id": offer.id,
                "name": offer.name,
                "category": offer.category,
                "category_label": offer.get_category_display(),
            }
            for offer in plan.active_offers
        ],
    }


def _coach_payload(coach, current_coach_id=None):
    return {
        "id": coach.id,
        "name": coach.name,
        "phone": coach.phone or "",
        "specialty": coach.specialty or "Coach sportif",
        "is_current": coach.id == current_coach_id,
        "member_count": getattr(coach, "member_count", coach.members.count()),
    }


def _group_program_payload(program, current_group_program_id=None):
    participants_total = getattr(program, "participants_total", program.participants.count())
    return {
        "id": program.id,
        "name": program.name,
        "objective": program.objective or "",
        "description": program.description or "",
        "coach": _coach_payload(program.coach),
        "capacity": program.capacity,
        "participants_total": participants_total,
        "is_current": program.id == current_group_program_id,
        "is_full": participants_total >= program.capacity,
    }


def _goal_payload(goal, goal_access):
    if not goal:
        return None
    return {
        "id": goal.id,
        "goal_type": goal.goal_type,
        "goal_type_label": goal.get_goal_type_display(),
        "target_weight": float(goal.target_weight),
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "measurement_starter": goal.measurement_starter,
        "measurement_starter_label": goal.get_measurement_starter_display(),
        "initial_weight": float(goal.initial_weight) if goal.initial_weight is not None else None,
        "current_weight": float(goal.current_weight) if goal.current_weight is not None else None,
        "remaining_weight": float(goal.remaining_weight) if goal.current_weight is not None else None,
        "progress_percent": goal.progress_percent,
        "status": goal.status,
        "note": goal.note or "",
        "can_member_record": goal_access["can_member_record"],
        "waiting_for": goal_access["waiting_for"],
        "direction_label": _goal_direction_label(goal),
        "measurements": [
            {
                "id": measurement.id,
                "weight": float(measurement.weight),
                "measured_at": measurement.measured_at.isoformat(),
                "source": measurement.source,
                "source_label": measurement.get_source_display(),
                "note": measurement.note or "",
            }
            for measurement in goal.measurements_ordered[:8]
        ],
    }


def _member_mobile_payload(request, member):
    subscription = member.active_subscription
    payments = list(
        Payment.objects.filter(member=member, gym=member.gym)
        .select_related("subscription", "subscription__plan", "product")
        .order_by("-created_at")[:6]
    )
    access_logs = list(
        AccessLog.objects.filter(member=member, gym=member.gym)
        .select_related("scanned_by")
        .order_by("-check_in_time")[:8]
    )
    can_choose_individual_coach = _member_can_choose_individual_coach(member, subscription)
    can_choose_group_program = _member_can_choose_group_program(member, subscription)
    coaches = list(
        Coach.objects.filter(gym=member.gym, members=member, is_active=True).order_by("name")
        if can_choose_individual_coach
        else []
    )
    selected_group_programs = list(
        GroupCoachingProgram.objects.filter(
            gym=member.gym,
            participants=member,
            is_active=True,
        ).select_related("coach").order_by("name")
        if can_choose_group_program
        else []
    )
    notifications = list(
        Notification.objects.filter(
            gym=member.gym,
            member=member,
            channel=Notification.CHANNEL_IN_APP,
            status=Notification.STATUS_SENT,
        ).select_related("sent_by").order_by("-created_at")[:18]
    )
    unread_count = sum(1 for notification in notifications if not notification.read_at)
    available_plans_queryset = SubscriptionPlan.objects.filter(
        gym=member.gym,
        is_active=True,
    ).prefetch_related("offers").annotate(
        total_sales_count=Count(
            "subscriptions",
            filter=Q(subscriptions__gym=member.gym),
            distinct=True,
        )
    )
    top_plan_sales_count = max((plan.total_sales_count for plan in available_plans_queryset), default=0)
    available_plans = list(available_plans_queryset.order_by("-total_sales_count", "price", "duration_days", "name"))
    available_coaches = list(
        Coach.objects.filter(gym=member.gym, is_active=True)
        .annotate(member_count=Count("members", distinct=True))
        .order_by("name")
        if can_choose_individual_coach
        else []
    )
    available_group_programs = list(
        GroupCoachingProgram.objects.filter(gym=member.gym, is_active=True)
        .select_related("coach")
        .annotate(participants_total=Count("participants", distinct=True))
        .order_by("name")
        if can_choose_group_program
        else []
    )
    pending_requests = list(
        SubscriptionRequest.objects.filter(
            gym=member.gym,
            member=member,
            status__in=[
                SubscriptionRequest.STATUS_PENDING,
                SubscriptionRequest.STATUS_AWAITING_PAYMENT,
            ],
        ).select_related("plan").order_by("-created_at")
    )
    pending_plan_ids = [request_item.plan_id for request_item in pending_requests]
    active_goal = member.active_goal
    goal_access = _member_goal_access(active_goal)
    status = member.computed_status
    current_coach_id = coaches[0].id if coaches else None
    current_group_program_id = selected_group_programs[0].id if selected_group_programs else None
    granted_access_count = sum(1 for log in access_logs if log.access_granted)
    denied_access_count = len(access_logs) - granted_access_count

    return {
        "member": {
            "id": member.id,
            "code": _member_code(member),
            "first_name": member.first_name,
            "last_name": member.last_name,
            "full_name": f"{member.first_name} {member.last_name}".strip(),
            "username": member.user.username,
            "phone": member.phone or "",
            "email": member.email or "",
            "photo_url": _absolute_media_url(request, member.photo),
            "qr_data": member.get_qr_data(),
            "status": status,
            "status_label": _status_label(status),
            "status_class": _status_class(status),
            "days_remaining": member.days_remaining,
        },
        "organization": {
            "id": member.gym.organization_id,
            "name": member.gym.organization.name,
            "logo_url": _absolute_media_url(request, member.gym.organization.logo),
        },
        "gym": {
            "id": member.gym_id,
            "name": member.gym.name,
        },
        "subscription": _subscription_payload(subscription),
        "coaching_rights": _member_coaching_rights(subscription),
        "payments": [_payment_payload(payment) for payment in payments],
        "access": {
            "granted_count": granted_access_count,
            "denied_count": denied_access_count,
            "logs": [_access_log_payload(log) for log in access_logs],
        },
        "messages": {
            "unread_count": unread_count,
            "items": [_notification_payload(notification) for notification in notifications],
        },
        "plans": {
            "items": [
                _plan_payload(
                    plan,
                    subscription.plan_id if subscription and subscription.plan_id else None,
                    pending_plan_ids,
                    top_plan_sales_count,
                )
                for plan in available_plans
            ],
            "pending_requests": [
                {
                    "id": request_item.id,
                    "plan_id": request_item.plan_id,
                    "plan_name": request_item.plan.name if request_item.plan_id else "-",
                    "price_usd": float(request_item.price_usd),
                    "status": request_item.status,
                    "status_label": request_item.get_status_display(),
                    "created_at": request_item.created_at.isoformat(),
                }
                for request_item in pending_requests
            ],
        },
        "coaching": {
            "current_coaches": [_coach_payload(coach, current_coach_id) for coach in coaches],
            "available_coaches": [_coach_payload(coach, current_coach_id) for coach in available_coaches],
            "selected_group_programs": [
                _group_program_payload(program, current_group_program_id)
                for program in selected_group_programs
            ],
            "available_group_programs": [
                _group_program_payload(program, current_group_program_id)
                for program in available_group_programs
            ],
            "can_choose_individual_coach": can_choose_individual_coach,
            "can_choose_group_program": can_choose_group_program,
        },
        "goal": _goal_payload(active_goal, goal_access),
    }


@login_required
def member_portal(request):
    """
    Espace mobile du membre connecte: carte, QR code, abonnement et historique.
    """
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    member = get_object_or_404(
        Member.objects.select_related("user", "gym", "gym__organization"),
        id=current_member.id,
        user=request.user,
    )
    subscription = member.active_subscription
    payments = (
        Payment.objects.filter(member=member, gym=member.gym)
        .select_related("subscription", "subscription__plan", "product")
        .order_by("-created_at")[:6]
    )
    access_logs = (
        AccessLog.objects.filter(member=member, gym=member.gym)
        .select_related("scanned_by")
        .order_by("-check_in_time")[:8]
    )
    # Un membre suspendu ne s'engage plus : ni coach, ni programme, ni
    # abonnement. Neutraliser les drapeaux ici retire d'un coup les sections
    # correspondantes du portail.
    member_is_suspended = _member_is_suspended(member)
    can_choose_individual_coach = (
        not member_is_suspended
        and _member_can_choose_individual_coach(member, subscription)
    )
    can_choose_group_program = (
        not member_is_suspended
        and _member_can_choose_group_program(member, subscription)
    )
    coaches = Coach.objects.filter(
        gym=member.gym,
        members=member,
        is_active=True,
    ).order_by("name") if can_choose_individual_coach else Coach.objects.none()
    selected_group_programs = (
        GroupCoachingProgram.objects.filter(
            gym=member.gym,
            participants=member,
            is_active=True,
        ).select_related("coach").order_by("name")
        if can_choose_group_program
        else GroupCoachingProgram.objects.none()
    )
    member_notifications = Notification.objects.filter(
        gym=member.gym,
        member=member,
        channel=Notification.CHANNEL_IN_APP,
        status=Notification.STATUS_SENT,
    ).select_related("sent_by").order_by("-created_at")[:18]
    unread_notification_count = Notification.objects.filter(
        gym=member.gym,
        member=member,
        channel=Notification.CHANNEL_IN_APP,
        status=Notification.STATUS_SENT,
        read_at__isnull=True,
    ).count()
    active_goal = member.active_goal
    goal_measurements = list(active_goal.measurements_ordered) if active_goal else []
    goal_access = _member_goal_access(active_goal)
    available_plans_queryset = SubscriptionPlan.objects.filter(
        gym=member.gym,
        is_active=True,
    ).prefetch_related("offers").annotate(
        total_sales_count=Count(
            "subscriptions",
            filter=Q(subscriptions__gym=member.gym),
            distinct=True,
        )
    )
    top_plan_sales_count = max(
        (plan.total_sales_count for plan in available_plans_queryset),
        default=0,
    )
    available_plans = available_plans_queryset.order_by("-total_sales_count", "price", "duration_days", "name")
    available_coaches = (
        Coach.objects.filter(gym=member.gym, is_active=True)
        .annotate(member_count=Count("members", distinct=True))
        .order_by("name")
        if can_choose_individual_coach
        else Coach.objects.none()
    )
    available_group_programs = (
        GroupCoachingProgram.objects.filter(gym=member.gym, is_active=True)
        .select_related("coach")
        .annotate(participants_total=Count("participants", distinct=True))
        .order_by("name")
        if can_choose_group_program
        else GroupCoachingProgram.objects.none()
    )
    pending_requests = SubscriptionRequest.objects.filter(
        gym=member.gym,
        member=member,
        status__in=[
            SubscriptionRequest.STATUS_PENDING,
            SubscriptionRequest.STATUS_AWAITING_PAYMENT,
        ],
    ).select_related("plan").order_by("-created_at")
    pending_plan_ids = list(pending_requests.values_list("plan_id", flat=True))
    status = member.computed_status
    active_tab = request.GET.get("tab", "home")
    payments_list = list(payments)
    recent_payments = payments_list[:4]
    archived_payments = payments_list[4:]
    access_logs_list = list(access_logs)
    recent_access_logs = access_logs_list[:4]
    archived_access_logs = access_logs_list[4:]
    granted_access_count = sum(1 for item in access_logs_list if item.access_granted)
    denied_access_count = len(access_logs_list) - granted_access_count
    member_notifications_list = list(member_notifications)
    selected_notification = None
    selected_notification_id = request.GET.get("message")
    if selected_notification_id:
        try:
            selected_notification_id = int(selected_notification_id)
        except (TypeError, ValueError):
            selected_notification_id = None
        if selected_notification_id:
            selected_notification = next(
                (
                    notification
                    for notification in member_notifications_list
                    if notification.id == selected_notification_id
                ),
                None,
            )
    unread_notifications = [item for item in member_notifications_list if not item.read_at]
    read_notifications = [item for item in member_notifications_list if item.read_at]
    visible_tabs = _member_tab_config(unread_notification_count)
    if active_tab not in {tab["key"] for tab in visible_tabs} | {"password"}:
        active_tab = "home"

    member_tabs = []
    for tab in visible_tabs:
        member_tabs.append(
            {
                **tab,
                "url": f"{reverse('members:member_portal')}?tab={tab['key']}",
                "is_active": tab["key"] == active_tab,
            }
        )

    password_form = PasswordChangeForm(user=request.user)
    coach_feedback_form = _build_feedback_form("coach-feedback")
    group_feedback_form = _build_feedback_form("group-feedback")
    goal_form = MemberGoalForm()
    measurement_form = MemberWeightMeasurementForm(
        initial={"measured_at": timezone.localdate()}
    )
    latest_coach_feedback = CoachingFeedback.objects.filter(
        gym=member.gym,
        member=member,
        coach__in=coaches,
        group_program__isnull=True,
    ).select_related("coach").first()
    latest_group_feedback = CoachingFeedback.objects.filter(
        gym=member.gym,
        member=member,
        group_program__in=selected_group_programs,
    ).select_related("coach", "group_program").first()

    context = {
        "member": member,
        "member_is_suspended": member_is_suspended,
        "suspended_member_message": SUSPENDED_MEMBER_MESSAGE,
        "member_code": _member_code(member),
        "organization": member.gym.organization,
        "gym": member.gym,
        "subscription": subscription,
        "subscription_progress": _subscription_progress(subscription),
        "payments": payments_list,
        "recent_payments": recent_payments,
        "archived_payments": archived_payments,
        "access_logs": access_logs_list,
        "recent_access_logs": recent_access_logs,
        "archived_access_logs": archived_access_logs,
        "granted_access_count": granted_access_count,
        "denied_access_count": denied_access_count,
        "coaches": coaches,
        "current_coach_id": coaches.first().id if coaches.exists() else None,
        "selected_group_programs": selected_group_programs,
        "current_group_program_id": selected_group_programs.first().id if selected_group_programs.exists() else None,
        "member_notifications": member_notifications_list,
        "selected_notification": selected_notification,
        "unread_notifications": unread_notifications[:5],
        "recent_notifications": read_notifications[:6],
        "archived_notifications": read_notifications[6:18],
        "unread_notification_count": unread_notification_count,
        "member_tabs": member_tabs,
        "active_tab": active_tab,
        "available_plans": available_plans,
        "available_coaches": available_coaches,
        "available_group_programs": available_group_programs,
        "can_choose_individual_coach": can_choose_individual_coach,
        "can_choose_group_program": can_choose_group_program,
        "top_plan_sales_count": top_plan_sales_count,
        "pending_requests": pending_requests,
        "pending_plan_ids": pending_plan_ids,
        "current_plan_id": subscription.plan_id if subscription and subscription.plan_id else None,
        "status": status,
        "status_label": _status_label(status),
        "status_class": _status_class(status),
        "days_remaining": member.days_remaining,
        "password_form": password_form,
        "coach_feedback_form": coach_feedback_form,
        "group_feedback_form": group_feedback_form,
        "latest_coach_feedback": latest_coach_feedback,
        "latest_group_feedback": latest_group_feedback,
        # Le navigateur telecharge le manifeste sans cookie de session : sans
        # l'organisation en parametre, il retomberait sur la marque generique
        # et l'icone installee ne serait pas celle de la salle.
        "pwa_manifest_url": (
            f"{reverse('members:member_app_manifest')}?org={member.gym.organization_id}"
        ),
        "pwa_service_worker_url": reverse("members:member_app_service_worker"),
        "pwa_icon_url": reverse("members:member_app_organization_icon", args=[member.gym.organization_id, 512]),
        "coaching_rights": _member_coaching_rights(subscription),
        "active_goal": active_goal,
        "goal_measurements": goal_measurements,
        "goal_form": goal_form,
        "goal_measurement_form": measurement_form,
        "can_member_record_goal_measurement": goal_access["can_member_record"],
        "goal_waiting_for": goal_access["waiting_for"],
        "goal_direction_label": _goal_direction_label(active_goal),
    }
    return render(request, "members/member_portal.html", context)


@login_required
@require_POST
def member_goal_create(request):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    suspended = _block_suspended_member(request, current_member)
    if suspended:
        return suspended

    member = get_object_or_404(
        Member.objects.select_related("gym"),
        id=current_member.id,
        user=request.user,
    )

    if member.active_goal:
        messages.error(request, "Un objectif actif existe deja sur ce compte.")
        return redirect(f"{reverse('members:member_portal')}?tab=goal")

    form = MemberGoalForm(request.POST)
    if not form.is_valid():
        messages.error(request, "L'objectif n'a pas pu etre enregistre. Verifiez les champs saisis.")
        return redirect(f"{reverse('members:member_portal')}?tab=goal")

    goal = form.save(commit=False)
    goal.gym = member.gym
    goal.member = member
    goal.created_by = request.user
    goal.save()

    starter_label = "vous" if goal.measurement_starter == MemberGoal.STARTER_MEMBER else "votre coach"
    messages.success(request, f"Objectif cree. La premiere pesee doit maintenant etre enregistree par {starter_label}.")
    return redirect(f"{reverse('members:member_portal')}?tab=goal")


@login_required
@require_POST
def member_goal_measurement_create(request):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    suspended = _block_suspended_member(request, current_member)
    if suspended:
        return suspended

    member = get_object_or_404(
        Member.objects.select_related("gym"),
        id=current_member.id,
        user=request.user,
    )
    goal = get_object_or_404(
        MemberGoal.objects.prefetch_related("measurements"),
        member=member,
        gym=member.gym,
        status=MemberGoal.STATUS_ACTIVE,
    )
    goal_access = _member_goal_access(goal)
    if not goal_access["can_member_record"]:
        messages.error(request, "La premiere pesee doit etre enregistree par le coach.")
        return redirect(f"{reverse('members:member_portal')}?tab=goal")

    form = MemberWeightMeasurementForm(request.POST)
    if not form.is_valid():
        messages.error(request, "La pesee n'a pas pu etre enregistree. Verifiez les champs saisis.")
        return redirect(f"{reverse('members:member_portal')}?tab=goal")

    measurement = form.save(commit=False)
    measurement.gym = member.gym
    measurement.goal = goal
    measurement.member = member
    measurement.source = MemberWeightMeasurement.SOURCE_MEMBER
    measurement.recorded_by = request.user
    measurement.save()
    goal.refresh_status_from_progress()

    messages.success(request, "Pesee enregistree dans votre suivi.")
    return redirect(f"{reverse('members:member_portal')}?tab=goal")


@login_required
@require_POST
def member_submit_coaching_feedback(request):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    suspended = _block_suspended_member(request, current_member)
    if suspended:
        return suspended

    member = get_object_or_404(
        Member.objects.select_related("gym"),
        id=current_member.id,
        user=request.user,
    )
    feedback_kind = request.POST.get("feedback_kind")
    coach_id = request.POST.get("coach_id")
    program_id = request.POST.get("program_id")
    form_prefix = "group-feedback" if feedback_kind == "group_program" else "coach-feedback"
    form = CoachingFeedbackForm(request.POST, prefix=form_prefix)

    if not form.is_valid():
        messages.error(request, "Votre avis n'a pas pu etre enregistre. Verifiez les notes renseignees.")
        return redirect(f"{reverse('members:member_portal')}?tab=home")

    subscription = member.active_subscription
    if feedback_kind == "group_program":
        if not _member_can_choose_group_program(member, subscription):
            messages.error(request, "Votre formule actuelle ne permet pas de laisser un avis sur un programme groupe.")
            return redirect(f"{reverse('members:member_portal')}?tab=home")
    elif not _member_can_choose_individual_coach(member, subscription):
        messages.error(request, "Votre formule actuelle ne permet pas de laisser un avis coaching individuel.")
        return redirect(f"{reverse('members:member_portal')}?tab=home")

    coach = get_object_or_404(Coach, id=coach_id, gym=member.gym, is_active=True)
    feedback = form.save(commit=False)
    feedback.gym = member.gym
    feedback.member = member
    feedback.coach = coach

    if feedback_kind == "group_program":
        group_program = get_object_or_404(
            GroupCoachingProgram.objects.select_related("coach"),
            id=program_id,
            gym=member.gym,
            is_active=True,
        )
        feedback.group_program = group_program

    try:
        feedback.save()
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if getattr(exc, "messages", None) else str(exc))
        return redirect(f"{reverse('members:member_portal')}?tab=home")

    messages.success(request, "Merci, votre avis coaching a bien ete enregistre.")
    return redirect(f"{reverse('members:member_portal')}?tab=home")


@login_required
@require_POST
def member_change_password(request):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    form = PasswordChangeForm(user=request.user, data=request.POST)
    if form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Votre mot de passe a ete mis a jour.")
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)

    return redirect(f"{reverse('members:member_portal')}?tab=password")


@login_required
@require_POST
def member_subscription_request(request):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    suspended = _block_suspended_member(request, current_member)
    if suspended:
        return suspended

    member = get_object_or_404(
        Member.objects.select_related("gym"),
        id=current_member.id,
        user=request.user,
    )
    plan = get_object_or_404(
        SubscriptionPlan,
        id=request.POST.get("plan_id"),
        gym=member.gym,
        is_active=True,
    )

    SubscriptionRequest.objects.filter(
        gym=member.gym,
        member=member,
        status=SubscriptionRequest.STATUS_PENDING,
    ).exclude(plan=plan).update(
        status=SubscriptionRequest.STATUS_CANCELLED,
        notes="Remplacee par une nouvelle demande depuis l'espace membre.",
    )

    request_obj, created = SubscriptionRequest.objects.get_or_create(
        gym=member.gym,
        member=member,
        plan=plan,
        status=SubscriptionRequest.STATUS_PENDING,
        defaults={
            "requested_by": request.user,
            "price_usd": plan.price,
        },
    )
    if not created and request_obj.price_usd != plan.price:
        request_obj.price_usd = plan.price
        request_obj.requested_by = request.user
        request_obj.save(update_fields=["price_usd", "requested_by", "updated_at"])

    messages.success(
        request,
        "Demande de souscription enregistree. Le paiement sera finalise quand le module de paiement sera branche.",
    )
    return redirect(f"{reverse('members:member_portal')}?tab=plans")


@login_required
@require_POST
def member_choose_coach(request):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    suspended = _block_suspended_member(request, current_member)
    if suspended:
        return suspended

    member = get_object_or_404(
        Member.objects.select_related("gym"),
        id=current_member.id,
        user=request.user,
    )
    subscription = member.active_subscription
    if not _member_can_choose_individual_coach(member, subscription):
        messages.error(request, "Votre formule actuelle ne permet pas de choisir un coach individuel.")
        return redirect(f"{reverse('members:member_portal')}?tab=home")

    coach = get_object_or_404(
        Coach,
        id=request.POST.get("coach_id"),
        gym=member.gym,
        is_active=True,
    )

    for existing_coach in Coach.objects.filter(gym=member.gym, members=member).exclude(id=coach.id):
        existing_coach.members.remove(member)
    coach.members.add(member)

    messages.success(request, f"{coach.name} est maintenant votre coach referent.")
    return redirect(f"{reverse('members:member_portal')}?tab=home")


@login_required
@require_POST
def member_choose_group_program(request):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    suspended = _block_suspended_member(request, current_member)
    if suspended:
        return suspended

    member = get_object_or_404(
        Member.objects.select_related("gym"),
        id=current_member.id,
        user=request.user,
    )
    subscription = member.active_subscription
    if not _member_can_choose_group_program(member, subscription):
        messages.error(request, "Votre formule actuelle ne permet pas de rejoindre un programme groupe.")
        return redirect(f"{reverse('members:member_portal')}?tab=home")

    program = get_object_or_404(
        GroupCoachingProgram.objects.select_related("coach"),
        id=request.POST.get("program_id"),
        gym=member.gym,
        is_active=True,
    )

    try:
        program.join_member(member)
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if getattr(exc, "messages", None) else str(exc))
        return redirect(f"{reverse('members:member_portal')}?tab=home")

    for existing_program in GroupCoachingProgram.objects.filter(gym=member.gym, participants=member).exclude(id=program.id):
        existing_program.participants.remove(member)

    messages.success(request, f'Vous avez rejoint le programme "{program.name}".')
    return redirect(f"{reverse('members:member_portal')}?tab=home")


@login_required
@require_POST
def member_notification_read(request, notification_id):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    member = get_object_or_404(
        Member.objects.select_related("gym"),
        id=current_member.id,
        user=request.user,
    )
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        gym=member.gym,
        member=member,
        channel=Notification.CHANNEL_IN_APP,
        status=Notification.STATUS_SENT,
    )

    if not notification.read_at:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])

    return redirect(f"{reverse('members:member_portal')}?tab=messages&message={notification.id}")


@login_required
def member_portal_qr(request):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    from members.card_images import render_member_qr_png

    return _image_response(
        render_member_qr_png(current_member, size=request.GET.get("size")),
        _member_filename(current_member, "qr"),
        _wants_download(request),
    )
@login_required
def member_organization_logo(request):
    if not _member_management_allowed(request):
        raise PermissionDenied

    organization = request.gym.organization if request.gym else None
    logo = getattr(organization, "logo", None)
    if not logo:
        raise Http404("Logo indisponible.")

    content_type = mimetypes.guess_type(logo.name)[0] or "application/octet-stream"
    return FileResponse(logo.open("rb"), content_type=content_type)


def _organization_from_request(request):
    """
    Organisation a afficher dans le manifeste.

    Le membre connecte fait foi. A defaut, on accepte l'organisation passee en
    parametre : le navigateur reclame le manifeste sans cookie de session, et
    sans cette porte de sortie l'application installee porterait le nom et
    l'icone generiques au lieu de ceux de la salle.
    """
    member = _get_current_member(request.user) if request.user.is_authenticated else None
    if member and member.gym_id:
        return member.gym.organization

    demande = request.GET.get("org")
    if not demande:
        return None
    try:
        return Organization.objects.get(id=int(demande), is_active=True)
    except (ValueError, TypeError, Organization.DoesNotExist):
        return None


def _member_app_brand(request):
    organization = _organization_from_request(request)
    if organization is None:
        return {
            "name": "SmartClub Membre",
            "short_name": "SmartClub",
            "description": "Carte membre, abonnement et acces SmartClub.",
            "icon_192_url": static("icons/1.png"),
            "icon_512_url": static("icons/1.png"),
        }

    name = f"{organization.name} Membre"
    icon_192_url = reverse("members:member_app_organization_icon", args=[organization.id, 192])
    icon_512_url = reverse("members:member_app_organization_icon", args=[organization.id, 512])
    return {
        "name": name,
        "short_name": organization.name[:12] or "SmartClub",
        "description": f"Carte membre, abonnement et acces {organization.name}.",
        "icon_192_url": icon_192_url,
        "icon_512_url": icon_512_url,
    }


@login_required
def member_app_icon(request, size):
    current_member = _get_current_member(request.user)
    if not current_member or not current_member.gym_id:
        raise PermissionDenied

    size = int(size)
    if size not in {192, 512}:
        raise Http404("Taille d'icone indisponible.")

    from members.card_images import render_organization_pwa_icon_png

    organization = current_member.gym.organization
    content = render_organization_pwa_icon_png(organization, size=size)
    response = HttpResponse(content, content_type="image/png")
    response["Cache-Control"] = "private, no-store"
    return response


def member_app_organization_icon(request, organization_id, size):
    size = int(size)
    if size not in {192, 512}:
        raise Http404("Taille d'icone indisponible.")

    organization = get_object_or_404(Organization, id=organization_id, is_active=True)
    from members.card_images import render_organization_pwa_icon_png

    content = render_organization_pwa_icon_png(organization, size=size)
    response = HttpResponse(content, content_type="image/png")
    response["Cache-Control"] = "public, max-age=3600"
    return response


def member_app_manifest(request):
    brand = _member_app_brand(request)
    manifest = {
        "name": brand["name"],
        "short_name": brand["short_name"],
        "description": brand["description"],
        "start_url": reverse("members:member_portal"),
        "scope": "/members/",
        "display": "standalone",
        "background_color": "#0B0B0B",
        "theme_color": "#0B0B0B",
        "orientation": "portrait",
        "icons": [
            {
                "src": brand["icon_192_url"],
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": brand["icon_512_url"],
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": brand["icon_512_url"],
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }
    response = JsonResponse(manifest)
    response["Cache-Control"] = "private, no-store"
    return response


def member_app_service_worker(request):
    content = """
const CACHE_NAME = "smartclub-member-v7";
const STATIC_ASSETS = [
  "/static/css/member-portal.css",
  "/static/js/member-portal.js",
  "/static/icons/1.png",
  "/static/avatar/logo_smartclub.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => null)
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
    ))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;

  if (request.mode === "navigate") {
    event.respondWith(fetch(request));
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request))
  );
});
"""
    response = HttpResponse(content, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/members/"
    return response


@csrf_exempt
@require_POST
def member_api_login(request):
    try:
        data = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400)

    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return _json_error("Identifiant et mot de passe requis.", status=400)

    user = authenticate(request, username=username, password=password)
    if not user:
        return _json_error("Identifiants invalides.", status=401)

    member = _get_current_member(user)
    if not member:
        return _json_error("Ce compte n'est pas un compte membre.", status=403)
    if not member.is_active or not member.gym.is_active or not member.gym.organization.is_active:
        return _json_error("Ce compte membre n'est pas actif.", status=403)

    login(request, user)
    member = get_object_or_404(
        Member.objects.select_related("user", "gym", "gym__organization"),
        id=member.id,
        user=user,
    )
    return _json_success(
        {
            "force_password_change": bool(user.force_password_change),
            "data": _member_mobile_payload(request, member),
        }
    )


@csrf_exempt
@require_POST
def member_api_logout(request):
    logout(request)
    return _json_success()


@require_http_methods(["GET"])
def member_api_me(request):
    member, error = _api_current_member(request)
    if error:
        return error
    return _json_success({"data": _member_mobile_payload(request, member)})


@csrf_exempt
@require_POST
def member_api_password(request):
    member, error = _api_current_member(request)
    if error:
        return error
    try:
        data = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400)

    form = PasswordChangeForm(user=request.user, data=data)
    if not form.is_valid():
        return _json_error("Mot de passe non modifie.", status=400, errors=_form_errors(form))

    user = form.save()
    if user.force_password_change:
        user.force_password_change = False
        user.save(update_fields=["force_password_change"])
    update_session_auth_hash(request, user)
    return _json_success({"data": _member_mobile_payload(request, member)})


@csrf_exempt
@require_POST
def member_api_notification_read(request, notification_id):
    member, error = _api_current_member(request)
    if error:
        return error

    notification = get_object_or_404(
        Notification,
        id=notification_id,
        gym=member.gym,
        member=member,
        channel=Notification.CHANNEL_IN_APP,
        status=Notification.STATUS_SENT,
    )
    if not notification.read_at:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
    return _json_success({"data": _member_mobile_payload(request, member)})


@csrf_exempt
@require_POST
def member_api_subscription_request(request):
    member, error = _api_current_member(request)
    if error:
        return error
    suspended = _api_block_suspended_member(member)
    if suspended:
        return suspended
    try:
        data = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400)

    plan = get_object_or_404(
        SubscriptionPlan,
        id=data.get("plan_id"),
        gym=member.gym,
        is_active=True,
    )
    SubscriptionRequest.objects.filter(
        gym=member.gym,
        member=member,
        status=SubscriptionRequest.STATUS_PENDING,
    ).exclude(plan=plan).update(
        status=SubscriptionRequest.STATUS_CANCELLED,
        notes="Remplacee par une nouvelle demande depuis l'application membre.",
    )
    request_obj, created = SubscriptionRequest.objects.get_or_create(
        gym=member.gym,
        member=member,
        plan=plan,
        status=SubscriptionRequest.STATUS_PENDING,
        defaults={
            "requested_by": request.user,
            "price_usd": plan.price,
        },
    )
    if not created and request_obj.price_usd != plan.price:
        request_obj.price_usd = plan.price
        request_obj.requested_by = request.user
        request_obj.save(update_fields=["price_usd", "requested_by", "updated_at"])
    return _json_success({"data": _member_mobile_payload(request, member)}, status=201 if created else 200)


@csrf_exempt
@require_POST
def member_api_goal_create(request):
    member, error = _api_current_member(request)
    if error:
        return error
    suspended = _api_block_suspended_member(member)
    if suspended:
        return suspended
    if member.active_goal:
        return _json_error("Un objectif actif existe deja sur ce compte.", status=400)
    try:
        data = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400)

    form = MemberGoalForm(data)
    if not form.is_valid():
        return _json_error("L'objectif n'a pas pu etre enregistre.", status=400, errors=_form_errors(form))

    goal = form.save(commit=False)
    goal.gym = member.gym
    goal.member = member
    goal.created_by = request.user
    goal.save()
    return _json_success({"data": _member_mobile_payload(request, member)}, status=201)


@csrf_exempt
@require_POST
def member_api_goal_measurement_create(request):
    member, error = _api_current_member(request)
    if error:
        return error
    suspended = _api_block_suspended_member(member)
    if suspended:
        return suspended
    goal = get_object_or_404(
        MemberGoal.objects.prefetch_related("measurements"),
        member=member,
        gym=member.gym,
        status=MemberGoal.STATUS_ACTIVE,
    )
    goal_access = _member_goal_access(goal)
    if not goal_access["can_member_record"]:
        return _json_error("La premiere pesee doit etre enregistree par le coach.", status=403)
    try:
        data = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400)

    form = MemberWeightMeasurementForm(data)
    if not form.is_valid():
        return _json_error("La pesee n'a pas pu etre enregistree.", status=400, errors=_form_errors(form))

    measurement = form.save(commit=False)
    measurement.gym = member.gym
    measurement.goal = goal
    measurement.member = member
    measurement.source = MemberWeightMeasurement.SOURCE_MEMBER
    measurement.recorded_by = request.user
    measurement.save()
    goal.refresh_status_from_progress()
    return _json_success({"data": _member_mobile_payload(request, member)}, status=201)


@csrf_exempt
@require_POST
def member_api_choose_coach(request):
    member, error = _api_current_member(request)
    if error:
        return error
    suspended = _api_block_suspended_member(member)
    if suspended:
        return suspended
    subscription = member.active_subscription
    if not _member_can_choose_individual_coach(member, subscription):
        return _json_error("Votre formule actuelle ne permet pas de choisir un coach individuel.", status=403)
    try:
        data = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400)

    coach = get_object_or_404(
        Coach,
        id=data.get("coach_id"),
        gym=member.gym,
        is_active=True,
    )
    for existing_coach in Coach.objects.filter(gym=member.gym, members=member).exclude(id=coach.id):
        existing_coach.members.remove(member)
    coach.members.add(member)
    return _json_success({"data": _member_mobile_payload(request, member)})


@csrf_exempt
@require_POST
def member_api_choose_group_program(request):
    member, error = _api_current_member(request)
    if error:
        return error
    suspended = _api_block_suspended_member(member)
    if suspended:
        return suspended
    subscription = member.active_subscription
    if not _member_can_choose_group_program(member, subscription):
        return _json_error("Votre formule actuelle ne permet pas de rejoindre un programme groupe.", status=403)
    try:
        data = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400)

    program = get_object_or_404(
        GroupCoachingProgram.objects.select_related("coach"),
        id=data.get("program_id"),
        gym=member.gym,
        is_active=True,
    )
    try:
        program.join_member(member)
    except ValidationError as exc:
        return _json_error(exc.messages[0] if getattr(exc, "messages", None) else str(exc), status=400)

    for existing_program in GroupCoachingProgram.objects.filter(gym=member.gym, participants=member).exclude(id=program.id):
        existing_program.participants.remove(member)
    return _json_success({"data": _member_mobile_payload(request, member)})


@csrf_exempt
@require_POST
def member_api_coaching_feedback(request):
    member, error = _api_current_member(request)
    if error:
        return error
    suspended = _api_block_suspended_member(member)
    if suspended:
        return suspended
    try:
        data = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400)

    feedback_kind = data.get("feedback_kind")
    coach_id = data.get("coach_id")
    program_id = data.get("program_id")
    form = CoachingFeedbackForm(data)
    if not form.is_valid():
        return _json_error("Votre avis n'a pas pu etre enregistre.", status=400, errors=_form_errors(form))

    subscription = member.active_subscription
    if feedback_kind == "group_program":
        if not _member_can_choose_group_program(member, subscription):
            return _json_error("Votre formule actuelle ne permet pas de laisser un avis sur un programme groupe.", status=403)
    elif not _member_can_choose_individual_coach(member, subscription):
        return _json_error("Votre formule actuelle ne permet pas de laisser un avis coaching individuel.", status=403)

    coach = get_object_or_404(Coach, id=coach_id, gym=member.gym, is_active=True)
    feedback = form.save(commit=False)
    feedback.gym = member.gym
    feedback.member = member
    feedback.coach = coach
    if feedback_kind == "group_program":
        feedback.group_program = get_object_or_404(
            GroupCoachingProgram.objects.select_related("coach"),
            id=program_id,
            gym=member.gym,
            is_active=True,
        )

    try:
        feedback.save()
    except ValidationError as exc:
        return _json_error(exc.messages[0] if getattr(exc, "messages", None) else str(exc), status=400)
    return _json_success({"data": _member_mobile_payload(request, member)}, status=201)

#######   liste  ######
# Paliers d'expiration proposes par le tableau de bord.
EXPIRING_WINDOWS = (1, 3, 7, 15)


@login_required
def member_list(request):
    """
    Liste des membres avec filtres avancés (SaaS multi-tenant sécurisé)
    """

    # 🔐 sécurité rôles
    if not _member_management_allowed(request):
        raise PermissionDenied

    _cleanup_expired_pre_registrations()
    gym = request.gym
    today = timezone.now().date()
    # Fenetre d'expiration choisie depuis le tableau de bord : chaque palier
    # renvoie ici pour que l'equipe puisse appeler les membres concernes.
    try:
        expiring_days = int(request.GET.get("expiring_days") or 7)
    except (TypeError, ValueError):
        expiring_days = 7
    if expiring_days not in EXPIRING_WINDOWS:
        expiring_days = 7
    limit = today + timedelta(days=expiring_days)

    active_subscription_exists = MemberSubscription.objects.filter(
        member=OuterRef("pk"),
        is_active=True,
        start_date__lte=today,
        end_date__gte=today,
        is_paused=False,
    )
    expiring_subscription_exists = MemberSubscription.objects.filter(
        member=OuterRef("pk"),
        is_active=True,
        start_date__lte=today,
        end_date__range=(today, limit),
        is_paused=False,
    )
    # Date de fin de l'abonnement en cours : sert a trier du plus urgent au
    # moins urgent, l'ordre dans lequel on passe les appels.
    active_subscription_end = (
        MemberSubscription.objects.filter(
            member=OuterRef("pk"),
            is_active=True,
            is_paused=False,
            start_date__lte=today,
            end_date__gte=today,
        )
        .order_by("end_date")
        .values("end_date")[:1]
    )
    any_access_exists = AccessLog.objects.filter(member=OuterRef("pk"))
    recent_access_exists = AccessLog.objects.filter(
        member=OuterRef("pk"),
        check_in_time__date__gte=today - timedelta(days=30),
    )

    # 🔥 base queryset optimisée
    members = (
        Member.objects
        .filter(gym=gym)
        # created_by est affiche sur chaque ligne : sans jointure, la liste
        # declenchait une requete par membre.
        .select_related("user", "created_by")
        .annotate(
            has_active_subscription=Exists(active_subscription_exists),
            has_expiring_subscription=Exists(expiring_subscription_exists),
            has_any_access=Exists(any_access_exists),
            has_recent_access=Exists(recent_access_exists),
            active_subscription_end=Subquery(active_subscription_end),
        )
    )

    # =====================
    # 🔎 FILTRES
    # =====================

    search = request.GET.get("search")
    status = request.GET.get("status")
    plan = request.GET.get("plan")
    access_filter = request.GET.get("access")
    created_from = request.GET.get("created_from")
    created_to = request.GET.get("created_to")
    sort = request.GET.get("sort", "newest")

    # 🔍 Recherche
    if search:
        members = members.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(phone__icontains=search) |
            Q(email__icontains=search) |
            Q(user__username__icontains=search)
        )

    # 📊 Statut
    if status == "active":
        members = members.filter(has_active_subscription=True)

    elif status == "expired":
        # Membres dont l'abonnement actif est expiré
        members = members.filter(
            has_active_subscription=False
        ).exclude(status="suspended")

    elif status == "suspended":
        members = members.filter(status="suspended")

    elif status == "expiring":
        members = members.filter(has_expiring_subscription=True)

    # 💳 Plan
    if plan:
        members = members.filter(
            subscriptions__plan_id=plan,
            subscriptions__is_active=True
        ).distinct()

    # 🔽 tri par défaut (important UX)
    if access_filter == "recent":
        members = members.filter(has_recent_access=True)
    elif access_filter == "never":
        members = members.filter(has_any_access=False)

    if created_from:
        try:
            members = members.filter(created_at__date__gte=date.fromisoformat(created_from))
        except ValueError:
            created_from = ""

    if created_to:
        try:
            members = members.filter(created_at__date__lte=date.fromisoformat(created_to))
        except ValueError:
            created_to = ""

    sort_options = {
        "newest": ["-created_at"],
        "oldest": ["created_at"],
        "name_asc": ["first_name", "last_name"],
        "name_desc": ["-first_name", "-last_name"],
        "expiry_asc": ["subscriptions__end_date", "-created_at"],
        "expiry_desc": ["-subscriptions__end_date", "-created_at"],
        "last_access": ["-access_logs__check_in_time", "-created_at"],
        # Echeance de l'abonnement en cours, du plus proche au plus lointain :
        # l'ordre dans lequel l'equipe passe ses appels de relance.
        "urgency": ["active_subscription_end", "first_name", "last_name"],
    }
    if status == "expiring" and not request.GET.get("sort"):
        sort = "urgency"
    sort = sort if sort in sort_options else "newest"
    members = members.order_by(*sort_options[sort]).distinct()

    # =====================
    # 📄 PAGINATION
    # =====================

    paginator = Paginator(members, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # =====================
    # 📦 DATA TEMPLATE
    # =====================

    plans = SubscriptionPlan.objects.filter(
        gym=gym,
        is_active=True
    )
    # AJOUT IMPORTANT : On passe le formulaire au template
    form = MemberCreationForm()
    pre_registration_link, _ = MemberPreRegistrationLink.objects.get_or_create(gym=gym)
    pre_registration_url = _get_pre_registration_public_url(request, pre_registration_link)
    pending_pre_registrations_count = MemberPreRegistration.objects.filter(
        gym=gym,
        status=MemberPreRegistration.STATUS_PENDING,
        expires_at__gt=timezone.now(),
    ).count()
    member_password_credentials = request.session.pop("member_password_credentials", None)

    context = {
        "page_obj": page_obj,
        "plans": plans,

        # 🔥 conserver filtres dans UI
        "search": search or "",
        "status": status or "",
        "plan_selected": plan or "",
        "access_filter": access_filter or "",
        "created_from": created_from or "",
        "created_to": created_to or "",
        "sort_selected": sort,
        "form" : form,
        "pre_registration_link": pre_registration_link,
        "pre_registration_url": pre_registration_url,
        "pending_pre_registrations_count": pending_pre_registrations_count,
        "member_password_credentials": member_password_credentials,
    }

    return render(request, "members/member_list.html", context)


#CREATION MEMBRE
@login_required
def create_member(request):

    if not _member_write_allowed(request):
        raise PermissionDenied
    
    if request.method != "POST":
        return redirect("members:member_list")

    form = MemberCreationForm(request.POST, request.FILES, gym=request.gym)

    if not form.is_valid():
        # Sans cette branche, un formulaire invalide renvoyait vers la liste
        # sans le moindre message : l'utilisateur croyait avoir enregistre.
        for field_name, errors in form.errors.items():
            label = (
                form.fields[field_name].label
                or field_name.replace("_", " ").capitalize()
                if field_name in form.fields
                else "Formulaire"
            )
            for error in errors:
                messages.error(request, f"{label} : {error}")
        return redirect("members:member_list")

    member = form.save(commit=False)
    member.gym = request.gym
    # La fiche porte le nom de qui l'a saisie : une coordonnee erronee ou un
    # doublon se remonte a son auteur sans fouiller le journal.
    member.created_by = request.user
    member.registration_source = Member.SOURCE_MANUAL
    member.save()  # déclenche signal → crée User automatiquement

    log_sensitive_action(
        request,
        "member.created",
        "Member",
        f"{member.first_name} {member.last_name}",
        metadata={
            "member_id": member.id,
            "phone": member.phone,
            "origine": member.registration_source,
        },
    )

    temporary_password = getattr(member, "_temporary_password", "")
    try:
        email_sent = send_member_creation_email(
            member,
            temporary_password=temporary_password,
            portal_url=build_public_url(request, reverse("members:member_portal")),
        )
    except Exception as exc:
        notify_creation_email_failure(str(member), exc)
        email_sent = False

    # format_html echappe les valeurs interpolees : un nom contenant des
    # balises ne peut pas s'executer dans ce message rendu en HTML brut.
    messages.success(
        request,
        format_html(
            '<div class="d-flex align-items-center gap-3">'
            '<span class="material-icons text-white" style="font-size:32px;">check_circle</span>'
            "<div>"
            '<strong style="font-size:1.1rem;">Membre cree avec succes !</strong><br>'
            '<span class="opacity-90">'
            "{first_name} {last_name}<br>"
            "Identifiant : <strong>{username}</strong><br>"
            "Mot de passe temporaire : <strong>{password}</strong><br>"
            "Changement obligatoire a la premiere connexion.<br>"
            "Espace membre : <strong>{portal}</strong><br>"
            "Email envoye : <strong>{email_sent}</strong>"
            "</span></div></div>",
            first_name=member.first_name,
            last_name=member.last_name,
            username=member.user.username if member.user else "-",
            password=temporary_password or "Genere automatiquement",
            portal=reverse("members:member_portal"),
            email_sent="oui" if email_sent else "non",
        ),
        # "persistent" : ce message porte le mot de passe temporaire, qui n'est
        # stocke nulle part en clair. Il ne doit pas disparaitre tout seul.
        extra_tags="safe toast-success persistent",
    )
    return redirect("members:member_list")

#Qrcode
@login_required
def member_qr(request, uuid):

    if not uuid:
        return HttpResponse(status=404)

    if not _member_management_allowed(request):
        raise PermissionDenied

    member = get_object_or_404(Member, qr_code=uuid, gym=request.gym)

    from members.card_images import render_member_qr_png

    return _image_response(
        render_member_qr_png(member, size=request.GET.get("size")),
        _member_filename(member, "qr"),
        _wants_download(request),
    )
@login_required
def edit_member(request, member_id):
    if not _member_write_allowed(request):
        raise PermissionDenied

    member = get_object_or_404(Member, id=member_id, gym=request.gym)

    if request.method == "POST":
        form = MemberCreationForm(
            request.POST, request.FILES, instance=member, gym=request.gym
        )

        if form.is_valid():
            changes = {
                field: {
                    "avant": str(form.initial.get(field, "")),
                    "apres": str(form.cleaned_data.get(field, "")),
                }
                for field in form.changed_data
            }
            form.save()
            log_sensitive_action(
                request,
                "member.updated",
                "Member",
                f"{member.first_name} {member.last_name}",
                metadata={"member_id": member.id, "changements": changes},
            )
            messages.success(request, "Membre modifié avec succès.")
            
            # Réponse JSON pour le modal (au lieu de redirect)
            return JsonResponse({
                'success': True,
                'message': 'Membre modifié avec succès.'
            })

        else:
            # Retourner les erreurs de validation
            return JsonResponse({
                'success': False,
                'errors': form.errors
            }, status=400)

    # GET : Retourner les données pour pré-remplir le formulaire
    data = {
        'id': member.id,
        'first_name': member.first_name,
        'last_name': member.last_name,
        'phone': member.phone,
        'email': member.email,
        'address': member.address,
        'photo_url': _absolute_media_url(request, member.photo) or None,
    }

    return JsonResponse(data)


#DETAIL D'UN MEMBRE
@login_required
def member_detail(request, member_id):
    if not _member_management_allowed(request):
        raise PermissionDenied

    member = get_object_or_404(
        Member.objects.select_related("user", "created_by"),
        id=member_id,
        gym=request.gym
    )
    subscription = member.active_subscription
    organization = request.gym.organization if request.gym else None
    
    payments = Payment.objects.filter(
        member=member, gym = request.gym
    ).order_by("-created_at")[:5]
    
    payments_data = []
    
    for p in payments:
        payments_data.append({
            "date": p.created_at.strftime("%d/%m/%Y"),
            "amount": float(p.amount_cdf),
            "original_amount": float(p.amount),
            "original_currency": p.currency,
            "method": p.method,
            "status": p.status
        })
        
    access_logs = AccessLog.objects.filter(
        member=member,
        gym=request.gym,
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
        "photo_url": _absolute_media_url(request, member.photo) or None,
        "organization_name": organization.name if organization else "",
        "organization_logo_url": reverse("members:organization_logo") if organization and organization.logo else "",
        "gym_name": request.gym.name if request.gym else "",
        "username": member.user.username if member.user else "Non défini",
        "first_name": member.first_name,
        "last_name": member.last_name,
        "phone": member.phone,
        "email": member.email,
        "status": member.computed_status,
        "qr_code": str(member.qr_code),
        "qr_code_expires_at": timezone.localtime(member.qr_code_expires_at).strftime("%d/%m/%Y %H:%M"),
        "can_regenerate_qr": _member_qr_admin_allowed(request),
        "member_code": _member_code(member),
        "card_image_url": reverse("members:member_card_image", args=[member.id]),
        "card_download_url": reverse("members:member_card_image", args=[member.id]) + "?download=1",
        "qr_download_url": reverse("members:member_qr", args=[member.qr_code]) + "?download=1",
        "member_portal_url": build_public_url(request, reverse("members:member_portal")),
        # Qui a inscrit ce membre, et par quel chemin.
        "registered_by": member.registered_by_label,
        "registration_source": member.get_registration_source_display(),
        "registered_on": timezone.localtime(member.created_at).strftime("%d/%m/%Y %H:%M"),
        # abonnement
        "subscription_type": member.subscription_type,
        "start_date": subscription.start_date.strftime("%d/%m/%Y") if subscription else None,
        "expiration_date": member.expiration_date.strftime("%d/%m/%Y") if member.expiration_date else None,
        "price": subscription.plan.price if subscription else 0,
        "subscription_offers": [
            offer.name for offer in subscription.plan.active_offers
        ] if subscription and subscription.plan else [],

        "payments": payments_data,
        "access_logs": access_data,
    }

    return JsonResponse(_json_safe_value(data))


@login_required
def member_card_image(request, member_id):
    if not _member_management_allowed(request):
        raise PermissionDenied

    member = get_object_or_404(
        Member.objects.select_related("gym", "gym__organization", "user"),
        id=member_id,
        gym=request.gym,
    )

    from members.card_images import render_member_card_png

    return _image_response(
        render_member_card_png(member),
        _member_filename(member, "carte_membre"),
        _wants_download(request),
    )


@login_required
@require_POST
def regenerate_member_qr(request, member_id):
    if not _member_qr_admin_allowed(request):
        raise PermissionDenied

    member = get_object_or_404(
        Member.objects.select_related("gym", "gym__organization", "user"),
        id=member_id,
        gym=request.gym,
    )
    previous_qr_code = str(member.qr_code)
    member.rotate_qr_code()
    member_label = f"{member.first_name} {member.last_name}".strip() or member.phone or f"Membre #{member.id}"

    log_sensitive_action(
        request,
        "member.qr_regenerated",
        "Member",
        member_label,
        metadata={
            "member_id": member.id,
            "member_code": _member_code(member),
            "previous_qr_code": previous_qr_code,
            "new_qr_code": str(member.qr_code),
            "qr_code_expires_at": member.qr_code_expires_at.isoformat(),
            "gym_id": member.gym_id,
        },
        gym=member.gym,
    )

    return JsonResponse(
        {
            "success": True,
            "qr_code": str(member.qr_code),
            "qr_code_expires_at": timezone.localtime(member.qr_code_expires_at).strftime("%d/%m/%Y %H:%M"),
            "card_image_url": reverse("members:member_card_image", args=[member.id]),
        "card_download_url": reverse("members:member_card_image", args=[member.id]) + "?download=1",
        "qr_download_url": reverse("members:member_qr", args=[member.qr_code]) + "?download=1",
        }
    )


@login_required
@require_POST
def reset_member_password(request, member_id):
    if not _member_write_allowed(request):
        raise PermissionDenied

    member = get_object_or_404(
        Member.objects.select_related("user"),
        id=member_id,
        gym=request.gym,
    )

    if not member.user:
        messages.error(request, "Ce membre n'a pas encore de compte utilisateur associe.")
        return redirect("members:member_list")

    temporary_password = generate_temporary_password()
    member.user.set_password(temporary_password)
    member.user.force_password_change = True
    member.user.save(update_fields=["password", "force_password_change"])

    request.session["member_password_credentials"] = {
        "member_name": f"{member.first_name} {member.last_name}".strip(),
        "username": member.user.username,
        "password": temporary_password,
    }

    # Les identifiants sont aussi envoyes au membre : sans cela, le personnel
    # devait les lui transmettre de vive voix.
    try:
        email_sent = send_member_password_reset_email(
            member,
            temporary_password=temporary_password,
            portal_url=build_public_url(request, reverse("members:member_portal")),
        )
    except Exception as exc:
        notify_creation_email_failure(str(member), exc)
        email_sent = False

    delivery = (
        "Identifiants envoyes par e-mail au membre."
        if email_sent
        else "L'envoi de l'e-mail a echoue : communiquez-les au membre."
    )
    log_sensitive_action(
        request,
        "member.password_reset",
        "Member",
        f"{member.first_name} {member.last_name}",
        metadata={"member_id": member.id, "email_envoye": email_sent},
    )
    messages.success(
        request,
        f"Mot de passe temporaire regenere pour {member.first_name} {member.last_name}. "
        f"{delivery}",
    )
    return redirect("members:member_list")


@login_required
@require_POST
def delete_member(request, member_id):

    if not has_role(request, MEMBER_DELETE_ROLES):
        raise PermissionDenied

    member = get_object_or_404(
        Member.objects.select_related("gym", "gym__organization", "user"),
        id=member_id,
        gym=request.gym
    )

    member_label = f"{member.first_name} {member.last_name}".strip() or member.phone or f"Membre #{member.id}"
    metadata = {
        "member_id": member.id,
        "member_code": _member_code(member),
        "phone": member.phone,
        "email": member.email,
        "user_id": member.user_id,
        "gym_id": member.gym_id,
    }
    gym = member.gym

    member.delete()
    log_sensitive_action(
        request,
        "member.deleted",
        "Member",
        member_label,
        metadata=metadata,
        gym=gym,
    )
    messages.success(request, "Membre supprime avec succes.")

    return redirect("members:member_list")


@login_required
@require_POST
def suspend_member(request, member_id):
    if not has_role(request, MEMBER_STATUS_ROLES):
        raise PermissionDenied

    member = get_object_or_404(Member, id=member_id, gym=request.gym)

    # Suspendre le membre
    member.status = "suspended"
    member.save()

    # Mettre en pause l'abonnement actif
    active_sub = member.latest_active_subscription
    if active_sub is None:
        detail = "Il n'avait aucun abonnement actif a mettre en pause."
    elif active_sub.is_paused:
        detail = "Son abonnement etait deja en pause."
    else:
        active_sub.is_paused = True
        active_sub.paused_at = timezone.now()
        active_sub.save()
        detail = "Son abonnement est en pause."

    log_sensitive_action(
        request,
        "member.suspended",
        "Member",
        f"{member.first_name} {member.last_name}",
        metadata={"member_id": member.id, "abonnement": detail},
    )
    messages.warning(
        request,
        f"{member.first_name} {member.last_name} a ete suspendu. {detail}",
    )
    return redirect("members:member_list")


@login_required
@require_POST
def reactivate_member(request, member_id):
    if not has_role(request, MEMBER_STATUS_ROLES):
        raise PermissionDenied

    member = get_object_or_404(Member, id=member_id, gym=request.gym)

    # Réactiver le membre
    member.status = "active"
    member.save()

    # Reprendre l'abonnement en pause
    active_sub = member.latest_active_subscription
    if active_sub is None:
        detail = "Il n'a aucun abonnement a reprendre."
    elif not active_sub.is_paused:
        detail = "Son abonnement n'etait pas en pause."
    else:
        recovered_days = active_sub.resume_subscription()
        if recovered_days:
            detail = (
                f"Son abonnement reprend, prolonge de {recovered_days} jour"
                f"{'s' if recovered_days > 1 else ''} "
                f"jusqu'au {active_sub.end_date:%d/%m/%Y}."
            )
        else:
            detail = (
                "Son abonnement reprend. La pause a dure moins d'une journee, "
                "l'echeance est inchangee."
            )

    log_sensitive_action(
        request,
        "member.reactivated",
        "Member",
        f"{member.first_name} {member.last_name}",
        metadata={"member_id": member.id, "abonnement": detail},
    )
    messages.success(
        request,
        f"{member.first_name} {member.last_name} a ete reactive. {detail}",
    )
    return redirect("members:member_list")

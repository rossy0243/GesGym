#members/views.py
from datetime import date, timedelta
from io import BytesIO
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.db.models import Q, Exists, OuterRef, Count
from django.core.paginator import Paginator
from django.urls import reverse
from django.templatetags.static import static
from django.views.decorators.http import require_POST
import qrcode
from access.models import AccessLog
from coaching.forms import CoachingFeedbackForm
from coaching.models import Coach, CoachingFeedback, GroupCoachingProgram
from smartclub.access_control import (
    MEMBER_ROLES,
    MEMBER_STATUS_ROLES,
    MEMBER_WRITE_ROLES,
    has_role,
)
from .forms import MemberCreationForm, MemberGoalForm, MemberWeightMeasurementForm
from .models import Member, MemberGoal, MemberPreRegistration, MemberPreRegistrationLink, MemberWeightMeasurement
from notifications.models import Notification
from pos.models import Payment
from subscriptions.models import MemberSubscription, SubscriptionPlan, SubscriptionRequest


#######   MEMBRE  ######


def _cleanup_expired_pre_registrations():
    MemberPreRegistration.delete_expired_pending()


def _member_management_allowed(request):
    return has_role(request, MEMBER_ROLES) and request.gym


def _member_write_allowed(request):
    return has_role(request, MEMBER_WRITE_ROLES) and request.gym


def _get_pre_registration_public_url(request, link):
    return request.build_absolute_uri(
        reverse("members:public_pre_registration", args=[link.token])
    )


def _get_current_member(user):
    return getattr(user, "member_profile", None)


def _member_code(member):
    return f"MEM-{member.id:05d}"


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
        {"key": "messages", "label": "Messages", "icon": "mail", "badge": badge},
        {"key": "subscription", "label": "Abonnement", "icon": "subscription"},
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
    can_choose_individual_coach = _member_can_choose_individual_coach(member, subscription)
    can_choose_group_program = _member_can_choose_group_program(member, subscription)
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
    unread_notifications = [item for item in member_notifications_list if not item.read_at]
    read_notifications = [item for item in member_notifications_list if item.read_at]
    if active_tab not in {tab["key"] for tab in _member_tab_config(unread_notification_count)}:
        active_tab = "home"

    member_tabs = []
    for tab in _member_tab_config(unread_notification_count):
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
        "pwa_manifest_url": reverse("members:member_app_manifest"),
        "pwa_service_worker_url": reverse("members:member_app_service_worker"),
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

    member = get_object_or_404(
        Member.objects.select_related("gym"),
        id=current_member.id,
        user=request.user,
    )

    if member.active_goal:
        messages.error(request, "Un objectif actif existe deja sur ce compte.")
        return redirect(f"{reverse('members:member_portal')}?tab=home")

    form = MemberGoalForm(request.POST)
    if not form.is_valid():
        messages.error(request, "L'objectif n'a pas pu etre enregistre. Verifiez les champs saisis.")
        return redirect(f"{reverse('members:member_portal')}?tab=home")

    goal = form.save(commit=False)
    goal.gym = member.gym
    goal.member = member
    goal.created_by = request.user
    goal.save()

    starter_label = "vous" if goal.measurement_starter == MemberGoal.STARTER_MEMBER else "votre coach"
    messages.success(request, f"Objectif cree. La premiere pesee doit maintenant etre enregistree par {starter_label}.")
    return redirect(f"{reverse('members:member_portal')}?tab=home")


@login_required
@require_POST
def member_goal_measurement_create(request):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

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
        return redirect(f"{reverse('members:member_portal')}?tab=home")

    form = MemberWeightMeasurementForm(request.POST)
    if not form.is_valid():
        messages.error(request, "La pesee n'a pas pu etre enregistree. Verifiez les champs saisis.")
        return redirect(f"{reverse('members:member_portal')}?tab=home")

    measurement = form.save(commit=False)
    measurement.gym = member.gym
    measurement.goal = goal
    measurement.member = member
    measurement.source = MemberWeightMeasurement.SOURCE_MEMBER
    measurement.recorded_by = request.user
    measurement.save()
    goal.refresh_status_from_progress()

    messages.success(request, "Pesee enregistree dans votre suivi.")
    return redirect(f"{reverse('members:member_portal')}?tab=home")


@login_required
@require_POST
def member_submit_coaching_feedback(request):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

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

    return redirect(f"{reverse('members:member_portal')}?tab=home")


@login_required
@require_POST
def member_subscription_request(request):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

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

    return redirect(f"{reverse('members:member_portal')}?tab=messages")


@login_required
def member_portal_qr(request):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    qr = qrcode.make(current_member.get_qr_data())
    buffer = BytesIO()
    qr.save(buffer)

    return HttpResponse(buffer.getvalue(), content_type="image/png")


def member_app_manifest(request):
    manifest = {
        "name": "SmartClub Membre",
        "short_name": "SmartClub",
        "description": "Carte membre, abonnement et acces SmartClub.",
        "start_url": reverse("members:member_portal"),
        "scope": "/members/",
        "display": "standalone",
        "background_color": "#f6f7f2",
        "theme_color": "#102820",
        "orientation": "portrait",
        "icons": [
            {
                "src": static("icons/1.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": static("avatar/logo_smartclub.png"),
                "sizes": "1536x1024",
                "type": "image/png",
            },
        ],
    }
    return JsonResponse(manifest)


def member_app_service_worker(request):
    content = """
const CACHE_NAME = "smartclub-member-v5";
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

#######   liste  ######
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
    limit = today + timedelta(days=7)
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
    any_access_exists = AccessLog.objects.filter(member=OuterRef("pk"))
    recent_access_exists = AccessLog.objects.filter(
        member=OuterRef("pk"),
        check_in_time__date__gte=today - timedelta(days=30),
    )

    # 🔥 base queryset optimisée
    members = (
        Member.objects
        .filter(gym=gym)
        .select_related("user")
        .annotate(
            has_active_subscription=Exists(active_subscription_exists),
            has_expiring_subscription=Exists(expiring_subscription_exists),
            has_any_access=Exists(any_access_exists),
            has_recent_access=Exists(recent_access_exists),
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
    }
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
    }

    return render(request, "members/member_list.html", context)


#CREATION MEMBRE
@login_required
def create_member(request):

    if not _member_write_allowed(request):
        raise PermissionDenied
    
    if request.method == "POST":
        form = MemberCreationForm(request.POST, request.FILES)
        if form.is_valid():
            member = form.save(commit=False)
            member.gym = request.gym
            member.save()  # déclenche signal → crée User automatiquement

            messages.success(
                request,
                f"""
                <div class="d-flex align-items-center gap-3">
                    <span class="material-icons text-white" style="font-size:32px;">check_circle</span>
                    <div>
                        <strong style="font-size:1.1rem;">Membre créé avec succès !</strong><br>
                        <span class="opacity-90">
                            {member.first_name} {member.last_name}<br>
                            Identifiant : <strong>{member.user.username}</strong><br>
                            Mot de passe temporaire : <strong>{getattr(member, "_temporary_password", "Genere automatiquement")}</strong><br>
                            Changement obligatoire a la premiere connexion.<br>
                            Espace membre : <strong>{reverse("members:member_portal")}</strong>
                        </span>
                    </div>
                </div>
                """,
                extra_tags='safe toast-success'
            )
            return redirect("members:member_list")
            
    else:
        form = MemberCreationForm()

    return redirect("members:member_list")

#Qrcode
@login_required
def member_qr(request, uuid):

    if not uuid:
        return HttpResponse(status=404)

    if not _member_management_allowed(request):
        raise PermissionDenied

    get_object_or_404(Member, qr_code=uuid, gym=request.gym)
    
    qr = qrcode.make(uuid)

    buffer = BytesIO()
    qr.save(buffer)

    return HttpResponse(
        buffer.getvalue(),
        content_type="image/png"
    )
    


@login_required
def edit_member(request, member_id):
    if not _member_write_allowed(request):
        raise PermissionDenied

    member = get_object_or_404(Member, id=member_id, gym=request.gym)

    if request.method == "POST":
        form = MemberCreationForm(request.POST, request.FILES, instance=member)
        
        if form.is_valid():
            form.save()
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
        'photo_url': member.photo.url if member.photo else None,
    }

    return JsonResponse(data)


#DETAIL D'UN MEMBRE
@login_required
def member_detail(request, member_id):
    if not _member_management_allowed(request):
        raise PermissionDenied

    member = get_object_or_404(
        Member.objects.select_related("user"),
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
        "photo_url": member.photo.url if member.photo else None,
        "organization_name": organization.name if organization else "",
        "organization_logo_url": organization.logo.url if organization and organization.logo else "",
        "gym_name": request.gym.name if request.gym else "",
        "username": member.user.username if member.user else "Non défini",
        "first_name": member.first_name,
        "last_name": member.last_name,
        "phone": member.phone,
        "email": member.email,
        "status": member.computed_status,
        "qr_code": str(member.qr_code),
        "member_code": _member_code(member),
        "member_portal_url": request.build_absolute_uri(reverse("members:member_portal")),
        # abonnement
        "subscription_type": member.subscription_type,
        "start_date": subscription.start_date.strftime("%d/%m/%Y") if subscription else None,
        "expiration_date": member.expiration_date.strftime("%d/%m/%Y") if member.expiration_date else None,
        "price": subscription.plan.price if subscription else 0,
        "subscription_offers": [
            offer.name for offer in subscription.plan.active_offers
        ] if subscription and subscription.plan else [],

        # paiements
        "paid": member.amount_paid if hasattr(member, "amount_paid") else 0,
        "remaining": member.amount_remaining if hasattr(member, "amount_remaining") else 0,
        
        "payments": payments_data,
        "access_logs": access_data,
    }

    return JsonResponse(data)


@login_required
def delete_member(request, member_id):

    if not has_role(request, {"owner"}):
        raise PermissionDenied

    member = get_object_or_404(
        Member,
        id=member_id,
        gym=request.gym
    )

    if request.method == "POST":
        member.delete()
        messages.success(request, "Membre supprimé avec succès.")

    return redirect("members:member_list")


@login_required
def suspend_member(request, member_id):
    if not has_role(request, MEMBER_STATUS_ROLES):
        raise PermissionDenied

    member = get_object_or_404(Member, id=member_id, gym=request.gym)

    # Suspendre le membre
    member.status = "suspended"
    member.save()

    # Mettre en pause l'abonnement actif
    active_sub = member.latest_active_subscription
    if active_sub and not active_sub.is_paused:
        active_sub.is_paused = True
        active_sub.paused_at = timezone.now()
        active_sub.save()

    messages.warning(request, f"{member.first_name} {member.last_name} a été suspendu. Son abonnement est en pause.")
    return redirect("members:member_list")


@login_required
def reactivate_member(request, member_id):
    if not has_role(request, MEMBER_STATUS_ROLES):
        raise PermissionDenied

    member = get_object_or_404(Member, id=member_id, gym=request.gym)

    # Réactiver le membre
    member.status = "active"
    member.save()

    # Reprendre l'abonnement en pause
    active_sub = member.latest_active_subscription
    if active_sub and active_sub.is_paused:
        active_sub.resume_subscription()   # utilise la méthode qu'on a ajoutée

    messages.success(request, f"{member.first_name} {member.last_name} a été réactivé avec succès.")
    return redirect("members:member_list")

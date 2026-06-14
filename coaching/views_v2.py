from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Avg, Count, Max, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from members.forms import MemberWeightMeasurementForm
from members.models import Member, MemberGoal, MemberWeightMeasurement
from smartclub.access_control import COACHING_ROLES, COACH_PORTAL_ROLES
from smartclub.decorators import module_required, role_required
from subscriptions.models import SubscriptionPlan

from .forms import CoachForm, CoachMemberForm, CoachingFollowUpForm, GroupCoachingProgramForm
from .kpis import build_coaching_kpis, coaches_queryset
from .models import Coach, CoachAssignment, CoachingFeedback, CoachingFollowUp, GroupCoachingProgram


def _validation_message(exc):
    return exc.messages[0] if getattr(exc, "messages", None) else str(exc)


def _resolve_current_coach(request):
    if getattr(request.user, "coach_profile", None) and request.user.coach_profile.gym_id == request.gym.id:
        return request.user.coach_profile

    candidate = Coach.objects.filter(gym=request.gym, user=request.user).first()
    if candidate:
        return candidate

    first_name = (request.user.first_name or "").strip()
    last_name = (request.user.last_name or "").strip()
    username = (request.user.username or "").strip()

    lookup = Q()
    if first_name:
        lookup |= Q(name__icontains=first_name)
    if last_name:
        lookup |= Q(name__icontains=last_name)
    if username:
        lookup |= Q(name__icontains=username)

    if lookup:
        candidate = Coach.objects.filter(gym=request.gym).filter(lookup).order_by("name").first()
        if candidate and not candidate.user_id:
            candidate.user = request.user
            candidate.save(update_fields=["user"])
            return candidate
        if candidate:
            return candidate

    candidate = Coach.objects.create(
        gym=request.gym,
        user=request.user,
        name=" ".join(part for part in [first_name, last_name] if part).strip() or username or "Coach",
        phone="",
        specialty="Coach sportif",
        is_active=True,
    )
    return candidate


def _filter_members_with_current_coaching_access(queryset, coaching_modes):
    today = timezone.localdate()
    access_filter = Q()
    if any(mode in coaching_modes for mode in [SubscriptionPlan.COACHING_MODE_INDIVIDUAL, SubscriptionPlan.COACHING_MODE_BOTH]):
        access_filter |= Q(
            subscriptions__plan__coaching_mode__in=[
                SubscriptionPlan.COACHING_MODE_INDIVIDUAL,
                SubscriptionPlan.COACHING_MODE_BOTH,
            ]
        ) | Q(
            subscriptions__plan__offers__is_active=True,
            subscriptions__plan__offers__grants_individual_coaching=True,
        )
    if any(mode in coaching_modes for mode in [SubscriptionPlan.COACHING_MODE_GROUP, SubscriptionPlan.COACHING_MODE_BOTH]):
        access_filter |= Q(
            subscriptions__plan__coaching_mode__in=[
                SubscriptionPlan.COACHING_MODE_GROUP,
                SubscriptionPlan.COACHING_MODE_BOTH,
            ]
        ) | Q(
            subscriptions__plan__offers__is_active=True,
            subscriptions__plan__offers__grants_group_coaching=True,
        )

    return queryset.filter(
        is_active=True,
        status="active",
        subscriptions__is_active=True,
        subscriptions__is_paused=False,
        subscriptions__start_date__lte=today,
        subscriptions__end_date__gte=today,
    ).filter(access_filter).distinct()


def _coach_portal_member_queryset(request, coach):
    return _filter_members_with_current_coaching_access(
        coach.members.filter(gym=request.gym),
        [
            SubscriptionPlan.COACHING_MODE_INDIVIDUAL,
            SubscriptionPlan.COACHING_MODE_BOTH,
        ],
    ).order_by("first_name", "last_name")


def _member_full_name(member):
    return f"{member.first_name} {member.last_name}".strip()


def _goal_access_for_coach(goal):
    if not goal:
        return {"can_coach_record": False, "waiting_for": ""}
    if not goal.is_started:
        return {
            "can_coach_record": goal.measurement_starter == MemberGoal.STARTER_COACH,
            "waiting_for": goal.measurement_starter,
        }
    return {"can_coach_record": True, "waiting_for": ""}


def _build_coach_priority_queue(priority_members, overdue_follow_ups, sensitive_feedbacks):
    items = []

    for feedback in sensitive_feedbacks:
        items.append(
            {
                "kind": "feedback",
                "severity": 1 if feedback.wants_contact else 2,
                "title": _member_full_name(feedback.member),
                "badge": "A rappeler" if feedback.wants_contact else "Avis faible",
                "summary": feedback.comment or "Feedback sensible a traiter rapidement.",
                "meta": f"{feedback.overall_rating}/5",
                "member_id": feedback.member_id,
            }
        )

    for follow_up in overdue_follow_ups:
        items.append(
            {
                "kind": "follow_up",
                "severity": 3,
                "title": _member_full_name(follow_up.member),
                "badge": "Relance en retard",
                "summary": follow_up.next_action or "Reprendre le contact prevu.",
                "meta": follow_up.next_follow_up_at.strftime("%d/%m/%Y") if follow_up.next_follow_up_at else "",
                "member_id": follow_up.member_id,
            }
        )

    for member in priority_members:
        items.append(
            {
                "kind": "member",
                "severity": 4 if not getattr(member, "latest_follow_up_at", None) else 5,
                "title": _member_full_name(member),
                "badge": "Premier contact" if not getattr(member, "latest_follow_up_at", None) else "Suivi ancien",
                "summary": "Aucun suivi n'a encore ete enregistre." if not getattr(member, "latest_follow_up_at", None) else "Le dernier suivi commence a dater.",
                "meta": member.phone or "",
                "member_id": member.id,
            }
        )

    items.sort(key=lambda item: (item["severity"], item["title"]))
    return items[:8]


def _build_manager_priority_queue(sensitive_feedbacks, overdue_follow_ups, first_contact_overdue_members, stale_follow_up_members):
    items = []

    for feedback in sensitive_feedbacks:
        items.append(
            {
                "kind": "feedback",
                "severity": 1 if feedback.wants_contact else 2,
                "title": _member_full_name(feedback.member),
                "badge": "A escalader" if feedback.wants_contact else "Avis faible",
                "summary": feedback.comment or "Feedback sensible recu.",
                "meta": f"{feedback.coach.name} • {feedback.overall_rating}/5",
            }
        )

    for follow_up in overdue_follow_ups:
        items.append(
            {
                "kind": "follow_up",
                "severity": 3,
                "title": _member_full_name(follow_up.member),
                "badge": "Relance en retard",
                "summary": follow_up.next_action or "Relance depassee a reprendre.",
                "meta": f"{follow_up.coach.name} • {follow_up.next_follow_up_at.strftime('%d/%m/%Y') if follow_up.next_follow_up_at else ''}",
            }
        )

    for member in first_contact_overdue_members:
        coach = member.coaches.filter(gym=member.gym, is_active=True).order_by("name").first()
        items.append(
            {
                "kind": "first_contact",
                "severity": 4,
                "title": _member_full_name(member),
                "badge": "Premier contact",
                "summary": "Toujours aucun premier suivi trace.",
                "meta": coach.name if coach else "Coach non resolu",
            }
        )

    for member in stale_follow_up_members:
        coach = member.coaches.filter(gym=member.gym, is_active=True).order_by("name").first()
        items.append(
            {
                "kind": "stale",
                "severity": 5,
                "title": _member_full_name(member),
                "badge": "Suivi ancien",
                "summary": "Le suivi commence a dater.",
                "meta": coach.name if coach else "Coach non resolu",
            }
        )

    items.sort(key=lambda item: (item["severity"], item["title"]))
    return items[:10]


@login_required
@module_required("COACHING")
@role_required(COACHING_ROLES)
def coach_list(request):
    gym = request.gym
    today = date.today()
    first_contact_deadline = today - timedelta(days=3)
    stale_follow_up_deadline = today - timedelta(days=14)
    coaches = coaches_queryset(gym).annotate(
        member_count=Count("members", distinct=True),
        last_follow_up_at=Max("follow_ups__created_at"),
        feedback_average=Avg("feedbacks__overall_rating"),
        feedback_count=Count("feedbacks", distinct=True),
        low_feedback_count=Count(
            "feedbacks",
            filter=Q(feedbacks__overall_rating__lte=2),
            distinct=True,
        ),
        contact_request_feedback_count=Count(
            "feedbacks",
            filter=Q(feedbacks__wants_contact=True),
            distinct=True,
        ),
        overdue_follow_ups=Count(
            "follow_ups",
            filter=Q(follow_ups__next_follow_up_at__isnull=False, follow_ups__next_follow_up_at__lte=today),
            distinct=True,
        ),
        first_contact_overdue_members=Count(
            "members",
            filter=Q(members__created_at__date__lte=first_contact_deadline, members__coaching_follow_ups__isnull=True),
            distinct=True,
        ),
    ).order_by("name")

    active_filter = request.GET.get("active")
    if active_filter == "active":
        coaches = coaches.filter(is_active=True)
    elif active_filter == "inactive":
        coaches = coaches.filter(is_active=False)

    search = request.GET.get("search", "").strip()
    if search:
        coaches = coaches.filter(
            Q(name__icontains=search)
            | Q(phone__icontains=search)
            | Q(specialty__icontains=search)
        )

    assigned_members = _filter_members_with_current_coaching_access(
        Member.objects.filter(
            gym=gym,
            coaches__is_active=True,
            coaches__gym=gym,
        ),
        [
            SubscriptionPlan.COACHING_MODE_INDIVIDUAL,
            SubscriptionPlan.COACHING_MODE_BOTH,
        ],
    ).annotate(last_follow_up_at=Max("coaching_follow_ups__created_at"))
    active_assignments = CoachAssignment.objects.filter(gym=gym, ended_at__isnull=True)
    attention_members = assigned_members.filter(last_follow_up_at__isnull=True).order_by("first_name", "last_name")[:5]
    first_contact_overdue_member_ids = active_assignments.filter(
        started_at__date__lte=first_contact_deadline,
    ).values_list("member_id", flat=True)
    first_contact_overdue_members = assigned_members.filter(
        id__in=first_contact_overdue_member_ids,
        last_follow_up_at__isnull=True,
    ).order_by("first_name", "last_name")[:5]
    stale_follow_up_members = assigned_members.filter(
        last_follow_up_at__isnull=False,
        last_follow_up_at__date__lte=stale_follow_up_deadline,
    ).order_by("last_follow_up_at", "first_name", "last_name")[:5]
    overdue_follow_ups = (
        CoachingFollowUp.objects.filter(
            gym=gym,
            next_follow_up_at__isnull=False,
            next_follow_up_at__lte=today,
        )
        .select_related("coach", "member")
        .order_by("next_follow_up_at", "-created_at")[:5]
    )
    recent_feedbacks = (
        CoachingFeedback.objects.filter(gym=gym)
        .select_related("coach", "member", "group_program")
        .order_by("-created_at")[:5]
    )
    sensitive_feedbacks = (
        CoachingFeedback.objects.filter(gym=gym)
        .filter(Q(overall_rating__lte=2) | Q(wants_contact=True))
        .select_related("coach", "member", "group_program")
        .order_by("-wants_contact", "overall_rating", "-created_at")[:5]
    )

    context = {
        "gym": gym,
        "coaches": coaches,
        "active_group_programs_count": GroupCoachingProgram.objects.filter(gym=gym, is_active=True).count(),
        "active_filter": active_filter,
        "search": search,
        "attention_members": attention_members,
        "first_contact_overdue_members": first_contact_overdue_members,
        "stale_follow_up_members": stale_follow_up_members,
        "overdue_follow_ups": overdue_follow_ups,
        "recent_feedbacks": recent_feedbacks,
        "sensitive_feedbacks": sensitive_feedbacks,
        "manager_priority_queue": _build_manager_priority_queue(
            sensitive_feedbacks,
            overdue_follow_ups,
            first_contact_overdue_members,
            stale_follow_up_members,
        ),
        **build_coaching_kpis(gym),
    }
    return render(request, "coaching/coach_list.html", context)


@login_required
@module_required("COACHING")
@role_required(COACHING_ROLES)
def coach_detail(request, coach_id):
    coach = get_object_or_404(Coach, id=coach_id, gym=request.gym)
    members = _coach_portal_member_queryset(request, coach)
    available_members = (
        _filter_members_with_current_coaching_access(
            Member.objects.filter(gym=request.gym),
            [
                SubscriptionPlan.COACHING_MODE_INDIVIDUAL,
                SubscriptionPlan.COACHING_MODE_BOTH,
            ],
        )
        .exclude(id__in=members.values_list("id", flat=True))
        .order_by("first_name", "last_name")
    )

    follow_ups = CoachingFollowUp.objects.filter(gym=request.gym, coach=coach)
    feedbacks = CoachingFeedback.objects.filter(gym=request.gym, coach=coach).select_related("member", "group_program")
    context = {
        "gym": request.gym,
        "coach": coach,
        "members": members,
        "available_members": available_members,
        "member_form": CoachMemberForm(coach=coach),
        "last_follow_up": follow_ups.order_by("-created_at").first(),
        "follow_ups_count": follow_ups.count(),
        "overdue_follow_ups_count": follow_ups.filter(
            next_follow_up_at__isnull=False,
            next_follow_up_at__lte=date.today(),
        ).count(),
        "feedbacks": feedbacks[:5],
        "feedback_average": round(
            feedbacks.aggregate(average=Avg("overall_rating"))["average"] or 0,
            1,
        ) if feedbacks.exists() else 0,
        "feedback_count": feedbacks.count(),
        "contact_requested_count": feedbacks.filter(wants_contact=True).count(),
        "low_feedback_count": feedbacks.filter(overall_rating__lte=2).count(),
        "sensitive_feedbacks": feedbacks.filter(Q(overall_rating__lte=2) | Q(wants_contact=True))[:5],
        **build_coaching_kpis(request.gym),
    }
    return render(request, "coaching/coach_detail.html", context)


@login_required
@module_required("COACHING")
@role_required(COACHING_ROLES)
def coach_create(request):
    gym = request.gym

    if request.method == "POST":
        form = CoachForm(request.POST, gym=gym)
        if form.is_valid():
            coach = form.save(commit=False)
            coach.gym = gym
            coach.save()
            messages.success(request, f'Coach "{coach.name}" cree avec succes.')
            return redirect("coaching:detail", coach_id=coach.id)
    else:
        form = CoachForm(gym=gym)

    return render(
        request,
        "coaching/coach_form.html",
        {"gym": gym, "form": form, "title": "Ajouter un coach"},
    )


@login_required
@module_required("COACHING")
@role_required(COACHING_ROLES)
def coach_update(request, coach_id):
    coach = get_object_or_404(Coach, id=coach_id, gym=request.gym)

    if request.method == "POST":
        form = CoachForm(request.POST, instance=coach, gym=request.gym)
        if form.is_valid():
            form.save()
            messages.success(request, f'Coach "{coach.name}" modifie avec succes.')
            return redirect("coaching:detail", coach_id=coach.id)
    else:
        form = CoachForm(instance=coach, gym=request.gym)

    return render(
        request,
        "coaching/coach_form.html",
        {
            "gym": request.gym,
            "form": form,
            "coach": coach,
            "title": "Modifier le coach",
        },
    )


@login_required
@module_required("COACHING")
@role_required(COACHING_ROLES)
def coach_delete(request, coach_id):
    coach = get_object_or_404(Coach, id=coach_id, gym=request.gym)

    if request.method == "POST":
        coach.is_active = False
        coach.save(update_fields=["is_active"])
        messages.success(request, f'Coach "{coach.name}" desactive avec succes.')
        return redirect("coaching:list")

    return render(
        request,
        "coaching/coach_confirm_delete.html",
        {"gym": request.gym, "coach": coach},
    )


@login_required
@require_POST
@module_required("COACHING")
@role_required(COACHING_ROLES)
def assign_member(request, coach_id):
    coach = get_object_or_404(Coach, id=coach_id, gym=request.gym)

    if request.method == "POST":
        form = CoachMemberForm(request.POST, coach=coach)
        if form.is_valid():
            try:
                coach.assign_member(form.cleaned_data["member"])
                member = form.cleaned_data["member"]
                messages.success(
                    request,
                    f'Membre "{member.first_name} {member.last_name}" assigne a {coach.name}.',
                )
            except ValidationError as exc:
                messages.error(request, _validation_message(exc))
        else:
            messages.error(request, "Membre invalide pour ce coach.")

    return redirect("coaching:detail", coach_id=coach.id)


@login_required
@require_POST
@module_required("COACHING")
@role_required(COACHING_ROLES)
def remove_member(request, coach_id, member_id):
    coach = get_object_or_404(Coach, id=coach_id, gym=request.gym)
    member = get_object_or_404(Member, id=member_id, gym=request.gym)

    if request.method == "POST":
        try:
            coach.remove_member(member)
            messages.success(request, f'Membre "{member.first_name}" retire de {coach.name}.')
        except ValidationError as exc:
            messages.error(request, _validation_message(exc))

    return redirect("coaching:detail", coach_id=coach.id)


@login_required
@module_required("COACHING")
@role_required(COACHING_ROLES)
def group_program_list(request):
    programs = (
        GroupCoachingProgram.objects.filter(gym=request.gym)
        .select_related("coach")
        .annotate(participant_total=Count("participants", distinct=True))
        .order_by("-is_active", "name")
    )
    return render(
        request,
        "coaching/group_program_list.html",
        {
            "gym": request.gym,
            "programs": programs,
            "active_programs_count": programs.filter(is_active=True).count(),
            **build_coaching_kpis(request.gym),
        },
    )


@login_required
@module_required("COACHING")
@role_required(COACHING_ROLES)
def group_program_detail(request, program_id):
    program = get_object_or_404(
        GroupCoachingProgram.objects.select_related("coach"),
        id=program_id,
        gym=request.gym,
    )
    participants = program.participants.filter(gym=request.gym, is_active=True).order_by("first_name", "last_name")
    return render(
        request,
        "coaching/group_program_detail.html",
        {
            "gym": request.gym,
            "program": program,
            "participants": participants,
            **build_coaching_kpis(request.gym),
        },
    )


@login_required
@module_required("COACHING")
@role_required(COACHING_ROLES)
def group_program_create(request):
    if request.method == "POST":
        form = GroupCoachingProgramForm(request.POST, gym=request.gym)
        if form.is_valid():
            program = form.save(commit=False)
            program.gym = request.gym
            program.save()
            messages.success(request, f'Programme "{program.name}" cree avec succes.')
            return redirect("coaching:group_program_detail", program_id=program.id)
    else:
        form = GroupCoachingProgramForm(gym=request.gym)

    return render(
        request,
        "coaching/group_program_form.html",
        {"gym": request.gym, "form": form, "title": "Creer un programme groupe"},
    )


@login_required
@module_required("COACHING")
@role_required(COACHING_ROLES)
def group_program_update(request, program_id):
    program = get_object_or_404(GroupCoachingProgram, id=program_id, gym=request.gym)
    if request.method == "POST":
        form = GroupCoachingProgramForm(request.POST, instance=program, gym=request.gym)
        if form.is_valid():
            form.save()
            messages.success(request, f'Programme "{program.name}" modifie avec succes.')
            return redirect("coaching:group_program_detail", program_id=program.id)
    else:
        form = GroupCoachingProgramForm(instance=program, gym=request.gym)

    return render(
        request,
        "coaching/group_program_form.html",
        {"gym": request.gym, "form": form, "program": program, "title": "Modifier le programme groupe"},
    )


@login_required
@module_required("COACHING")
@role_required(COACHING_ROLES)
def group_program_delete(request, program_id):
    program = get_object_or_404(GroupCoachingProgram, id=program_id, gym=request.gym)
    if request.method == "POST":
        program.is_active = False
        program.save(update_fields=["is_active"])
        messages.success(request, f'Programme "{program.name}" desactive avec succes.')
        return redirect("coaching:group_program_list")

    return render(
        request,
        "coaching/group_program_confirm_delete.html",
        {"gym": request.gym, "program": program},
    )


@login_required
@module_required("COACHING")
@role_required(COACH_PORTAL_ROLES)
def coach_portal(request):
    coach = _resolve_current_coach(request)
    if not coach:
        raise Http404("Coach introuvable")

    active_tab = request.GET.get("tab", "home")
    if active_tab not in {"home", "members", "programs"}:
        active_tab = "home"

    today = date.today()
    first_contact_deadline = today - timedelta(days=3)
    stale_follow_up_deadline = today - timedelta(days=14)

    members = _coach_portal_member_queryset(request, coach).annotate(
        latest_follow_up_at=Max("coaching_follow_ups__created_at")
    )
    active_assignments = CoachAssignment.objects.filter(gym=request.gym, coach=coach, ended_at__isnull=True)
    programs = (
        GroupCoachingProgram.objects.filter(gym=request.gym, coach=coach, is_active=True)
        .annotate(participants_total=Count("participants", distinct=True))
        .order_by("name")
    )
    recent_member_ids = set(members.order_by("-created_at").values_list("id", flat=True)[:5])
    coach_overdue_follow_ups = CoachingFollowUp.objects.filter(
        gym=request.gym,
        coach=coach,
        next_follow_up_at__isnull=False,
        next_follow_up_at__lte=today,
    ).select_related("member").order_by("next_follow_up_at", "-created_at")
    due_follow_ups_count = coach_overdue_follow_ups.count()
    sensitive_feedbacks = (
        CoachingFeedback.objects.filter(gym=request.gym, coach=coach)
        .filter(Q(overall_rating__lte=2) | Q(wants_contact=True))
        .select_related("member", "group_program")
        .order_by("-wants_contact", "overall_rating", "-created_at")[:5]
    )
    first_contact_overdue_members = members.filter(
        id__in=active_assignments.filter(started_at__date__lte=first_contact_deadline).values_list("member_id", flat=True),
        latest_follow_up_at__isnull=True,
    )
    stale_follow_up_members = members.filter(
        latest_follow_up_at__isnull=False,
        latest_follow_up_at__date__lte=stale_follow_up_deadline,
    )
    priority_members = list(first_contact_overdue_members[:3]) + [
        member for member in stale_follow_up_members[:3] if member.id not in {item.id for item in first_contact_overdue_members[:3]}
    ]

    context = {
        "gym": request.gym,
        "coach": coach,
        "active_tab": active_tab,
        "members": members,
        "programs": programs,
        "recent_member_ids": list(recent_member_ids),
        "members_count": members.count(),
        "programs_count": programs.count(),
        "recent_members_count": len(recent_member_ids),
        "due_follow_ups_count": due_follow_ups_count,
        "members_without_follow_up_count": members.filter(latest_follow_up_at__isnull=True).count(),
        "first_contact_overdue_count": first_contact_overdue_members.count(),
        "stale_follow_up_members_count": stale_follow_up_members.count(),
        "priority_members": priority_members,
        "sensitive_feedbacks": sensitive_feedbacks,
        "sensitive_feedback_count": sensitive_feedbacks.count(),
        "coach_priority_queue": _build_coach_priority_queue(priority_members, coach_overdue_follow_ups[:5], sensitive_feedbacks),
        "current_load_label": "Charge elevee" if members.count() >= 10 else "Charge moyenne" if members.count() >= 5 else "Disponible",
    }
    return render(request, "coaching/coach_portal.html", context)


@login_required
@module_required("COACHING")
@role_required(COACH_PORTAL_ROLES)
def coach_member_detail(request, member_id):
    coach = _resolve_current_coach(request)
    if not coach:
        raise Http404("Coach introuvable")

    member = get_object_or_404(_coach_portal_member_queryset(request, coach), id=member_id)
    follow_ups = CoachingFollowUp.objects.filter(
        gym=request.gym,
        coach=coach,
        member=member,
    ).order_by("-created_at")

    if request.method == "POST":
        form = CoachingFollowUpForm(request.POST)
        if form.is_valid():
            follow_up = form.save(commit=False)
            follow_up.gym = request.gym
            follow_up.coach = coach
            follow_up.member = member
            follow_up.save()
            messages.success(request, "Suivi enregistre avec succes.")
            return redirect("coaching:coach_member_detail", member_id=member.id)
        messages.error(request, "Le suivi n'a pas pu etre enregistre. Verifie les champs saisis.")
    else:
        form = CoachingFollowUpForm()

    latest_follow_up = follow_ups.first()
    active_goal = member.active_goal
    goal_measurements = list(active_goal.measurements_ordered) if active_goal else []
    goal_access = _goal_access_for_coach(active_goal)
    context = {
        "gym": request.gym,
        "coach": coach,
        "member": member,
        "follow_ups": follow_ups,
        "follow_ups_count": follow_ups.count(),
        "latest_follow_up": latest_follow_up,
        "form": form,
        "active_goal": active_goal,
        "goal_measurements": goal_measurements,
        "goal_measurement_form": MemberWeightMeasurementForm(initial={"measured_at": timezone.localdate()}),
        "can_coach_record_goal_measurement": goal_access["can_coach_record"],
        "goal_waiting_for": goal_access["waiting_for"],
    }
    return render(request, "coaching/coach_member_detail.html", context)


@login_required
@require_POST
@module_required("COACHING")
@role_required(COACH_PORTAL_ROLES)
def coach_member_weight_measurement_create(request, member_id):
    coach = _resolve_current_coach(request)
    if not coach:
        raise Http404("Coach introuvable")

    member = get_object_or_404(_coach_portal_member_queryset(request, coach), id=member_id)
    goal = get_object_or_404(
        MemberGoal.objects.prefetch_related("measurements"),
        member=member,
        gym=request.gym,
        status=MemberGoal.STATUS_ACTIVE,
    )
    goal_access = _goal_access_for_coach(goal)
    if not goal_access["can_coach_record"]:
        messages.error(request, "La premiere pesee doit etre enregistree par le membre.")
        return redirect("coaching:coach_member_detail", member_id=member.id)

    form = MemberWeightMeasurementForm(request.POST)
    if not form.is_valid():
        messages.error(request, "La pesee n'a pas pu etre enregistree. Verifie les champs saisis.")
        return redirect("coaching:coach_member_detail", member_id=member.id)

    measurement = form.save(commit=False)
    measurement.gym = request.gym
    measurement.goal = goal
    measurement.member = member
    measurement.source = MemberWeightMeasurement.SOURCE_COACH
    measurement.recorded_by = request.user
    measurement.save()
    goal.refresh_status_from_progress()

    messages.success(request, "Pesee enregistree dans le suivi du membre.")
    return redirect("coaching:coach_member_detail", member_id=member.id)

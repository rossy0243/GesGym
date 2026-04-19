from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.timezone import localtime, now
from django.views.decorators.http import require_POST

from members.models import Member
from smartclub.access_control import ACCESS_ROLES
from smartclub.decorators import role_required
from .models import AccessLog


DOUBLE_SCAN_REASON = "Ce membre est d\u00e9j\u00e0 dans la salle."


def _today():
    return localtime(now()).date()


def _member_has_valid_access(member):
    if not member.is_active:
        return False, "Membre inactif"

    if member.status == "suspended":
        return False, "Membre suspendu"

    has_valid_subscription = member.subscriptions.filter(
        gym=member.gym,
        is_active=True,
        is_paused=False,
        end_date__gte=_today(),
    ).exists()

    if not has_valid_subscription:
        return False, "Aucun abonnement actif"

    return True, ""


def _member_already_checked_in_today(gym, member):
    return AccessLog.objects.filter(
        gym=gym,
        member=member,
        access_granted=True,
        check_in_time__date=_today(),
    ).exists()


def _today_stats(gym):
    logs_today = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date=_today(),
    )

    return {
        "entries": logs_today.filter(access_granted=True).count(),
        "denied": logs_today.filter(access_granted=False).count(),
    }


def _record_access(gym, member, user, method):
    with transaction.atomic():
        member = Member.objects.select_for_update().get(id=member.id, gym=gym)
        access_granted, reason = _member_has_valid_access(member)

        if access_granted and _member_already_checked_in_today(gym, member):
            access_granted = False
            reason = DOUBLE_SCAN_REASON

        log = AccessLog.objects.create(
            gym=gym,
            member=member,
            access_granted=access_granted,
            denial_reason=reason,
            device_used=method,
            scanned_by=user,
        )

    return access_granted, reason, log


def _serialize_log(log):
    checked_at = localtime(log.check_in_time)

    return {
        "id": log.id,
        "member": f"{log.member.first_name} {log.member.last_name}",
        "phone": log.member.phone,
        "qr_code": str(log.member.qr_code),
        "time": checked_at.strftime("%H:%M"),
        "date": checked_at.strftime("%d/%m/%Y"),
        "date_iso": checked_at.strftime("%Y-%m-%d"),
        "status": "success" if log.access_granted else "denied",
        "reason": log.denial_reason or "",
        "method": log.device_used or "-",
        "agent": log.scanned_by.get_full_name() or log.scanned_by.username if log.scanned_by else "-",
        "agent_id": str(log.scanned_by_id or ""),
    }

#vue (scanner + pointage manuel)
@login_required
@role_required(ACCESS_ROLES)
def acces_dashboard(request):
    gym = request.gym
    query = (request.GET.get("q") or "").strip()
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


    stats = _today_stats(gym)
    recent_logs = AccessLog.objects.filter(
        gym=gym
    ).select_related("member", "scanned_by").order_by("-check_in_time")[:10]
    history_logs = AccessLog.objects.filter(
        gym=gym
    ).select_related("member", "scanned_by").order_by("-check_in_time")[:200]
    agents = (
        AccessLog.objects.filter(gym=gym, scanned_by__isnull=False)
        .select_related("scanned_by")
        .order_by("scanned_by__first_name", "scanned_by__last_name", "scanned_by__username")
    )
    unique_agents = []
    seen_agent_ids = set()
    for log in agents:
        if log.scanned_by_id in seen_agent_ids:
            continue
        seen_agent_ids.add(log.scanned_by_id)
        unique_agents.append(log.scanned_by)


    return render(request, "access/acces.html", {
        "members": members,
        "selected_member": selected_member,
        "today_entries": stats["entries"],
        "today_denied": stats["denied"],
        "section": section,
        "recent_logs": recent_logs,
        "history_logs": history_logs,
        "history_agents": unique_agents,
    })

def _legacy_member_access_unused(request, qr_code):
    return member_access(request, qr_code)


@login_required
@role_required(ACCESS_ROLES)
def realtime_access(request):
    logs = AccessLog.objects.filter(
        gym=request.gym
    ).select_related("member", "scanned_by").order_by("-check_in_time")[:10]

    return JsonResponse([_serialize_log(log) for log in logs], safe=False)


@login_required
@role_required(ACCESS_ROLES)
@require_POST
def manual_access_entry(request, member_id):
    member = get_object_or_404(
        Member,
        id=member_id,
        gym=request.gym
    )

    access_granted, reason, log = _record_access(
        gym=request.gym,
        member=member,
        user=request.user,
        method="Manuel",
    )

    return JsonResponse({
        "member": f"{member.first_name} {member.last_name}",
        "access": access_granted,
        "reason": reason,
        "stats": _today_stats(request.gym),
        "log": _serialize_log(log),
    })


@login_required
@role_required(ACCESS_ROLES)
@require_POST
def member_access(request, qr_code):
    member = get_object_or_404(
        Member,
        qr_code=qr_code,
        gym=request.gym
    )

    access_granted, reason, log = _record_access(
        gym=request.gym,
        member=member,
        user=request.user,
        method="QR Scanner",
    )

    return JsonResponse({
        "member": f"{member.first_name} {member.last_name}",
        "access": access_granted,
        "reason": reason,
        "stats": _today_stats(request.gym),
        "log": _serialize_log(log),
    })

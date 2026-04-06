from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse
from django.utils.timezone import now, localtime
from .models import AccessLog
from members.models import Member
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count, Sum
# Create your views here.

#vue (scanner + pointage manuel)
@login_required
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


    return render(request, "access/acces.html", {
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

from decimal import Decimal

from django.db.models import Count
from django.utils import timezone

from members.models import Member

from .models import Coach


def coaches_queryset(gym):
    return Coach.objects.filter(gym=gym)


def build_coaching_kpis(gym, period_data=None):
    today = timezone.localdate()
    period_data = period_data or {
        "start_date": today.replace(day=1),
        "end_date": today,
    }

    coaches = coaches_queryset(gym)
    active_coaches = coaches.filter(is_active=True)
    active_members = Member.objects.filter(gym=gym, is_active=True)
    assigned_member_ids = active_coaches.values_list("members__id", flat=True)
    assigned_members = active_members.filter(id__in=assigned_member_ids).distinct()
    new_coaches_period = coaches.filter(
        created_at__date__range=(period_data["start_date"], period_data["end_date"])
    ).count()
    top_coaches = (
        active_coaches.annotate(member_count=Count("members", distinct=True))
        .filter(member_count__gt=0)
        .order_by("-member_count", "name")[:5]
    )
    total_active_coaches = active_coaches.count()
    assigned_count = assigned_members.count()
    average_members = (
        (Decimal(assigned_count) / Decimal(total_active_coaches)).quantize(Decimal("0.1"))
        if total_active_coaches
        else Decimal("0.0")
    )

    return {
        "total_coaches": coaches.count(),
        "active_coaches": total_active_coaches,
        "inactive_coaches": coaches.filter(is_active=False).count(),
        "assigned_members_count": assigned_count,
        "unassigned_members_count": active_members.exclude(id__in=assigned_member_ids).count(),
        "average_members_per_coach": average_members,
        "new_coaches_period": new_coaches_period,
        "top_coaches": top_coaches,
        "coaching_status_chart_labels": ["Actifs", "Inactifs"],
        "coaching_status_chart_values": [
            total_active_coaches,
            coaches.filter(is_active=False).count(),
        ],
        "coaching_workload_chart_labels": [coach.name for coach in top_coaches],
        "coaching_workload_chart_values": [coach.member_count for coach in top_coaches],
    }

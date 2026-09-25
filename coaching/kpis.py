from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Max, Q
from django.utils import timezone

from members.models import Member

from .eligibilite import membres_avec_droit
from .models import Coach, CoachAssignment, CoachingFeedback, CoachingFollowUp


def coaches_queryset(gym):
    return Coach.objects.filter(gym=gym)


def build_coaching_kpis(gym, period_data=None):
    today = timezone.localdate()
    first_contact_deadline = today - timedelta(days=3)
    stale_follow_up_deadline = today - timedelta(days=14)
    period_data = period_data or {
        "start_date": today.replace(day=1),
        "end_date": today,
    }

    coaches = coaches_queryset(gym)
    active_coaches = coaches.filter(is_active=True)
    active_members = Member.objects.filter(gym=gym, is_active=True)
    assigned_member_ids = active_coaches.values_list("members__id", flat=True)
    assigned_members = active_members.filter(id__in=assigned_member_ids).distinct()

    # La politique de la salle : le coaching appartient aux formules qui y
    # donnent droit. L'ancien compteur retranchait les membres suivis de toute
    # la salle et appelait le reste "membres sans coach" : un abonne Standard
    # y figurait comme un membre a repartir entre les coaches.
    membres_avec_acces = membres_avec_droit(gym, today=today)
    ids_avec_acces = set(membres_avec_acces.values_list("id", flat=True))
    ids_suivis = set(assigned_members.values_list("id", flat=True))
    # Un membre suivi dont l'abonnement ne donne plus droit au coaching existe :
    # son abonnement a change ou s'est termine. Le taire ferait disparaitre
    # une affectation a regulariser.
    suivis_sans_acces = len(ids_suivis - ids_avec_acces)
    active_assignments = CoachAssignment.objects.filter(gym=gym, ended_at__isnull=True)
    new_coaches_period = coaches.filter(
        created_at__date__range=(period_data["start_date"], period_data["end_date"])
    ).count()
    top_coaches = (
        active_coaches.annotate(
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
        )
        .filter(member_count__gt=0)
        .order_by("-member_count", "name")[:5]
    )
    members_with_follow_up = CoachingFollowUp.objects.filter(gym=gym).values_list("member_id", flat=True)
    members_without_follow_up = assigned_members.exclude(id__in=members_with_follow_up).count()
    first_contact_overdue_count = active_assignments.filter(
        started_at__date__lte=first_contact_deadline,
        member_id__in=assigned_members.values_list("id", flat=True),
    ).exclude(member_id__in=members_with_follow_up).count()
    stale_follow_up_members_count = assigned_members.filter(
        coaching_follow_ups__created_at__date__lte=stale_follow_up_deadline,
    ).exclude(id__in=CoachingFollowUp.objects.filter(
        gym=gym,
        created_at__date__gt=stale_follow_up_deadline,
    ).values_list("member_id", flat=True)).distinct().count()
    overdue_follow_ups_count = CoachingFollowUp.objects.filter(
        gym=gym,
        next_follow_up_at__isnull=False,
        next_follow_up_at__lte=today,
    ).count()
    recent_follow_ups_count = CoachingFollowUp.objects.filter(
        gym=gym,
        created_at__date__range=(period_data["start_date"], period_data["end_date"]),
    ).count()
    feedback_average = CoachingFeedback.objects.filter(gym=gym).aggregate(value=Avg("overall_rating"))["value"]
    feedback_count = CoachingFeedback.objects.filter(gym=gym).count()
    contact_requested_count = CoachingFeedback.objects.filter(gym=gym, wants_contact=True).count()
    low_feedback_count = CoachingFeedback.objects.filter(gym=gym, overall_rating__lte=2).count()
    sensitive_feedback_count = CoachingFeedback.objects.filter(
        gym=gym,
    ).filter(Q(overall_rating__lte=2) | Q(wants_contact=True)).count()
    most_exposed_coaches = (
        active_coaches.annotate(
            member_count=Count("members", distinct=True),
            overdue_follow_ups=Count(
                "follow_ups",
                filter=Q(follow_ups__next_follow_up_at__isnull=False, follow_ups__next_follow_up_at__lte=today),
                distinct=True,
            ),
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
        )
        .filter(
            Q(member_count__gt=0)
            | Q(overdue_follow_ups__gt=0)
            | Q(low_feedback_count__gt=0)
            | Q(contact_request_feedback_count__gt=0)
        )
        .order_by(
            "-contact_request_feedback_count",
            "-low_feedback_count",
            "-overdue_follow_ups",
            "last_follow_up_at",
            "name",
        )[:5]
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
        "coaching_eligible_count": len(ids_avec_acces),
        "coaching_eligible_with_coach_count": len(ids_avec_acces & ids_suivis),
        "coaching_eligible_without_coach_count": len(ids_avec_acces - ids_suivis),
        "coached_without_access_count": suivis_sans_acces,
        "group_eligible_count": membres_avec_droit(
            gym, individuel=False, groupe=True, today=today
        ).count(),
        "members_without_follow_up_count": members_without_follow_up,
        "first_contact_overdue_count": first_contact_overdue_count,
        "stale_follow_up_members_count": stale_follow_up_members_count,
        "overdue_follow_ups_count": overdue_follow_ups_count,
        "recent_follow_ups_count": recent_follow_ups_count,
        "feedback_average": round(feedback_average or 0, 1),
        "feedback_count": feedback_count,
        "contact_requested_count": contact_requested_count,
        "low_feedback_count": low_feedback_count,
        "sensitive_feedback_count": sensitive_feedback_count,
        "average_members_per_coach": average_members,
        "new_coaches_period": new_coaches_period,
        "top_coaches": top_coaches,
        "most_exposed_coaches": most_exposed_coaches,
        "coaching_status_chart_labels": ["Actifs", "Inactifs"],
        "coaching_status_chart_values": [
            total_active_coaches,
            coaches.filter(is_active=False).count(),
        ],
        "coaching_workload_chart_labels": [coach.name for coach in top_coaches],
        "coaching_workload_chart_values": [coach.member_count for coach in top_coaches],
    }

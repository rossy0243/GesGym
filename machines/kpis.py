from datetime import timedelta

from django.db.models import Avg, Count, Sum
from django.utils import timezone

from .models import Machine, MaintenanceLog


PERIOD_CHOICES = (
    ("day", "Jour"),
    ("week", "Semaine"),
    ("month", "Mois"),
    ("year", "Annee"),
)


def get_period_window(period_key="month"):
    today = timezone.localdate()
    period_key = period_key if period_key in dict(PERIOD_CHOICES) else "month"

    if period_key == "day":
        start_date = end_date = today
    elif period_key == "week":
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    elif period_key == "year":
        start_date = today.replace(month=1, day=1)
        end_date = today.replace(month=12, day=31)
    else:
        start_date = today.replace(day=1)
        if start_date.month == 12:
            next_month = start_date.replace(year=start_date.year + 1, month=1, day=1)
        else:
            next_month = start_date.replace(month=start_date.month + 1, day=1)
        end_date = next_month - timedelta(days=1)

    days = (end_date - start_date).days + 1
    return {
        "key": period_key,
        "label": dict(PERIOD_CHOICES)[period_key],
        "start_date": start_date,
        "end_date": end_date,
        "days": days,
    }


def machines_queryset(gym):
    return Machine.objects.filter(gym=gym)


def maintenance_queryset(gym):
    return MaintenanceLog.objects.filter(machine__gym=gym).select_related("machine")


def percentage(part, total):
    return round((part / total) * 100, 1) if total else 0


def build_machine_kpis(gym, period_data=None):
    period_data = period_data or get_period_window("month")
    machines = machines_queryset(gym)
    maintenances = maintenance_queryset(gym)
    period_maintenances = maintenances.filter(
        created_at__date__range=(period_data["start_date"], period_data["end_date"])
    )

    total_machines = machines.count()
    machines_ok = machines.filter(status="ok").count()
    machines_maintenance = machines.filter(status="maintenance").count()
    machines_broken = machines.filter(status="broken").count()
    total_maintenance_cost = maintenances.aggregate(total=Sum("cost"))["total"] or 0
    period_maintenance_cost = period_maintenances.aggregate(total=Sum("cost"))["total"] or 0
    average_maintenance_cost = period_maintenances.aggregate(avg=Avg("cost"))["avg"] or 0
    top_costly = (
        maintenances.values("machine__name")
        .annotate(total_cost=Sum("cost"))
        .order_by("-total_cost")
        .first()
    )

    return {
        "total_machines": total_machines,
        "machines_ok": machines_ok,
        "machines_maintenance": machines_maintenance,
        "machines_broken": machines_broken,
        "machines_ok_percent": percentage(machines_ok, total_machines),
        "machines_maintenance_percent": percentage(machines_maintenance, total_machines),
        "machines_broken_percent": percentage(machines_broken, total_machines),
        "availability_rate": percentage(machines_ok, total_machines),
        "attention_count": machines_maintenance + machines_broken,
        "total_maintenances": maintenances.count(),
        "total_maintenance_cost": total_maintenance_cost,
        "period_maintenances": period_maintenances.count(),
        "period_maintenance_cost": period_maintenance_cost,
        "monthly_maintenance_cost": period_maintenance_cost,
        "average_maintenance_cost": average_maintenance_cost,
        "top_costly_machine": top_costly["machine__name"] if top_costly else "-",
    }

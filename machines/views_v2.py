from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Count, Sum
from django.shortcuts import get_object_or_404, redirect, render

from pos.services import record_expense
from smartclub.access_control import MACHINE_ROLES
from smartclub.decorators import module_required, role_required

from .forms import MachineForm, MaintenanceLogForm
from .kpis import (
    PERIOD_CHOICES,
    build_machine_kpis,
    get_period_window,
    machines_queryset,
    maintenance_queryset,
)
from .models import Machine, MaintenanceLog


def _validation_message(exc):
    return exc.messages[0] if getattr(exc, "messages", None) else str(exc)


@login_required
@module_required("MACHINES")
@role_required(MACHINE_ROLES)
def machine_list(request):
    gym = request.gym
    machines = machines_queryset(gym).order_by("name")

    status_filter = request.GET.get("status")
    if status_filter:
        machines = machines.filter(status=status_filter)

    paginator = Paginator(machines, 10)
    machines_page = paginator.get_page(request.GET.get("page"))
    period_data = get_period_window("month")

    context = {
        "gym": gym,
        "machines": machines_page,
        "status_filter": status_filter,
        "status_choices": Machine.STATUS,
        **build_machine_kpis(gym, period_data),
    }
    return render(request, "machines/machine_list.html", context)


@login_required
@module_required("MACHINES")
@role_required(MACHINE_ROLES)
def machine_detail(request, machine_id):
    machine = get_object_or_404(Machine, id=machine_id, gym=request.gym)
    maintenance_logs = machine.maintenance_logs.all().order_by("-created_at")

    context = {
        "gym": request.gym,
        "machine": machine,
        "maintenance_logs": maintenance_logs,
        "maintenance_total_cost": maintenance_logs.aggregate(total=Sum("cost"))["total"] or 0,
    }
    return render(request, "machines/machine_detail.html", context)


@login_required
@module_required("MACHINES")
@role_required(MACHINE_ROLES)
def machine_create(request):
    gym = request.gym

    if request.method == "POST":
        form = MachineForm(request.POST)
        if form.is_valid():
            machine = form.save(commit=False)
            machine.gym = gym
            machine.save()
            messages.success(request, f'Machine "{machine.name}" creee avec succes.')
            return redirect("machines:detail", machine_id=machine.id)
    else:
        form = MachineForm()

    return render(
        request,
        "machines/machine_form.html",
        {"gym": gym, "form": form, "title": "Ajouter une machine"},
    )


@login_required
@module_required("MACHINES")
@role_required(MACHINE_ROLES)
def machine_update(request, machine_id):
    machine = get_object_or_404(Machine, id=machine_id, gym=request.gym)

    if request.method == "POST":
        form = MachineForm(request.POST, instance=machine)
        if form.is_valid():
            form.save()
            messages.success(request, f'Machine "{machine.name}" modifiee avec succes.')
            return redirect("machines:detail", machine_id=machine.id)
    else:
        form = MachineForm(instance=machine)

    return render(
        request,
        "machines/machine_form.html",
        {
            "gym": request.gym,
            "form": form,
            "machine": machine,
            "title": "Modifier la machine",
        },
    )


@login_required
@module_required("MACHINES")
@role_required(MACHINE_ROLES)
def machine_delete(request, machine_id):
    machine = get_object_or_404(Machine, id=machine_id, gym=request.gym)

    if request.method == "POST":
        machine_name = machine.name
        machine.delete()
        messages.success(request, f'Machine "{machine_name}" supprimee avec succes.')
        return redirect("machines:list")

    return render(
        request,
        "machines/machine_confirm_delete.html",
        {"gym": request.gym, "machine": machine},
    )


@login_required
@module_required("MACHINES")
@role_required(MACHINE_ROLES)
def maintenance_log_create(request, machine_id):
    machine = get_object_or_404(Machine, id=machine_id, gym=request.gym)

    if request.method == "POST":
        form = MaintenanceLogForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    log = form.save(commit=False)
                    log.machine = machine

                    if log.cost and log.cost > 0:
                        pos_payment = record_expense(
                            gym=request.gym,
                            amount_cdf=log.cost,
                            method="cash",
                            category="maintenance",
                            description=f"Maintenance machine: {machine.name}",
                            created_by=request.user,
                            source_app="machines",
                            source_model="Machine",
                            source_id=machine.id,
                        )
                        log.pos_payment = pos_payment

                    log.save()

                    if log.pos_payment_id:
                        log.pos_payment.source_model = "MaintenanceLog"
                        log.pos_payment.source_id = log.id
                        log.pos_payment.save(update_fields=["source_model", "source_id"])

                    if request.POST.get("change_status"):
                        new_status = request.POST.get("status")
                        if new_status in dict(Machine.STATUS):
                            machine.status = new_status
                            machine.save(update_fields=["status"])
            except ValidationError as exc:
                messages.error(request, _validation_message(exc))
                return redirect("machines:add_maintenance", machine_id=machine.id)

            messages.success(request, f'Maintenance ajoutee pour "{machine.name}" avec succes.')
            return redirect("machines:detail", machine_id=machine.id)
    else:
        form = MaintenanceLogForm()

    return render(
        request,
        "machines/maintenance_form.html",
        {
            "gym": request.gym,
            "machine": machine,
            "form": form,
            "title": f"Ajouter une maintenance - {machine.name}",
        },
    )


@login_required
@module_required("MACHINES")
@role_required(MACHINE_ROLES)
def maintenance_list(request):
    gym = request.gym
    maintenances = maintenance_queryset(gym).order_by("-created_at")

    paginator = Paginator(maintenances, 15)
    maintenances_page = paginator.get_page(request.GET.get("page"))

    stats = {
        "total": maintenances.count(),
        "total_cost": maintenances.aggregate(total=Sum("cost"))["total"] or 0,
        "average_cost": maintenances.aggregate(avg=Avg("cost"))["avg"] or 0,
        "by_machine": maintenances.values("machine__name").annotate(
            count=Count("id"),
            total=Sum("cost"),
        ),
    }

    return render(
        request,
        "machines/maintenance_list.html",
        {"gym": gym, "maintenances": maintenances_page, "stats": stats},
    )


@login_required
@module_required("MACHINES")
@role_required(MACHINE_ROLES)
def maintenance_dashboard(request):
    gym = request.gym
    period_data = get_period_window(request.GET.get("period", "month"))
    all_maintenances = maintenance_queryset(gym)
    period_maintenances = all_maintenances.filter(
        created_at__date__range=(period_data["start_date"], period_data["end_date"])
    )
    machine_kpis = build_machine_kpis(gym, period_data)

    machines_by_status = {
        "ok": machine_kpis["machines_ok"],
        "maintenance": machine_kpis["machines_maintenance"],
        "broken": machine_kpis["machines_broken"],
    }
    top_maintenance_machines = (
        machines_queryset(gym)
        .annotate(maintenance_count=Count("maintenance_logs"))
        .filter(maintenance_count__gt=0)
        .order_by("-maintenance_count", "name")[:5]
    )
    maintenance_cost_by_machine = (
        period_maintenances.values("machine__name")
        .annotate(total_cost=Sum("cost"), count=Count("id"))
        .order_by("-total_cost")[:5]
    )

    context = {
        "gym": gym,
        "period_choices": PERIOD_CHOICES,
        "selected_period": period_data["key"],
        "period_label": period_data["label"],
        "period_start": period_data["start_date"],
        "period_end": period_data["end_date"],
        "machines_by_status": machines_by_status,
        "recent_maintenances": all_maintenances.order_by("-created_at")[:10],
        "top_maintenance_machines": top_maintenance_machines,
        "maintenance_cost_by_machine": maintenance_cost_by_machine,
        **machine_kpis,
    }
    return render(request, "machines/maintenance_dashboard_v2.html", context)


@login_required
@module_required("MACHINES")
@role_required(MACHINE_ROLES)
def maintenance_delete(request, maintenance_id):
    maintenance = get_object_or_404(
        MaintenanceLog,
        id=maintenance_id,
        machine__gym=request.gym,
    )
    machine = maintenance.machine

    if request.method == "POST":
        maintenance.delete()
        messages.success(request, "Log de maintenance supprime avec succes.")
        return redirect("machines:detail", machine_id=machine.id)

    return render(
        request,
        "machines/maintenance_confirme_delete.html",
        {"gym": request.gym, "maintenance": maintenance},
    )

from calendar import month_name

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from pos.services import record_expense
from smartclub.access_control import RH_ATTENDANCE_ROLES, RH_EMPLOYEE_ROLES, RH_PAYROLL_ROLES
from smartclub.decorators import module_required, role_required

from .forms import (
    AttendanceForm,
    BulkAttendanceForm,
    EmployeeForm,
    LeaveRequestForm,
    OvertimeEntryForm,
    PaymentForm,
    PayrollAdjustmentForm,
    PayrollContributionRuleForm,
)
from .kpis import available_months, build_rh_kpis, payroll_rows
from .models import (
    Attendance,
    Employee,
    LeaveRequest,
    OvertimeEntry,
    PaymentRecord,
    PayrollAdjustment,
    PayrollContributionRule,
    PayrollSlip,
    PayrollWorkflowLog,
)


def _parse_year_month(request):
    current_date = timezone.localdate()
    try:
        year = int(request.GET.get("year", current_date.year))
    except (TypeError, ValueError):
        year = current_date.year
    try:
        month = int(request.GET.get("month", current_date.month))
    except (TypeError, ValueError):
        month = current_date.month
    if month < 1 or month > 12:
        month = current_date.month
    return year, month


def _redirect_to_payroll_dashboard(request):
    current_date = timezone.localdate()
    try:
        year = int(request.POST.get("year", request.GET.get("year", current_date.year)))
    except (TypeError, ValueError):
        year = current_date.year
    try:
        month = int(request.POST.get("month", request.GET.get("month", current_date.month)))
    except (TypeError, ValueError):
        month = current_date.month
    if month < 1 or month > 12:
        month = current_date.month
    return redirect(f"{reverse('rh:payroll_dashboard')}?year={year}&month={month}")


def _month_name(month):
    return month_name[month]


def _validation_message(exc):
    return exc.messages[0] if getattr(exc, "messages", None) else str(exc)


def _detail_url(employee_id, year, month):
    return f"{reverse('rh:detail', args=[employee_id])}?year={year}&month={month}"


def _paid_slip_guard(request, employee, year, month):
    slip = PayrollSlip.ensure_for_period(employee, year, month)
    if slip.status == PayrollSlip.STATUS_PAID and slip.payment_record_id:
        messages.warning(
            request,
            "Ce bulletin est deja paye via POS. Les ajustements de paie sont desormais bloques pour preserver la coherence comptable.",
        )
        return slip
    return None


def _pdf_escape(value):
    return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _simple_pdf_response(filename, lines):
    content_stream = ["BT", "/F1 12 Tf", "40 790 Td"]
    first = True
    for line in lines:
        safe_line = _pdf_escape(line)
        if first:
            content_stream.append(f"({safe_line}) Tj")
            first = False
        else:
            content_stream.append("0 -18 Td")
            content_stream.append(f"({safe_line}) Tj")
    content_stream.append("ET")
    stream_data = "\n".join(content_stream).encode("latin-1", errors="replace")

    objects = []
    objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    objects.append(b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n")
    objects.append(
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
    )
    objects.append(f"4 0 obj << /Length {len(stream_data)} >> stream\n".encode("ascii") + stream_data + b"\nendstream endobj\n")
    objects.append(b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("ascii")
    )

    response = HttpResponse(bytes(pdf), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _log_workflow_action(slip, user, action, note=""):
    PayrollWorkflowLog.objects.create(slip=slip, actor=user, action=action, note=note)


@login_required
@module_required("RH")
@role_required(RH_EMPLOYEE_ROLES)
def employee_list(request):
    gym = request.gym
    employees = Employee.objects.filter(gym=gym).order_by("name")

    role_filter = request.GET.get("role")
    if role_filter:
        employees = employees.filter(role=role_filter)

    active_filter = request.GET.get("active")
    if active_filter == "active":
        employees = employees.filter(is_active=True)
    elif active_filter == "inactive":
        employees = employees.filter(is_active=False)

    context = {
        "gym": gym,
        "employees": employees,
        "role_filter": role_filter,
        "active_filter": active_filter,
        "role_choices": Employee.ROLE_CHOICES,
        **build_rh_kpis(gym),
    }
    return render(request, "rh/employee_list.html", context)


@login_required
@module_required("RH")
@role_required(RH_EMPLOYEE_ROLES)
def employee_detail(request, employee_id):
    employee = get_object_or_404(Employee, id=employee_id, gym=request.gym)
    year, month = _parse_year_month(request)
    slip = PayrollSlip.ensure_for_period(employee, year, month)
    attendances = employee.attendances.filter(gym=request.gym, date__year=year, date__month=month).order_by("-date")
    payments = employee.payments.filter(gym=request.gym).order_by("-year", "-month")
    adjustments = employee.payroll_adjustments.filter(gym=request.gym, year=year, month=month).order_by("-created_at")
    leaves = employee.leaves.filter(gym=request.gym, start_date__year__lte=year).order_by("-start_date")[:8]
    overtime_entries = employee.overtime_entries.filter(
        gym=request.gym, work_date__year=year, work_date__month=month
    ).order_by("-work_date", "-created_at")
    workflow_logs = slip.workflow_logs.select_related("actor").all()
    contribution_lines = slip.contribution_breakdown()

    context = {
        "gym": request.gym,
        "employee": employee,
        "year": year,
        "month": month,
        "month_name": _month_name(month),
        "monthly_salary": slip.net_salary,
        "present_days": slip.present_days,
        "is_paid": slip.status == PayrollSlip.STATUS_PAID,
        "slip": slip,
        "attendances": attendances,
        "payments": payments,
        "adjustments": adjustments,
        "leaves": leaves,
        "overtime_entries": overtime_entries,
        "workflow_logs": workflow_logs,
        "contribution_lines": contribution_lines,
        "adjustment_form": PayrollAdjustmentForm(),
        "leave_form": LeaveRequestForm(initial={"start_date": timezone.localdate(), "end_date": timezone.localdate()}),
        "overtime_form": OvertimeEntryForm(initial={"work_date": timezone.localdate()}),
        "available_months": available_months(),
    }
    return render(request, "rh/employee_detail.html", context)


@login_required
@module_required("RH")
@role_required(RH_EMPLOYEE_ROLES)
def employee_create(request):
    gym = request.gym

    if request.method == "POST":
        form = EmployeeForm(request.POST)
        if form.is_valid():
            employee = form.save(commit=False)
            employee.gym = gym
            employee.save()
            messages.success(request, f'Employe "{employee.name}" cree avec succes.')
            return redirect("rh:detail", employee_id=employee.id)
    else:
        form = EmployeeForm()

    return render(request, "rh/employee_form.html", {"gym": gym, "form": form, "title": "Ajouter un employe"})


@login_required
@module_required("RH")
@role_required(RH_EMPLOYEE_ROLES)
def employee_update(request, employee_id):
    employee = get_object_or_404(Employee, id=employee_id, gym=request.gym)

    if request.method == "POST":
        form = EmployeeForm(request.POST, instance=employee)
        if form.is_valid():
            form.save()
            messages.success(request, f'Employe "{employee.name}" modifie avec succes.')
            return redirect("rh:detail", employee_id=employee.id)
    else:
        form = EmployeeForm(instance=employee)

    return render(
        request,
        "rh/employee_form.html",
        {"gym": request.gym, "form": form, "employee": employee, "title": "Modifier l'employe"},
    )


@login_required
@module_required("RH")
@role_required(RH_EMPLOYEE_ROLES)
def employee_delete(request, employee_id):
    employee = get_object_or_404(Employee, id=employee_id, gym=request.gym)

    if request.method == "POST":
        employee.is_active = False
        employee.save(update_fields=["is_active"])
        messages.success(request, f'Employe "{employee.name}" desactive avec succes.')
        return redirect("rh:list")

    return render(request, "rh/employee_confirm_delete.html", {"gym": request.gym, "employee": employee})


@login_required
@module_required("RH")
@role_required(RH_ATTENDANCE_ROLES)
def attendance_create(request):
    gym = request.gym

    if request.method == "POST":
        form = AttendanceForm(request.POST, gym=gym)
        if form.is_valid():
            attendance = form.save(commit=False)
            attendance.gym = gym
            attendance.save()
            messages.success(request, f"Presence enregistree pour {attendance.employee.name}.")
            return redirect("rh:attendance_list")
    else:
        form = AttendanceForm(gym=gym)

    return render(request, "rh/attendance_form.html", {"gym": gym, "form": form, "title": "Enregistrer une presence"})


@login_required
@module_required("RH")
@role_required(RH_ATTENDANCE_ROLES)
def attendance_bulk(request):
    gym = request.gym
    active_employees = Employee.objects.filter(gym=gym, is_active=True).order_by("name")

    if request.method == "POST":
        form = BulkAttendanceForm(request.POST, gym=gym)
        if form.is_valid():
            attendance_date = form.cleaned_data["date"]
            count = 0
            for employee in active_employees:
                status = form.cleaned_data.get(f"attendance_{employee.id}")
                if status:
                    Attendance.objects.update_or_create(
                        employee=employee,
                        date=attendance_date,
                        defaults={"status": status, "gym": gym},
                    )
                    count += 1
            messages.success(request, f"{count} presences enregistrees pour le {attendance_date}.")
            return redirect("rh:attendance_list")
    else:
        form = BulkAttendanceForm(gym=gym)
        form.fields["date"].initial = timezone.localdate()

    return render(
        request,
        "rh/attendance_bulk.html",
        {"gym": gym, "form": form, "active_employees": active_employees, "title": "Enregistrement groupe des presences"},
    )


@login_required
@module_required("RH")
@role_required(RH_ATTENDANCE_ROLES)
def attendance_list(request):
    gym = request.gym
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    employee_id = request.GET.get("employee")

    attendances = Attendance.objects.filter(gym=gym).select_related("employee")
    if date_from:
        attendances = attendances.filter(date__gte=date_from)
    if date_to:
        attendances = attendances.filter(date__lte=date_to)
    if employee_id:
        attendances = attendances.filter(employee_id=employee_id, employee__gym=gym)

    attendances = attendances.order_by("-date", "employee__name")
    paginator = Paginator(attendances, 20)
    attendances_page = paginator.get_page(request.GET.get("page"))
    attendance_stats = attendances.aggregate(total=Count("id"))

    context = {
        "gym": gym,
        "attendances": attendances_page,
        "employees": Employee.objects.filter(gym=gym, is_active=True).order_by("name"),
        "date_from": date_from,
        "date_to": date_to,
        "selected_employee": employee_id,
        "attendance_stats": attendance_stats,
        **build_rh_kpis(gym),
    }
    return render(request, "rh/attendance_list.html", context)


@login_required
@module_required("RH")
@role_required(RH_PAYROLL_ROLES)
def payroll_dashboard(request):
    gym = request.gym
    year, month = _parse_year_month(request)
    payroll = payroll_rows(gym, year, month)
    contribution_rules = PayrollContributionRule.objects.filter(gym=gym).order_by("display_order", "name")

    context = {
        "gym": gym,
        "year": year,
        "month": month,
        "month_name": _month_name(month),
        "payroll_data": payroll["rows"],
        "total_salaries": payroll["total_salaries"],
        "paid_salaries": payroll["paid_salaries"],
        "pending_salaries": payroll["pending_salaries"],
        "pending_count": payroll["pending_count"],
        "contribution_rules": contribution_rules,
        "contribution_rule_form": PayrollContributionRuleForm(),
        "available_months": available_months(),
        **build_rh_kpis(gym),
    }
    return render(request, "rh/payroll_dashboard.html", context)


@login_required
@require_POST
@module_required("RH")
@role_required(RH_PAYROLL_ROLES)
def add_contribution_rule(request):
    if request.method == "POST":
        form = PayrollContributionRuleForm(request.POST)
        if form.is_valid():
            rule = form.save(commit=False)
            rule.gym = request.gym
            rule.save()
            messages.success(request, "Regle de cotisation ajoutee.")
        else:
            messages.error(request, "Impossible d'ajouter la regle de cotisation.")
    return _redirect_to_payroll_dashboard(request)


@login_required
@require_POST
@module_required("RH")
@role_required(RH_PAYROLL_ROLES)
def toggle_contribution_rule(request, rule_id):
    rule = get_object_or_404(PayrollContributionRule, id=rule_id, gym=request.gym)
    if request.method == "POST":
        rule.is_active = not rule.is_active
        rule.save(update_fields=["is_active", "updated_at"])
        messages.success(request, "Regle de cotisation mise a jour.")
    return _redirect_to_payroll_dashboard(request)


@login_required
@require_POST
@module_required("RH")
@role_required(RH_PAYROLL_ROLES)
def add_adjustment(request, employee_id, year, month):
    employee = get_object_or_404(Employee, id=employee_id, gym=request.gym)
    paid_slip = _paid_slip_guard(request, employee, year, month)
    if paid_slip:
        return redirect(_detail_url(employee.id, year, month))
    if request.method == "POST":
        form = PayrollAdjustmentForm(request.POST)
        if form.is_valid():
            adjustment = form.save(commit=False)
            adjustment.employee = employee
            adjustment.gym = request.gym
            adjustment.year = year
            adjustment.month = month
            adjustment.save()
            PayrollSlip.ensure_for_period(employee, year, month)
            messages.success(request, "Ajustement de paie ajoute.")
        else:
            messages.error(request, "Impossible d'ajouter l'ajustement de paie.")
    return redirect(_detail_url(employee.id, year, month))


@login_required
@require_POST
@module_required("RH")
@role_required(RH_PAYROLL_ROLES)
def add_leave_request(request, employee_id, year, month):
    employee = get_object_or_404(Employee, id=employee_id, gym=request.gym)
    paid_slip = _paid_slip_guard(request, employee, year, month)
    if paid_slip:
        return redirect(_detail_url(employee.id, year, month))
    if request.method == "POST":
        form = LeaveRequestForm(request.POST)
        if form.is_valid():
            leave = form.save(commit=False)
            leave.employee = employee
            leave.gym = request.gym
            leave.save()
            PayrollSlip.ensure_for_period(employee, year, month)
            messages.success(request, "Conge enregistre.")
        else:
            messages.error(request, "Impossible d'enregistrer le conge.")
    return redirect(_detail_url(employee.id, year, month))


@login_required
@require_POST
@module_required("RH")
@role_required(RH_PAYROLL_ROLES)
def add_overtime_entry(request, employee_id, year, month):
    employee = get_object_or_404(Employee, id=employee_id, gym=request.gym)
    paid_slip = _paid_slip_guard(request, employee, year, month)
    if paid_slip:
        return redirect(_detail_url(employee.id, year, month))
    if request.method == "POST":
        form = OvertimeEntryForm(request.POST)
        if form.is_valid():
            overtime_entry = form.save(commit=False)
            overtime_entry.employee = employee
            overtime_entry.gym = request.gym
            overtime_entry.save()
            PayrollSlip.ensure_for_period(employee, year, month)
            messages.success(request, "Heures supplementaires ajoutees.")
        else:
            messages.error(request, "Impossible d'ajouter les heures supplementaires.")
    return redirect(_detail_url(employee.id, year, month))


@login_required
@require_POST
@module_required("RH")
@role_required(RH_PAYROLL_ROLES)
def review_payroll_slip(request, employee_id, year, month):
    employee = get_object_or_404(Employee, id=employee_id, gym=request.gym)
    slip = PayrollSlip.ensure_for_period(employee, year, month)
    if request.method == "POST":
        try:
            slip.review(request.user)
            slip.save(update_fields=["status", "reviewed_at", "reviewed_by", "updated_at"])
            _log_workflow_action(slip, request.user, PayrollWorkflowLog.ACTION_REVIEW)
            messages.success(request, f"Bulletin de {employee.name} verifie.")
        except ValidationError as exc:
            messages.error(request, _validation_message(exc))
    return redirect(_detail_url(employee.id, year, month))


@login_required
@require_POST
@module_required("RH")
@role_required(RH_PAYROLL_ROLES)
def approve_payroll_slip(request, employee_id, year, month):
    employee = get_object_or_404(Employee, id=employee_id, gym=request.gym)
    slip = PayrollSlip.ensure_for_period(employee, year, month)
    if request.method == "POST":
        try:
            slip.approve(request.user)
            slip.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])
            _log_workflow_action(slip, request.user, PayrollWorkflowLog.ACTION_APPROVE)
            messages.success(request, f"Bulletin de {employee.name} approuve.")
        except ValidationError as exc:
            messages.error(request, _validation_message(exc))
    return redirect(_detail_url(employee.id, year, month))


@login_required
@module_required("RH")
@role_required(RH_PAYROLL_ROLES)
def process_payment(request, employee_id, year, month):
    employee = get_object_or_404(Employee, id=employee_id, gym=request.gym)
    slip = PayrollSlip.ensure_for_period(employee, year, month)
    existing_payment = PaymentRecord.objects.filter(employee=employee, gym=request.gym, year=year, month=month).first()

    if existing_payment and existing_payment.is_paid and existing_payment.pos_payment_id:
        messages.warning(request, f"Le salaire de {employee.name} est deja paye.")
        return redirect("rh:payroll_dashboard")

    salary = slip.net_salary
    present_days = slip.present_days

    if request.method == "POST":
        if slip.status != PayrollSlip.STATUS_APPROVED:
            messages.warning(request, "Le bulletin doit etre approuve avant paiement.")
            return redirect(_detail_url(employee.id, year, month))
        form = PaymentForm(request.POST, instance=existing_payment)
        if form.is_valid():
            try:
                with transaction.atomic():
                    pos_payment = record_expense(
                        gym=request.gym,
                        amount_cdf=salary,
                        method=form.cleaned_data["payment_method"],
                        category="salary",
                        description=f"Salaire {employee.name} - {month}/{year}",
                        created_by=request.user,
                        source_app="rh",
                        source_model="PayrollSlip",
                        source_id=slip.id,
                    )
                    payment = form.save(commit=False)
                    payment.employee = employee
                    payment.gym = request.gym
                    payment.year = year
                    payment.month = month
                    payment.amount = salary
                    payment.present_days = present_days
                    payment.pos_payment = pos_payment
                    payment.save()

                    pos_payment.source_model = "PaymentRecord"
                    pos_payment.source_id = payment.id
                    pos_payment.save(update_fields=["source_model", "source_id"])

                    slip.mark_paid(payment)
                    slip.save(update_fields=["payment_record", "status", "reviewed_at", "approved_at", "paid_at", "updated_at"])
                    _log_workflow_action(slip, request.user, PayrollWorkflowLog.ACTION_PAY)
            except ValidationError as exc:
                messages.error(request, _validation_message(exc))
                return redirect("rh:process_payment", employee_id=employee.id, year=year, month=month)

            messages.success(request, f"Paiement de {salary} CDF enregistre via POS pour {employee.name}.")
            return redirect("rh:payroll_dashboard")
    else:
        form = PaymentForm(instance=existing_payment)

    context = {
        "gym": request.gym,
        "employee": employee,
        "year": year,
        "month": month,
        "month_name": _month_name(month),
        "salary": salary,
        "present_days": present_days,
        "slip": slip,
        "form": form,
    }
    return render(request, "rh/payment_form.html", context)


@login_required
@module_required("RH")
@role_required(RH_PAYROLL_ROLES)
def download_payslip_pdf(request, employee_id, year, month):
    employee = get_object_or_404(Employee, id=employee_id, gym=request.gym)
    slip = PayrollSlip.ensure_for_period(employee, year, month)
    contribution_lines = slip.contribution_breakdown()
    lines = [
        "GesGym - Bulletin de paie",
        f"Employe : {employee.name}",
        f"Gym : {request.gym.name}",
        f"Periode : {slip.get_month_display()} {slip.year}",
        f"Role : {employee.get_role_display()}",
        f"Type remuneration : {employee.get_compensation_label()}",
        f"Base salariale : {slip.base_salary} CDF",
        f"Jours presents : {slip.present_days}",
        f"Conges payes : {slip.paid_leave_days}",
        f"Conges sans solde : {slip.unpaid_leave_days}",
        f"Primes : {slip.bonus_total} CDF",
        f"Heures supplementaires : {slip.overtime_total} CDF",
        f"Avances : {slip.advance_total} CDF",
        f"Retenues : {slip.deduction_total} CDF",
        f"Retenue conges : {slip.leave_deduction_total} CDF",
        f"Taxes employee : {slip.employee_tax_total} CDF",
        f"Cotisations employee : {slip.employee_contribution_total} CDF",
        f"Cotisations employeur : {slip.employer_contribution_total} CDF",
        f"Salaire brut : {slip.gross_salary} CDF",
        f"Net a payer : {slip.net_salary} CDF",
        f"Statut : {slip.get_status_display()}",
        f"Verifie le : {slip.reviewed_at.strftime('%d/%m/%Y %H:%M') if slip.reviewed_at else '-'}",
        f"Approuve le : {slip.approved_at.strftime('%d/%m/%Y %H:%M') if slip.approved_at else '-'}",
        f"Paye le : {slip.paid_at.strftime('%d/%m/%Y %H:%M') if slip.paid_at else '-'}",
    ]
    if contribution_lines:
        lines.append("Detail cotisations :")
        for line in contribution_lines:
            lines.append(f"- {line['name']} ({line['party_label']}) : {line['amount']} CDF")
    filename = f"bulletin-paie-{employee.id}-{year}-{month}.pdf"
    return _simple_pdf_response(filename, lines)

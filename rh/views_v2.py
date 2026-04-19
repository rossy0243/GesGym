from calendar import month_name

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from pos.services import record_expense
from smartclub.access_control import RH_ATTENDANCE_ROLES, RH_EMPLOYEE_ROLES, RH_PAYROLL_ROLES
from smartclub.decorators import module_required, role_required

from .forms import AttendanceForm, BulkAttendanceForm, EmployeeForm, PaymentForm
from .kpis import available_months, build_rh_kpis, payroll_rows
from .models import Attendance, Employee, PaymentRecord


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


def _month_name(month):
    return month_name[month]


def _validation_message(exc):
    return exc.messages[0] if getattr(exc, "messages", None) else str(exc)


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

    monthly_salary = employee.calculate_monthly_salary(year, month)
    present_days = employee.attendances.filter(
        gym=request.gym,
        date__year=year,
        date__month=month,
        status="present",
    ).count()
    is_paid = PaymentRecord.objects.filter(
        employee=employee,
        gym=request.gym,
        year=year,
        month=month,
        is_paid=True,
        pos_payment__isnull=False,
        pos_payment__status="success",
    ).exists()
    attendances = employee.attendances.filter(
        gym=request.gym,
        date__year=year,
        date__month=month,
    ).order_by("-date")
    payments = employee.payments.filter(gym=request.gym).order_by("-year", "-month")

    context = {
        "gym": request.gym,
        "employee": employee,
        "year": year,
        "month": month,
        "month_name": _month_name(month),
        "monthly_salary": monthly_salary,
        "present_days": present_days,
        "is_paid": is_paid,
        "attendances": attendances,
        "payments": payments,
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

    return render(
        request,
        "rh/employee_form.html",
        {"gym": gym, "form": form, "title": "Ajouter un employe"},
    )


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
        {
            "gym": request.gym,
            "form": form,
            "employee": employee,
            "title": "Modifier l'employe",
        },
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

    return render(
        request,
        "rh/employee_confirm_delete.html",
        {"gym": request.gym, "employee": employee},
    )


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

    return render(
        request,
        "rh/attendance_form.html",
        {"gym": gym, "form": form, "title": "Enregistrer une presence"},
    )


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
        {
            "gym": gym,
            "form": form,
            "active_employees": active_employees,
            "title": "Enregistrement groupe des presences",
        },
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
        "available_months": available_months(),
        **build_rh_kpis(gym),
    }
    return render(request, "rh/payroll_dashboard.html", context)


@login_required
@module_required("RH")
@role_required(RH_PAYROLL_ROLES)
def process_payment(request, employee_id, year, month):
    employee = get_object_or_404(Employee, id=employee_id, gym=request.gym)
    existing_payment = PaymentRecord.objects.filter(
        employee=employee,
        gym=request.gym,
        year=year,
        month=month,
    ).first()

    if existing_payment and existing_payment.is_paid and existing_payment.pos_payment_id:
        messages.warning(request, f"Le salaire de {employee.name} est deja paye.")
        return redirect("rh:payroll_dashboard")

    salary = employee.calculate_monthly_salary(year, month)
    present_days = employee.attendances.filter(
        gym=request.gym,
        date__year=year,
        date__month=month,
        status="present",
    ).count()

    if request.method == "POST":
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
                        source_model="Employee",
                        source_id=employee.id,
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
        "form": form,
    }
    return render(request, "rh/payment_form.html", context)

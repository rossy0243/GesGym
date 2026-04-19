from datetime import date
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from .models import Attendance, Employee, PaymentRecord


def month_bounds(year, month):
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    return start_date, end_date


def available_months(reference_date=None, limit=12):
    reference_date = reference_date or timezone.localdate()
    months = []
    cursor = reference_date.replace(day=1)
    for _ in range(limit):
        months.append({
            "year": cursor.year,
            "month": cursor.month,
            "name": cursor.strftime("%B %Y"),
        })
        if cursor.month == 1:
            cursor = cursor.replace(year=cursor.year - 1, month=12)
        else:
            cursor = cursor.replace(month=cursor.month - 1)
    return months


def payroll_rows(gym, year, month):
    employees = Employee.objects.filter(gym=gym, is_active=True).order_by("name")
    rows = []
    total_salaries = Decimal("0")
    paid_salaries = Decimal("0")
    pending_salaries = Decimal("0")

    for employee in employees:
        salary = employee.calculate_monthly_salary(year, month)
        present_days = employee.attendances.filter(
            gym=gym,
            date__year=year,
            date__month=month,
            status="present",
        ).count()
        is_paid = PaymentRecord.objects.filter(
            employee=employee,
            gym=gym,
            year=year,
            month=month,
            is_paid=True,
            pos_payment__isnull=False,
            pos_payment__status="success",
        ).exists()

        if salary > 0 or present_days > 0:
            rows.append({
                "employee": employee,
                "present_days": present_days,
                "salary": salary,
                "is_paid": is_paid,
            })
            total_salaries += salary
            if is_paid:
                paid_salaries += salary
            else:
                pending_salaries += salary

    return {
        "rows": rows,
        "total_salaries": total_salaries,
        "paid_salaries": paid_salaries,
        "pending_salaries": pending_salaries,
        "pending_count": sum(1 for row in rows if not row["is_paid"]),
    }


def build_rh_kpis(gym, period_data=None):
    today = timezone.localdate()
    period_data = period_data or {
        "start_date": today.replace(day=1),
        "end_date": today,
    }

    employees = Employee.objects.filter(gym=gym)
    active_employees = employees.filter(is_active=True)
    period_attendances = Attendance.objects.filter(
        gym=gym,
        date__range=(period_data["start_date"], period_data["end_date"]),
    )
    today_attendances = Attendance.objects.filter(gym=gym, date=today)
    paid_period = PaymentRecord.objects.filter(
        gym=gym,
        is_paid=True,
        pos_payment__isnull=False,
        pos_payment__status="success",
        pos_payment__type="out",
        pos_payment__category="salary",
        payment_date__range=(period_data["start_date"], period_data["end_date"]),
    )
    month_payroll = payroll_rows(gym, today.year, today.month)
    role_breakdown = active_employees.values("role").annotate(total=Count("id")).order_by("-total")

    today_total = today_attendances.count()
    today_present = today_attendances.filter(status="present").count()
    period_total = period_attendances.count()
    period_present = period_attendances.filter(status="present").count()

    return {
        "total_employees": employees.count(),
        "active_employees": active_employees.count(),
        "inactive_employees": employees.filter(is_active=False).count(),
        "attendance_today_present": today_present,
        "attendance_today_absent": today_attendances.filter(status="absent").count(),
        "attendance_today_rate": round((today_present / today_total) * 100, 1) if today_total else 0,
        "attendance_period_present": period_present,
        "attendance_period_absent": period_attendances.filter(status="absent").count(),
        "attendance_period_rate": round((period_present / period_total) * 100, 1) if period_total else 0,
        "monthly_payroll": month_payroll["total_salaries"],
        "monthly_payroll_paid": month_payroll["paid_salaries"],
        "monthly_payroll_pending": month_payroll["pending_salaries"],
        "monthly_payroll_pending_count": month_payroll["pending_count"],
        "salary_paid_period": paid_period.aggregate(total=Sum("amount"))["total"] or Decimal("0"),
        "salary_payments_period": paid_period.count(),
        "employee_role_breakdown": role_breakdown,
    }

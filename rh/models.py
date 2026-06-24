from calendar import month_name, monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from organizations.models import Gym


MONEY_QUANTIZER = Decimal("0.01")


def _money(value):
    return Decimal(str(value or "0")).quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)


def month_bounds(year, month):
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    return start_date, end_date


class Employee(models.Model):
    """Employe RH rattache a un gym."""

    ROLE_CHOICES = (
        ("manager", "Manager"),
        ("coach", "Coach"),
        ("reception", "Accueil"),
        ("cashier", "Caissier"),
        ("cleaner", "Agent d'entretien"),
    )

    COMPENSATION_DAILY = "daily"
    COMPENSATION_MONTHLY = "monthly"
    COMPENSATION_TYPE_CHOICES = (
        (COMPENSATION_DAILY, "Salaire journalier"),
        (COMPENSATION_MONTHLY, "Salaire mensuel fixe"),
    )

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="employees", db_index=True)
    name = models.CharField(max_length=255)
    role = models.CharField(max_length=50, choices=ROLE_CHOICES)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True, db_index=True)
    compensation_type = models.CharField(max_length=20, choices=COMPENSATION_TYPE_CHOICES, default=COMPENSATION_DAILY)
    daily_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    monthly_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["gym"])]

    def __str__(self):
        gym_name = self.gym.name if self.gym_id else "Sans gym"
        return f"{self.name} - {self.get_role_display()} - {gym_name}"

    def clean(self):
        super().clean()
        if self.daily_salary is not None and self.daily_salary < 0:
            raise ValidationError({"daily_salary": "Le salaire journalier ne peut pas etre negatif."})
        if self.monthly_salary is not None and self.monthly_salary < 0:
            raise ValidationError({"monthly_salary": "Le salaire mensuel ne peut pas etre negatif."})
        if self.compensation_type == self.COMPENSATION_DAILY and self.daily_salary <= 0:
            raise ValidationError({"daily_salary": "Le salaire journalier doit etre superieur a zero."})
        if self.compensation_type == self.COMPENSATION_MONTHLY and self.monthly_salary <= 0:
            raise ValidationError({"monthly_salary": "Le salaire mensuel doit etre superieur a zero."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def working_days_in_month(self, year, month):
        return monthrange(year, month)[1]

    def daily_rate_for_month(self, year, month):
        if self.compensation_type == self.COMPENSATION_MONTHLY:
            return _money(self.monthly_salary / Decimal(str(self.working_days_in_month(year, month))))
        return _money(self.daily_salary)

    def hourly_rate_for_month(self, year, month):
        return _money(self.daily_rate_for_month(year, month) / Decimal("8"))

    def paid_leave_days_for_month(self, year, month):
        start_date, end_date = month_bounds(year, month)
        return self.leaves.filter(
            status=LeaveRequest.STATUS_APPROVED,
            leave_type=LeaveRequest.TYPE_PAID,
            start_date__lt=end_date,
            end_date__gte=start_date,
        ).count_days_in_month(year, month)

    def unpaid_leave_days_for_month(self, year, month):
        start_date, end_date = month_bounds(year, month)
        return self.leaves.filter(
            status=LeaveRequest.STATUS_APPROVED,
            leave_type=LeaveRequest.TYPE_UNPAID,
            start_date__lt=end_date,
            end_date__gte=start_date,
        ).count_days_in_month(year, month)

    def approved_overtime_amount_for_month(self, year, month):
        total = (
            self.overtime_entries.filter(
                status=OvertimeEntry.STATUS_APPROVED,
                work_date__year=year,
                work_date__month=month,
            ).aggregate(total=models.Sum("amount"))["total"]
            or Decimal("0")
        )
        return _money(total)

    def present_days_for_month(self, year, month):
        start_date, end_date = month_bounds(year, month)
        return self.attendances.filter(date__gte=start_date, date__lt=end_date, status="present").count()

    def calculate_monthly_salary(self, year, month):
        paid_leave_days = self.paid_leave_days_for_month(year, month)
        unpaid_leave_days = self.unpaid_leave_days_for_month(year, month)
        daily_rate = self.daily_rate_for_month(year, month)
        overtime_amount = self.approved_overtime_amount_for_month(year, month)

        if self.compensation_type == self.COMPENSATION_MONTHLY:
            unpaid_leave_deduction = _money(daily_rate * unpaid_leave_days)
            return _money(self.monthly_salary - unpaid_leave_deduction + overtime_amount)

        payable_days = self.present_days_for_month(year, month) + paid_leave_days
        return _money((daily_rate * payable_days) + overtime_amount)

    def get_compensation_amount(self):
        if self.compensation_type == self.COMPENSATION_MONTHLY:
            return self.monthly_salary
        return self.daily_salary

    def get_compensation_label(self):
        if self.compensation_type == self.COMPENSATION_MONTHLY:
            return "Salaire mensuel fixe"
        return "Salaire journalier"

    def get_unpaid_months(self):
        unpaid_months = []
        current_date = date.today()

        for _ in range(12):
            year = current_date.year
            month = current_date.month
            slip = PayrollSlip.ensure_for_period(self, year, month)
            if slip.status != PayrollSlip.STATUS_PAID and slip.net_salary > 0:
                unpaid_months.append(
                    {
                        "year": year,
                        "month": month,
                        "month_name": current_date.strftime("%B %Y"),
                        "salary": slip.net_salary,
                        "present_days": slip.present_days,
                        "status": slip.status,
                    }
                )

            if month == 1:
                current_date = date(year - 1, 12, 1)
            else:
                current_date = date(year, month - 1, 1)

        return unpaid_months


class Attendance(models.Model):
    """Presence journaliere des employes."""

    STATUS = (
        ("present", "Present"),
        ("absent", "Absent"),
    )

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="attendances", db_index=True)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="attendances")
    date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS, default="present")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("employee", "date")
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["gym"]),
            models.Index(fields=["employee"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self):
        return f"{self.employee} - {self.date} - {self.get_status_display()}"

    def clean(self):
        super().clean()
        if self.employee_id and not self.gym_id:
            self.gym = self.employee.gym
        if self.employee_id and self.gym_id and self.employee.gym_id != self.gym_id:
            raise ValidationError({"employee": "L'employe doit appartenir au gym de la presence."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class PaymentRecord(models.Model):
    """Paiement effectif d'un salaire."""

    PAYMENT_METHOD = (
        ("cash", "Especes"),
        ("bank_transfer", "Virement bancaire"),
        ("check", "Cheque"),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payments")
    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="salary_payments")
    year = models.IntegerField()
    month = models.IntegerField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    present_days = models.IntegerField()
    payment_date = models.DateField(auto_now_add=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD, default="cash")
    reference = models.CharField(max_length=100, blank=True, help_text="Numero de recu/virement")
    notes = models.TextField(blank=True)
    is_paid = models.BooleanField(default=True)
    pos_payment = models.OneToOneField(
        "pos.Payment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="salary_record",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("employee", "year", "month")
        ordering = ["-year", "-month"]

    def __str__(self):
        return f"{self.employee.name} - {self.month}/{self.year} - {self.amount} CDF"

    def clean(self):
        super().clean()
        if self.employee_id and not self.gym_id:
            self.gym = self.employee.gym
        if self.employee_id and self.gym_id and self.employee.gym_id != self.gym_id:
            raise ValidationError({"employee": "L'employe doit appartenir au gym du paiement."})
        if self.month is not None and (self.month < 1 or self.month > 12):
            raise ValidationError({"month": "Le mois doit etre compris entre 1 et 12."})
        if self.amount is not None and self.amount < 0:
            raise ValidationError({"amount": "Le montant ne peut pas etre negatif."})
        if self.present_days is not None and self.present_days < 0:
            raise ValidationError({"present_days": "Le nombre de jours presents ne peut pas etre negatif."})
        if self.pos_payment_id:
            if self.pos_payment.gym_id != self.gym_id:
                raise ValidationError({"pos_payment": "Le paiement POS doit appartenir au meme gym."})
            if self.pos_payment.type != "out" or self.pos_payment.category != "salary":
                raise ValidationError({"pos_payment": "Le paiement POS doit etre une sortie de type salaire."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def get_month_display(self):
        return month_name[self.month]


class LeaveRequestQuerySet(models.QuerySet):
    def count_days_in_month(self, year, month):
        start_date, end_date = month_bounds(year, month)
        total = 0
        for leave in self:
            leave_start = max(leave.start_date, start_date)
            leave_end = min(leave.end_date + timedelta(days=1), end_date)
            if leave_start < leave_end:
                total += (leave_end - leave_start).days
        return total


class LeaveRequest(models.Model):
    TYPE_PAID = "paid"
    TYPE_UNPAID = "unpaid"
    TYPE_SICK = "sick"
    LEAVE_TYPE_CHOICES = (
        (TYPE_PAID, "Conge paye"),
        (TYPE_UNPAID, "Conge sans solde"),
        (TYPE_SICK, "Conge maladie"),
    )

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = (
        (STATUS_PENDING, "En attente"),
        (STATUS_APPROVED, "Approuve"),
        (STATUS_REJECTED, "Refuse"),
    )

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="leave_requests")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="leaves")
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPE_CHOICES, default=TYPE_PAID)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = LeaveRequestQuerySet.as_manager()

    class Meta:
        ordering = ["-start_date", "-created_at"]
        indexes = [models.Index(fields=["gym", "status"]), models.Index(fields=["employee", "start_date"])]

    def __str__(self):
        return f"{self.employee.name} - {self.get_leave_type_display()} ({self.start_date} au {self.end_date})"

    def clean(self):
        super().clean()
        if self.employee_id and not self.gym_id:
            self.gym = self.employee.gym
        if self.employee_id and self.gym_id and self.employee.gym_id != self.gym_id:
            raise ValidationError({"employee": "L'employe doit appartenir au gym du conge."})
        if self.end_date < self.start_date:
            raise ValidationError({"end_date": "La date de fin doit etre posterieure a la date de debut."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def count_days_in_month(self, year, month):
        return LeaveRequest.objects.filter(pk=self.pk).count_days_in_month(year, month)


class OvertimeEntry(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = (
        (STATUS_PENDING, "En attente"),
        (STATUS_APPROVED, "Approuve"),
        (STATUS_REJECTED, "Refuse"),
    )

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="overtime_entries")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="overtime_entries")
    work_date = models.DateField()
    hours = models.DecimalField(max_digits=6, decimal_places=2)
    rate_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.25"))
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reason = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-work_date", "-created_at"]
        indexes = [models.Index(fields=["gym", "status"]), models.Index(fields=["employee", "work_date"])]

    def __str__(self):
        return f"{self.employee.name} - {self.hours}h sup ({self.work_date})"

    def clean(self):
        super().clean()
        if self.employee_id and not self.gym_id:
            self.gym = self.employee.gym
        if self.employee_id and self.gym_id and self.employee.gym_id != self.gym_id:
            raise ValidationError({"employee": "L'employe doit appartenir au gym des heures sup."})
        if self.hours is not None and self.hours <= 0:
            raise ValidationError({"hours": "Le nombre d'heures doit etre superieur a zero."})
        if self.rate_multiplier is not None and self.rate_multiplier <= 0:
            raise ValidationError({"rate_multiplier": "Le coefficient doit etre superieur a zero."})

    def save(self, *args, **kwargs):
        if self.employee_id and self.work_date:
            hourly_rate = self.employee.hourly_rate_for_month(self.work_date.year, self.work_date.month)
            self.amount = _money(hourly_rate * self.hours * self.rate_multiplier)
        self.full_clean()
        super().save(*args, **kwargs)


class PayrollAdjustment(models.Model):
    TYPE_BONUS = "bonus"
    TYPE_ADVANCE = "advance"
    TYPE_DEDUCTION = "deduction"
    TYPE_CHOICES = (
        (TYPE_BONUS, "Prime"),
        (TYPE_ADVANCE, "Avance"),
        (TYPE_DEDUCTION, "Retenue"),
    )

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="payroll_adjustments")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payroll_adjustments")
    year = models.IntegerField()
    month = models.IntegerField()
    adjustment_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    label = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year", "-month", "-created_at"]
        indexes = [
            models.Index(fields=["gym", "year", "month"]),
            models.Index(fields=["employee", "year", "month"]),
        ]

    def __str__(self):
        return f"{self.employee.name} - {self.get_adjustment_type_display()} - {self.amount}"

    def clean(self):
        super().clean()
        if self.employee_id and not self.gym_id:
            self.gym = self.employee.gym
        if self.employee_id and self.gym_id and self.employee.gym_id != self.gym_id:
            raise ValidationError({"employee": "L'employe doit appartenir au gym de l'ajustement."})
        if self.month is not None and (self.month < 1 or self.month > 12):
            raise ValidationError({"month": "Le mois doit etre compris entre 1 et 12."})
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({"amount": "Le montant doit etre superieur a zero."})

    def save(self, *args, **kwargs):
        self.amount = _money(self.amount)
        self.full_clean()
        super().save(*args, **kwargs)


class PayrollContributionRule(models.Model):
    PARTY_EMPLOYEE_TAX = "employee_tax"
    PARTY_EMPLOYEE_CONTRIBUTION = "employee_contribution"
    PARTY_EMPLOYER_CONTRIBUTION = "employer_contribution"
    PARTY_CHOICES = (
        (PARTY_EMPLOYEE_TAX, "Taxe employee"),
        (PARTY_EMPLOYEE_CONTRIBUTION, "Cotisation employee"),
        (PARTY_EMPLOYER_CONTRIBUTION, "Cotisation employeur"),
    )

    CALC_PERCENTAGE = "percentage"
    CALC_FIXED = "fixed"
    CALCULATION_CHOICES = (
        (CALC_PERCENTAGE, "Pourcentage du brut"),
        (CALC_FIXED, "Montant fixe"),
    )

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="payroll_contribution_rules")
    name = models.CharField(max_length=120)
    party = models.CharField(max_length=30, choices=PARTY_CHOICES)
    calculation_type = models.CharField(max_length=20, choices=CALCULATION_CHOICES, default=CALC_PERCENTAGE)
    rate_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    fixed_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name"]
        indexes = [models.Index(fields=["gym", "is_active"])]

    def __str__(self):
        return f"{self.name} - {self.get_party_display()}"

    def clean(self):
        super().clean()
        if self.calculation_type == self.CALC_PERCENTAGE and self.rate_percent <= 0:
            raise ValidationError({"rate_percent": "Le pourcentage doit etre superieur a zero."})
        if self.calculation_type == self.CALC_FIXED and self.fixed_amount <= 0:
            raise ValidationError({"fixed_amount": "Le montant fixe doit etre superieur a zero."})
        if self.rate_percent is not None and self.rate_percent < 0:
            raise ValidationError({"rate_percent": "Le pourcentage ne peut pas etre negatif."})
        if self.fixed_amount is not None and self.fixed_amount < 0:
            raise ValidationError({"fixed_amount": "Le montant fixe ne peut pas etre negatif."})

    def save(self, *args, **kwargs):
        self.rate_percent = _money(self.rate_percent)
        self.fixed_amount = _money(self.fixed_amount)
        self.full_clean()
        super().save(*args, **kwargs)

    def compute_amount(self, base_amount):
        base_amount = _money(base_amount)
        if self.calculation_type == self.CALC_PERCENTAGE:
            return _money(base_amount * self.rate_percent / Decimal("100"))
        return _money(self.fixed_amount)


class PayrollSlip(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_REVIEWED = "reviewed"
    STATUS_APPROVED = "approved"
    STATUS_PAID = "paid"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Brouillon"),
        (STATUS_REVIEWED, "Verifie"),
        (STATUS_APPROVED, "Approuve"),
        (STATUS_PAID, "Paye"),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payroll_slips")
    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="payroll_slips")
    year = models.IntegerField()
    month = models.IntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    compensation_type = models.CharField(max_length=20, choices=Employee.COMPENSATION_TYPE_CHOICES)
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    present_days = models.IntegerField(default=0)
    paid_leave_days = models.IntegerField(default=0)
    unpaid_leave_days = models.IntegerField(default=0)
    bonus_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    overtime_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    deduction_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    advance_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    leave_deduction_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    employee_tax_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    employee_contribution_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    employer_contribution_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    gross_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payroll_slips_reviewed",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payroll_slips_approved",
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_record = models.OneToOneField(
        PaymentRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_slip",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("employee", "year", "month")
        ordering = ["-year", "-month", "employee__name"]
        indexes = [models.Index(fields=["gym", "year", "month"]), models.Index(fields=["gym", "status"])]

    def __str__(self):
        return f"Bulletin {self.employee.name} - {self.month}/{self.year}"

    @classmethod
    def ensure_for_period(cls, employee, year, month):
        payment_record = PaymentRecord.objects.filter(
            employee=employee,
            gym=employee.gym,
            year=year,
            month=month,
        ).first()
        slip, _ = cls.objects.get_or_create(
            employee=employee,
            gym=employee.gym,
            year=year,
            month=month,
            defaults={
                "compensation_type": employee.compensation_type,
                "base_salary": Decimal("0"),
                "present_days": 0,
                "gross_salary": Decimal("0"),
                "net_salary": Decimal("0"),
            },
        )
        if payment_record and not slip.payment_record_id:
            slip.payment_record = payment_record
        if payment_record and payment_record.is_paid and payment_record.pos_payment_id:
            slip.status = cls.STATUS_PAID
            if not slip.paid_at:
                slip.paid_at = timezone.now()
            if not slip.approved_at:
                slip.approved_at = slip.paid_at
        slip.recalculate_from_employee()
        slip.save(
            update_fields=[
                "compensation_type",
                "base_salary",
                "present_days",
                "paid_leave_days",
                "unpaid_leave_days",
                "bonus_total",
                "overtime_total",
                "deduction_total",
                "advance_total",
                "leave_deduction_total",
                "employee_tax_total",
                "employee_contribution_total",
                "employer_contribution_total",
                "gross_salary",
                "net_salary",
                "payment_record",
                "status",
                "approved_at",
                "paid_at",
                "updated_at",
            ]
        )
        return slip

    def clean(self):
        super().clean()
        if self.employee_id and not self.gym_id:
            self.gym = self.employee.gym
        if self.employee_id and self.gym_id and self.employee.gym_id != self.gym_id:
            raise ValidationError({"employee": "L'employe doit appartenir au gym du bulletin."})
        if self.month is not None and (self.month < 1 or self.month > 12):
            raise ValidationError({"month": "Le mois doit etre compris entre 1 et 12."})
        for field_name in ["present_days", "paid_leave_days", "unpaid_leave_days"]:
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValidationError({field_name: "La valeur ne peut pas etre negative."})
        for field_name in [
            "base_salary",
            "bonus_total",
            "overtime_total",
            "deduction_total",
            "advance_total",
            "leave_deduction_total",
            "employee_tax_total",
            "employee_contribution_total",
            "employer_contribution_total",
            "gross_salary",
            "net_salary",
        ]:
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValidationError({field_name: "Le montant ne peut pas etre negatif."})
        if self.status == self.STATUS_PAID and not self.payment_record_id:
            raise ValidationError({"payment_record": "Un bulletin paye doit etre lie a un paiement."})

    def recalculate_from_employee(self):
        self.compensation_type = self.employee.compensation_type
        self.present_days = self.employee.present_days_for_month(self.year, self.month)
        self.paid_leave_days = self.employee.paid_leave_days_for_month(self.year, self.month)
        self.unpaid_leave_days = self.employee.unpaid_leave_days_for_month(self.year, self.month)
        daily_rate = self.employee.daily_rate_for_month(self.year, self.month)

        if self.compensation_type == Employee.COMPENSATION_MONTHLY:
            self.base_salary = self.employee.monthly_salary
            base_gross = _money(self.employee.monthly_salary)
        else:
            self.base_salary = daily_rate
            payable_days = self.present_days + self.paid_leave_days
            base_gross = _money(daily_rate * payable_days)

        self.leave_deduction_total = _money(daily_rate * self.unpaid_leave_days)
        adjustments = PayrollAdjustment.objects.filter(employee=self.employee, gym=self.gym, year=self.year, month=self.month)
        self.bonus_total = _money(
            adjustments.filter(adjustment_type=PayrollAdjustment.TYPE_BONUS).aggregate(total=models.Sum("amount"))["total"]
            or 0
        )
        self.advance_total = _money(
            adjustments.filter(adjustment_type=PayrollAdjustment.TYPE_ADVANCE).aggregate(total=models.Sum("amount"))["total"]
            or 0
        )
        self.deduction_total = _money(
            adjustments.filter(adjustment_type=PayrollAdjustment.TYPE_DEDUCTION).aggregate(total=models.Sum("amount"))["total"]
            or 0
        )
        self.overtime_total = self.employee.approved_overtime_amount_for_month(self.year, self.month)
        self.gross_salary = _money(base_gross + self.bonus_total + self.overtime_total)
        self.employee_tax_total = Decimal("0")
        self.employee_contribution_total = Decimal("0")
        self.employer_contribution_total = Decimal("0")
        for rule in PayrollContributionRule.objects.filter(gym=self.gym, is_active=True):
            amount = rule.compute_amount(self.gross_salary)
            if rule.party == PayrollContributionRule.PARTY_EMPLOYEE_TAX:
                self.employee_tax_total = _money(self.employee_tax_total + amount)
            elif rule.party == PayrollContributionRule.PARTY_EMPLOYEE_CONTRIBUTION:
                self.employee_contribution_total = _money(self.employee_contribution_total + amount)
            else:
                self.employer_contribution_total = _money(self.employer_contribution_total + amount)
        self.net_salary = _money(
            self.gross_salary
            - self.advance_total
            - self.deduction_total
            - self.leave_deduction_total
            - self.employee_tax_total
            - self.employee_contribution_total
        )

    def review(self, user):
        if self.status == self.STATUS_PAID:
            raise ValidationError("Le bulletin est deja paye.")
        self.status = self.STATUS_REVIEWED
        self.reviewed_at = timezone.now()
        self.reviewed_by = user

    def approve(self, user):
        if self.status == self.STATUS_PAID:
            raise ValidationError("Le bulletin est deja paye.")
        if self.status == self.STATUS_DRAFT:
            raise ValidationError("Le bulletin doit d'abord etre verifie.")
        self.status = self.STATUS_APPROVED
        self.approved_at = timezone.now()
        self.approved_by = user

    def mark_paid(self, payment_record):
        now_value = timezone.now()
        self.payment_record = payment_record
        self.status = self.STATUS_PAID
        if not self.reviewed_at:
            self.reviewed_at = now_value
        if not self.approved_at:
            self.approved_at = now_value
        self.paid_at = now_value

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def get_month_display(self):
        return month_name[self.month]

    @property
    def total_deductions(self):
        return _money(
            self.deduction_total
            + self.advance_total
            + self.leave_deduction_total
            + self.employee_tax_total
            + self.employee_contribution_total
        )

    @property
    def payroll_deductions_total(self):
        return _money(
            self.deduction_total
            + self.leave_deduction_total
            + self.employee_tax_total
            + self.employee_contribution_total
        )

    @property
    def employee_withholding_total(self):
        return _money(self.employee_tax_total + self.employee_contribution_total)

    def contribution_breakdown(self):
        lines = []
        for rule in PayrollContributionRule.objects.filter(gym=self.gym, is_active=True):
            lines.append(
                {
                    "name": rule.name,
                    "party": rule.party,
                    "party_label": rule.get_party_display(),
                    "amount": rule.compute_amount(self.gross_salary),
                }
            )
        return lines


class PayrollWorkflowLog(models.Model):
    ACTION_REVIEW = "review"
    ACTION_APPROVE = "approve"
    ACTION_PAY = "pay"
    ACTION_CHOICES = (
        (ACTION_REVIEW, "Verification"),
        (ACTION_APPROVE, "Approbation"),
        (ACTION_PAY, "Paiement"),
    )

    slip = models.ForeignKey(PayrollSlip, on_delete=models.CASCADE, related_name="workflow_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.slip} - {self.get_action_display()}"

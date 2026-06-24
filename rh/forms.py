from django import forms

from .models import (
    Attendance,
    Employee,
    LeaveRequest,
    OvertimeEntry,
    PaymentRecord,
    PayrollAdjustment,
    PayrollContributionRule,
)


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            "name",
            "role",
            "phone",
            "email",
            "compensation_type",
            "daily_salary",
            "monthly_salary",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom complet"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Numero de telephone"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Email"}),
            "compensation_type": forms.Select(attrs={"class": "form-select"}),
            "daily_salary": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "placeholder": "Salaire journalier"}
            ),
            "monthly_salary": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "placeholder": "Salaire mensuel fixe"}
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "name": "Nom",
            "role": "Role",
            "phone": "Telephone",
            "email": "Email",
            "compensation_type": "Mode de remuneration",
            "daily_salary": "Salaire journalier (CDF)",
            "monthly_salary": "Salaire mensuel fixe (CDF)",
            "is_active": "Actif",
        }

    def clean_daily_salary(self):
        daily_salary = self.cleaned_data.get("daily_salary")
        if daily_salary is not None and daily_salary < 0:
            raise forms.ValidationError("Le salaire journalier ne peut pas etre negatif.")
        return daily_salary

    def clean_monthly_salary(self):
        monthly_salary = self.cleaned_data.get("monthly_salary")
        if monthly_salary is not None and monthly_salary < 0:
            raise forms.ValidationError("Le salaire mensuel ne peut pas etre negatif.")
        return monthly_salary

    def clean(self):
        cleaned_data = super().clean()
        compensation_type = cleaned_data.get("compensation_type")
        daily_salary = cleaned_data.get("daily_salary")
        monthly_salary = cleaned_data.get("monthly_salary")

        if compensation_type == Employee.COMPENSATION_DAILY and (daily_salary is None or daily_salary <= 0):
            self.add_error("daily_salary", "Le salaire journalier doit etre superieur a zero.")
        if compensation_type == Employee.COMPENSATION_MONTHLY and (monthly_salary is None or monthly_salary <= 0):
            self.add_error("monthly_salary", "Le salaire mensuel doit etre superieur a zero.")
        return cleaned_data


class AttendanceForm(forms.ModelForm):
    class Meta:
        model = Attendance
        fields = ["employee", "date", "status"]
        widgets = {
            "employee": forms.Select(attrs={"class": "form-select"}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        self.gym = kwargs.pop("gym", None)
        super().__init__(*args, **kwargs)
        if self.gym:
            self.fields["employee"].queryset = Employee.objects.filter(gym=self.gym, is_active=True)


class BulkAttendanceForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))

    def __init__(self, *args, **kwargs):
        self.gym = kwargs.pop("gym", None)
        super().__init__(*args, **kwargs)
        if self.gym:
            employees = Employee.objects.filter(gym=self.gym, is_active=True)
            for employee in employees:
                self.fields[f"attendance_{employee.id}"] = forms.ChoiceField(
                    choices=[("present", "Present"), ("absent", "Absent")],
                    label=employee.name,
                    initial="present",
                    widget=forms.Select(attrs={"class": "form-select"}),
                )


class PaymentForm(forms.ModelForm):
    class Meta:
        model = PaymentRecord
        fields = ["payment_method", "reference", "notes"]
        widgets = {
            "payment_method": forms.Select(attrs={"class": "form-select"}),
            "reference": forms.TextInput(attrs={"class": "form-control", "placeholder": "Numero de recu/virement"}),
            "notes": forms.Textarea(
                attrs={"class": "form-control", "rows": 3, "placeholder": "Notes supplementaires"}
            ),
        }
        labels = {
            "payment_method": "Mode de paiement",
            "reference": "Reference",
            "notes": "Notes",
        }


class PayrollAdjustmentForm(forms.ModelForm):
    class Meta:
        model = PayrollAdjustment
        fields = ["adjustment_type", "label", "amount", "notes"]
        widgets = {
            "adjustment_type": forms.Select(attrs={"class": "form-select"}),
            "label": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Prime performance"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }
        labels = {
            "adjustment_type": "Type",
            "label": "Libelle",
            "amount": "Montant (CDF)",
            "notes": "Notes",
        }


class LeaveRequestForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ["leave_type", "start_date", "end_date", "reason", "status"]
        widgets = {
            "leave_type": forms.Select(attrs={"class": "form-select"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "reason": forms.TextInput(attrs={"class": "form-control", "placeholder": "Motif"}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "leave_type": "Type de conge",
            "start_date": "Debut",
            "end_date": "Fin",
            "reason": "Motif",
            "status": "Statut",
        }


class OvertimeEntryForm(forms.ModelForm):
    class Meta:
        model = OvertimeEntry
        fields = ["work_date", "hours", "rate_multiplier", "reason", "status"]
        widgets = {
            "work_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "hours": forms.NumberInput(attrs={"class": "form-control", "step": "0.25"}),
            "rate_multiplier": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "reason": forms.TextInput(attrs={"class": "form-control", "placeholder": "Motif"}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "work_date": "Date",
            "hours": "Heures",
            "rate_multiplier": "Coefficient",
            "reason": "Motif",
            "status": "Statut",
        }


class PayrollContributionRuleForm(forms.ModelForm):
    class Meta:
        model = PayrollContributionRule
        fields = ["name", "party", "calculation_type", "rate_percent", "fixed_amount", "display_order", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: INSS, IPR, CNSS..."}),
            "party": forms.Select(attrs={"class": "form-select"}),
            "calculation_type": forms.Select(attrs={"class": "form-select"}),
            "rate_percent": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "fixed_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "display_order": forms.NumberInput(attrs={"class": "form-control", "step": "1", "min": "0"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "name": "Libelle",
            "party": "Portee",
            "calculation_type": "Mode de calcul",
            "rate_percent": "Pourcentage",
            "fixed_amount": "Montant fixe (CDF)",
            "display_order": "Ordre",
            "is_active": "Actif",
        }

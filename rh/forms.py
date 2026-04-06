from django import forms
from .models import Employee, Attendance, PaymentRecord
from django.utils import timezone

class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ['name', 'role', 'phone', 'daily_salary', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom complet'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Numéro de téléphone'}),
            'daily_salary': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Salaire journalier'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'name': 'Nom',
            'role': 'Rôle',
            'phone': 'Téléphone',
            'daily_salary': 'Salaire journalier (€)',
            'is_active': 'Actif',
        }

class AttendanceForm(forms.ModelForm):
    class Meta:
        model = Attendance
        fields = ['employee', 'date', 'status']
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.gym = kwargs.pop('gym', None)
        super().__init__(*args, **kwargs)
        if self.gym:
            self.fields['employee'].queryset = Employee.objects.filter(gym=self.gym, is_active=True)

class BulkAttendanceForm(forms.Form):
    date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    
    def __init__(self, *args, **kwargs):
        self.gym = kwargs.pop('gym', None)
        super().__init__(*args, **kwargs)
        if self.gym:
            employees = Employee.objects.filter(gym=self.gym, is_active=True)
            for employee in employees:
                self.fields[f'attendance_{employee.id}'] = forms.ChoiceField(
                    choices=[('present', 'Présent'), ('absent', 'Absent')],
                    label=employee.name,
                    initial='present',
                    widget=forms.Select(attrs={'class': 'form-select'})
                )

class PaymentForm(forms.ModelForm):
    class Meta:
        model = PaymentRecord
        fields = ['payment_method', 'reference', 'notes']
        widgets = {
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'reference': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'N° de reçu/virement'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Notes supplémentaires'}),
        }
        labels = {
            'payment_method': 'Mode de paiement',
            'reference': 'Référence',
            'notes': 'Notes',
        }
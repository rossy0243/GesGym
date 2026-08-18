from django import forms
from .models import Machine, MaintenanceLog

class MachineForm(forms.ModelForm):
    class Meta:
        model = Machine
        fields = ['name', 'status', 'purchase_date', 'maintenance_interval_days']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom de la machine'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'purchase_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'maintenance_interval_days': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'placeholder': 'Ex : 90',
            }),
        }
        labels = {
            'name': 'Nom',
            'status': 'Statut',
            'purchase_date': "Date d'achat",
            'maintenance_interval_days': "Maintenance tous les (jours)",
        }
        help_texts = {
            'maintenance_interval_days':
                "Laisser vide si cette machine n'a pas d'entretien periodique. "
                "L'echeance part de la derniere maintenance enregistree, ou de la date d'achat.",
        }

class MaintenanceLogForm(forms.ModelForm):
    class Meta:
        model = MaintenanceLog
        fields = ['description', 'cost']
        widgets = {
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Description détaillée de la maintenance...'}),
            'cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
        }
        labels = {
            'description': 'Description',
            'cost': 'Coût (CDF)',
        }

    def clean_cost(self):
        cost = self.cleaned_data.get('cost')
        if cost is not None and cost < 0:
            raise forms.ValidationError("Le cout ne peut pas etre negatif.")
        return cost

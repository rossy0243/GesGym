from django import forms
from .models import Coach
from members.models import Member

class CoachForm(forms.ModelForm):
    class Meta:
        model = Coach
        fields = ['name', 'phone', 'specialty', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom complet'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Téléphone'}),
            'specialty': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Crossfit, Yoga, Musculation...'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'name': 'Nom',
            'phone': 'Téléphone',
            'specialty': 'Spécialité',
            'is_active': 'Actif',
        }

class CoachMemberForm(forms.Form):
    member = forms.ModelChoiceField(
        queryset=Member.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    def __init__(self, *args, **kwargs):
        coach = kwargs.pop('coach', None)
        super().__init__(*args, **kwargs)
        if coach:
            self.fields['member'].queryset = Member.objects.filter(
                gym=coach.gym,
                status='active'  # ← Filtrer uniquement les membres actifs
            ).exclude(id__in=coach.members.all())
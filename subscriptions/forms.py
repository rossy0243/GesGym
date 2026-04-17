# subscriptions/forms.py
from django import forms
from django.utils import timezone
from members.models import Member
from .models import MemberSubscription, SubscriptionPlan

class SubscriptionPlanForm(forms.ModelForm):
    def __init__(self, *args, gym=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.gym = gym

    class Meta:
        model = SubscriptionPlan
        fields = ['name', 'duration_days', 'price', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'duration_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': '0.01'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise forms.ValidationError("Le nom de la formule est obligatoire.")

        if self.gym:
            exists = SubscriptionPlan.objects.filter(
                gym=self.gym,
                name__iexact=name,
            ).exclude(pk=self.instance.pk).exists()
            if exists:
                raise forms.ValidationError("Une formule avec ce nom existe deja dans ce gym.")

        return name
        

class MemberSubscriptionForm(forms.ModelForm):
    def __init__(self, *args, gym=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.gym = gym

        if gym:
            self.fields['member'].queryset = Member.objects.filter(
                gym=gym,
                is_active=True,
            ).order_by('first_name', 'last_name')
            self.fields['plan'].queryset = SubscriptionPlan.objects.filter(
                gym=gym,
                is_active=True,
            ).order_by('name')

        self.fields['start_date'].initial = timezone.now().date()
        self.fields['start_date'].input_formats = ['%Y-%m-%d']

    class Meta:
        model = MemberSubscription
        fields = ['member', 'plan', 'start_date', 'auto_renew']
        widgets = {
            'member': forms.Select(attrs={'class': 'form-control'}),
            'plan': forms.Select(attrs={'class': 'form-control'}),
            'start_date': forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control', 'type': 'date'}),
            'auto_renew': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        member = cleaned_data.get('member')
        plan = cleaned_data.get('plan')

        if self.gym:
            if member and member.gym_id != self.gym.id:
                raise forms.ValidationError("Ce membre n'appartient pas au gym courant.")

            if plan and plan.gym_id != self.gym.id:
                raise forms.ValidationError("Cette formule n'appartient pas au gym courant.")

        if member and plan and member.gym_id != plan.gym_id:
            raise forms.ValidationError("Le membre et la formule doivent appartenir au meme gym.")

        return cleaned_data

    def _post_clean(self):
        self.instance._skip_active_collision_validation = True
        try:
            super()._post_clean()
        finally:
            self.instance._skip_active_collision_validation = False
        

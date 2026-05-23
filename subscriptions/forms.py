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
        fields = [
            'name',
            'duration_days',
            'price',
            'description',
            'coaching_mode',
            'coaching_level',
            'is_active',
        ]
        labels = {
            'price': 'Prix (USD)',
            'coaching_mode': 'Acces coaching',
            'coaching_level': 'Niveau de service coaching',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'duration_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': '0.01'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'coaching_mode': forms.Select(attrs={'class': 'form-select'}),
            'coaching_level': forms.Select(attrs={'class': 'form-select'}),
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
    PAYMENT_METHOD_CHOICES = (
        ("cash", "Especes"),
        ("card", "Carte bancaire"),
        ("mobile_money", "Mobile Money"),
        ("bank_transfer", "Virement bancaire"),
        ("check", "Cheque"),
    )

    CURRENCY_CHOICES = (
        ("USD", "USD"),
        ("CDF", "CDF"),
    )

    payment_method = forms.ChoiceField(
        choices=PAYMENT_METHOD_CHOICES,
        initial="cash",
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Mode de paiement",
    )
    currency = forms.ChoiceField(
        choices=CURRENCY_CHOICES,
        initial="USD",
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Devise",
    )

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
        start_date = cleaned_data.get('start_date')

        if self.gym:
            if member and member.gym_id != self.gym.id:
                raise forms.ValidationError("Ce membre n'appartient pas au gym courant.")

            if plan and plan.gym_id != self.gym.id:
                raise forms.ValidationError("Cette formule n'appartient pas au gym courant.")

        if member and plan and member.gym_id != plan.gym_id:
            raise forms.ValidationError("Le membre et la formule doivent appartenir au meme gym.")

        if start_date and start_date > timezone.localdate():
            self.add_error("start_date", "La date de debut ne peut pas etre dans le futur pour un abonnement encaisse.")

        return cleaned_data

    def _post_clean(self):
        self.instance._skip_active_collision_validation = True
        try:
            super()._post_clean()
        finally:
            self.instance._skip_active_collision_validation = False
        

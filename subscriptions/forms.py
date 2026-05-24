# subscriptions/forms.py
from django import forms
from django.utils import timezone
from members.models import Member
from .models import MemberSubscription, SubscriptionOffer, SubscriptionPlan


class SubscriptionOfferForm(forms.ModelForm):
    def __init__(self, *args, gym=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.gym = gym

    class Meta:
        model = SubscriptionOffer
        fields = [
            "name",
            "category",
            "description",
            "grants_individual_coaching",
            "grants_group_coaching",
            "is_active",
        ]
        labels = {
            "name": "Nom de l'offre",
            "category": "Categorie",
            "description": "Description",
            "grants_individual_coaching": "Donne acces au coaching individuel",
            "grants_group_coaching": "Donne acces au coaching groupe",
            "is_active": "Offre active",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "grants_individual_coaching": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "grants_group_coaching": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Le nom de l'offre est obligatoire.")

        if self.gym:
            exists = SubscriptionOffer.objects.filter(
                gym=self.gym,
                name__iexact=name,
            ).exclude(pk=self.instance.pk).exists()
            if exists:
                raise forms.ValidationError("Une offre avec ce nom existe deja dans ce gym.")
        return name

class SubscriptionPlanForm(forms.ModelForm):
    coaching_mode = forms.CharField(required=False, widget=forms.HiddenInput())
    coaching_level = forms.CharField(required=False, widget=forms.HiddenInput())
    offers = forms.ModelMultipleChoiceField(
        queryset=SubscriptionOffer.objects.none(),
        required=False,
        label="Offres incluses",
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, gym=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.gym = gym
        if gym:
            self.fields["offers"].queryset = SubscriptionOffer.objects.filter(gym=gym).order_by("name")
        if self.instance and self.instance.pk:
            self.fields["coaching_mode"].initial = self.instance.coaching_mode
            self.fields["coaching_level"].initial = self.instance.coaching_level
        else:
            self.fields["coaching_mode"].initial = SubscriptionPlan.COACHING_MODE_NONE
            self.fields["coaching_level"].initial = SubscriptionPlan.COACHING_LEVEL_STANDARD

    class Meta:
        model = SubscriptionPlan
        fields = [
            'name',
            'duration_days',
            'price',
            'description',
            'offers',
            'coaching_mode',
            'coaching_level',
            'is_active',
        ]
        labels = {
            'price': 'Prix (USD)',
        }
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

    def clean(self):
        cleaned_data = super().clean()
        offers = cleaned_data.get("offers")
        has_individual = any(offer.grants_individual_coaching for offer in offers) if offers else False
        has_group = any(offer.grants_group_coaching for offer in offers) if offers else False

        if has_individual and has_group:
            cleaned_data["coaching_mode"] = SubscriptionPlan.COACHING_MODE_BOTH
        elif has_individual:
            cleaned_data["coaching_mode"] = SubscriptionPlan.COACHING_MODE_INDIVIDUAL
        elif has_group:
            cleaned_data["coaching_mode"] = SubscriptionPlan.COACHING_MODE_GROUP
        else:
            cleaned_data["coaching_mode"] = SubscriptionPlan.COACHING_MODE_NONE

        if not cleaned_data.get("coaching_level"):
            cleaned_data["coaching_level"] = (
                self.instance.coaching_level
                if self.instance and self.instance.pk
                else SubscriptionPlan.COACHING_LEVEL_STANDARD
            )
        return cleaned_data
        

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
        

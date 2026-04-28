from datetime import timedelta

from django import forms
from django.db.models import Exists, OuterRef
from django.utils import timezone

from members.models import Member
from subscriptions.models import MemberSubscription


class InAppMessageForm(forms.Form):
    TARGET_INDIVIDUAL = "individual"
    TARGET_ALL = "all"
    TARGET_ACTIVE = "active"
    TARGET_EXPIRED = "expired"
    TARGET_EXPIRING_SOON = "expiring_soon"
    TARGET_SUSPENDED = "suspended"
    TARGET_WITHOUT_SUBSCRIPTION = "without_subscription"

    TARGET_CHOICES = (
        (TARGET_INDIVIDUAL, "Un membre precis"),
        (TARGET_ALL, "Tous les membres"),
        (TARGET_ACTIVE, "Membres actifs"),
        (TARGET_EXPIRED, "Membres expires"),
        (TARGET_EXPIRING_SOON, "Expiration dans 7 jours"),
        (TARGET_SUSPENDED, "Membres suspendus"),
        (TARGET_WITHOUT_SUBSCRIPTION, "Sans abonnement"),
    )

    target = forms.ChoiceField(
        label="Destinataires",
        choices=TARGET_CHOICES,
        initial=TARGET_INDIVIDUAL,
        widget=forms.Select(attrs={"class": "form-select", "data-target-select": "true"}),
    )
    member = forms.ModelChoiceField(
        queryset=Member.objects.none(),
        label="Membre",
        empty_label="Choisir un membre",
        required=False,
        widget=forms.Select(attrs={"class": "form-select", "data-member-select": "true"}),
    )
    title = forms.CharField(
        label="Titre",
        max_length=120,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ex: Votre abonnement expire bientot",
            }
        ),
    )
    message = forms.CharField(
        label="Message",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Ecrivez le message visible dans l'espace membre...",
            }
        ),
    )

    def __init__(self, *args, gym=None, **kwargs):
        self.gym = gym
        super().__init__(*args, **kwargs)
        if gym:
            self.fields["member"].queryset = self._base_members().order_by(
                "first_name",
                "last_name",
            )

    def clean(self):
        cleaned_data = super().clean()
        target = cleaned_data.get("target")
        member = cleaned_data.get("member")

        if target == self.TARGET_INDIVIDUAL and not member:
            self.add_error("member", "Choisissez le membre qui doit recevoir ce message.")

        return cleaned_data

    def _base_members(self):
        return Member.objects.filter(gym=self.gym, is_active=True)

    def _annotated_members(self):
        today = timezone.localdate()
        active_subscription = MemberSubscription.objects.filter(
            member=OuterRef("pk"),
            is_active=True,
            is_paused=False,
            end_date__gte=today,
        )
        expiring_subscription = active_subscription.filter(
            end_date__lte=today + timedelta(days=7),
        )
        any_subscription = MemberSubscription.objects.filter(member=OuterRef("pk"))

        return self._base_members().annotate(
            has_active_subscription=Exists(active_subscription),
            has_expiring_subscription=Exists(expiring_subscription),
            has_any_subscription=Exists(any_subscription),
        )

    def get_recipients(self):
        target = self.cleaned_data["target"]

        if target == self.TARGET_INDIVIDUAL:
            return Member.objects.filter(pk=self.cleaned_data["member"].pk)

        return self.get_recipients_for_target(target)

    def get_recipients_for_target(self, target):
        members = self._annotated_members()

        if target == self.TARGET_ALL:
            return self._base_members()
        if target == self.TARGET_ACTIVE:
            return members.filter(has_active_subscription=True).exclude(status="suspended")
        if target == self.TARGET_EXPIRED:
            return members.filter(has_active_subscription=False).exclude(status="suspended")
        if target == self.TARGET_EXPIRING_SOON:
            return members.filter(has_expiring_subscription=True).exclude(status="suspended")
        if target == self.TARGET_SUSPENDED:
            return self._base_members().filter(status="suspended")
        if target == self.TARGET_WITHOUT_SUBSCRIPTION:
            return members.filter(has_any_subscription=False).exclude(status="suspended")

        return Member.objects.none()

    @classmethod
    def target_label(cls, target):
        return dict(cls.TARGET_CHOICES).get(target, "Destinataires")

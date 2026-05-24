from django import forms
from django.db.models import Q
from django.utils import timezone

from members.models import Member
from subscriptions.models import SubscriptionPlan

from .models import Coach, CoachSpecialty, CoachingFeedback, CoachingFollowUp, GroupCoachingProgram


class CoachForm(forms.ModelForm):
    specialty = forms.ChoiceField(
        required=False,
        choices=[],
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Specialite",
    )

    def __init__(self, *args, **kwargs):
        gym = kwargs.pop("gym", None)
        super().__init__(*args, **kwargs)
        choices = [("", "Choisir une specialite")]
        if gym:
            choices.extend(
                (specialty.name, specialty.name)
                for specialty in CoachSpecialty.objects.filter(gym=gym, is_active=True)
            )
        current_specialty = getattr(self.instance, "specialty", "") if self.instance else ""
        if current_specialty and current_specialty not in [value for value, _ in choices]:
            choices.append((current_specialty, current_specialty))
        self.fields["specialty"].choices = choices

    class Meta:
        model = Coach
        fields = ["name", "phone", "specialty", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom complet"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Telephone"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "name": "Nom",
            "phone": "Telephone",
            "specialty": "Specialite",
            "is_active": "Actif",
        }


class CoachMemberForm(forms.Form):
    member = forms.ModelChoiceField(
        queryset=Member.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        coach = kwargs.pop("coach", None)
        super().__init__(*args, **kwargs)
        if coach:
            today = timezone.localdate()
            individual_filter = Q(
                subscriptions__plan__coaching_mode__in=[
                    SubscriptionPlan.COACHING_MODE_INDIVIDUAL,
                    SubscriptionPlan.COACHING_MODE_BOTH,
                ]
            ) | Q(
                subscriptions__plan__offers__is_active=True,
                subscriptions__plan__offers__grants_individual_coaching=True,
            )
            self.fields["member"].queryset = Member.objects.filter(
                gym=coach.gym,
                is_active=True,
                status="active",
                subscriptions__is_active=True,
                subscriptions__is_paused=False,
                subscriptions__start_date__lte=today,
                subscriptions__end_date__gte=today,
            ).filter(individual_filter).exclude(id__in=coach.members.all()).distinct()


class GroupCoachingProgramForm(forms.ModelForm):
    coach = forms.ModelChoiceField(
        queryset=Coach.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Coach referent",
    )

    class Meta:
        model = GroupCoachingProgram
        fields = ["name", "objective", "description", "coach", "capacity", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Transformation 8 semaines"}),
            "objective": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Perte de poids, reprise, debutants"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "Decris le programme et ce que les membres vont y trouver."}),
            "capacity": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "name": "Nom du programme",
            "objective": "Objectif",
            "description": "Description",
            "coach": "Coach referent",
            "capacity": "Capacite",
            "is_active": "Actif",
        }

    def __init__(self, *args, **kwargs):
        gym = kwargs.pop("gym", None)
        super().__init__(*args, **kwargs)
        if gym:
            self.fields["coach"].queryset = Coach.objects.filter(gym=gym, is_active=True).order_by("name")


class CoachingFollowUpForm(forms.ModelForm):
    class Meta:
        model = CoachingFollowUp
        fields = ["interaction_type", "summary", "next_action", "next_follow_up_at"]
        widgets = {
            "interaction_type": forms.Select(attrs={"class": "form-select"}),
            "summary": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Resume rapidement ce qui a ete fait, constate ou decide.",
                }
            ),
            "next_action": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex: relancer sur la nutrition ou planifier un bilan.",
                }
            ),
            "next_follow_up_at": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }
        labels = {
            "interaction_type": "Type d'action",
            "summary": "Resume du suivi",
            "next_action": "Prochaine action",
            "next_follow_up_at": "Date de relance",
        }


class CoachingFeedbackForm(forms.ModelForm):
    SCORE_CHOICES = [(score, f"{score}/5") for score in range(1, 6)]

    overall_rating = forms.TypedChoiceField(choices=SCORE_CHOICES, coerce=int, widget=forms.Select(attrs={"class": "form-select"}))
    listening_rating = forms.TypedChoiceField(choices=SCORE_CHOICES, coerce=int, widget=forms.Select(attrs={"class": "form-select"}))
    clarity_rating = forms.TypedChoiceField(choices=SCORE_CHOICES, coerce=int, widget=forms.Select(attrs={"class": "form-select"}))
    motivation_rating = forms.TypedChoiceField(choices=SCORE_CHOICES, coerce=int, widget=forms.Select(attrs={"class": "form-select"}))
    availability_rating = forms.TypedChoiceField(choices=SCORE_CHOICES, coerce=int, widget=forms.Select(attrs={"class": "form-select"}))

    class Meta:
        model = CoachingFeedback
        fields = [
            "overall_rating",
            "listening_rating",
            "clarity_rating",
            "motivation_rating",
            "availability_rating",
            "comment",
            "wants_contact",
        ]
        widgets = {
            "comment": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Qu'est-ce qui vous a aide ou qu'est-ce qu'on peut ameliorer ?",
                }
            ),
            "wants_contact": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "overall_rating": "Satisfaction globale",
            "listening_rating": "Ecoute",
            "clarity_rating": "Clarte des conseils",
            "motivation_rating": "Motivation transmise",
            "availability_rating": "Disponibilite / suivi",
            "comment": "Commentaire",
            "wants_contact": "Je souhaite etre recontacte",
        }

from django import forms

from members.models import Member

from .models import Coach, CoachSpecialty


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
            self.fields["member"].queryset = Member.objects.filter(
                gym=coach.gym,
                is_active=True,
                status="active",
            ).exclude(id__in=coach.members.all())

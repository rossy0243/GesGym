from django import forms

from members.models import Member

from .models import Coach


class CoachForm(forms.ModelForm):
    class Meta:
        model = Coach
        fields = ["name", "phone", "specialty", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom complet"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Telephone"}),
            "specialty": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ex: Crossfit, Yoga, Musculation..."}
            ),
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

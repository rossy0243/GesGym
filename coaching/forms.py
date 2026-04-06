from django import forms
from .models import Coach
from members.models import Member


class CoachForm(forms.ModelForm):
    """
    Formulaire création coach
    """

    members = forms.ModelMultipleChoiceField(
        queryset=Member.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={
            "class": "form-control"
        })
    )

    class Meta:
        model = Coach
        fields = ["name", "phone", "specialty", "members"]

        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom du coach"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Téléphone"}),
            "specialty": forms.TextInput(attrs={"class": "form-control", "placeholder": "Spécialité"}),
        }

    def __init__(self, *args, **kwargs):
        gym = kwargs.pop("gym", None)
        super().__init__(*args, **kwargs)

        # 🔐 multi-tenant
        if gym:
            self.fields["members"].queryset = Member.objects.filter(gym=gym)
from django import forms

from members.models import Member


class InAppMessageForm(forms.Form):
    member = forms.ModelChoiceField(
        queryset=Member.objects.none(),
        label="Membre",
        empty_label="Choisir un membre",
        widget=forms.Select(attrs={"class": "form-select"}),
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
        super().__init__(*args, **kwargs)
        if gym:
            self.fields["member"].queryset = Member.objects.filter(gym=gym).order_by(
                "first_name",
                "last_name",
            )

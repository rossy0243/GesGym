from django import forms


class ContactRequestForm(forms.Form):
    full_name = forms.CharField(
        label="Nom complet",
        max_length=120,
    )
    email = forms.EmailField(
        label="E-mail",
        max_length=254,
        required=False,
    )
    phone = forms.CharField(
        label="Téléphone / WhatsApp",
        max_length=30,
    )
    message = forms.CharField(
        label="Votre message",
        required=False,
        widget=forms.Textarea,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base_input_classes = (
            "w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 "
            "outline-none transition focus:border-[#C9A227] focus:ring-4 focus:ring-[#F7EFD9]"
        )
        self.fields["full_name"].widget.attrs.update(
            {
                "class": base_input_classes,
                "placeholder": "Votre nom",
            }
        )
        self.fields["email"].widget.attrs.update(
            {
                "class": base_input_classes,
                "placeholder": "vous@exemple.com",
            }
        )
        self.fields["phone"].widget.attrs.update(
            {
                "class": base_input_classes,
                "placeholder": "+243 ...",
            }
        )
        self.fields["message"].widget.attrs.update(
            {
                "class": base_input_classes + " min-h-[140px] resize-y",
                "placeholder": "Dites-nous ce que vous recherchez : essai gratuit, tarifs, coaching...",
            }
        )

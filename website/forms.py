from django import forms


class DemoRequestForm(forms.Form):
    PACK_CHOICES = (
        ("", "Non precise"),
        ("club", "Pack Club"),
        ("premium", "Pack Premium"),
    )

    selected_pack = forms.ChoiceField(
        required=False,
        choices=PACK_CHOICES,
        widget=forms.HiddenInput,
    )
    full_name = forms.CharField(
        label="Nom complet",
        max_length=120,
    )
    email = forms.EmailField(
        label="Email professionnel",
        max_length=254,
    )
    phone = forms.CharField(
        label="Telephone",
        max_length=30,
    )
    club_name = forms.CharField(
        label="Nom du club",
        max_length=120,
    )
    sites_count = forms.IntegerField(
        label="Nombre de sites actifs",
        min_value=1,
    )
    message = forms.CharField(
        label="Votre besoin",
        required=False,
        widget=forms.Textarea,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base_input_classes = (
            "w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 "
            "outline-none transition focus:border-[#004e92] focus:ring-4 focus:ring-blue-100"
        )
        self.fields["full_name"].widget.attrs.update(
            {
                "class": base_input_classes,
                "placeholder": "Ex: Rosette Mukendi",
            }
        )
        self.fields["email"].widget.attrs.update(
            {
                "class": base_input_classes,
                "placeholder": "contact@votreclub.com",
            }
        )
        self.fields["phone"].widget.attrs.update(
            {
                "class": base_input_classes,
                "placeholder": "+243 ...",
            }
        )
        self.fields["club_name"].widget.attrs.update(
            {
                "class": base_input_classes,
                "placeholder": "Nom de votre salle",
            }
        )
        self.fields["sites_count"].widget.attrs.update(
            {
                "class": base_input_classes,
                "placeholder": "1",
            }
        )
        self.fields["message"].widget.attrs.update(
            {
                "class": base_input_classes + " min-h-[140px] resize-y",
                "placeholder": "Expliquez brièvement votre contexte, vos objectifs ou vos questions.",
            }
        )

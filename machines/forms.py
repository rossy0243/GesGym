from django import forms
from django.utils import timezone

from .models import Machine, MaintenanceLog

class MachineForm(forms.ModelForm):
    """
    Fiche d'un equipement, machine ou accessoire.

    Le declassement ne passe pas par ce formulaire : c'est une decision datee
    et motivee, pas un statut qu'on change au passage en corrigeant un nom.
    """

    class Meta:
        model = Machine
        fields = ['name', 'equipment_type', 'status', 'purchase_date', 'maintenance_interval_days']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Nom de l'equipement"}),
            'equipment_type': forms.Select(attrs={'class': 'form-select', 'data-equipment-type': 'true'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'purchase_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'maintenance_interval_days': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'placeholder': 'Ex : 90',
            }),
        }
        labels = {
            'name': 'Nom',
            'equipment_type': 'Nature',
            'status': 'Statut',
            'purchase_date': "Date d'achat",
            'maintenance_interval_days': "Maintenance tous les (jours)",
        }
        help_texts = {
            'equipment_type':
                "Une machine s'entretient (tapis, velo, presse). "
                "Un accessoire ne s'entretient pas : il se declasse quand il est use "
                "(halteres, tapis de sol, elastiques).",
            'maintenance_interval_days':
                "Reserve aux machines. Laisser vide s'il n'y a pas d'entretien periodique. "
                "L'echeance part de la derniere maintenance enregistree, ou de la date d'achat.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Le declassement se fait par une action dediee, qui exige un motif :
        # l'offrir dans la liste deroulante permettrait de sortir un
        # equipement du parc sans dire pourquoi ni depuis quand.
        self.fields["status"].choices = [
            (valeur, libelle)
            for valeur, libelle in Machine.STATUS
            if valeur != Machine.STATUS_DECLASSED
        ]

    def clean(self):
        cleaned = super().clean()
        nature = cleaned.get("equipment_type")

        if nature == Machine.TYPE_ACCESSORY:
            if cleaned.get("maintenance_interval_days"):
                self.add_error(
                    "maintenance_interval_days",
                    "Un accessoire ne s'entretient pas : laissez ce champ vide, "
                    "ou declarez cet equipement comme machine.",
                )
            if cleaned.get("status") == Machine.STATUS_MAINTENANCE:
                self.add_error(
                    "status",
                    "Un accessoire ne passe pas en maintenance. "
                    "Declassez-le s'il est hors d'usage.",
                )

        return cleaned


class DeclassementForm(forms.Form):
    """
    Sortie d'un equipement du parc.

    Le motif est obligatoire : un equipement qui disparait du parc sans
    explication laisse l'equipe suivante sans moyen de savoir s'il a ete casse,
    vole, vendu ou simplement remplace.
    """

    MOTIFS = (
        ("use", "Use / fin de vie"),
        ("casse", "Casse irreparable"),
        ("vole", "Vole ou perdu"),
        ("vendu", "Vendu ou cede"),
        ("remplace", "Remplace par un neuf"),
        ("autre", "Autre"),
    )

    motif = forms.ChoiceField(
        choices=MOTIFS,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Motif",
    )

    precision = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Detail utile a l'equipe (optionnel)",
        }),
        label="Precision",
    )

    date_declassement = forms.DateField(
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        label="Date du declassement",
    )

    def clean_date_declassement(self):
        jour = self.cleaned_data.get("date_declassement")
        if jour and jour > timezone.localdate():
            raise forms.ValidationError(
                "Un declassement ne se date pas dans le futur."
            )
        return jour

    def motif_complet(self):
        """Libelle a consigner sur la fiche et dans le journal sensible."""
        libelle = dict(self.MOTIFS)[self.cleaned_data["motif"]]
        precision = (self.cleaned_data.get("precision") or "").strip()
        return f"{libelle} - {precision}" if precision else libelle

class MaintenanceLogForm(forms.ModelForm):
    class Meta:
        model = MaintenanceLog
        fields = ['description', 'cost']
        widgets = {
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Description détaillée de la maintenance...'}),
            'cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
        }
        labels = {
            'description': 'Description',
            'cost': 'Coût (CDF)',
        }

    def clean_cost(self):
        cost = self.cleaned_data.get('cost')
        if cost is not None and cost < 0:
            raise forms.ValidationError("Le cout ne peut pas etre negatif.")
        return cost

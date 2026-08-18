from django import forms
from .models import Product, StockMovement

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'price', 'currency', 'quantity', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom du produit'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Prix de vente'}),
            'currency': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'name': 'Nom',
            'price': 'Prix de vente',
            'currency': 'Devise du prix',
            'quantity': 'Quantité initiale',
            'is_active': 'Actif',
        }
        help_texts = {
            'currency': "Devise dans laquelle le prix est affiche en rayon. "
                        "La caisse convertit au taux de la session si le client paie dans l'autre devise.",
        }

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is not None and price < 0:
            raise forms.ValidationError("Le prix ne peut pas etre negatif.")
        return price

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if quantity is not None and quantity < 0:
            raise forms.ValidationError("La quantite ne peut pas etre negative.")
        return quantity

class StockMovementForm(forms.ModelForm):
    """
    Saisie manuelle d'une entree de stock.

    Les sorties ne sont plus saisies ici : elles decoulent uniquement d'une
    vente encaissee, qui decremente le stock elle-meme. Laisser une sortie
    manuelle a cote de la caisse permettait de sortir deux fois le meme
    produit, une fois a la vente et une fois a la main.
    """

    class Meta:
        model = StockMovement
        fields = ['quantity', 'reason']
        widgets = {
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'reason': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Provenance ou motif (optionnel)'}),
        }
        labels = {
            'quantity': 'Quantité reçue',
            'reason': 'Motif',
        }

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if quantity is not None and quantity <= 0:
            raise forms.ValidationError("La quantite doit etre superieure a zero.")
        return quantity

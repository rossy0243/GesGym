from decimal import Decimal, ROUND_HALF_UP

from django.db import models, transaction
from django.core.exceptions import ValidationError
from organizations.models import Gym


def _arrondi(valeur):
    return Decimal(valeur).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

class Product(models.Model):
    """
    Produit vendu dans le gym (boisson, complément, etc.)
    """

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="products",
        db_index=True
    )

    name = models.CharField(max_length=255)

    CURRENCY_USD = "USD"
    CURRENCY_CDF = "CDF"
    CURRENCY_CHOICES = (
        (CURRENCY_USD, "USD (Dollar americain)"),
        (CURRENCY_CDF, "CDF (Franc congolais)"),
    )

    price = models.DecimalField(max_digits=10, decimal_places=2)

    # Certains produits sont achetes et revendus en francs : les afficher en
    # dollars obligeait la salle a reconvertir un prix qu'elle n'a jamais fixe
    # en dollars, et le prix affiche bougeait a chaque changement de taux.
    currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        default=CURRENCY_USD,
    )

    quantity = models.IntegerField(default=0)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["gym"]),
        ]

    def __str__(self):
        gym_name = self.gym.name if self.gym_id else "Sans gym"
        return f"{self.name} - {gym_name}"

    def clean(self):
        super().clean()
        if self.price is not None and self.price < 0:
            raise ValidationError({"price": "Le prix ne peut pas etre negatif."})
        if self.quantity is not None and self.quantity < 0:
            raise ValidationError({"quantity": "La quantite ne peut pas etre negative."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def price_in(self, currency, exchange_rate):
        """
        Prix unitaire exprime dans la devise demandee.

        Le prix saisi fait foi : c'est celui affiche en rayon. La conversion ne
        sert qu'a encaisser dans l'autre devise, au taux de la session de
        caisse, pour que la contre-valeur suive le taux du jour.
        """
        prix = self.price or Decimal("0")
        if currency == self.currency:
            return _arrondi(prix)

        if not exchange_rate or exchange_rate <= 0:
            raise ValueError("Taux de change indisponible pour convertir le prix.")

        if self.currency == self.CURRENCY_USD:
            return _arrondi(prix * exchange_rate)
        return _arrondi(prix / exchange_rate)

    def price_usd(self, exchange_rate):
        """Contre-valeur en dollars, unite commune des indicateurs de stock."""
        return self.price_in(self.CURRENCY_USD, exchange_rate)

    def update_stock(self, quantity, movement_type, reason=None):
        """Met à jour le stock et crée un mouvement"""
        if quantity <= 0:
            raise ValueError("La quantite doit etre superieure a zero.")
        if movement_type not in dict(StockMovement.MOVEMENT_TYPE):
            raise ValueError("Type de mouvement invalide.")

        if movement_type == 'in':
            self.quantity += quantity
        elif movement_type == 'out':
            if self.quantity < quantity:
                raise ValueError(f"Stock insuffisant pour {self.name}")
            self.quantity -= quantity
        
        with transaction.atomic():
            self.save()
            StockMovement.objects.create(
                gym=self.gym,
                product=self,
                quantity=quantity,
                movement_type=movement_type,
                reason=reason
            )


class StockMovement(models.Model):
    """
    Historique des mouvements de stock
    """

    MOVEMENT_TYPE = (
        ("in", "Entrée"),
        ("out", "Sortie"),
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="stock_movements",
        db_index=True
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="movements"
    )

    quantity = models.IntegerField()

    movement_type = models.CharField(
        max_length=10,
        choices=MOVEMENT_TYPE
    )

    reason = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["gym"]),
            models.Index(fields=["product"]),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.product.name} - {self.get_movement_type_display()} - {self.quantity}"

    def clean(self):
        super().clean()
        if self.product_id and not self.gym_id:
            self.gym = self.product.gym
        if self.product_id and self.gym_id and self.product.gym_id != self.gym_id:
            raise ValidationError({"product": "Le produit doit appartenir au gym du mouvement."})
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({"quantity": "La quantite doit etre superieure a zero."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

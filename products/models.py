from django.db import models, transaction
from django.core.exceptions import ValidationError
from organizations.models import Gym

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

    price = models.DecimalField(max_digits=10, decimal_places=2)

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

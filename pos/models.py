from django.db import models
from django.conf import settings
from django.db.models import Sum
from django.core.exceptions import ValidationError
from decimal import Decimal, ROUND_HALF_UP
from organizations.models import Gym
from members.models import Member
from products.models import Product
from subscriptions.models import MemberSubscription


MONEY_QUANTIZER = Decimal("0.01")


def _money(value):
    return Decimal(str(value)).quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)


class CashRegister(models.Model):

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="cash_registers",
        db_index=True
    )

    session_code = models.CharField(
        max_length=30,
        unique=True,
        blank=True,
        null=True
    )

    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="register_opened"
    )

    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="register_closed"
    )

    opening_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Taux fige pour cette session: 1 USD = X CDF"
    )

    closing_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    difference = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    opened_at = models.DateTimeField(auto_now_add=True)

    closed_at = models.DateTimeField(null=True, blank=True)

    is_closed = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["gym"]),
            models.Index(fields=["gym", "is_closed"]),
        ]

    def save(self, *args, **kwargs):

        self.full_clean()

        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new and not self.session_code:
            self.session_code = f"{self.gym.id}-CS-{self.opened_at.year}-{self.id:04d}"
            super().save(update_fields=["session_code"])

    def total_entries(self):
        return self.payments.filter(
            gym=self.gym,
            type="in",
            status="success"
        ).aggregate(total=Sum("amount_cdf"))["total"] or 0

    def total_exits(self):
        return self.payments.filter(
            gym=self.gym,
            type="out",
            status="success"
        ).aggregate(total=Sum("amount_cdf"))["total"] or 0

    def expected_total(self):
        return self.opening_amount + self.total_entries() - self.total_exits()
    
    def clean(self):

        if not self.is_closed:
            exists = CashRegister.objects.filter(
                gym=self.gym,
                is_closed=False
            ).exclude(pk=self.pk).exists()

            if not self.exchange_rate or self.exchange_rate <= 0:
                raise ValidationError("Le taux USD-CDF est obligatoire pour ouvrir la caisse.")

            if exists:
                raise ValidationError("Une caisse est déjà ouverte pour ce gym.")
        if self.opening_amount < 0:
            raise ValidationError("Le fonds d'ouverture ne peut pas etre negatif.")

    def __str__(self):
        return self.session_code or f"Register {self.id}"
    

class Payment(models.Model):

    PAYMENT_METHODS = (
        ("cash", "Cash"),
        ("card", "Card"),
        ("mobile_money", "Mobile Money"),
    )

    TRANSACTION_TYPE = (
        ("in", "Entrée"),
        ("out", "Sortie"),
    )

    STATUS = (
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="payments",
        db_index=True
    )

    cash_register = models.ForeignKey(
        CashRegister,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments"
    )

    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="payments"
    )

    subscription = models.ForeignKey(
        MemberSubscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments"
    )
    currency = models.CharField(
    max_length=5,
    choices=(
        ("USD", "USD"),
        ("CDF", "CDF"),
    ),
    default="USD"
)

    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    amount_cdf = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        blank=True
    )

    amount_usd = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Montant de reference en USD lorsque la vente est pricee en USD"
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    method = models.CharField(max_length=20, choices=PAYMENT_METHODS)

    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default="pending"
    )

    type = models.CharField(
        max_length=10,
        choices=TRANSACTION_TYPE,
        default="in"
    )

    transaction_id = models.CharField(
        max_length=200,
        blank=True,
        null=True
    )

    description = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    product = models.ForeignKey(
    Product,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="payments"
)
    class Meta:
        indexes = [
            models.Index(fields=["gym"]),
            models.Index(fields=["status"]),
            models.Index(fields=["gym", "status"]),
            models.Index(fields=["gym", "created_at"]),
            models.Index(fields=["type"]),
            models.Index(fields=["currency"]),
        ]

    def clean(self):
        if self.cash_register and self.cash_register.gym != self.gym:
            raise ValidationError("La caisse n'appartient pas a ce gym.")

        if self.cash_register and not self.exchange_rate:
            self.exchange_rate = self.cash_register.exchange_rate

        if self.exchange_rate is not None and self.exchange_rate <= 0:
            raise ValidationError("Le taux de change doit etre superieur a zero.")

        if self.amount <= 0:
            raise ValidationError("Le montant doit etre superieur a zero.")

        if self.currency == "CDF":
            self.amount = _money(self.amount)
            self.amount_cdf = self.amount

        elif self.currency == "USD":
            if not self.exchange_rate:
                raise ValidationError("Le taux de change est requis pour USD")
            self.amount = _money(self.amount)
            self.amount_cdf = _money(self.amount * self.exchange_rate)

        if self.amount_usd is None and self.currency == "USD":
            self.amount_usd = self.amount

        # Sécurité multi-tenant
        if self.member and self.member.gym != self.gym:
            raise ValidationError("Le membre n'appartient pas à ce gym.")
        if self.subscription and self.subscription.gym != self.gym:
            raise ValidationError("L'abonnement n'appartient pas à ce gym.")
        if self.product and self.product.gym != self.gym:
            raise ValidationError("Le produit n'appartient pas à ce gym.")
        
    def save(self, *args, **kwargs):
        if self.cash_register and not self.exchange_rate:
            self.exchange_rate = self.cash_register.exchange_rate

        if self.currency == "CDF":
            self.amount = _money(self.amount)
            self.amount_cdf = self.amount

        elif self.currency == "USD":
            if not self.exchange_rate:
                raise ValidationError("Le taux de change est requis pour USD")

            self.amount = _money(self.amount)
            self.amount_cdf = _money(self.amount * self.exchange_rate)

        if self.amount_usd is None and self.currency == "USD":
            self.amount_usd = self.amount

        self.full_clean()
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"{self.amount} - {self.gym}"
    
    
class ExchangeRate(models.Model):
    """
    Taux du jour défini manuellement par le gym
    """

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="exchange_rates"
    )

    rate = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    date = models.DateField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("gym", "date")
        indexes = [
            models.Index(fields=["gym", "date"])
        ]

    def __str__(self):
        return f"{self.gym} - {self.rate} ({self.date})"

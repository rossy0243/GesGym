from django.db import models
from django.core.exceptions import ValidationError
from organizations.models import Gym

class Machine(models.Model):
    """
    Machines du gym (tapis, vélo, etc.)
    """

    STATUS = (
        ("ok", "OK"),
        ("maintenance", "Maintenance"),
        ("broken", "En panne"),
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="machines",
        db_index=True
    )

    name = models.CharField(max_length=255)

    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default="ok"
    )

    purchase_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        gym_name = self.gym.name if self.gym_id else "Sans gym"
        return f"{self.name} - {gym_name}"


class MaintenanceLog(models.Model):
    """
    Historique des maintenances machines
    """

    machine = models.ForeignKey(
        Machine,
        on_delete=models.CASCADE,
        related_name="maintenance_logs"
    )

    description = models.TextField()

    cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    pos_payment = models.OneToOneField(
        "pos.Payment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="maintenance_log"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.machine.name} - {self.created_at.strftime('%Y-%m-%d')}"

    def clean(self):
        super().clean()
        if self.cost is not None and self.cost < 0:
            raise ValidationError({"cost": "Le cout ne peut pas etre negatif."})
        if self.pos_payment_id:
            if self.pos_payment.gym_id != self.machine.gym_id:
                raise ValidationError({"pos_payment": "Le paiement POS doit appartenir au meme gym."})
            if self.pos_payment.type != "out" or self.pos_payment.category != "maintenance":
                raise ValidationError({"pos_payment": "Le paiement POS doit etre une sortie de maintenance."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

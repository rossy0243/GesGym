from django.db import models
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
        return self.name


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

    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.machine.name} - {self.created_at.strftime('%Y-%m-%d')}"
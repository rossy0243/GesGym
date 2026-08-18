from datetime import timedelta

from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
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

    # Une maintenance manquee coute plus cher qu'une maintenance faite : la
    # salle declare son rythme, le logiciel se charge de prevenir a temps.
    maintenance_interval_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Intervalle de maintenance (jours)",
        help_text="Laisser vide si cette machine n'a pas d'entretien periodique.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        gym_name = self.gym.name if self.gym_id else "Sans gym"
        return f"{self.name} - {gym_name}"

    def clean(self):
        super().clean()
        if self.maintenance_interval_days is not None and self.maintenance_interval_days < 1:
            raise ValidationError({
                "maintenance_interval_days": "L'intervalle doit valoir au moins un jour."
            })

    def last_maintenance_on(self):
        """
        Point de depart du prochain cycle.

        La derniere intervention fait foi. Sans intervention, on part de la date
        d'achat : une machine neuve entre dans son cycle des sa mise en service.
        """
        derniere = self.maintenance_logs.order_by("-created_at").first()
        if derniere:
            return timezone.localtime(derniere.created_at).date()
        return self.purchase_date

    def next_maintenance_on(self):
        """Date de la prochaine maintenance, ou None si aucun rythme declare."""
        if not self.maintenance_interval_days:
            return None

        depart = self.last_maintenance_on()
        if not depart:
            return None

        return depart + timedelta(days=self.maintenance_interval_days)

    def days_until_maintenance(self):
        """Jours restants ; negatif si l'echeance est deja passee."""
        echeance = self.next_maintenance_on()
        if not echeance:
            return None
        return (echeance - timezone.localdate()).days

    def maintenance_is_due_soon(self, lead_days):
        """Vrai si l'echeance tombe dans le delai de prevenance, ou est passee."""
        restant = self.days_until_maintenance()
        return restant is not None and restant <= lead_days


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

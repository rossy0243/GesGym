from datetime import timedelta

from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from organizations.models import Gym


class Machine(models.Model):
    """
    Equipement du gym.

    Deux natures cohabitent, parce qu'elles ne se gerent pas pareil :

    - une **machine** (tapis, velo, presse) s'entretient. Elle a un rythme de
      maintenance, un historique d'interventions, et un cout d'entretien ;
    - un **accessoire** (halteres, tapis de sol, elastiques) ne s'entretient
      pas. Quand il est use, on ne le repare pas : on le sort du parc.

    Les confondre revenait a proposer un entretien periodique pour une corde a
    sauter, et a n'offrir aucun moyen propre de sortir du parc un accessoire
    hors d'usage autrement qu'en le supprimant, ce qui effacait son historique.
    """

    TYPE_MACHINE = "machine"
    TYPE_ACCESSORY = "accessory"
    EQUIPMENT_TYPES = (
        (TYPE_MACHINE, "Machine"),
        (TYPE_ACCESSORY, "Accessoire"),
    )

    STATUS_OK = "ok"
    STATUS_MAINTENANCE = "maintenance"
    STATUS_BROKEN = "broken"
    STATUS_DECLASSED = "declasse"
    STATUS = (
        (STATUS_OK, "OK"),
        (STATUS_MAINTENANCE, "Maintenance"),
        (STATUS_BROKEN, "En panne"),
        (STATUS_DECLASSED, "Declasse"),
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="machines",
        db_index=True
    )

    name = models.CharField(max_length=255)

    equipment_type = models.CharField(
        max_length=20,
        choices=EQUIPMENT_TYPES,
        default=TYPE_MACHINE,
        db_index=True,
        verbose_name="Nature",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default=STATUS_OK
    )

    purchase_date = models.DateField(null=True, blank=True)

    # Une maintenance manquee coute plus cher qu'une maintenance faite : la
    # salle declare son rythme, le logiciel se charge de prevenir a temps.
    maintenance_interval_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Intervalle de maintenance (jours)",
        help_text="Laisser vide si cet equipement n'a pas d'entretien periodique.",
    )

    # Le declassement sort l'equipement du parc sans effacer son passe : les
    # couts deja engages restent lisibles dans les rapports.
    declassed_on = models.DateField(
        null=True,
        blank=True,
        verbose_name="Declasse le",
    )

    declassed_reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Motif du declassement",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        gym_name = self.gym.name if self.gym_id else "Sans gym"
        return f"{self.name} - {gym_name}"

    # --- Nature et cycle de vie ---------------------------------------------

    @property
    def is_accessory(self):
        return self.equipment_type == self.TYPE_ACCESSORY

    @property
    def is_declassed(self):
        return self.status == self.STATUS_DECLASSED

    @property
    def is_maintainable(self):
        """Seule une machine encore au parc se maintient."""
        return self.equipment_type == self.TYPE_MACHINE and not self.is_declassed

    def declass(self, reason="", on=None):
        """Sort l'equipement du parc. Reversible par remise en service."""
        self.status = self.STATUS_DECLASSED
        self.declassed_on = on or timezone.localdate()
        self.declassed_reason = (reason or "").strip()
        self.save(update_fields=["status", "declassed_on", "declassed_reason"])

    def return_to_service(self):
        """Annule un declassement : une erreur de saisie doit se corriger."""
        self.status = self.STATUS_OK
        self.declassed_on = None
        self.declassed_reason = ""
        self.save(update_fields=["status", "declassed_on", "declassed_reason"])

    def clean(self):
        super().clean()
        if self.maintenance_interval_days is not None and self.maintenance_interval_days < 1:
            raise ValidationError({
                "maintenance_interval_days": "L'intervalle doit valoir au moins un jour."
            })

        if self.is_accessory and self.maintenance_interval_days:
            raise ValidationError({
                "maintenance_interval_days":
                    "Un accessoire ne s'entretient pas : laissez l'intervalle vide, "
                    "ou declarez cet equipement comme machine."
            })

        if self.is_accessory and self.status == self.STATUS_MAINTENANCE:
            raise ValidationError({
                "status":
                    "Un accessoire ne passe pas en maintenance. "
                    "Declassez-le s'il est hors d'usage."
            })

        if self.is_declassed and not self.declassed_on:
            raise ValidationError({
                "declassed_on": "Un equipement declasse doit porter sa date de declassement."
            })

        if not self.is_declassed and (self.declassed_on or self.declassed_reason):
            raise ValidationError(
                "Un equipement en service ne peut pas porter de declassement."
            )

    # --- Maintenance ---------------------------------------------------------

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
        if not self.is_maintainable or not self.maintenance_interval_days:
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
    Historique des maintenances machines.

    Reserve aux machines encore au parc : un accessoire ne se repare pas, et
    un equipement declasse n'a plus a coûter d'entretien.
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

        if self.machine_id and self.machine.is_accessory:
            raise ValidationError(
                "Un accessoire ne s'entretient pas : il se declasse quand il est hors d'usage."
            )

        if self.machine_id and self.machine.is_declassed:
            raise ValidationError(
                "Cet equipement est declasse : remettez-le en service avant d'y engager une depense."
            )

        if self.pos_payment_id:
            if self.pos_payment.gym_id != self.machine.gym_id:
                raise ValidationError({"pos_payment": "Le paiement POS doit appartenir au meme gym."})
            if self.pos_payment.type != "out" or self.pos_payment.category != "maintenance":
                raise ValidationError({"pos_payment": "Le paiement POS doit etre une sortie de maintenance."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

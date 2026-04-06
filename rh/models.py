#rh/models.py
from django.db import models
from django.utils import timezone
from organizations.models import Gym
from decimal import Decimal

class Employee(models.Model):
    """
    Employé du gym (RH simple)
    """

    ROLE_CHOICES = (
        ("manager", "Manager"),
        ("coach", "Coach"),
        ("reception", "Accueil"),
        ("cashier", "Caissier"),
        ("cleaner", "Agent d'entretien"),
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="employees",
        db_index=True
    )

    name = models.CharField(max_length=255)

    role = models.CharField(max_length=50, choices=ROLE_CHOICES)

    phone = models.CharField(max_length=20, blank=True, null=True)

    daily_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["gym"]),
        ]

    def __str__(self):
        return f"{self.name} - {self.role}"
    
    def calculate_monthly_salary(self, year, month):
        """Calcule le salaire mensuel basé sur les présences"""
        from datetime import date
        start_date = date(year, month, 1)
        
        # Dernier jour du mois
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)
        
        # Compter les présences
        present_days = self.attendances.filter(
            date__gte=start_date,
            date__lt=end_date,
            status="present"
        ).count()
        
        return present_days * self.daily_salary
    
    def get_unpaid_months(self):
        """Récupère les mois non payés"""
        from datetime import date, timedelta
        from calendar import monthrange
        
        unpaid_months = []
        current_date = date.today()
        
        # Vérifier les 12 derniers mois
        for i in range(12):
            year = current_date.year
            month = current_date.month
            
            # Vérifier si déjà payé
            if not PaymentRecord.objects.filter(
                employee=self,
                year=year,
                month=month,
                is_paid=True
            ).exists():
                # Calculer le salaire du mois
                salary = self.calculate_monthly_salary(year, month)
                if salary > 0:  # Ne montrer que les mois avec des présences
                    unpaid_months.append({
                        'year': year,
                        'month': month,
                        'month_name': current_date.strftime('%B %Y'),
                        'salary': salary,
                        'present_days': self.attendances.filter(
                            date__year=year,
                            date__month=month,
                            status="present"
                        ).count()
                    })
            
            # Mois précédent
            if month == 1:
                current_date = date(year - 1, 12, 1)
            else:
                current_date = date(year, month - 1, 1)
        
        return unpaid_months


class Attendance(models.Model):
    """
    Présence journalière des employés
    """

    STATUS = (
        ("present", "Présent"),
        ("absent", "Absent"),
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="attendances",
        db_index=True
    )

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendances"
    )

    date = models.DateField()

    status = models.CharField(
        max_length=10,
        choices=STATUS,
        default="present"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("employee", "date")
        ordering = ['-date']

        indexes = [
            models.Index(fields=["gym"]),
            models.Index(fields=["employee"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self):
        return f"{self.employee} - {self.date} - {self.get_status_display()}"


class PaymentRecord(models.Model):
    """
    Enregistrement des paiements des salaires
    """
    
    PAYMENT_METHOD = (
        ("cash", "Espèces"),
        ("bank_transfer", "Virement bancaire"),
        ("check", "Chèque"),
    )

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="payments"
    )
    
    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="salary_payments"
    )
    
    year = models.IntegerField()
    month = models.IntegerField()
    
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )
    
    present_days = models.IntegerField()
    
    payment_date = models.DateField(auto_now_add=True)
    
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD,
        default="cash"
    )
    
    reference = models.CharField(max_length=100, blank=True, help_text="Numéro de reçu/virement")
    
    notes = models.TextField(blank=True)
    
    is_paid = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ("employee", "year", "month")
        ordering = ['-year', '-month']
    
    def __str__(self):
        return f"{self.employee.name} - {self.month}/{self.year} - {self.amount}€"
    
    def get_month_display(self):
        """Retourne le nom du mois"""
        from calendar import month_name
        return month_name[self.month]
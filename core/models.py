# core/models.py
import datetime
import uuid
import qrcode
from io import BytesIO
from django.core.files import File

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.db.models import Sum

from .managers import GymManager

class Gym(models.Model):

    name = models.CharField(max_length=150)

    # nouvelle relation SaaS
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    logo = models.ImageField(upload_to="gym_logos/", blank=True, null=True)

    phone = models.CharField(max_length=20)

    email = models.EmailField(blank=True, null=True)

    address = models.TextField()

    currency = models.CharField(max_length=10, default="CDF")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:

        indexes = [
            models.Index(fields=["organization"]),
        ]

    def __str__(self):
        return self.name
    
    
class Member(models.Model):
    STATUS_CHOICES = (
        ("active", "Active"),
        ("expired", "Expired"),
        ("suspended", "Suspended"),
    )

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, db_index=True)
    objects = GymManager()
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="member_profile",
        null=True,
        blank=True
    )
    qr_code = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    qr_image = models.ImageField(upload_to="qrcodes/", blank=True, null=True)

    def generate_qr_code(self):

        qr_data = str(self.qr_code)

        qr = qrcode.make(qr_data)

        buffer = BytesIO()
        qr.save(buffer)

        filename = f"member_{self.id}.png"

        self.qr_image.save(filename, File(buffer), save=False)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    photo = models.ImageField(upload_to="members/", blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:

        indexes = [

            models.Index(fields=["gym"]),

            models.Index(fields=["gym", "status"]),

            models.Index(fields=["gym", "created_at"]),

        ]
        
    @property
    def active_subscription(self):
        return self.subscription_set.filter(
            is_active=True
        ).select_related("plan").first()
    @property
    def expiration_date(self):
        sub = self.active_subscription
        return sub.end_date if sub else None
    @property
    def subscription_type(self):
        sub = self.active_subscription
        return sub.plan.name if sub else "Aucun"
    @property
    def last_access(self):
        log = self.accesslog_set.order_by("-check_in_time").first()
        return log.check_in_time if log else None
    @property
    def computed_status(self):
        if self.status == "suspended":
            return "suspended"

        today = timezone.now().date()

        active_subscription = self.subscription_set.filter(
            end_date__gte=today,
            is_active=True
        ).exists()

        if active_subscription:
            return "active"

        return "expired"
    
    @property
    def days_remaining(self):

        if not self.expiration_date:
            return None

        return (self.expiration_date - timezone.now().date()).days
    
    def save(self, *args, **kwargs):

        if not self.qr_image:
            super().save(*args, **kwargs)
            self.generate_qr_code()

        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"{self.first_name} {self.last_name}"

class SubscriptionPlan(models.Model):
    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, db_index=True)
    name = models.CharField(max_length=100)
    duration_days = models.IntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Subscription(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    auto_renew = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-start_date"]
    

    def __str__(self):
        return f"{self.member} - {self.plan}"
    
    
class CashRegister(models.Model):

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        db_index=True
    )
    
    session_code = models.CharField(max_length=20, blank=True, null=True, unique=True)
    
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
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

    difference = models.DecimalField(
    max_digits=10,
    decimal_places=2,
    null=True,
    blank=True
)
    
    closing_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    opened_at = models.DateTimeField(auto_now_add=True)

    closed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    is_closed = models.BooleanField(default=False)
    
    def save(self, *args, **kwargs):

        is_new = self.pk is None

        super().save(*args, **kwargs)

        if is_new and not self.session_code:
            self.session_code = f"CS-{self.opened_at.year}-{self.id:04d}"
            super().save(update_fields=["session_code"])
            
    def total_entries(self):
        return Payment.objects.filter(
            cash_register=self,
            type="in",
            status="success"
        ).aggregate(total=Sum("amount"))["total"] or 0

    def total_exits(self):
        return Payment.objects.filter(
            cash_register=self,
            type="out",
            status="success"
        ).aggregate(total=Sum("amount"))["total"] or 0

    def expected_total(self):
        return self.total_entries() - self.total_exits()
    
    
    def __str__(self):
        return self.session_code
    

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
    cash_register = models.ForeignKey(
        CashRegister,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        db_index=True
    )

    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE, 
        null=True,
        blank=True
    )

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHODS
    )

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

    created_at = models.DateTimeField(auto_now_add=True)
    
    @staticmethod
    def calculate_cash_total(register):

        entries = Payment.objects.filter(
            cash_register=register,
            type="in",
            status="success"
        ).aggregate(total=Sum("amount"))["total"] or 0

        exits = Payment.objects.filter(
            cash_register=register,
            type="out",
            status="success"
        ).aggregate(total=Sum("amount"))["total"] or 0

        return entries - exits
    
    def __str__(self):
        return f"{self.member} - {self.amount}"

class AccessLog(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    check_in_time = models.DateTimeField(auto_now_add=True)
    access_granted = models.BooleanField(default=True)
    device_used = models.CharField(max_length=100, blank=True, null=True)
    
    
class Notification(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    message = models.TextField()
    sent_via = models.CharField(max_length=20, choices=(
        ("sms", "SMS"),
        ("whatsapp", "WhatsApp"),
        ("email", "Email"),
    ))
    sent_at = models.DateTimeField(auto_now_add=True)
    status = models.BooleanField(default=False)
    
    

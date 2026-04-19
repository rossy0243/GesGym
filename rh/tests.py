from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from compte.models import User, UserGymRole
from organizations.models import Gym, GymModule, Module, Organization
from pos.models import CashRegister, Payment

from .models import Attendance, Employee, PaymentRecord


class RhTenantTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Org A", slug="rh-org-a")
        self.org_b = Organization.objects.create(name="Org B", slug="rh-org-b")
        self.gym_a = Gym.objects.create(
            organization=self.org_a,
            name="Gym A",
            slug="rh-gym-a",
            subdomain="rh-gym-a",
        )
        self.gym_b = Gym.objects.create(
            organization=self.org_b,
            name="Gym B",
            slug="rh-gym-b",
            subdomain="rh-gym-b",
        )
        module, _ = Module.objects.get_or_create(code="RH", defaults={"name": "RH"})
        GymModule.objects.create(gym=self.gym_a, module=module, is_active=True)
        GymModule.objects.create(gym=self.gym_b, module=module, is_active=True)

        self.user = User.objects.create_user(username="rh-manager", password="test-pass")
        UserGymRole.objects.create(user=self.user, gym=self.gym_a, role="manager")
        self.register_a = CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=Decimal("0.00"),
            exchange_rate=Decimal("2800.00"),
        )

        self.employee_a = Employee.objects.create(
            gym=self.gym_a,
            name="Alice RH",
            role="manager",
            daily_salary=100,
        )
        self.employee_b = Employee.objects.create(
            gym=self.gym_b,
            name="Bob RH",
            role="cashier",
            daily_salary=999,
        )
        self.today = timezone.localdate()
        Attendance.objects.create(
            gym=self.gym_a,
            employee=self.employee_a,
            date=self.today,
            status="present",
        )
        Attendance.objects.create(
            gym=self.gym_b,
            employee=self.employee_b,
            date=self.today,
            status="present",
        )
        PaymentRecord.objects.create(
            gym=self.gym_b,
            employee=self.employee_b,
            year=self.today.year,
            month=self.today.month,
            amount=999,
            present_days=1,
        )
        self.client.login(username="rh-manager", password="test-pass")

    def test_employee_list_is_scoped_to_current_gym(self):
        response = self.client.get(reverse("rh:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice RH")
        self.assertNotContains(response, "Bob RH")
        self.assertContains(response, "Employes actifs")

    def test_other_gym_employee_detail_is_not_accessible(self):
        response = self.client.get(reverse("rh:detail", args=[self.employee_b.id]))

        self.assertEqual(response.status_code, 404)

    def test_attendance_list_is_scoped_to_current_gym(self):
        response = self.client.get(reverse("rh:attendance_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice RH")
        self.assertNotContains(response, "Bob RH")

    def test_payroll_dashboard_is_scoped_to_current_gym(self):
        response = self.client.get(reverse("rh:payroll_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice RH")
        self.assertNotContains(response, "Bob RH")
        self.assertNotContains(response, "999 CDF")

    def test_payment_cannot_target_other_gym_employee(self):
        response = self.client.get(
            reverse(
                "rh:process_payment",
                args=[self.employee_b.id, self.today.year, self.today.month],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_salary_payment_creates_pos_expense(self):
        response = self.client.post(
            reverse("rh:process_payment", args=[self.employee_a.id, self.today.year, self.today.month]),
            {"payment_method": "cash", "reference": "SAL-001", "notes": ""},
        )

        self.assertRedirects(response, reverse("rh:payroll_dashboard"))
        salary_payment = PaymentRecord.objects.get(
            gym=self.gym_a,
            employee=self.employee_a,
            year=self.today.year,
            month=self.today.month,
        )
        self.assertIsNotNone(salary_payment.pos_payment)
        self.assertEqual(salary_payment.amount, Decimal("100.00"))
        self.assertEqual(salary_payment.pos_payment.category, "salary")
        self.assertEqual(salary_payment.pos_payment.type, "out")
        self.assertEqual(salary_payment.pos_payment.amount_cdf, Decimal("100.00"))
        self.assertTrue(
            Payment.objects.filter(
                gym=self.gym_a,
                cash_register=self.register_a,
                category="salary",
                amount_cdf=Decimal("100.00"),
            ).exists()
        )

    def test_form_pages_render_without_gym_id_urls(self):
        urls = [
            reverse("rh:create"),
            reverse("rh:update", args=[self.employee_a.id]),
            reverse("rh:attendance_create"),
            reverse("rh:attendance_bulk"),
            reverse("rh:process_payment", args=[self.employee_a.id, self.today.year, self.today.month]),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_attendance_rejects_cross_gym_employee(self):
        with self.assertRaises(ValidationError):
            Attendance.objects.create(
                gym=self.gym_a,
                employee=self.employee_b,
                date=self.today + timedelta(days=1),
                status="present",
            )

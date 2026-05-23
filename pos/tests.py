from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from compte.models import User, UserGymRole
from members.models import Member
from organizations.models import Gym, GymModule, Module, Organization, SensitiveActivityLog
from products.models import Product, StockMovement
from subscriptions.models import MemberSubscription, SubscriptionPlan
from .models import CashRegister, ExchangeRate, Payment
from .services import record_product_sale, record_subscription_payment


class PosAccountingTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Org A", slug="org-a")
        self.org_b = Organization.objects.create(name="Org B", slug="org-b")
        self.gym_a = Gym.objects.create(
            organization=self.org_a,
            name="Gym A",
            slug="gym-a",
            subdomain="gym-a",
        )
        self.gym_b = Gym.objects.create(
            organization=self.org_b,
            name="Gym B",
            slug="gym-b",
            subdomain="gym-b",
        )
        self.member_a = Member.objects.create(
            gym=self.gym_a,
            first_name="Alice",
            last_name="Tenant",
            phone="10001",
            email="alice@example.com",
        )
        self.member_b = Member.objects.create(
            gym=self.gym_b,
            first_name="Bob",
            last_name="Tenant",
            phone="20001",
            email="bob@example.com",
        )
        self.plan_a = SubscriptionPlan.objects.create(
            gym=self.gym_a,
            name="Mensuel",
            duration_days=30,
            price=Decimal("25.00"),
        )
        self.cashier = User.objects.create_user(username="cashier-pos", password="test-pass")
        self.manager = User.objects.create_user(username="manager-pos", password="test-pass")
        UserGymRole.objects.create(user=self.cashier, gym=self.gym_a, role="cashier")
        UserGymRole.objects.create(user=self.manager, gym=self.gym_a, role="manager")
        module, _ = Module.objects.get_or_create(code="POS", defaults={"name": "POS"})
        GymModule.objects.get_or_create(gym=self.gym_a, module=module, defaults={"is_active": True})

    def test_cash_register_requires_exchange_rate_when_opening(self):
        with self.assertRaises(ValidationError):
            CashRegister.objects.create(
                gym=self.gym_a,
                opening_amount=Decimal("1000.00"),
            )

    def test_exchange_rate_is_saved_per_gym_and_day(self):
        ExchangeRate.objects.create(
            gym=self.gym_a,
            rate=Decimal("2800.00"),
            date=date(2026, 4, 17),
        )
        ExchangeRate.objects.create(
            gym=self.gym_b,
            rate=Decimal("2700.00"),
            date=date(2026, 4, 17),
        )

        self.assertEqual(
            ExchangeRate.objects.get(gym=self.gym_a, date=date(2026, 4, 17)).rate,
            Decimal("2800.00"),
        )

    def test_usd_payment_is_converted_to_cdf_with_register_rate(self):
        register = CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=Decimal("1000.00"),
            exchange_rate=Decimal("2800.00"),
        )

        payment = Payment.objects.create(
            gym=self.gym_a,
            cash_register=register,
            member=self.member_a,
            amount=Decimal("10.00"),
            currency="USD",
            method="cash",
            type="in",
            status="success",
        )
        payment.refresh_from_db()

        self.assertEqual(payment.exchange_rate, Decimal("2800.00"))
        self.assertEqual(payment.amount_usd, Decimal("10.00"))
        self.assertEqual(payment.amount_cdf, Decimal("28000.00"))

    def test_cdf_payment_clears_any_usd_reference(self):
        register = CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=Decimal("1000.00"),
            exchange_rate=Decimal("2800.00"),
        )

        payment = Payment.objects.create(
            gym=self.gym_a,
            cash_register=register,
            member=self.member_a,
            amount=Decimal("5000.00"),
            amount_usd=Decimal("10.00"),
            currency="CDF",
            method="cash",
            type="in",
            status="success",
        )
        payment.refresh_from_db()

        self.assertEqual(payment.amount_cdf, Decimal("5000.00"))
        self.assertIsNone(payment.amount_usd)

    def test_payment_requires_cash_register(self):
        with self.assertRaises(ValidationError):
            Payment.objects.create(
                gym=self.gym_a,
                amount=Decimal("5000.00"),
                currency="CDF",
                method="cash",
                type="in",
                status="success",
            )

    def test_product_sale_is_recorded_in_pos_and_updates_stock(self):
        CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=Decimal("0.00"),
            exchange_rate=Decimal("2800.00"),
        )
        product = Product.objects.create(
            gym=self.gym_a,
            name="Water",
            price=Decimal("2.50"),
            quantity=10,
        )

        payment = record_product_sale(
            gym=self.gym_a,
            product=product,
            quantity=3,
            currency="USD",
            method="cash",
        )

        product.refresh_from_db()
        self.assertEqual(product.quantity, 7)
        self.assertEqual(payment.category, "product")
        self.assertEqual(payment.type, "in")
        self.assertEqual(payment.amount_usd, Decimal("7.50"))
        self.assertEqual(payment.amount_cdf, Decimal("21000.00"))
        self.assertTrue(
            StockMovement.objects.filter(
                gym=self.gym_a,
                product=product,
                quantity=3,
                movement_type="out",
                reason="Vente POS",
            ).exists()
        )

    def test_subscription_payment_respects_start_date_and_auto_renew(self):
        CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=Decimal("0.00"),
            exchange_rate=Decimal("2800.00"),
        )
        start_date = date(2026, 4, 17)

        subscription, payment = record_subscription_payment(
            gym=self.gym_a,
            member=self.member_a,
            plan=self.plan_a,
            currency="USD",
            method="cash",
            start_date=start_date,
            auto_renew=True,
        )

        self.assertEqual(subscription.start_date, start_date)
        self.assertEqual(subscription.end_date, date(2026, 5, 17))
        self.assertTrue(subscription.auto_renew)
        self.assertEqual(payment.subscription_id, subscription.id)
        self.assertEqual(payment.category, "subscription")
        self.assertEqual(payment.amount_usd, Decimal("25.00"))
        self.assertEqual(payment.amount_cdf, Decimal("70000.00"))

    def test_subscription_payment_rejects_inactive_member(self):
        CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=Decimal("0.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.member_a.is_active = False
        self.member_a.save(update_fields=["is_active"])

        with self.assertRaises(ValidationError):
            record_subscription_payment(
                gym=self.gym_a,
                member=self.member_a,
                plan=self.plan_a,
                currency="USD",
                method="cash",
            )

    def test_cash_register_totals_use_cdf_accounting_amounts(self):
        register = CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=Decimal("1000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        Payment.objects.create(
            gym=self.gym_a,
            cash_register=register,
            amount=Decimal("10.00"),
            currency="USD",
            method="cash",
            type="in",
            status="success",
        )
        Payment.objects.create(
            gym=self.gym_a,
            cash_register=register,
            amount=Decimal("5000.00"),
            currency="CDF",
            exchange_rate=Decimal("2800.00"),
            method="cash",
            type="out",
            status="success",
            description="Achat papier",
        )

        self.assertEqual(register.total_entries(), Decimal("28000.00"))
        self.assertEqual(register.total_exits(), Decimal("5000.00"))
        self.assertEqual(register.expected_total(), Decimal("24000.00"))

    def test_payment_rejects_cross_gym_member(self):
        register = CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=Decimal("0.00"),
            exchange_rate=Decimal("2800.00"),
        )

        with self.assertRaises(ValidationError):
            Payment.objects.create(
                gym=self.gym_a,
                cash_register=register,
                member=self.member_b,
                amount=Decimal("10.00"),
                currency="USD",
                method="cash",
                type="in",
                status="success",
            )

    def test_cashier_dashboard_requires_active_module(self):
        self.client.login(username="cashier-pos", password="test-pass")
        GymModule.objects.filter(gym=self.gym_a, module__code="POS").update(is_active=False)

        response = self.client.get(reverse("pos:cashier_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_open_register_logs_sensitive_action(self):
        self.client.login(username="cashier-pos", password="test-pass")

        response = self.client.post(
            reverse("pos:open_register"),
            {"opening_amount": "100.00", "exchange_rate": "2800.00"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            SensitiveActivityLog.objects.filter(
                organization=self.org_a,
                action="pos.register_opened",
            ).exists()
        )

    def test_cashier_dashboard_labels_machine_maintenance_payments(self):
        register = CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=Decimal("0.00"),
            exchange_rate=Decimal("2800.00"),
        )
        Payment.objects.create(
            gym=self.gym_a,
            cash_register=register,
            amount=Decimal("15000.00"),
            currency="CDF",
            method="cash",
            type="out",
            category="maintenance",
            status="success",
            description="Maintenance machine: Tapis A",
        )
        self.client.login(username="cashier-pos", password="test-pass")

        response = self.client.get(reverse("pos:cashier_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Maintenance")
        self.assertContains(response, "Maintenance machine: Tapis A")
        self.assertContains(response, "Sortie liee au module machines")

    def test_register_detail_labels_machine_maintenance_payments(self):
        register = CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=Decimal("0.00"),
            exchange_rate=Decimal("2800.00"),
        )
        Payment.objects.create(
            gym=self.gym_a,
            cash_register=register,
            amount=Decimal("8000.00"),
            currency="CDF",
            method="cash",
            type="out",
            category="maintenance",
            status="success",
            description="Maintenance machine: Velo A",
        )
        self.client.login(username="manager-pos", password="test-pass")

        response = self.client.get(reverse("pos:register_detail", args=[register.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Maintenance")
        self.assertContains(response, "Maintenance machine: Velo A")

    def test_cashier_dashboard_labels_salary_payments(self):
        register = CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=Decimal("0.00"),
            exchange_rate=Decimal("2800.00"),
        )
        Payment.objects.create(
            gym=self.gym_a,
            cash_register=register,
            amount=Decimal("25000.00"),
            currency="CDF",
            method="cash",
            type="out",
            category="salary",
            status="success",
            description="Salaire Alice RH - 5/2026",
        )
        self.client.login(username="cashier-pos", password="test-pass")

        response = self.client.get(reverse("pos:cashier_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Salaire")
        self.assertContains(response, "Salaire Alice RH - 5/2026")
        self.assertContains(response, "Sortie liee au module RH")

    def test_register_detail_labels_salary_payments(self):
        register = CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=Decimal("0.00"),
            exchange_rate=Decimal("2800.00"),
        )
        Payment.objects.create(
            gym=self.gym_a,
            cash_register=register,
            amount=Decimal("18000.00"),
            currency="CDF",
            method="cash",
            type="out",
            category="salary",
            status="success",
            description="Salaire Bob RH - 5/2026",
        )
        self.client.login(username="manager-pos", password="test-pass")

        response = self.client.get(reverse("pos:register_detail", args=[register.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Salaire")
        self.assertContains(response, "Salaire Bob RH - 5/2026")

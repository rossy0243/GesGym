from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from members.models import Member
from organizations.models import Gym, Organization
from .models import CashRegister, ExchangeRate, Payment


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

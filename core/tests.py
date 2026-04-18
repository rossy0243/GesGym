from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

from django.test import TestCase
from django.urls import reverse

from compte.models import User
from members.models import Member
from organizations.models import Gym, Organization
from pos.models import CashRegister, Payment


class AccountingReportExportTests(TestCase):
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
        self.owner = User.objects.create_user(
            username="owner-a",
            password="pass",
            owned_organization=self.org_a,
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
        self.register_a = CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=Decimal("1000.00"),
            exchange_rate=Decimal("2800.00"),
            opened_by=self.owner,
        )
        self.register_b = CashRegister.objects.create(
            gym=self.gym_b,
            opening_amount=Decimal("1000.00"),
            exchange_rate=Decimal("2900.00"),
        )
        Payment.objects.create(
            gym=self.gym_a,
            cash_register=self.register_a,
            member=self.member_a,
            amount=Decimal("10.00"),
            currency="USD",
            method="cash",
            type="in",
            category="subscription",
            status="success",
            description="Abonnement Alice",
            created_by=self.owner,
        )
        Payment.objects.create(
            gym=self.gym_a,
            cash_register=self.register_a,
            amount=Decimal("5000.00"),
            currency="CDF",
            method="cash",
            type="out",
            category="expense",
            status="success",
            description="Achat fournitures",
            created_by=self.owner,
        )
        Payment.objects.create(
            gym=self.gym_b,
            cash_register=self.register_b,
            member=self.member_b,
            amount=Decimal("99.00"),
            currency="USD",
            method="cash",
            type="in",
            category="subscription",
            status="success",
            description="Other Tenant Subscription",
        )

        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()

    def test_csv_export_is_accounting_file_scoped_to_current_gym(self):
        response = self.client.get(
            reverse("core:rapport_export"),
            {"format": "csv", "period": "month"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        content = response.content.decode("utf-8")

        self.assertIn("Rapport comptable GesGym", content)
        self.assertIn("Compte debit", content)
        self.assertIn("5710 - Caisse", content)
        self.assertIn("7060 - Ventes abonnements", content)
        self.assertIn("6280 - Charges diverses", content)
        self.assertIn("Alice", content)
        self.assertIn("Achat fournitures", content)
        self.assertNotIn("Other Tenant Subscription", content)

    def test_xlsx_export_contains_expected_sheets_and_no_other_tenant_data(self):
        response = self.client.get(
            reverse("core:rapport_export"),
            {"format": "xlsx", "period": "month"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(response.content.startswith(b"PK"))

        with ZipFile(BytesIO(response.content)) as archive:
            names = archive.namelist()
            self.assertIn("xl/worksheets/sheet1.xml", names)
            self.assertIn("xl/worksheets/sheet2.xml", names)
            self.assertIn("xl/worksheets/sheet5.xml", names)
            journal = archive.read("xl/worksheets/sheet2.xml").decode("utf-8")

        self.assertIn("Abonnement Alice", journal)
        self.assertIn("Compte debit", journal)
        self.assertNotIn("Other Tenant Subscription", journal)

    def test_report_page_uses_selected_gym_and_shows_accounting_summary(self):
        response = self.client.get(reverse("core:rapport"), {"period": "month"})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Synthese du fichier comptable", content)
        self.assertIn("Alice", content)
        self.assertNotIn("Other Tenant Subscription", content)

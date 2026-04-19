from decimal import Decimal
from datetime import datetime, time
from io import BytesIO
from zipfile import ZipFile

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from access.models import AccessLog
from compte.models import User
from compte.models import UserGymRole
from coaching.forms import CoachForm
from coaching.models import CoachSpecialty
from members.models import Member
from organizations.models import Gym, Organization, SensitiveActivityLog
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

    def _create_access_log_at(self, gym, member, hour, granted=True):
        checked_at = timezone.make_aware(
            datetime.combine(timezone.localdate(), time(hour=hour, minute=15))
        )
        log = AccessLog.objects.create(
            gym=gym,
            member=member,
            access_granted=granted,
            device_used="Test",
            scanned_by=self.owner,
        )
        AccessLog.objects.filter(pk=log.pk).update(check_in_time=checked_at)
        return log

    def test_dashboard_displays_peak_hour_scoped_to_current_gym(self):
        for _ in range(3):
            self._create_access_log_at(self.gym_a, self.member_a, 18)
        self._create_access_log_at(self.gym_a, self.member_a, 9)
        self._create_access_log_at(self.gym_a, self.member_a, 19, granted=False)

        for _ in range(5):
            self._create_access_log_at(self.gym_b, self.member_b, 20)

        response = self.client.get(
            reverse("core:gym_dashboard", args=[self.gym_a.id]),
            {"period": "day"},
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Heure de pointe", content)
        self.assertIn("18h-19h", content)
        self.assertIn("3 passages autorises", content)
        self.assertNotIn("20h-21h", content)

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

    def test_custom_report_preview_uses_selected_types_and_columns(self):
        response = self.client.get(
            reverse("core:rapport"),
            {
                "section": "personnalise",
                "period": "month",
                "types": ["transactions"],
                "columns": ["date", "description", "amount_cdf"],
            },
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Apercu du rapport personnalise", content)
        self.assertIn("Abonnement Alice", content)
        self.assertIn("Achat fournitures", content)
        self.assertNotIn("Other Tenant Subscription", content)

    def test_custom_report_export_is_scoped_to_current_gym(self):
        response = self.client.get(
            reverse("core:rapport_export"),
            {
                "format": "csv",
                "section": "personnalise",
                "period": "month",
                "types": ["transactions"],
                "columns": ["date", "description", "amount_cdf"],
            },
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Rapport personnalise GesGym", content)
        self.assertIn("Abonnement Alice", content)
        self.assertIn("Achat fournitures", content)
        self.assertNotIn("Other Tenant Subscription", content)

    def test_settings_owner_can_create_internal_employee_for_selected_gym(self):
        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_create",
                "first_name": "Marc",
                "last_name": "Manager",
                "email": "marc@example.com",
                "gym": self.gym_a.id,
                "role": "manager",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        employee_role = UserGymRole.objects.get(user__email="marc@example.com", gym=self.gym_a)
        self.assertEqual(employee_role.role, "manager")
        self.assertTrue(employee_role.is_active)
        self.assertNotEqual(employee_role.role, "owner")
        self.assertTrue(
            SensitiveActivityLog.objects.filter(
                organization=self.org_a,
                action="employee.created",
                target_label__icontains="manager",
            ).exists()
        )

    def test_settings_dashboard_renders_v1_sections(self):
        response = self.client.get(reverse("core:settings"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Parametres V1", content)
        self.assertIn("Utilisateurs & roles", content)
        self.assertIn("Journal d'activite sensible", content)

    def test_settings_can_update_organization_and_log_activity(self):
        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "organization",
                "name": "Org A Updated",
                "address": "1 Avenue Test",
                "phone": "+243900000000",
                "email": "org@example.com",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.org_a.refresh_from_db()
        self.assertEqual(self.org_a.name, "Org A Updated")
        self.assertEqual(self.org_a.email, "org@example.com")
        self.assertTrue(
            SensitiveActivityLog.objects.filter(
                organization=self.org_a,
                action="organization.updated",
            ).exists()
        )

    def test_settings_create_coach_specialty_and_form_uses_it(self):
        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "specialty_create",
                "name": "Crossfit",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(CoachSpecialty.objects.filter(gym=self.gym_a, name="Crossfit").exists())
        form = CoachForm(gym=self.gym_a)
        self.assertIn(("Crossfit", "Crossfit"), form.fields["specialty"].choices)

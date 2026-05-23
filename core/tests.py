from decimal import Decimal
from datetime import date, datetime, time, timedelta
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from access.models import AccessLog
from coaching.kpis import build_coaching_kpis
from coaching.models import Coach, CoachingFeedback, CoachingFollowUp
from compte.models import User
from compte.models import UserGymRole
from coaching.forms import CoachForm
from coaching.models import CoachSpecialty
from compte.forms import CreateUserForm
from members.models import Member
from machines.kpis import build_machine_kpis
from machines.models import Machine, MaintenanceLog
from products.kpis import build_product_kpis
from products.models import Product, StockMovement
from rh.kpis import build_rh_kpis
from rh.models import Attendance, Employee, PaymentRecord, PayrollContributionRule, PayrollSlip
from subscriptions.models import MemberSubscription, SubscriptionPlan
from .forms import InternalEmployeeForm
from .accounting_reports import (
    CUSTOM_COLUMNS,
    CUSTOM_DATA_TYPES,
    build_accounting_report,
    build_custom_report,
    get_report_period,
)
from .views import _get_period_window
from organizations.models import Gym, GymModule, Module, Organization, SensitiveActivityLog
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

        self.employee_a = Employee.objects.create(
            gym=self.gym_a,
            name="Alice RH",
            role="manager",
            daily_salary=Decimal("100.00"),
        )
        Attendance.objects.create(
            gym=self.gym_a,
            employee=self.employee_a,
            date=timezone.localdate(),
            status="present",
        )
        PayrollContributionRule.objects.create(
            gym=self.gym_a,
            name="IPR",
            party=PayrollContributionRule.PARTY_EMPLOYEE_TAX,
            calculation_type=PayrollContributionRule.CALC_PERCENTAGE,
            rate_percent=Decimal("10.00"),
        )
        PayrollContributionRule.objects.create(
            gym=self.gym_a,
            name="INSS Employeur",
            party=PayrollContributionRule.PARTY_EMPLOYER_CONTRIBUTION,
            calculation_type=PayrollContributionRule.CALC_PERCENTAGE,
            rate_percent=Decimal("5.00"),
        )
        self.payroll_slip = PayrollSlip.ensure_for_period(
            self.employee_a,
            timezone.localdate().year,
            timezone.localdate().month,
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

    def test_journalier_report_defaults_to_today_period(self):
        response = self.client.get(reverse("core:rapport"), {"section": "journalier"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_period"], "today")

    def test_journalier_export_defaults_to_today_period(self):
        today_payment = Payment.objects.create(
            gym=self.gym_a,
            cash_register=self.register_a,
            member=self.member_a,
            amount=Decimal("8.00"),
            currency="USD",
            method="cash",
            type="in",
            category="subscription",
            status="success",
            description="Paiement du jour",
            created_by=self.owner,
        )
        old_payment = Payment.objects.create(
            gym=self.gym_a,
            cash_register=self.register_a,
            member=self.member_a,
            amount=Decimal("9.00"),
            currency="USD",
            method="cash",
            type="in",
            category="subscription",
            status="success",
            description="Paiement ancien",
            created_by=self.owner,
        )
        Payment.objects.filter(pk=today_payment.pk).update(created_at=timezone.now())
        Payment.objects.filter(pk=old_payment.pk).update(created_at=timezone.now() - timedelta(days=12))

        response = self.client.get(
            reverse("core:rapport_export"),
            {"section": "journalier", "format": "csv"},
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Paiement du jour", content)
        self.assertNotIn("Paiement ancien", content)

    def test_mensuel_report_defaults_to_month_period(self):
        response = self.client.get(reverse("core:rapport"), {"section": "mensuel"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_period"], "month")

    def test_mensuel_export_defaults_to_month_period(self):
        period_payment = Payment.objects.create(
            gym=self.gym_a,
            cash_register=self.register_a,
            member=self.member_a,
            amount=Decimal("11.00"),
            currency="USD",
            method="cash",
            type="in",
            category="subscription",
            status="success",
            description="Paiement du mois",
            created_by=self.owner,
        )
        old_payment = Payment.objects.create(
            gym=self.gym_a,
            cash_register=self.register_a,
            member=self.member_a,
            amount=Decimal("7.00"),
            currency="USD",
            method="cash",
            type="in",
            category="subscription",
            status="success",
            description="Paiement ancien mensuel",
            created_by=self.owner,
        )
        Payment.objects.filter(pk=period_payment.pk).update(created_at=timezone.now())
        Payment.objects.filter(pk=old_payment.pk).update(created_at=timezone.now() - timedelta(days=45))

        response = self.client.get(
            reverse("core:rapport_export"),
            {"section": "mensuel", "format": "csv"},
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Paiement du mois", content)
        self.assertNotIn("Paiement ancien mensuel", content)

    def test_custom_subscription_rows_only_sum_pos_payments_inside_period(self):
        today = timezone.localdate()
        plan = SubscriptionPlan.objects.create(
            gym=self.gym_a,
            name="Mensuel rapport",
            duration_days=30,
            price=Decimal("30.00"),
        )
        subscription = MemberSubscription.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            plan=plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )
        in_period_payment = Payment.objects.create(
            gym=self.gym_a,
            cash_register=self.register_a,
            member=self.member_a,
            subscription=subscription,
            amount=Decimal("10.00"),
            currency="USD",
            method="cash",
            type="in",
            category="subscription",
            status="success",
            description="Paiement dans la periode",
            created_by=self.owner,
        )
        Payment.objects.filter(pk=in_period_payment.pk).update(created_at=timezone.now())
        old_payment = Payment.objects.create(
            gym=self.gym_a,
            cash_register=self.register_a,
            member=self.member_a,
            subscription=subscription,
            amount=Decimal("12.00"),
            currency="USD",
            method="cash",
            type="in",
            category="subscription",
            status="success",
            description="Paiement hors periode",
            created_by=self.owner,
        )
        Payment.objects.filter(pk=old_payment.pk).update(created_at=timezone.now() - timedelta(days=90))
        period_data = get_report_period({"period": "month"}, today=today)
        params = QueryDict("", mutable=True)
        params.setlist("types", ["subscriptions"])
        params.setlist("columns", list(CUSTOM_COLUMNS.keys()))
        params["grouping"] = "none"

        report = build_custom_report(self.gym_a, params, period_data)

        subscription_row = next(row for row in report["rows"] if row["reference"] == f"SUB-{subscription.id:06d}")
        self.assertEqual(subscription_row["amount_cdf"], Decimal("28000.00"))

    def test_custom_transaction_rows_use_real_status_and_keep_entry_type_in_description(self):
        today = timezone.localdate()
        period_data = get_report_period({"period": "month"}, today=today)
        params = QueryDict("", mutable=True)
        params.setlist("types", ["transactions"])
        params.setlist("columns", list(CUSTOM_COLUMNS.keys()))
        params["grouping"] = "none"

        report = build_custom_report(self.gym_a, params, period_data)

        row = next(row for row in report["rows"] if row["reference"].startswith("POS-"))
        self.assertEqual(row["status"], "Success")
        self.assertIn("Entrée", row["description"])

    def test_custom_register_rows_include_opening_and_theoretical_balance(self):
        today = timezone.localdate()
        period_data = get_report_period({"period": "month"}, today=today)
        params = QueryDict("", mutable=True)
        params.setlist("types", ["registers"])
        params.setlist("columns", list(CUSTOM_COLUMNS.keys()))
        params["grouping"] = "none"

        report = build_custom_report(self.gym_a, params, period_data)

        row = next(row for row in report["rows"] if row["reference"] == self.register_a.session_code)
        self.assertIn("Ouverture", row["description"])
        self.assertIn("Solde theorique", row["description"])
        self.assertEqual(row["amount_cdf"], Decimal("24000.00"))

    def test_dashboard_excludes_future_subscriptions_from_active_metrics(self):
        today = timezone.localdate()
        self.member_a.status = "active"
        self.member_a.save(update_fields=["status"])
        current_plan = SubscriptionPlan.objects.create(
            gym=self.gym_a,
            name="Pack courant",
            duration_days=30,
            price=Decimal("15.00"),
        )
        MemberSubscription.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            plan=current_plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )
        future_member = Member.objects.create(
            gym=self.gym_a,
            first_name="Future",
            last_name="Dashboard",
            phone="10009",
            email="future.dashboard@example.com",
            status="active",
        )
        future_plan = SubscriptionPlan.objects.create(
            gym=self.gym_a,
            name="Pack futur",
            duration_days=30,
            price=Decimal("20.00"),
        )
        MemberSubscription.objects.create(
            gym=self.gym_a,
            member=future_member,
            plan=future_plan,
            start_date=today + timedelta(days=4),
            end_date=today + timedelta(days=34),
            is_active=True,
        )

        response = self.client.get(reverse("core:gym_dashboard", args=[self.gym_a.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_members"], 1)
        self.assertEqual(response.context["total_subscriptions"], 1)

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

    def test_report_page_displays_rh_payroll_summary_with_contributions(self):
        response = self.client.get(reverse("core:rapport"), {"period": "month"})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Synthese RH", content)
        self.assertIn("Alice RH", content)
        self.assertIn("Retenues salarie", content)
        self.assertIn("Cotis. employeur", content)

    def test_custom_report_preview_supports_payroll_dataset(self):
        response = self.client.get(
            reverse("core:rapport"),
            {
                "section": "personnalise",
                "period": "month",
                "types": ["payroll"],
                "columns": ["date", "client", "description", "amount_cdf", "status"],
            },
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Alice RH", content)
        self.assertIn("Cotis employeur", content)

    def test_custom_report_preview_displays_grouping_label_and_period_scoped_payroll_summary(self):
        response = self.client.get(
            reverse("core:rapport"),
            {
                "section": "personnalise",
                "period": "custom",
                "date_from": timezone.localdate().replace(day=1).isoformat(),
                "date_to": timezone.localdate().isoformat(),
                "types": ["transactions"],
                "columns": ["date", "description"],
                "grouping": "day",
            },
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Regroupement : Par jour", content)
        self.assertIn(f"Synthese RH - Du 01/{timezone.localdate():%m/%Y} au {timezone.localdate():%d/%m/%Y}", content)

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

    def test_custom_report_xlsx_export_contains_expected_sheet_and_scoped_data(self):
        response = self.client.get(
            reverse("core:rapport_export"),
            {
                "format": "xlsx",
                "section": "personnalise",
                "period": "month",
                "types": ["transactions"],
                "columns": ["date", "description", "amount_cdf"],
            },
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
            sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")

        self.assertIn("Rapport personnalise GesGym", sheet)
        self.assertIn("Abonnement Alice", sheet)
        self.assertNotIn("Other Tenant Subscription", sheet)

    def test_report_exports_use_period_based_filename(self):
        response = self.client.get(
            reverse("core:rapport_export"),
            {
                "format": "csv",
                "section": "journalier",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn("rapport-comptable-gym-a-", response["Content-Disposition"])
        self.assertTrue(response["Content-Disposition"].endswith(".csv\""))

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
        self.assertIn("Paramètres", content)
        self.assertIn("Gerer l'organisation", content)
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


class RoleAccessMatrixTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Matrix Org", slug="matrix-org")
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Matrix Gym",
            slug="matrix-gym",
            subdomain="matrix-gym",
        )
        self.other_gym = Gym.objects.create(
            organization=self.organization,
            name="Other Gym",
            slug="other-gym",
            subdomain="other-gym",
        )
        for code in ["POS", "ACCESS", "MEMBERS", "RH", "CORE"]:
            module, _ = Module.objects.get_or_create(code=code, defaults={"name": code})
            GymModule.objects.get_or_create(gym=self.gym, module=module, defaults={"is_active": True})

        self.manager = User.objects.create_user(username="matrix-manager", password="pass")
        UserGymRole.objects.create(user=self.manager, gym=self.gym, role="manager")
        self.reception = User.objects.create_user(username="matrix-reception", password="pass")
        UserGymRole.objects.create(user=self.reception, gym=self.gym, role="reception")
        self.cashier = User.objects.create_user(username="matrix-cashier", password="pass")
        UserGymRole.objects.create(user=self.cashier, gym=self.gym, role="cashier")

    def test_cashier_home_redirects_to_pos_not_dashboard(self):
        self.client.force_login(self.cashier)

        response = self.client.get(reverse("core:dashboard_redirect"))

        self.assertRedirects(
            response,
            reverse("pos:cashier_dashboard"),
            fetch_redirect_response=False,
        )

    def test_cashier_cannot_open_dashboard_or_transaction_journal(self):
        self.client.force_login(self.cashier)

        dashboard_response = self.client.get(reverse("core:gym_dashboard", args=[self.gym.id]))
        journal_response = self.client.get(reverse("pos:register_history"))
        pos_response = self.client.get(reverse("pos:cashier_dashboard"))

        self.assertEqual(dashboard_response.status_code, 403)
        self.assertEqual(journal_response.status_code, 403)
        self.assertEqual(pos_response.status_code, 200)

    def test_reception_can_control_access_but_cannot_open_reports(self):
        self.client.force_login(self.reception)

        access_response = self.client.get(reverse("access:acces_dashboard"))
        report_response = self.client.get(reverse("core:rapport"))

        self.assertEqual(access_response.status_code, 200)
        self.assertEqual(report_response.status_code, 403)

    def test_cashier_navigation_only_exposes_cashier_scope(self):
        self.client.force_login(self.cashier)

        response = self.client.get(reverse("pos:cashier_dashboard"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Caisse & paiements", content)
        self.assertIn('href="/pos/"', content)
        self.assertNotIn('href="/members/"', content)
        self.assertNotIn(
            f'href="{reverse("core:gym_dashboard", args=[self.gym.id])}?view=analytics"',
            content,
        )
        self.assertNotIn('href="/rapport/?section=journalier"', content)
        self.assertNotIn('href="/parametres/?tab=employees"', content)
        self.assertNotIn('href="/access/access-dashboard/?section=scan"', content)

    def test_reception_navigation_exposes_access_and_operational_tools_only(self):
        self.client.force_login(self.reception)

        response = self.client.get(reverse("access:acces_dashboard"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Membres", content)
        self.assertIn('href="/members/"', content)
        self.assertIn("Caisse & paiements", content)
        self.assertIn('href="/access/access-dashboard/?section=scan"', content)
        self.assertIn('href="/pos/"', content)
        self.assertNotIn(
            f'href="{reverse("core:gym_dashboard", args=[self.gym.id])}?view=analytics"',
            content,
        )
        self.assertNotIn('href="/rapport/?section=journalier"', content)
        self.assertNotIn('href="/parametres/?tab=employees"', content)
        self.assertNotIn('href="/pos/register-history/"', content)

    def test_manager_navigation_exposes_dashboard_reports_and_settings(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("core:gym_dashboard", args=[self.gym.id]))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn(
            f'href="{reverse("core:gym_dashboard", args=[self.gym.id])}?view=analytics"',
            content,
        )
        self.assertIn('href="/rapport/?section=journalier"', content)
        self.assertIn('href="/parametres/?tab=employees"', content)
        self.assertIn('href="/pos/register-history/"', content)

    def test_manager_settings_excludes_organization_management(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("core:settings"), {"tab": "organization"})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Utilisateurs & roles", content)
        self.assertNotIn("Gerer l'organisation", content)

    def test_manager_cannot_create_employee_for_another_gym(self):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_create",
                "first_name": "Bad",
                "last_name": "Scope",
                "email": "bad-scope@example.com",
                "gym": self.other_gym.id,
                "role": "cashier",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserGymRole.objects.filter(user__email="bad-scope@example.com").exists())

    def test_manager_cannot_reset_password_for_shared_user_identity(self):
        shared_user = User.objects.create_user(
            username="shared-employee",
            password="InitialPass123!",
            email="shared-employee@example.com",
        )
        current_role = UserGymRole.objects.create(user=shared_user, gym=self.gym, role="cashier")
        UserGymRole.objects.create(user=shared_user, gym=self.other_gym, role="cashier")
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_reset_password",
                "role_id": current_role.id,
            },
        )

        self.assertRedirects(response, reverse("core:settings"), fetch_redirect_response=False)
        shared_user.refresh_from_db()
        self.assertFalse(shared_user.force_password_change)
        self.assertTrue(shared_user.check_password("InitialPass123!"))

    def test_manager_deactivation_only_disables_current_role_for_shared_user_identity(self):
        shared_user = User.objects.create_user(
            username="shared-access",
            password="SharedAccess123!",
            email="shared-access@example.com",
        )
        current_role = UserGymRole.objects.create(user=shared_user, gym=self.gym, role="cashier")
        other_role = UserGymRole.objects.create(user=shared_user, gym=self.other_gym, role="cashier")
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_deactivate",
                "role_id": current_role.id,
            },
        )

        self.assertRedirects(response, reverse("core:settings"), fetch_redirect_response=False)
        current_role.refresh_from_db()
        other_role.refresh_from_db()
        shared_user.refresh_from_db()
        self.assertFalse(current_role.is_active)
        self.assertTrue(other_role.is_active)
        self.assertTrue(shared_user.is_active)

    def test_non_owner_cannot_open_dashboard_for_other_gym_than_request_context(self):
        UserGymRole.objects.create(user=self.manager, gym=self.other_gym, role="manager")
        self.client.force_login(self.manager)

        response = self.client.get(reverse("core:gym_dashboard", args=[self.other_gym.id]))

        self.assertEqual(response.status_code, 403)


class RoleChoiceCleanupTests(TestCase):
    def test_internal_employee_form_excludes_accountant_role(self):
        form = InternalEmployeeForm()

        role_values = [value for value, _label in form.fields["role"].choices]

        self.assertNotIn("accountant", role_values)
        self.assertNotIn("owner", role_values)

    def test_owner_create_user_form_excludes_accountant_role(self):
        form = CreateUserForm()

        role_values = [value for value, _label in form.fields["role"].choices]

        self.assertNotIn("accountant", role_values)


class AccountingReportCoverageMatrixTests(TestCase):
    """
    Suite de couverture quasi exhaustive pour les rapports:
    - matrice des periodes
    - dataset canonique stable
    - rapports personnalises parametres par type/colonne/regroupement
    - expected outputs stables sur le builder comptable
    - invariants automatiques de scoping et de totalisation
    """

    reference_date = date(2026, 5, 21)

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name="Org Canonique", slug="org-canonique")
        cls.org_b = Organization.objects.create(name="Org Externe", slug="org-externe")
        cls.gym_a = Gym.objects.create(
            organization=cls.org_a,
            name="Gym Canonique",
            slug="gym-canonique",
            subdomain="gym-canonique",
        )
        cls.gym_b = Gym.objects.create(
            organization=cls.org_b,
            name="Gym Externe",
            slug="gym-externe",
            subdomain="gym-externe",
        )
        cls.owner = User.objects.create_user(
            username="owner-canonique",
            password="pass",
            owned_organization=cls.org_a,
            first_name="Olivia",
            last_name="Owner",
        )

        cls.member_a1 = Member.objects.create(
            gym=cls.gym_a,
            first_name="Alice",
            last_name="Canon",
            phone="10001",
            email="alice.canon@example.com",
        )
        cls.member_a2 = Member.objects.create(
            gym=cls.gym_a,
            first_name="Brice",
            last_name="Canon",
            phone="10002",
            email="brice.canon@example.com",
        )
        cls.member_b1 = Member.objects.create(
            gym=cls.gym_b,
            first_name="Bob",
            last_name="Externe",
            phone="20001",
            email="bob.externe@example.com",
        )

        cls._set_member_created_at(cls.member_a1, datetime(2026, 5, 20, 7, 30))
        cls._set_member_created_at(cls.member_a2, datetime(2026, 5, 21, 12, 0))
        cls._set_member_created_at(cls.member_b1, datetime(2026, 5, 21, 10, 0))

        cls.plan_a = SubscriptionPlan.objects.create(
            gym=cls.gym_a,
            name="Mensuel Premium",
            duration_days=30,
            price=Decimal("10.00"),
        )
        cls.plan_b = SubscriptionPlan.objects.create(
            gym=cls.gym_b,
            name="Mensuel Externe",
            duration_days=30,
            price=Decimal("99.00"),
        )

        cls.subscription_a = MemberSubscription.objects.create(
            gym=cls.gym_a,
            member=cls.member_a1,
            plan=cls.plan_a,
            start_date=date(2026, 5, 20),
            end_date=date(2026, 6, 19),
            is_active=True,
        )
        cls.subscription_b = MemberSubscription.objects.create(
            gym=cls.gym_b,
            member=cls.member_b1,
            plan=cls.plan_b,
            start_date=date(2026, 5, 20),
            end_date=date(2026, 6, 19),
            is_active=True,
        )

        cls.register_a = CashRegister.objects.create(
            gym=cls.gym_a,
            opening_amount=Decimal("1000.00"),
            exchange_rate=Decimal("2800.00"),
            opened_by=cls.owner,
        )
        cls.register_b = CashRegister.objects.create(
            gym=cls.gym_b,
            opening_amount=Decimal("1000.00"),
            exchange_rate=Decimal("2900.00"),
        )
        cls._set_register_opened_at(cls.register_a, datetime(2026, 5, 20, 8, 0))
        cls._set_register_opened_at(cls.register_b, datetime(2026, 5, 20, 8, 0))

        cls.payment_subscription = cls._create_payment_at(
            gym=cls.gym_a,
            register=cls.register_a,
            created_at=datetime(2026, 5, 20, 9, 15),
            amount=Decimal("10.00"),
            currency="USD",
            method="cash",
            payment_type="in",
            category="subscription",
            description="Abonnement Alice",
            member=cls.member_a1,
            subscription=cls.subscription_a,
            transaction_id="TX-SUB-001",
            created_by=cls.owner,
        )
        cls.payment_product = cls._create_payment_at(
            gym=cls.gym_a,
            register=cls.register_a,
            created_at=datetime(2026, 5, 21, 11, 45),
            amount=Decimal("9000.00"),
            currency="CDF",
            method="mobile_money",
            payment_type="in",
            category="product",
            description="Boisson isotonique",
            member=cls.member_a2,
            source_app="products",
            source_model="Product",
            source_id=17,
            created_by=cls.owner,
        )
        cls.payment_salary = cls._create_payment_at(
            gym=cls.gym_a,
            register=cls.register_a,
            created_at=datetime(2026, 5, 21, 17, 30),
            amount=Decimal("7000.00"),
            currency="CDF",
            method="card",
            payment_type="out",
            category="salary",
            description="Prime coach",
            transaction_id="TX-SAL-001",
            created_by=cls.owner,
        )
        cls.payment_other_income = cls._create_payment_at(
            gym=cls.gym_a,
            register=cls.register_a,
            created_at=datetime(2026, 1, 15, 8, 0),
            amount=Decimal("5600.00"),
            currency="CDF",
            method="bank_transfer",
            payment_type="in",
            category="other",
            description="Location salle",
            transaction_id="TX-OTH-001",
            created_by=cls.owner,
        )
        cls._create_payment_at(
            gym=cls.gym_b,
            register=cls.register_b,
            created_at=datetime(2026, 5, 21, 13, 0),
            amount=Decimal("99.00"),
            currency="USD",
            method="cash",
            payment_type="in",
            category="subscription",
            description="Other Tenant Subscription",
            member=cls.member_b1,
            subscription=cls.subscription_b,
        )

        cls._create_access_log_at(
            gym=cls.gym_a,
            member=cls.member_a1,
            checked_at=datetime(2026, 5, 20, 18, 15),
            granted=True,
        )
        cls._create_access_log_at(
            gym=cls.gym_a,
            member=cls.member_a2,
            checked_at=datetime(2026, 5, 21, 7, 40),
            granted=False,
        )
        cls._create_access_log_at(
            gym=cls.gym_b,
            member=cls.member_b1,
            checked_at=datetime(2026, 5, 21, 20, 10),
            granted=True,
        )

        cls.coverage_matrix = {
            "periods": ["today", "yesterday", "week", "month", "year", "custom"],
            "custom_types": list(CUSTOM_DATA_TYPES.keys()),
            "custom_columns": list(CUSTOM_COLUMNS.keys()),
            "groupings": ["none", "day", "week", "month", "type"],
            "exports": ["csv", "xlsx"],
            "invariants": [
                "tenant_scope",
                "entries_minus_exits_equals_net",
                "journal_sums_match_header_totals",
                "custom_headers_follow_requested_columns",
                "grouped_counts_preserve_base_row_count",
            ],
        }

    @classmethod
    def _aware(cls, naive_dt):
        return timezone.make_aware(naive_dt, timezone.get_current_timezone())

    @classmethod
    def _set_member_created_at(cls, member, naive_dt):
        aware_dt = cls._aware(naive_dt)
        Member.objects.filter(pk=member.pk).update(created_at=aware_dt)
        member.refresh_from_db()

    @classmethod
    def _set_register_opened_at(cls, register, naive_dt):
        aware_dt = cls._aware(naive_dt)
        CashRegister.objects.filter(pk=register.pk).update(opened_at=aware_dt)
        register.refresh_from_db()

    @classmethod
    def _create_payment_at(
        cls,
        *,
        gym,
        register,
        created_at,
        amount,
        currency,
        method,
        payment_type,
        category,
        description,
        member=None,
        subscription=None,
        transaction_id=None,
        source_app="",
        source_model="",
        source_id=None,
        created_by=None,
    ):
        payment = Payment.objects.create(
            gym=gym,
            cash_register=register,
            member=member,
            subscription=subscription,
            amount=amount,
            currency=currency,
            method=method,
            type=payment_type,
            category=category,
            status="success",
            description=description,
            transaction_id=transaction_id,
            source_app=source_app,
            source_model=source_model,
            source_id=source_id,
            created_by=created_by,
        )
        Payment.objects.filter(pk=payment.pk).update(created_at=cls._aware(created_at))
        return Payment.objects.get(pk=payment.pk)

    @classmethod
    def _create_access_log_at(cls, *, gym, member, checked_at, granted):
        log = AccessLog.objects.create(
            gym=gym,
            member=member,
            access_granted=granted,
            device_used="Scanner test",
            scanned_by=cls.owner,
            denial_reason="" if granted else "Carte expirée",
        )
        AccessLog.objects.filter(pk=log.pk).update(check_in_time=cls._aware(checked_at))
        return AccessLog.objects.get(pk=log.pk)

    def _period(self, key, **extra_params):
        params = {"period": key}
        params.update(extra_params)
        return get_report_period(params, today=self.reference_date, default_period=key)

    def _querydict(self, **params):
        query = QueryDict("", mutable=True)
        for key, value in params.items():
            if isinstance(value, (list, tuple)):
                query.setlist(key, [str(item) for item in value])
            else:
                query[key] = str(value)
        return query

    def test_coverage_matrix_documents_supported_axes(self):
        self.assertEqual(
            self.coverage_matrix["periods"],
            ["today", "yesterday", "week", "month", "year", "custom"],
        )
        self.assertEqual(self.coverage_matrix["custom_types"], list(CUSTOM_DATA_TYPES.keys()))
        self.assertEqual(self.coverage_matrix["custom_columns"], list(CUSTOM_COLUMNS.keys()))
        self.assertEqual(self.coverage_matrix["groupings"], ["none", "day", "week", "month", "type"])

    def test_report_period_matrix_returns_expected_windows(self):
        expectations = {
            "today": (date(2026, 5, 21), date(2026, 5, 21), "today"),
            "yesterday": (date(2026, 5, 20), date(2026, 5, 20), "yesterday"),
            "week": (date(2026, 5, 18), date(2026, 5, 24), "week"),
            "month": (date(2026, 5, 1), date(2026, 5, 21), "month"),
            "year": (date(2026, 1, 1), date(2026, 12, 31), "year"),
        }
        for period_key, (expected_start, expected_end, expected_key) in expectations.items():
            with self.subTest(period=period_key):
                period_data = self._period(period_key)
                self.assertEqual(period_data["key"], expected_key)
                self.assertEqual(period_data["start_date"], expected_start)
                self.assertEqual(period_data["end_date"], expected_end)

        custom_period = self._period("custom", date_from="2026-05-21", date_to="2026-05-19")
        self.assertEqual(custom_period["key"], "custom")
        self.assertEqual(custom_period["start_date"], date(2026, 5, 19))
        self.assertEqual(custom_period["end_date"], date(2026, 5, 21))

    def test_accounting_report_expected_outputs_are_stable_for_month(self):
        report = build_accounting_report(self.gym_a, self._period("month"))

        self.assertEqual(report["organization"], "Org Canonique")
        self.assertEqual(report["gym"], "Gym Canonique")
        self.assertEqual(report["transaction_count"], 3)
        self.assertEqual(report["register_count"], 1)
        self.assertEqual(report["total_entries_cdf"], Decimal("37000.00"))
        self.assertEqual(report["total_exits_cdf"], Decimal("7000.00"))
        self.assertEqual(report["net_total_cdf"], Decimal("30000.00"))
        self.assertEqual(report["total_usd_reference"], Decimal("10.00"))
        self.assertEqual(
            [row["description"] for row in report["journal_rows"]],
            ["Abonnement Alice", "Boisson isotonique", "Prime coach"],
        )
        self.assertEqual(
            [row["debit_account"] for row in report["journal_rows"]],
            ["5710 - Caisse", "5125 - Mobile money", "6410 - Salaires"],
        )
        self.assertEqual(
            [row["credit_account"] for row in report["journal_rows"]],
            ["7060 - Ventes abonnements", "7070 - Ventes produits", "5120 - Banque"],
        )

    def test_accounting_report_invariants_hold_for_every_supported_period(self):
        periods = {
            "today": self._period("today"),
            "yesterday": self._period("yesterday"),
            "week": self._period("week"),
            "month": self._period("month"),
            "year": self._period("year"),
            "custom": self._period("custom", date_from="2026-05-20", date_to="2026-05-21"),
        }
        for period_key, period_data in periods.items():
            with self.subTest(period=period_key):
                report = build_accounting_report(self.gym_a, period_data)
                journal_rows = report["journal_rows"]
                entries = sum(
                    row["amount_cdf"] for row in journal_rows if row["type"] == "Entrée"
                )
                exits = sum(
                    row["amount_cdf"] for row in journal_rows if row["type"] == "Sortie"
                )
                flat_values = " ".join(
                    str(value)
                    for row in journal_rows
                    for value in row.values()
                    if value not in (None, "")
                )

                self.assertNotIn("Gym Externe", flat_values)
                self.assertNotIn("Org Externe", flat_values)
                self.assertNotIn("Other Tenant Subscription", flat_values)
                self.assertEqual(entries, report["total_entries_cdf"])
                self.assertEqual(exits, report["total_exits_cdf"])
                self.assertEqual(entries - exits, report["net_total_cdf"])
                self.assertEqual(len(journal_rows), report["transaction_count"])
                self.assertEqual(len(report["register_rows"]), report["register_count"])

    def test_custom_report_type_matrix_returns_expected_dataset_only(self):
        expected_dataset_labels = {
            "transactions": "Transaction POS",
            "members": "Membre",
            "access": "Acces",
            "subscriptions": "Abonnement",
            "registers": "Session de caisse",
        }
        period_data = self._period("month")
        for data_type, expected_label in expected_dataset_labels.items():
            with self.subTest(data_type=data_type):
                report = build_custom_report(
                    self.gym_a,
                    self._querydict(types=[data_type], columns=["dataset", "description", "reference"]),
                    period_data,
                )
                self.assertGreater(report["total_count"], 0)
                self.assertEqual(report["selected_types"], [data_type])
                self.assertTrue(all(row["dataset"] == expected_label for row in report["rows"]))
                flat_values = " ".join(
                    str(value)
                    for row in report["rows"]
                    for value in row.values()
                    if value not in (None, "")
                )
                self.assertNotIn("Other Tenant Subscription", flat_values)
                self.assertNotIn("Bob Externe", flat_values)

    def test_custom_report_column_matrix_preserves_requested_order(self):
        period_data = self._period("month")
        for column_key, expected_label in CUSTOM_COLUMNS.items():
            with self.subTest(column=column_key):
                report = build_custom_report(
                    self.gym_a,
                    self._querydict(types=["transactions"], columns=[column_key]),
                    period_data,
                )
                self.assertEqual([header["key"] for header in report["headers"]], [column_key])
                self.assertEqual([header["label"] for header in report["headers"]], [expected_label])
                self.assertTrue(all(len(row["cells"]) == 1 for row in report["rows"]))

    def test_custom_report_grouping_matrix_preserves_base_row_count(self):
        period_data = self._period("month")
        base_report = build_custom_report(
            self.gym_a,
            self._querydict(
                types=list(CUSTOM_DATA_TYPES.keys()),
                columns=["date", "dataset", "amount_cdf", "status"],
                grouping="none",
            ),
            period_data,
        )
        base_count = base_report["total_count"]

        for grouping in ["day", "week", "month", "type"]:
            with self.subTest(grouping=grouping):
                grouped_report = build_custom_report(
                    self.gym_a,
                    self._querydict(
                        types=list(CUSTOM_DATA_TYPES.keys()),
                        columns=["date", "dataset", "amount_cdf", "status"],
                        grouping=grouping,
                    ),
                    period_data,
                )
                grouped_count = sum(int(row["status"].split()[0]) for row in grouped_report["rows"])
                self.assertEqual(grouped_count, base_count)
                self.assertLessEqual(grouped_report["total_count"], base_count)
                self.assertTrue(all(row["dataset"] == "Regroupement" for row in grouped_report["rows"]))


class DashboardKpiCoverageMatrixTests(TestCase):
    reference_date = date(2026, 5, 21)

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name="Org KPI", slug="org-kpi")
        cls.org_b = Organization.objects.create(name="Org KPI B", slug="org-kpi-b")
        cls.gym_a = Gym.objects.create(
            organization=cls.org_a,
            name="Gym KPI A",
            slug="gym-kpi-a",
            subdomain="gym-kpi-a",
        )
        cls.gym_b = Gym.objects.create(
            organization=cls.org_b,
            name="Gym KPI B",
            slug="gym-kpi-b",
            subdomain="gym-kpi-b",
        )
        for code in ["MACHINES", "RH", "PRODUCTS", "COACHING", "CORE"]:
            module, _ = Module.objects.get_or_create(code=code, defaults={"name": code})
            GymModule.objects.create(gym=cls.gym_a, module=module, is_active=True)
            GymModule.objects.create(gym=cls.gym_b, module=module, is_active=True)

        cls.owner = User.objects.create_user(
            username="owner-kpi",
            password="pass",
            owned_organization=cls.org_a,
        )

        cls.member_a1 = Member.objects.create(
            gym=cls.gym_a,
            first_name="Alice",
            last_name="KPI",
            phone="30001",
            email="alice.kpi@example.com",
            is_active=True,
        )
        cls.member_a2 = Member.objects.create(
            gym=cls.gym_a,
            first_name="Brice",
            last_name="KPI",
            phone="30002",
            email="brice.kpi@example.com",
            is_active=True,
        )
        cls.member_a3 = Member.objects.create(
            gym=cls.gym_a,
            first_name="Cleo",
            last_name="KPI",
            phone="30003",
            email="cleo.kpi@example.com",
            is_active=True,
        )
        cls.member_b1 = Member.objects.create(
            gym=cls.gym_b,
            first_name="Bob",
            last_name="Leak",
            phone="40001",
            email="bob.leak@example.com",
            is_active=True,
        )
        cls._set_member_created_at(cls.member_a1, datetime(2026, 5, 20, 9, 0))
        cls._set_member_created_at(cls.member_a2, datetime(2026, 5, 21, 10, 0))
        cls._set_member_created_at(cls.member_a3, datetime(2026, 1, 10, 10, 0))
        cls._set_member_created_at(cls.member_b1, datetime(2026, 5, 21, 11, 0))

        cls.register_a = CashRegister.objects.create(
            gym=cls.gym_a,
            opening_amount=Decimal("1000.00"),
            exchange_rate=Decimal("2800.00"),
            opened_by=cls.owner,
        )
        cls.register_b = CashRegister.objects.create(
            gym=cls.gym_b,
            opening_amount=Decimal("1000.00"),
            exchange_rate=Decimal("2900.00"),
        )

        cls.machine_ok = Machine.objects.create(gym=cls.gym_a, name="Tapis A", status="ok")
        cls.machine_maintenance = Machine.objects.create(
            gym=cls.gym_a, name="Velo A", status="maintenance"
        )
        cls.machine_broken = Machine.objects.create(gym=cls.gym_a, name="Presse A", status="broken")
        cls.machine_b = Machine.objects.create(gym=cls.gym_b, name="Leak Machine", status="ok")
        cls._create_maintenance_at(
            machine=cls.machine_maintenance,
            description="Courroie",
            cost=Decimal("75.00"),
            created_at=datetime(2026, 5, 20, 9, 0),
        )
        cls._create_maintenance_at(
            machine=cls.machine_broken,
            description="Moteur",
            cost=Decimal("25.00"),
            created_at=datetime(2026, 1, 12, 9, 0),
        )
        cls._create_maintenance_at(
            machine=cls.machine_b,
            description="Leak maintenance",
            cost=Decimal("999.00"),
            created_at=datetime(2026, 5, 21, 9, 0),
        )

        cls.product_ok = Product.objects.create(
            gym=cls.gym_a, name="Whey", price=Decimal("10.00"), quantity=8, is_active=True
        )
        cls.product_low = Product.objects.create(
            gym=cls.gym_a, name="Barre", price=Decimal("5.00"), quantity=3, is_active=True
        )
        cls.product_out = Product.objects.create(
            gym=cls.gym_a, name="Shaker", price=Decimal("7.00"), quantity=0, is_active=True
        )
        cls.product_inactive = Product.objects.create(
            gym=cls.gym_a, name="Ancien", price=Decimal("20.00"), quantity=2, is_active=False
        )
        cls.product_b = Product.objects.create(
            gym=cls.gym_b, name="Leak Product", price=Decimal("999.00"), quantity=1, is_active=True
        )
        cls._create_stock_movement_at(
            gym=cls.gym_a,
            product=cls.product_ok,
            quantity=5,
            movement_type="in",
            reason="Reassort",
            created_at=datetime(2026, 5, 20, 8, 0),
        )
        cls._create_stock_movement_at(
            gym=cls.gym_a,
            product=cls.product_low,
            quantity=2,
            movement_type="out",
            reason="Vente",
            created_at=datetime(2026, 5, 21, 8, 0),
        )
        cls._create_stock_movement_at(
            gym=cls.gym_a,
            product=cls.product_ok,
            quantity=1,
            movement_type="out",
            reason="Vente",
            created_at=datetime(2026, 1, 15, 8, 0),
        )
        cls._create_stock_movement_at(
            gym=cls.gym_b,
            product=cls.product_b,
            quantity=99,
            movement_type="out",
            reason="Leak",
            created_at=datetime(2026, 5, 21, 8, 0),
        )

        cls.employee_active = Employee.objects.create(
            gym=cls.gym_a, name="Alice Staff", role="manager", daily_salary=Decimal("100.00"), is_active=True
        )
        cls.employee_inactive = Employee.objects.create(
            gym=cls.gym_a, name="Brice Staff", role="cashier", daily_salary=Decimal("80.00"), is_active=False
        )
        cls.employee_b = Employee.objects.create(
            gym=cls.gym_b, name="Leak Staff", role="cashier", daily_salary=Decimal("999.00"), is_active=True
        )
        Attendance.objects.create(
            gym=cls.gym_a, employee=cls.employee_active, date=cls.reference_date, status="present"
        )
        Attendance.objects.create(
            gym=cls.gym_a, employee=cls.employee_inactive, date=cls.reference_date, status="absent"
        )
        Attendance.objects.create(
            gym=cls.gym_a, employee=cls.employee_active, date=date(2026, 5, 20), status="present"
        )
        Attendance.objects.create(
            gym=cls.gym_b, employee=cls.employee_b, date=cls.reference_date, status="present"
        )
        cls.salary_payment = cls._create_payment_at(
            gym=cls.gym_a,
            register=cls.register_a,
            created_at=datetime(2026, 5, 20, 18, 0),
            amount=Decimal("100.00"),
            currency="CDF",
            method="cash",
            payment_type="out",
            category="salary",
            description="Salaire Alice",
            created_by=cls.owner,
        )
        cls.salary_record = cls._create_payment_record(
            gym=cls.gym_a,
            employee=cls.employee_active,
            year=2026,
            month=5,
            amount=Decimal("100.00"),
            present_days=1,
            payment_date=date(2026, 5, 20),
            pos_payment=cls.salary_payment,
            is_paid=True,
        )
        cls._create_payment_record(
            gym=cls.gym_b,
            employee=cls.employee_b,
            year=2026,
            month=5,
            amount=Decimal("999.00"),
            present_days=1,
            payment_date=date(2026, 5, 21),
            is_paid=True,
        )

        cls.coach_active = Coach.objects.create(
            gym=cls.gym_a, name="Coach A", phone="111", specialty="Cardio", is_active=True
        )
        cls.coach_inactive = Coach.objects.create(
            gym=cls.gym_a, name="Coach B", phone="112", specialty="Force", is_active=False
        )
        cls.coach_b = Coach.objects.create(
            gym=cls.gym_b, name="Leak Coach", phone="999", specialty="Leak", is_active=True
        )
        cls.coach_active.members.add(cls.member_a1, cls.member_a2)
        cls.coach_b.members.add(cls.member_b1)
        cls._set_active_assignment_started_at(cls.coach_active, cls.member_a1, datetime(2026, 5, 1, 9, 0))
        cls._set_active_assignment_started_at(cls.coach_active, cls.member_a2, datetime(2026, 5, 18, 9, 0))
        cls.follow_up_old = CoachingFollowUp.objects.create(
            gym=cls.gym_a,
            coach=cls.coach_active,
            member=cls.member_a1,
            interaction_type=CoachingFollowUp.INTERACTION_FOLLOW_UP,
            summary="Relance",
            next_action="Rappeler",
            next_follow_up_at=date(2026, 5, 20),
        )
        cls._set_follow_up_created_at(cls.follow_up_old, datetime(2026, 5, 5, 10, 0))
        cls.feedback_low = CoachingFeedback.objects.create(
            gym=cls.gym_a,
            member=cls.member_a1,
            coach=cls.coach_active,
            overall_rating=2,
            listening_rating=2,
            clarity_rating=2,
            motivation_rating=2,
            availability_rating=2,
            comment="Fragile",
            wants_contact=True,
        )
        cls._set_feedback_created_at(cls.feedback_low, datetime(2026, 5, 20, 12, 0))
        cls.feedback_good = CoachingFeedback.objects.create(
            gym=cls.gym_a,
            member=cls.member_a2,
            coach=cls.coach_active,
            overall_rating=4,
            listening_rating=4,
            clarity_rating=4,
            motivation_rating=4,
            availability_rating=4,
            comment="Solide",
            wants_contact=False,
        )
        cls._set_feedback_created_at(cls.feedback_good, datetime(2026, 5, 21, 12, 0))
        feedback_b = CoachingFeedback.objects.create(
            gym=cls.gym_b,
            member=cls.member_b1,
            coach=cls.coach_b,
            overall_rating=1,
            listening_rating=1,
            clarity_rating=1,
            motivation_rating=1,
            availability_rating=1,
            comment="Leak",
            wants_contact=True,
        )
        cls._set_feedback_created_at(feedback_b, datetime(2026, 5, 21, 12, 0))

        cls.coverage_matrix = {
            "periods": ["day", "week", "month", "year"],
            "modules": ["machines", "rh", "products", "coaching"],
            "surfaces": ["builder", "dashboard"],
            "invariants": [
                "tenant_scope",
                "counts_non_negative",
                "chart_totals_match_counts",
                "ratios_in_range",
                "dashboard_context_matches_builders",
            ],
        }

    @classmethod
    def _aware(cls, naive_dt):
        return timezone.make_aware(naive_dt, timezone.get_current_timezone())

    @classmethod
    def _set_member_created_at(cls, member, naive_dt):
        Member.objects.filter(pk=member.pk).update(created_at=cls._aware(naive_dt))
        member.refresh_from_db()

    @classmethod
    def _create_maintenance_at(cls, *, machine, description, cost, created_at):
        log = MaintenanceLog.objects.create(machine=machine, description=description, cost=cost)
        MaintenanceLog.objects.filter(pk=log.pk).update(created_at=cls._aware(created_at))
        return MaintenanceLog.objects.get(pk=log.pk)

    @classmethod
    def _create_stock_movement_at(cls, *, gym, product, quantity, movement_type, reason, created_at):
        movement = StockMovement.objects.create(
            gym=gym,
            product=product,
            quantity=quantity,
            movement_type=movement_type,
            reason=reason,
        )
        StockMovement.objects.filter(pk=movement.pk).update(created_at=cls._aware(created_at))
        return StockMovement.objects.get(pk=movement.pk)

    @classmethod
    def _create_payment_at(
        cls,
        *,
        gym,
        register,
        created_at,
        amount,
        currency,
        method,
        payment_type,
        category,
        description,
        created_by=None,
    ):
        payment = Payment.objects.create(
            gym=gym,
            cash_register=register,
            amount=amount,
            currency=currency,
            method=method,
            type=payment_type,
            category=category,
            status="success",
            description=description,
            created_by=created_by,
        )
        Payment.objects.filter(pk=payment.pk).update(created_at=cls._aware(created_at))
        return Payment.objects.get(pk=payment.pk)

    @classmethod
    def _create_payment_record(
        cls,
        *,
        gym,
        employee,
        year,
        month,
        amount,
        present_days,
        payment_date,
        pos_payment=None,
        is_paid=True,
    ):
        record = PaymentRecord.objects.create(
            gym=gym,
            employee=employee,
            year=year,
            month=month,
            amount=amount,
            present_days=present_days,
            payment_method="cash",
            reference="PAY",
            is_paid=is_paid,
            pos_payment=pos_payment,
        )
        PaymentRecord.objects.filter(pk=record.pk).update(payment_date=payment_date)
        return PaymentRecord.objects.get(pk=record.pk)

    @classmethod
    def _set_active_assignment_started_at(cls, coach, member, naive_dt):
        assignment = coach.assignments.get(member=member, ended_at__isnull=True)
        assignment.started_at = cls._aware(naive_dt)
        assignment.save(update_fields=["started_at"])
        return assignment

    @classmethod
    def _set_follow_up_created_at(cls, follow_up, naive_dt):
        CoachingFollowUp.objects.filter(pk=follow_up.pk).update(created_at=cls._aware(naive_dt))
        follow_up.refresh_from_db()

    @classmethod
    def _set_feedback_created_at(cls, feedback, naive_dt):
        CoachingFeedback.objects.filter(pk=feedback.pk).update(created_at=cls._aware(naive_dt))
        feedback.refresh_from_db()

    def setUp(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()

    def _patch_kpi_today(self):
        return patch.multiple(
            "rh.kpis.timezone",
            localdate=lambda: self.reference_date,
        )

    def test_kpi_coverage_matrix_documents_supported_axes(self):
        self.assertEqual(self.coverage_matrix["periods"], ["day", "week", "month", "year"])
        self.assertEqual(self.coverage_matrix["modules"], ["machines", "rh", "products", "coaching"])
        self.assertEqual(self.coverage_matrix["surfaces"], ["builder", "dashboard"])

    def test_machine_kpis_expected_outputs_are_stable(self):
        kpis = build_machine_kpis(self.gym_a, _get_period_window("month", self.reference_date))
        self.assertEqual(kpis["total_machines"], 3)
        self.assertEqual(kpis["machines_ok"], 1)
        self.assertEqual(kpis["machines_maintenance"], 1)
        self.assertEqual(kpis["machines_broken"], 1)
        self.assertEqual(kpis["availability_rate"], 33.3)
        self.assertEqual(kpis["attention_count"], 2)
        self.assertEqual(kpis["total_maintenances"], 2)
        self.assertEqual(kpis["period_maintenances"], 1)
        self.assertEqual(kpis["total_maintenance_cost"], Decimal("100.00"))
        self.assertEqual(kpis["period_maintenance_cost"], Decimal("75.00"))
        self.assertEqual(kpis["top_costly_machine"], "Velo A")

    def test_product_kpis_expected_outputs_are_stable(self):
        kpis = build_product_kpis(self.gym_a, _get_period_window("month", self.reference_date))
        self.assertEqual(kpis["total_products"], 3)
        self.assertEqual(kpis["all_products_count"], 4)
        self.assertEqual(kpis["inactive_products"], 1)
        self.assertEqual(kpis["stock_ok_count"], 1)
        self.assertEqual(kpis["low_stock_count"], 1)
        self.assertEqual(kpis["out_of_stock_count"], 1)
        self.assertEqual(kpis["stock_value_total"], Decimal("95.00"))
        self.assertEqual(kpis["stock_movements_period"], 2)
        self.assertEqual(kpis["stock_in_period"], 5)
        self.assertEqual(kpis["stock_out_period"], 2)
        self.assertEqual(kpis["stock_status_chart_values"], [1, 1, 1])
        self.assertEqual(kpis["stock_value_chart_labels"][0], "Whey")

    def test_rh_kpis_expected_outputs_are_stable(self):
        with patch("rh.kpis.timezone.localdate", return_value=self.reference_date):
            kpis = build_rh_kpis(self.gym_a, _get_period_window("month", self.reference_date))
        self.assertEqual(kpis["total_employees"], 2)
        self.assertEqual(kpis["active_employees"], 1)
        self.assertEqual(kpis["inactive_employees"], 1)
        self.assertEqual(kpis["attendance_today_present"], 1)
        self.assertEqual(kpis["attendance_today_absent"], 1)
        self.assertEqual(kpis["attendance_today_rate"], 50.0)
        self.assertEqual(kpis["attendance_period_present"], 2)
        self.assertEqual(kpis["attendance_period_absent"], 1)
        self.assertEqual(kpis["attendance_period_rate"], 66.7)
        self.assertEqual(kpis["monthly_payroll_gross"], Decimal("200.00"))
        self.assertEqual(kpis["monthly_payroll"], Decimal("200.00"))
        self.assertEqual(kpis["monthly_payroll_paid"], Decimal("200.00"))
        self.assertEqual(kpis["monthly_payroll_pending"], Decimal("0"))
        self.assertEqual(kpis["salary_paid_period"], Decimal("100.00"))

    def test_coaching_kpis_expected_outputs_are_stable(self):
        with patch("coaching.kpis.timezone.localdate", return_value=self.reference_date):
            kpis = build_coaching_kpis(self.gym_a, _get_period_window("month", self.reference_date))
        self.assertEqual(kpis["total_coaches"], 2)
        self.assertEqual(kpis["active_coaches"], 1)
        self.assertEqual(kpis["inactive_coaches"], 1)
        self.assertEqual(kpis["assigned_members_count"], 2)
        self.assertEqual(kpis["unassigned_members_count"], 1)
        self.assertEqual(kpis["members_without_follow_up_count"], 1)
        self.assertEqual(kpis["first_contact_overdue_count"], 1)
        self.assertEqual(kpis["stale_follow_up_members_count"], 1)
        self.assertEqual(kpis["overdue_follow_ups_count"], 1)
        self.assertEqual(kpis["recent_follow_ups_count"], 1)
        self.assertEqual(kpis["feedback_average"], 3.0)
        self.assertEqual(kpis["feedback_count"], 2)
        self.assertEqual(kpis["contact_requested_count"], 1)
        self.assertEqual(kpis["low_feedback_count"], 1)
        self.assertEqual(kpis["sensitive_feedback_count"], 1)
        self.assertEqual(kpis["average_members_per_coach"], Decimal("2.0"))
        self.assertEqual(kpis["coaching_status_chart_values"], [1, 1])
        self.assertEqual(kpis["coaching_workload_chart_values"], [2])

    def test_kpi_builders_preserve_scope_and_invariants_for_all_periods(self):
        for period in ["day", "week", "month", "year"]:
            period_data = _get_period_window(period, self.reference_date)
            with self.subTest(period=period, module="machines"):
                machine_kpis = build_machine_kpis(self.gym_a, period_data)
                self.assertEqual(
                    machine_kpis["machines_ok"] + machine_kpis["machines_maintenance"] + machine_kpis["machines_broken"],
                    machine_kpis["total_machines"],
                )
                self.assertLessEqual(machine_kpis["period_maintenance_cost"], machine_kpis["total_maintenance_cost"])
                self.assertNotEqual(machine_kpis["top_costly_machine"], "Leak Machine")
            with self.subTest(period=period, module="products"):
                product_kpis = build_product_kpis(self.gym_a, period_data)
                self.assertEqual(sum(product_kpis["stock_status_chart_values"]), product_kpis["total_products"])
                self.assertGreaterEqual(product_kpis["stock_value_total"], Decimal("0"))
                self.assertFalse(any(product.name == "Leak Product" for product in product_kpis["top_value_products"]))
            with self.subTest(period=period, module="rh"):
                with patch("rh.kpis.timezone.localdate", return_value=self.reference_date):
                    rh_kpis = build_rh_kpis(self.gym_a, period_data)
                self.assertGreaterEqual(rh_kpis["attendance_today_rate"], 0)
                self.assertLessEqual(rh_kpis["attendance_today_rate"], 100)
                self.assertGreaterEqual(rh_kpis["attendance_period_rate"], 0)
                self.assertLessEqual(rh_kpis["attendance_period_rate"], 100)
                self.assertEqual(
                    rh_kpis["active_employees"] + rh_kpis["inactive_employees"],
                    rh_kpis["total_employees"],
                )
            with self.subTest(period=period, module="coaching"):
                with patch("coaching.kpis.timezone.localdate", return_value=self.reference_date):
                    coaching_kpis = build_coaching_kpis(self.gym_a, period_data)
                self.assertEqual(sum(coaching_kpis["coaching_status_chart_values"]), coaching_kpis["total_coaches"])
                self.assertGreaterEqual(coaching_kpis["assigned_members_count"], 0)
                self.assertFalse(any(coach.name == "Leak Coach" for coach in coaching_kpis["top_coaches"]))

    def test_dashboard_context_matches_kpi_builders_for_every_period(self):
        for period in ["day", "week", "month", "year"]:
            period_data = _get_period_window(period, self.reference_date)
            with self.subTest(period=period):
                with patch("core.views.now", return_value=self._aware(datetime(2026, 5, 21, 12, 0))), \
                    patch("rh.kpis.timezone.localdate", return_value=self.reference_date), \
                    patch("coaching.kpis.timezone.localdate", return_value=self.reference_date):
                    response = self.client.get(
                        reverse("core:gym_dashboard", args=[self.gym_a.id]),
                        {"period": period},
                    )
                self.assertEqual(response.status_code, 200)
                machine_kpis = build_machine_kpis(self.gym_a, period_data)
                product_kpis = build_product_kpis(self.gym_a, period_data)
                with patch("rh.kpis.timezone.localdate", return_value=self.reference_date):
                    rh_kpis = build_rh_kpis(self.gym_a, period_data)
                with patch("coaching.kpis.timezone.localdate", return_value=self.reference_date):
                    coaching_kpis = build_coaching_kpis(self.gym_a, period_data)

                self.assertEqual(response.context["availability_rate"], machine_kpis["availability_rate"])
                self.assertEqual(response.context["monthly_maintenance_cost"], machine_kpis["monthly_maintenance_cost"])
                self.assertEqual(response.context["active_employees"], rh_kpis["active_employees"])
                self.assertEqual(response.context["attendance_period_rate"], rh_kpis["attendance_period_rate"])
                self.assertEqual(response.context["stock_value_total"], product_kpis["stock_value_total"])
                self.assertEqual(response.context["stock_status_chart_values"], product_kpis["stock_status_chart_values"])
                self.assertEqual(response.context["active_coaches"], coaching_kpis["active_coaches"])
                self.assertEqual(response.context["coaching_workload_chart_values"], coaching_kpis["coaching_workload_chart_values"])

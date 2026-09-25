import uuid
import json
import re
from decimal import Decimal
from datetime import date, datetime, time, timedelta
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch
from unittest.mock import patch
from zipfile import ZipFile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.http import QueryDict
from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from access.models import AccessDevice, AccessLog
from coaching.kpis import build_coaching_kpis
from coaching.models import Coach, CoachingFeedback, CoachingFollowUp, GroupCoachingProgram
from compte.models import User
from compte.models import UserGymRole
from core import marketing_qr
from core.templatetags.formats import montant, montant_signe
from core.log_filtering import doit_journaliser
from core.forms import INTERNAL_ROLE_CHOICES, InternalEmployeeForm
from members.models import GuestPass, Member, MemberPreRegistration, MemberPreRegistrationLink
from organizations.models import LandingFaq
from smartclub.access_control import (
    DASHBOARD_ROLES,
    EMPLOYEE_ROLES_BY_MANAGER,
    EMPLOYEE_ROLES_BY_OWNER,
    DASHBOARD_SALES_ROLES,
    MACHINE_ROLES,
    MEMBER_DELETE_ROLES,
    MEMBER_ROLES,
    POS_CASHIER_ROLES,
    POS_HISTORY_ROLES,
    REPORT_ROLES,
    RH_PAYROLL_ROLES,
    SETTINGS_ORGANIZATION_ROLES,
)
from coaching.forms import CoachForm
from coaching.models import CoachSpecialty
from compte.forms import CreateUserForm
from core.forms import OrganizationSettingsForm
from members.models import Member, MemberGoal, MemberPreRegistration, MemberWeightMeasurement
from machines.kpis import build_machine_kpis
from machines.models import Machine, MaintenanceLog
from products.kpis import build_product_kpis
from products.models import Product, StockMovement
from rh.kpis import build_rh_kpis
from notifications.models import Notification
from rh.models import (
    Attendance,
    Employee,
    LeaveRequest,
    OvertimeEntry,
    PaymentRecord,
    PayrollAdjustment,
    PayrollContributionRule,
    PayrollSlip,
    PayrollWorkflowLog,
)
from subscriptions.models import (
    MemberSubscription,
    SubscriptionOffer,
    SubscriptionPlan,
    SubscriptionRequest,
)
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
from pos import validation
from pos.services import (
    record_cash_injection,
    record_expense,
    record_expense_refund,
    record_payment,
)
from pos.models import CashRegister, ExchangeRate, Payment


class SeedDemoDataSafetyTests(TestCase):
    @override_settings(DEBUG=False)
    def test_seed_demo_data_refuses_to_run_in_production_without_opt_in(self):
        call_command("seed_demo_data")

        self.assertFalse(Organization.objects.filter(slug__startswith="demo-").exists())

    @override_settings(DEBUG=True)
    def test_seed_demo_data_creates_complete_module_kpi_dataset(self):
        out = StringIO()
        call_command("seed_demo_data", "--reset", stdout=out)

        self.assertIn("Base de demonstration prete", out.getvalue())
        expected_modules = {
            "ACCESS",
            "COACHING",
            "COMPTE",
            "CORE",
            "MACHINES",
            "MEMBERS",
            "NOTIFICATIONS",
            "POS",
            "PRODUCTS",
            "RH",
            "SUBSCRIPTIONS",
            "WEBSITE",
        }
        gyms = Gym.objects.filter(organization__slug__startswith="demo-").order_by("slug")
        self.assertEqual(gyms.count(), 3)

        for gym in gyms:
            with self.subTest(gym=gym.slug):
                active_module_codes = set(
                    GymModule.objects.filter(gym=gym, is_active=True).values_list("module__code", flat=True)
                )
                self.assertTrue(expected_modules.issubset(active_module_codes))

                self.assertTrue(gym.members.filter(status="active").exists())
                self.assertTrue(gym.members.filter(status="suspended").exists())
                self.assertGreaterEqual(MemberSubscription.objects.filter(gym=gym).count(), gym.members.count())
                self.assertTrue(SubscriptionOffer.objects.filter(gym=gym, grants_individual_coaching=True).exists())
                self.assertTrue(SubscriptionOffer.objects.filter(gym=gym, grants_group_coaching=True).exists())
                self.assertEqual(
                    set(SubscriptionRequest.objects.filter(gym=gym).values_list("status", flat=True)),
                    {
                        SubscriptionRequest.STATUS_PENDING,
                        SubscriptionRequest.STATUS_AWAITING_PAYMENT,
                        SubscriptionRequest.STATUS_PAID,
                        SubscriptionRequest.STATUS_CANCELLED,
                        SubscriptionRequest.STATUS_FAILED,
                    },
                )

                self.assertTrue(CashRegister.objects.filter(gym=gym, is_closed=False).exists())
                self.assertTrue(CashRegister.objects.filter(gym=gym, is_closed=True).exists())
                self.assertTrue(ExchangeRate.objects.filter(gym=gym).exists())
                self.assertTrue(Payment.objects.filter(gym=gym, status="success", type="in").exists())
                self.assertTrue(Payment.objects.filter(gym=gym, status="success", type="out").exists())
                self.assertTrue(Payment.objects.filter(gym=gym, status="pending").exists())
                self.assertTrue(Payment.objects.filter(gym=gym, status="failed").exists())
                self.assertTrue(Payment.objects.filter(gym=gym, category="subscription").exists())
                self.assertTrue(Payment.objects.filter(gym=gym, category="product").exists())
                self.assertTrue(Payment.objects.filter(gym=gym, category="maintenance").exists())
                self.assertTrue(Payment.objects.filter(gym=gym, category="salary").exists())

                self.assertTrue(AccessLog.objects.filter(gym=gym, access_granted=True).exists())
                self.assertTrue(AccessLog.objects.filter(gym=gym, access_granted=False).exists())
                self.assertTrue(Product.objects.filter(gym=gym, is_active=True, quantity__gt=3).exists())
                self.assertTrue(Product.objects.filter(gym=gym, is_active=True, quantity__lte=3, quantity__gt=0).exists())
                self.assertTrue(Product.objects.filter(gym=gym, is_active=True, quantity=0).exists())
                self.assertTrue(Product.objects.filter(gym=gym, is_active=False).exists())
                self.assertTrue(StockMovement.objects.filter(gym=gym, movement_type="in").exists())
                self.assertTrue(StockMovement.objects.filter(gym=gym, movement_type="out").exists())

                self.assertTrue(Machine.objects.filter(gym=gym, status="ok").exists())
                self.assertTrue(Machine.objects.filter(gym=gym, status="maintenance").exists())
                self.assertTrue(Machine.objects.filter(gym=gym, status="broken").exists())
                self.assertTrue(MaintenanceLog.objects.filter(machine__gym=gym).exists())

                self.assertTrue(Coach.objects.filter(gym=gym, is_active=True).exists())
                self.assertTrue(GroupCoachingProgram.objects.filter(gym=gym, participants__isnull=False).distinct().exists())
                self.assertTrue(CoachingFollowUp.objects.filter(gym=gym).exists())
                self.assertTrue(CoachingFeedback.objects.filter(gym=gym, wants_contact=True).exists())
                self.assertTrue(MemberGoal.objects.filter(gym=gym, status=MemberGoal.STATUS_ACTIVE).exists())
                self.assertTrue(MemberGoal.objects.filter(gym=gym, status=MemberGoal.STATUS_ACHIEVED).exists())
                self.assertTrue(MemberGoal.objects.filter(gym=gym, status=MemberGoal.STATUS_CANCELLED).exists())
                self.assertTrue(MemberWeightMeasurement.objects.filter(gym=gym).exists())

                self.assertTrue(Employee.objects.filter(gym=gym, compensation_type=Employee.COMPENSATION_DAILY).exists())
                self.assertTrue(Employee.objects.filter(gym=gym, compensation_type=Employee.COMPENSATION_MONTHLY).exists())
                self.assertTrue(Attendance.objects.filter(gym=gym, status="present").exists())
                self.assertTrue(Attendance.objects.filter(gym=gym, status="absent").exists())
                self.assertTrue(LeaveRequest.objects.filter(gym=gym).exists())
                self.assertTrue(OvertimeEntry.objects.filter(gym=gym).exists())
                self.assertTrue(PayrollAdjustment.objects.filter(gym=gym).exists())
                self.assertTrue(PayrollContributionRule.objects.filter(gym=gym).exists())
                self.assertTrue(PaymentRecord.objects.filter(gym=gym, is_paid=True).exists())
                self.assertTrue(PayrollSlip.objects.filter(gym=gym, status=PayrollSlip.STATUS_PAID).exists())
                self.assertTrue(PayrollWorkflowLog.objects.filter(slip__gym=gym).exists())

                self.assertEqual(
                    set(Notification.objects.filter(gym=gym).values_list("status", flat=True)),
                    {Notification.STATUS_PENDING, Notification.STATUS_SENT, Notification.STATUS_FAILED},
                )
                self.assertTrue(Notification.objects.filter(gym=gym, read_at__isnull=False).exists())
                self.assertTrue(MemberPreRegistration.objects.filter(gym=gym, status=MemberPreRegistration.STATUS_PENDING).exists())
                self.assertTrue(MemberPreRegistration.objects.filter(gym=gym, status=MemberPreRegistration.STATUS_CONFIRMED).exists())
                self.assertTrue(MemberPreRegistration.objects.filter(gym=gym, status=MemberPreRegistration.STATUS_CANCELLED).exists())

                dashboard_period = _get_period_window("month", timezone.localdate())
                self.assertGreaterEqual(build_machine_kpis(gym, dashboard_period)["total_machines"], 3)
                self.assertGreaterEqual(build_product_kpis(gym, dashboard_period)["total_products"], 3)
                self.assertGreaterEqual(build_coaching_kpis(gym, dashboard_period)["assigned_members_count"], 1)
                self.assertGreaterEqual(build_rh_kpis(gym, dashboard_period)["total_employees"], 3)

                accounting_report = build_accounting_report(
                    gym,
                    get_report_period({"period": "month"}, today=timezone.localdate()),
                )
                self.assertGreater(accounting_report["transaction_count"], 0)
                self.assertGreater(accounting_report["total_entries_cdf"], 0)
                self.assertGreater(accounting_report["total_exits_cdf"], 0)


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

        # L'heure de pointe releve de l'analyse, pas de l'urgence du jour :
        # elle a quitte la vue d'ensemble avec le reste des graphiques. Ce que
        # ce test garde, c'est le cloisonnement par salle.
        response = self.client.get(
            reverse("core:gym_dashboard", args=[self.gym_a.id]),
            {"period": "day", "view": "analytics"},
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

    def test_report_page_exposes_accounting_chart_data_and_visual_blocks(self):
        response = self.client.get(reverse("core:rapport"), {"period": "month"})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("accountingCategoryChart", content)
        self.assertIn("accountingMethodChart", content)
        chart_data = response.context["report_chart_data"]
        accounting_report = response.context["accounting_report"]

        self.assertEqual(chart_data["totals"]["transactions"], accounting_report["transaction_count"])
        self.assertEqual(chart_data["totals"]["entries"], float(accounting_report["total_entries_cdf"]))
        self.assertEqual(chart_data["totals"]["exits"], float(accounting_report["total_exits_cdf"]))
        self.assertNotIn("Other Tenant Subscription", content)

    def test_dashboard_chart_data_is_scoped_and_matches_existing_kpis(self):
        today = timezone.localdate()
        self.member_a.status = "active"
        self.member_a.save(update_fields=["status"])
        plan_a = SubscriptionPlan.objects.create(
            gym=self.gym_a,
            name="Pack A",
            duration_days=30,
            price=Decimal("10.00"),
        )
        plan_b = SubscriptionPlan.objects.create(
            gym=self.gym_b,
            name="Leak Pack",
            duration_days=30,
            price=Decimal("99.00"),
        )
        MemberSubscription.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            plan=plan_a,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )
        MemberSubscription.objects.create(
            gym=self.gym_b,
            member=self.member_b,
            plan=plan_b,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )
        self._create_access_log_at(self.gym_a, self.member_a, 18)
        self._create_access_log_at(self.gym_a, self.member_a, 19, granted=False)
        self._create_access_log_at(self.gym_b, self.member_b, 20)

        response = self.client.get(
            reverse("core:gym_dashboard", args=[self.gym_a.id]),
            {"view": "analytics", "period": "month"},
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("dashboard-chart-data", content)
        self.assertIn("accessDecisionChart", content)
        chart_data = response.context["dashboard_chart_data"]

        self.assertEqual(sum(chart_data["member_status"]["values"]), response.context["total_members"])
        self.assertEqual(sum(chart_data["attendance"]["values"]), response.context["visits_period"])
        self.assertEqual(chart_data["access"]["values"], [response.context["visits_period"], response.context["denied_period"]])
        self.assertEqual(sum(chart_data["revenue"]["values"]), float(response.context["period_revenue"]))
        self.assertIn("Pack A", chart_data["plans"]["labels"])
        self.assertNotIn("Leak Pack", chart_data["plans"]["labels"])

    def test_dashboard_chart_data_has_valid_series_for_supported_periods(self):
        for period in ["day", "week", "month", "year"]:
            with self.subTest(period=period):
                response = self.client.get(
                    reverse("core:gym_dashboard", args=[self.gym_a.id]),
                    {"view": "analytics", "period": period},
                )

                self.assertEqual(response.status_code, 200)
                chart_data = response.context["dashboard_chart_data"]
                self.assertEqual(
                    len(chart_data["revenue"]["labels"]),
                    len(chart_data["revenue"]["values"]),
                )
                self.assertEqual(
                    len(chart_data["attendance"]["labels"]),
                    len(chart_data["attendance"]["values"]),
                )
                # Les tranches ne se recouvrent plus : chaque abonnement en
                # compte pour un, dans une seule.
                self.assertEqual(
                    chart_data["expirations"]["labels"],
                    [
                        "Aujourd'hui ou demain",
                        "Dans 2 a 7 jours",
                        "Dans 8 a 15 jours",
                        "Au-dela de 15 jours",
                    ],
                )

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

    @patch("core.views.generate_temporary_password", return_value="EmployeeTemp123!")
    def test_settings_owner_can_create_internal_employee_for_selected_gym(self, _mock_password):
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
            follow=True,
        )

        self.assertEqual(response.redirect_chain, [(f"{reverse('core:settings')}?tab=employees", 302)])
        employee_role = UserGymRole.objects.get(user__email="marc@example.com", gym=self.gym_a)
        self.assertEqual(employee_role.role, "manager")
        self.assertTrue(employee_role.is_active)
        self.assertNotEqual(employee_role.role, "owner")
        self.assertTrue(employee_role.user.force_password_change)
        self.assertTrue(employee_role.user.check_password("EmployeeTemp123!"))
        self.assertContains(response, "Identifiants du nouvel employe")
        self.assertContains(response, employee_role.user.username)
        self.assertContains(response, "EmployeeTemp123!")
        self.assertTrue(
            SensitiveActivityLog.objects.filter(
                organization=self.org_a,
                action="employee.created",
                target_label__icontains="manager",
            ).exists()
        )

    def test_settings_owner_can_open_internal_employee_edit_mode(self):
        employee = User.objects.create_user(
            username="settings-edit",
            password="pass",
            first_name="Old",
            last_name="Name",
            email="old-edit@example.com",
        )
        role = UserGymRole.objects.create(user=employee, gym=self.gym_a, role="cashier")

        response = self.client.get(reverse("core:settings"), {"tab": "employees", "edit_role": role.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Modifier un employe interne")
        self.assertContains(response, "settings-edit")
        self.assertContains(response, 'value="Old"', html=False)
        self.assertContains(response, "Enregistrer les modifications")

    def test_settings_owner_can_update_internal_employee_profile(self):
        employee = User.objects.create_user(
            username="settings-update",
            password="pass",
            first_name="Old",
            last_name="Cashier",
            email="old-cashier@example.com",
        )
        role = UserGymRole.objects.create(user=employee, gym=self.gym_a, role="cashier")

        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_update",
                "role_id": role.id,
                "first_name": "New",
                "last_name": "Coach",
                "email": "new-coach@example.com",
                "gym": self.gym_a.id,
                "role": "coach",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, f"{reverse('core:settings')}?tab=employees", fetch_redirect_response=False)
        employee.refresh_from_db()
        role.refresh_from_db()
        self.assertEqual(employee.first_name, "New")
        self.assertEqual(employee.last_name, "Coach")
        self.assertEqual(employee.email, "new-coach@example.com")
        self.assertEqual(role.role, "coach")
        self.assertTrue(
            SensitiveActivityLog.objects.filter(
                organization=self.org_a,
                action="employee.updated",
                target_label__icontains="settings-update",
            ).exists()
        )

    def test_settings_owner_can_delete_internal_employee_profile(self):
        employee = User.objects.create_user(username="settings-delete", password="pass", is_active=True)
        role = UserGymRole.objects.create(user=employee, gym=self.gym_a, role="cashier")

        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_delete",
                "role_id": role.id,
            },
        )

        self.assertRedirects(response, f"{reverse('core:settings')}?tab=employees", fetch_redirect_response=False)
        self.assertFalse(UserGymRole.objects.filter(id=role.id).exists())
        employee.refresh_from_db()
        self.assertFalse(employee.is_active)
        self.assertTrue(
            SensitiveActivityLog.objects.filter(
                organization=self.org_a,
                action="employee.deleted",
                target_label__icontains="settings-delete",
            ).exists()
        )

    def test_settings_employee_delete_preserves_shared_member_profile(self):
        shared_user = User.objects.create_user(
            username="member-staff",
            password="pass",
            first_name="Member",
            last_name="Staff",
            email="member-staff@example.com",
            is_active=True,
        )
        member = Member.objects.create(
            gym=self.gym_a,
            user=shared_user,
            first_name="Client",
            last_name="Photo",
            phone="90001",
            email="client-photo@example.com",
        )
        role = UserGymRole.objects.create(user=shared_user, gym=self.gym_a, role="cashier")

        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_delete",
                "role_id": role.id,
            },
        )

        self.assertRedirects(response, f"{reverse('core:settings')}?tab=employees", fetch_redirect_response=False)
        self.assertFalse(UserGymRole.objects.filter(id=role.id).exists())
        self.assertTrue(Member.objects.filter(id=member.id, user=shared_user).exists())
        shared_user.refresh_from_db()
        self.assertTrue(shared_user.is_active)

    def test_settings_employee_update_blocks_shared_member_profile(self):
        shared_user = User.objects.create_user(
            username="member-staff-update",
            password="pass",
            first_name="Member",
            last_name="Staff",
            email="member-staff-update@example.com",
        )
        Member.objects.create(
            gym=self.gym_a,
            user=shared_user,
            first_name="Client",
            last_name="Protected",
            phone="90002",
            email="client-protected@example.com",
        )
        role = UserGymRole.objects.create(user=shared_user, gym=self.gym_a, role="cashier")

        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_update",
                "role_id": role.id,
                "first_name": "Changed",
                "last_name": "Name",
                "email": "changed@example.com",
                "gym": self.gym_a.id,
                "role": "coach",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, f"{reverse('core:settings')}?tab=employees", fetch_redirect_response=False)
        shared_user.refresh_from_db()
        role.refresh_from_db()
        self.assertEqual(shared_user.first_name, "Member")
        self.assertEqual(shared_user.email, "member-staff-update@example.com")
        self.assertEqual(role.role, "cashier")

    @patch("core.views.generate_temporary_password", return_value="OwnerReset123!")
    def test_settings_owner_can_manage_employee_across_organization_gyms(self, _mock_password):
        gym_c = Gym.objects.create(
            organization=self.org_a,
            name="Gym C",
            slug="gym-c",
            subdomain="gym-c",
        )
        employee = User.objects.create_user(
            username="org-cashier",
            password="InitialPass123!",
            email="org-cashier@example.com",
        )
        employee_role = UserGymRole.objects.create(user=employee, gym=gym_c, role="cashier")

        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_reset_password",
                "role_id": employee_role.id,
            },
            follow=True,
        )

        self.assertRedirects(response, f"{reverse('core:settings')}?tab=employees")
        employee.refresh_from_db()
        self.assertTrue(employee.force_password_change)
        self.assertTrue(employee.check_password("OwnerReset123!"))
        self.assertContains(response, "Nouveau mot de passe temporaire")

    def test_organization_logo_upload_rejects_non_image_file(self):
        uploaded = SimpleUploadedFile(
            "logo.html",
            b"<script>alert(1)</script>",
            content_type="text/html",
        )
        form = OrganizationSettingsForm(
            data={
                "name": self.org_a.name,
                "address": "",
                "phone": "",
                "email": "",
            },
            files={"logo": uploaded},
            instance=self.org_a,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("logo", form.errors)

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
        self.assertEqual(response["Location"], f"{reverse('core:settings')}?tab=organization")
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
        self.assertEqual(response["Location"], f"{reverse('core:settings')}?tab=specialties")
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
        # La caisse enrole les visages et ouvre la porte : le controle d'acces
        # lui est ouvert, contrairement aux rapports et aux reglages.
        self.assertIn('href="/access/access-dashboard/?section=scan"', content)

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

    def test_manager_cannot_create_another_manager(self):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_create",
                "first_name": "Peer",
                "last_name": "Manager",
                "email": "peer-manager@example.com",
                "gym": self.gym.id,
                "role": "manager",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserGymRole.objects.filter(user__email="peer-manager@example.com").exists())

    def test_manager_settings_hides_manager_creation_and_manager_rows(self):
        peer_manager = User.objects.create_user(
            username="peer-manager",
            password="pass",
            first_name="Peer",
            last_name="Manager",
        )
        UserGymRole.objects.create(user=peer_manager, gym=self.gym, role="manager")
        cashier = User.objects.create_user(
            username="visible-cashier",
            password="pass",
            first_name="Visible",
            last_name="Cashier",
        )
        UserGymRole.objects.create(user=cashier, gym=self.gym, role="cashier")
        self.client.force_login(self.manager)

        response = self.client.get(reverse("core:settings"), {"tab": "employees"})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<option value="manager"', html=False)
        self.assertNotContains(response, "peer-manager")
        self.assertContains(response, "visible-cashier")

    def test_manager_settings_locks_gym_choice_to_active_gym(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("core:settings"), {"tab": "employees"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Salle active")
        self.assertContains(response, self.gym.name)
        self.assertContains(response, f'<input type="hidden" name="gym" value="{self.gym.id}"', html=False)
        self.assertNotContains(response, '<select name="gym"', html=False)

    def test_manager_cannot_reset_password_for_manager_role(self):
        peer_manager = User.objects.create_user(
            username="protected-manager",
            password="InitialPass123!",
            email="protected-manager@example.com",
        )
        manager_role = UserGymRole.objects.create(user=peer_manager, gym=self.gym, role="manager")
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_reset_password",
                "role_id": manager_role.id,
            },
        )

        self.assertEqual(response.status_code, 403)
        peer_manager.refresh_from_db()
        self.assertFalse(peer_manager.force_password_change)
        self.assertTrue(peer_manager.check_password("InitialPass123!"))

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

        self.assertRedirects(response, f"{reverse('core:settings')}?tab=employees", fetch_redirect_response=False)
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

        self.assertRedirects(response, f"{reverse('core:settings')}?tab=employees", fetch_redirect_response=False)
        current_role.refresh_from_db()
        other_role.refresh_from_db()
        shared_user.refresh_from_db()
        self.assertFalse(current_role.is_active)
        self.assertTrue(other_role.is_active)
        self.assertTrue(shared_user.is_active)

    def test_manager_can_update_allowed_employee_profile_in_current_gym(self):
        employee = User.objects.create_user(
            username="manager-edit-cashier",
            password="pass",
            first_name="Cash",
            last_name="Old",
            email="cash-old@example.com",
        )
        role = UserGymRole.objects.create(user=employee, gym=self.gym, role="cashier")
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_update",
                "role_id": role.id,
                "first_name": "Reception",
                "last_name": "New",
                "email": "reception-new@example.com",
                "gym": self.gym.id,
                "role": "reception",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, f"{reverse('core:settings')}?tab=employees", fetch_redirect_response=False)
        employee.refresh_from_db()
        role.refresh_from_db()
        self.assertEqual(employee.first_name, "Reception")
        self.assertEqual(employee.email, "reception-new@example.com")
        self.assertEqual(role.role, "reception")

    def test_manager_can_delete_allowed_employee_profile_in_current_gym(self):
        employee = User.objects.create_user(username="manager-delete-cashier", password="pass", is_active=True)
        role = UserGymRole.objects.create(user=employee, gym=self.gym, role="cashier")
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_delete",
                "role_id": role.id,
            },
        )

        self.assertRedirects(response, f"{reverse('core:settings')}?tab=employees", fetch_redirect_response=False)
        self.assertFalse(UserGymRole.objects.filter(id=role.id).exists())
        employee.refresh_from_db()
        self.assertFalse(employee.is_active)

    def test_manager_cannot_delete_manager_profile(self):
        peer_manager = User.objects.create_user(username="manager-delete-protected", password="pass", is_active=True)
        manager_role = UserGymRole.objects.create(user=peer_manager, gym=self.gym, role="manager")
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_delete",
                "role_id": manager_role.id,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(UserGymRole.objects.filter(id=manager_role.id).exists())
        peer_manager.refresh_from_db()
        self.assertTrue(peer_manager.is_active)

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

    def test_internal_employee_form_can_limit_roles_for_manager_scope(self):
        form = InternalEmployeeForm(allowed_roles=["coach", "reception", "cashier"])

        role_values = [value for value, _label in form.fields["role"].choices]

        self.assertNotIn("manager", role_values)
        self.assertEqual(role_values, ["coach", "reception", "cashier"])

    def test_internal_employee_form_hides_locked_gym_field(self):
        organization = Organization.objects.create(name="Form Org", slug="form-org")
        gym = Gym.objects.create(
            organization=organization,
            name="Form Gym",
            slug="form-gym",
            subdomain="form-gym",
        )

        form = InternalEmployeeForm(organization=organization, locked_gym=gym)

        self.assertEqual(form.fields["gym"].initial, gym)
        self.assertEqual(form.locked_gym, gym)
        self.assertEqual(form.fields["gym"].widget.input_type, "hidden")

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
        # Toutes les periodes s'arretent au jour courant : un rapport ne couvre
        # pas des journees a venir. Seule une periode personnalisee peut aller
        # au-dela, l'utilisateur l'ayant explicitement demandee.
        expectations = {
            "today": (date(2026, 5, 21), date(2026, 5, 21), "today"),
            "yesterday": (date(2026, 5, 20), date(2026, 5, 20), "yesterday"),
            "week": (date(2026, 5, 18), date(2026, 5, 21), "week"),
            "month": (date(2026, 5, 1), date(2026, 5, 21), "month"),
            "year": (date(2026, 1, 1), date(2026, 5, 21), "year"),
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
        # Aucun membre de cette salle n'a d'abonnement : personne n'a droit au
        # coaching. L'ancien compteur annoncait pourtant "1 membre sans coach",
        # et les deux membres suivis le sont sans droit actif.
        self.assertEqual(kpis["coaching_eligible_count"], 0)
        self.assertEqual(kpis["coaching_eligible_with_coach_count"], 0)
        self.assertEqual(kpis["coaching_eligible_without_coach_count"], 0)
        self.assertEqual(kpis["coached_without_access_count"], 2)
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


class ReportPeriodBoundsTests(TestCase):
    """Aucune periode relative ne doit deborder sur des journees a venir."""

    reference = date(2026, 5, 21)  # un jeudi

    def _period(self, key, **params):
        return get_report_period({"period": key, **params}, today=self.reference)

    def test_no_relative_period_ends_in_the_future(self):
        for key in ["today", "yesterday", "week", "month", "year"]:
            with self.subTest(period=key):
                self.assertLessEqual(self._period(key)["end_date"], self.reference)

    def test_the_current_week_stops_today(self):
        period = self._period("week")

        self.assertEqual(period["start_date"], date(2026, 5, 18))
        self.assertEqual(period["end_date"], self.reference)

    def test_the_current_year_stops_today(self):
        period = self._period("year")

        self.assertEqual(period["start_date"], date(2026, 1, 1))
        self.assertEqual(period["end_date"], self.reference)

    def test_a_custom_range_is_left_untouched(self):
        """Une borne future explicitement saisie reste celle de l'utilisateur."""
        period = self._period("custom", date_from="2026-05-01", date_to="2026-12-31")

        self.assertEqual(period["end_date"], date(2026, 12, 31))

    def test_period_windows_stay_consistent_between_each_other(self):
        day = self._period("today")
        week = self._period("week")
        month = self._period("month")
        year = self._period("year")

        self.assertEqual(day["end_date"], week["end_date"])
        self.assertEqual(week["end_date"], month["end_date"])
        self.assertEqual(month["end_date"], year["end_date"])
        self.assertLessEqual(year["start_date"], month["start_date"])
        self.assertLessEqual(month["start_date"], week["start_date"])


class SettingsRefusalAuditTests(TestCase):
    """Un refus doit s'expliquer a l'utilisateur et laisser une trace."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Refus", slug="org-refus"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Refus",
            slug="gym-refus",
            subdomain="gym-refus",
        )
        self.owner = User.objects.create_user(
            username="owner-refus",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.manager = User.objects.create_user(
            username="manager-refus", password="pass12345"
        )
        self.manager.force_password_change = False
        self.manager.save()
        self.manager_role = UserGymRole.objects.create(
            user=self.manager, gym=self.gym, role="manager", is_active=True
        )
        self.client.force_login(self.manager)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()
        self.url = reverse("core:settings")

    def _refusals(self):
        return SensitiveActivityLog.objects.filter(action="settings.action_refused")

    # --- Des messages qui expliquent la regle ---------------------------------

    def test_an_out_of_reach_role_is_explained_in_plain_words(self):
        response = self.client.post(
            self.url,
            {
                "action": "employee_create",
                "first_name": "Nouveau",
                "last_name": "Gerant",
                "email": "nouveau@refus.test",
                "phone": "+243920000001",
                "role": "manager",
                "gym": self.gym.id,
            },
        )

        errors = response.context["employee_form"].errors["role"]
        self.assertIn("Vous ne pouvez pas attribuer ce role", errors[0])
        self.assertNotIn("Selectionnez un choix valide", errors[0])

    def test_the_message_lists_the_roles_actually_allowed(self):
        response = self.client.post(
            self.url,
            {
                "action": "employee_create",
                "first_name": "Nouveau",
                "last_name": "Gerant",
                "email": "nouveau2@refus.test",
                "phone": "+243920000002",
                "role": "owner",
                "gym": self.gym.id,
            },
        )

        errors = response.context["employee_form"].errors["role"]
        self.assertTrue(any("Coach" in message for message in errors))

    # --- Les tentatives laissent une trace -------------------------------------

    def test_touching_a_higher_account_is_recorded(self):
        before = self._refusals().count()

        self.client.post(
            self.url,
            {"action": "employee_delete", "role_id": self.manager_role.id},
        )

        self.assertEqual(self._refusals().count(), before + 1)
        entry = self._refusals().latest("id")
        self.assertEqual(entry.actor, self.manager)
        self.assertEqual(entry.metadata["action"], "employee_delete")
        self.assertEqual(entry.metadata["target_role"], "manager")

    def test_editing_the_organization_without_the_right_is_recorded(self):
        before = self._refusals().count()

        response = self.client.post(
            self.url, {"action": "organization", "name": "Nom pirate"}
        )

        self.organization.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.organization.name, "Org Refus")
        self.assertEqual(self._refusals().count(), before + 1)

    def test_opening_a_higher_account_sheet_is_recorded(self):
        before = self._refusals().count()

        self.client.get(
            self.url, {"tab": "employees", "edit_role": self.manager_role.id}
        )

        self.assertEqual(self._refusals().count(), before + 1)
        self.assertEqual(
            self._refusals().latest("id").metadata["action"], "employee_edit_open"
        )

    def test_a_legitimate_action_is_not_recorded_as_refused(self):
        before = self._refusals().count()

        self.client.post(
            self.url,
            {
                "action": "employee_create",
                "first_name": "Vrai",
                "last_name": "Caissier",
                "email": "caissier@refus.test",
                "phone": "+243920000003",
                "role": "cashier",
                "gym": self.gym.id,
            },
        )

        self.assertEqual(self._refusals().count(), before)
        self.assertTrue(
            UserGymRole.objects.filter(gym=self.gym, role="cashier").exists()
        )


class ActivityLogConsultationTests(TestCase):
    """Le journal doit rester exploitable : filtrable et exportable."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Trace", slug="org-trace"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Trace",
            slug="gym-trace",
            subdomain="gym-trace",
        )
        self.owner = User.objects.create_user(
            username="owner-trace",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.other_actor = User.objects.create_user(
            username="agent-trace", password="pass12345"
        )
        self.cashier = User.objects.create_user(
            username="cashier-trace", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.cashier, gym=self.gym, role="cashier", is_active=True
        )
        self.now = timezone.now()

        self._trace("rh.employee_deactivated", "Agent Paie")
        self._trace("member.updated", "Rebecca")
        self._trace("pos.register_closed", "Caisse 1")
        self._trace("machines.machine_deleted", "Tapis 1", actor=self.other_actor)
        self._trace("access.door_opened_remotely", "Lecteur principal")
        self.old_entry = self._trace("rh.employee_deactivated", "Vieux Dossier", days=90)

        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _trace(self, action, label, days=0, actor=None):
        entry = SensitiveActivityLog.objects.create(
            organization=self.organization,
            gym=self.gym,
            actor=actor or self.owner,
            action=action,
            target_type="Test",
            target_label=label,
            metadata={"ip": "127.0.0.1", "path": "/x", "detail": "valeur"},
        )
        if days:
            SensitiveActivityLog.objects.filter(pk=entry.pk).update(
                created_at=self.now - timedelta(days=days)
            )
        return entry

    def _page(self, **params):
        return self.client.get(
            reverse("core:settings"), {"tab": "activity", **params}
        )

    # --- Perimetre par defaut --------------------------------------------------

    def test_the_default_window_covers_the_last_thirty_days(self):
        response = self._page()

        self.assertEqual(response.context["activity_total"], 5)

    def test_an_older_entry_reappears_on_a_wider_window(self):
        response = self._page(
            log_from=(self.now - timedelta(days=120)).date().isoformat(),
            log_to=self.now.date().isoformat(),
        )

        self.assertEqual(response.context["activity_total"], 6)

    def test_reversed_dates_are_reordered_instead_of_emptying_the_page(self):
        response = self._page(
            log_from=self.now.date().isoformat(),
            log_to=(self.now - timedelta(days=120)).date().isoformat(),
        )

        filters = response.context["log_filters"]
        self.assertLess(filters["date_from"], filters["date_to"])
        self.assertEqual(response.context["activity_total"], 6)

    def test_an_unreadable_date_falls_back_on_the_default_window(self):
        response = self._page(log_from="pas-une-date")

        self.assertEqual(response.context["activity_total"], 5)

    # --- Filtres ----------------------------------------------------------------

    def test_filtering_by_domain(self):
        for group, expected in [
            ("employee", 1),
            ("member", 1),
            ("money", 1),
            ("stock", 1),
            ("access", 1),
        ]:
            with self.subTest(group=group):
                self.assertEqual(
                    self._page(log_group=group).context["activity_total"], expected
                )

    def test_filtering_by_actor(self):
        response = self._page(log_actor="agent-trace")

        self.assertEqual(response.context["activity_total"], 1)

    def test_searching_a_target(self):
        response = self._page(log_q="Rebecca")

        self.assertEqual(response.context["activity_total"], 1)

    def test_an_unknown_domain_is_ignored_rather_than_emptying(self):
        response = self._page(log_group="n-importe-quoi")

        self.assertEqual(response.context["activity_total"], 5)

    # --- Export -----------------------------------------------------------------

    def test_the_export_mirrors_the_filters(self):
        response = self.client.get(
            reverse("core:activity_log_export"), {"log_group": "access"}
        )

        body = response.content.decode("utf-8-sig")
        rows = [line for line in body.splitlines() if line.strip()]
        self.assertEqual(response.status_code, 200)
        self.assertIn("Lecteur principal", body)
        self.assertNotIn("Tapis 1", body)
        self.assertEqual(len(rows), 2)  # en-tete + une action

    def test_the_export_is_named_after_the_period(self):
        response = self.client.get(
            reverse("core:activity_log_export"),
            {
                "log_from": "2026-01-01",
                "log_to": "2026-01-31",
            },
        )

        self.assertIn("20260101-20260131.csv", response["Content-Disposition"])

    def test_the_export_hides_technical_metadata(self):
        """L'IP et le chemin interne n'ont pas leur place dans un document remis."""
        response = self.client.get(reverse("core:activity_log_export"))

        body = response.content.decode("utf-8-sig")
        self.assertNotIn("127.0.0.1", body)
        self.assertIn("detail=valeur", body)

    def test_exporting_is_itself_recorded(self):
        self.client.get(reverse("core:activity_log_export"))

        entry = SensitiveActivityLog.objects.filter(
            action="settings.activity_log_exported"
        ).latest("id")
        self.assertEqual(entry.actor, self.owner)

    def test_a_cashier_cannot_export_the_log(self):
        self.client.force_login(self.cashier)

        response = self.client.get(reverse("core:activity_log_export"))

        self.assertEqual(response.status_code, 403)


class DashboardKpiConsistencyTests(TestCase):
    """Les indicateurs doivent dire vrai et mener a une action."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Kpi", slug="org-kpi"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Kpi",
            slug="gym-kpi",
            subdomain="gym-kpi",
        )
        for code in ["MEMBERS", "SUBSCRIPTIONS", "COACHING"]:
            module, _ = Module.objects.get_or_create(code=code, defaults={"name": code})
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )
        self.owner = User.objects.create_user(
            username="owner-kpi",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", duration_days=30, price=50
        )
        self.today = timezone.localdate()

        self._member("Demain", self.today + timedelta(days=1))
        self._member("Cinq", self.today + timedelta(days=5))
        self._member("Quinze", self.today + timedelta(days=15))
        self._member("Echu", self.today - timedelta(days=5))
        self._member("Jamais")
        self._member("Suspendu", self.today - timedelta(days=5), status="suspended")

        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _member(self, name, end=None, status="active"):
        member = Member.objects.create(
            gym=self.gym,
            first_name=name,
            last_name="Kpi",
            phone=f"+2438500{abs(hash(name)) % 10000:04d}",
            email=f"{name.lower()}.kpi@example.com",
            status=status,
        )
        if end is not None:
            MemberSubscription.objects.create(
                gym=self.gym,
                member=member,
                plan=self.plan,
                start_date=self.today - timedelta(days=20),
                end_date=end,
                is_active=True,
            )
        return member

    def _dashboard(self):
        return self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id])
        ).context

    def _member_list(self, **params):
        return self.client.get(reverse("members:member_list"), params)

    # --- Membres expires : mesure et non deduction -----------------------------

    def test_expired_members_only_counts_those_who_had_a_subscription(self):
        context = self._dashboard()

        self.assertEqual(context["expired_members"], 1)

    def test_members_who_never_subscribed_are_counted_apart(self):
        context = self._dashboard()

        self.assertEqual(context["never_subscribed_members"], 1)

    def test_the_old_subtraction_would_have_overcounted(self):
        """Le calcul par soustraction comptait aussi ceux qui n'ont jamais souscrit."""
        context = self._dashboard()

        deduced = (
            context["total_members"]
            - context["active_members"]
            - context["suspended_members"]
        )
        self.assertGreater(deduced, context["expired_members"])

    # --- Paliers d'expiration : cumulatifs -------------------------------------

    def test_expiry_tiers_accumulate(self):
        """Un membre a echeance dans cinq jours n'apparaissait dans aucun palier."""
        context = self._dashboard()

        self.assertEqual(context["expiry_1_day"], 1)
        self.assertEqual(context["expiry_3_days"], 1)
        self.assertEqual(context["expiry_7_days"], 2)
        self.assertEqual(context["expiry_soon"], 3)

    def test_each_tier_matches_the_list_it_links_to(self):
        context = self._dashboard()

        for days, key in [(1, "expiry_1_day"), (7, "expiry_7_days"), (15, "expiry_soon")]:
            with self.subTest(days=days):
                listed = self._member_list(status="expiring", expiring_days=days)
                self.assertEqual(
                    listed.context["page_obj"].paginator.count, context[key]
                )

    # --- Liste d'appel ----------------------------------------------------------

    def test_the_call_list_starts_with_the_most_urgent(self):
        response = self._member_list(status="expiring", expiring_days=15)

        names = [member.first_name for member in response.context["page_obj"]]
        self.assertEqual(names, ["Demain", "Cinq", "Quinze"])

    def test_an_explicit_sort_is_respected(self):
        response = self._member_list(
            status="expiring", expiring_days=15, sort="name_desc"
        )

        names = [member.first_name for member in response.context["page_obj"]]
        self.assertEqual(names[0], "Quinze")

    def test_an_unknown_window_falls_back_on_seven_days(self):
        response = self._member_list(status="expiring", expiring_days="999")

        self.assertEqual(response.context["page_obj"].paginator.count, 2)

    # --- Indicateurs branches ----------------------------------------------------

    def test_the_coach_ratio_is_no_longer_frozen_at_zero(self):
        coach = Coach.objects.create(
            gym=self.gym, name="Coach Kpi", phone="0850000009", is_active=True
        )
        coach.members.add(Member.objects.get(gym=self.gym, first_name="Demain"))

        context = self._dashboard()

        self.assertEqual(
            context["coach_member_ratio"], context["average_members_per_coach"]
        )

    def test_period_comparisons_are_supplied_to_the_template(self):
        """Les badges existaient dans le template sans donnee derriere."""
        context = self._dashboard()

        for key in ["revenue_trend", "new_members_trend", "renewals_trend", "expirations_trend"]:
            with self.subTest(trend=key):
                self.assertIn("display", context[key])
                self.assertIn("badge_class", context[key])


class TemplateCommentSyntaxTests(SimpleTestCase):
    """Aucun gabarit ne doit afficher ses propres commentaires."""

    # {# ... #} ne tient que sur une ligne. Sur plusieurs, Django ne le
    # reconnait pas comme un commentaire et l'ecrit tel quel dans la page :
    # le visiteur lit les notes de developpement.
    COMMENTAIRE_MULTILIGNE = re.compile(r"\{#[^#]*?\n.*?#\}", re.S)

    def test_no_template_uses_a_multiline_short_comment(self):
        racine = Path(settings.BASE_DIR)
        fautifs = []

        for gabarit in racine.rglob("*.html"):
            if ".venv" in gabarit.parts or "node_modules" in gabarit.parts:
                continue
            texte = gabarit.read_text(encoding="utf-8", errors="replace")
            if self.COMMENTAIRE_MULTILIGNE.search(texte):
                fautifs.append(str(gabarit.relative_to(racine)))

        self.assertEqual(
            fautifs,
            [],
            "Ces gabarits afficheraient leurs commentaires : "
            "utilisez {% comment %}...{% endcomment %}.",
        )


class CommercialRoleTests(TestCase):
    """
    Le commercial demarche et convertit les prospects.

    Il tient les messages aux membres, les preinscriptions, les coordonnees de
    la salle et la vitrine publique. Il ne touche ni a l'argent, ni aux fiches
    membres, ni au personnel, ni a l'identite de l'organisation.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Commercial", slug="org-commercial"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Commercial",
            slug="gym-commercial",
            subdomain="gym-commercial",
        )
        for code in ("MEMBERS", "POS", "REPORTS", "MACHINES", "NOTIFICATIONS"):
            module, _ = Module.objects.get_or_create(code=code, defaults={"name": code})
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )

        self.commercial = User.objects.create_user(
            username="commercial-perimetre", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.commercial, gym=self.gym, role="commercial", is_active=True
        )
        self.client.force_login(self.commercial)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _refuse(self, url):
        reponse = self.client.get(url)
        self.assertIn(
            reponse.status_code, (302, 403, 404), f"{url} devrait etre refuse"
        )

    # --- Ce qu'il peut faire ---------------------------------------------------

    def test_he_reaches_the_pre_registrations(self):
        reponse = self.client.get(reverse("members:pre_registration_list"))

        self.assertEqual(reponse.status_code, 200)

    def test_he_confirms_a_pre_registration(self):
        demande = MemberPreRegistration.objects.create(
            gym=self.gym,
            first_name="Prospect",
            last_name="Converti",
            phone="+243890000001",
            email="prospect.converti@example.com",
        )

        self.client.post(
            reverse("members:confirm_pre_registration", args=[demande.id]), follow=True
        )

        demande.refresh_from_db()
        self.assertEqual(demande.status, MemberPreRegistration.STATUS_CONFIRMED)
        self.assertEqual(demande.confirmed_by, self.commercial)

    def test_he_regenerates_the_public_link(self):
        reponse = self.client.post(
            reverse("members:regenerate_pre_registration_link"), follow=True
        )

        self.assertEqual(reponse.status_code, 200)

    def test_he_reaches_the_member_messages(self):
        reponse = self.client.get(reverse("notifications:dashboard"))

        self.assertEqual(reponse.status_code, 200)

    def test_he_reaches_the_settings_page(self):
        reponse = self.client.get(reverse("core:settings"))

        self.assertEqual(reponse.status_code, 200)

    def test_he_edits_the_gym_contact_details(self):
        self.client.post(
            reverse("core:settings"),
            {
                "action": "gym_contact",
                "address": "12 avenue du Commerce",
                "phone": "+243890000009",
                "email": "",
                "opening_hours": "",
            },
            follow=True,
        )

        self.gym.refresh_from_db()
        self.assertEqual(self.gym.address, "12 avenue du Commerce")

    def test_he_edits_the_public_landing(self):
        self._poster_organisation(landing_kicker="Notre nouvelle accroche")

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.landing_kicker, "Notre nouvelle accroche")

    def test_he_manages_the_landing_faq(self):
        self.client.post(
            reverse("core:settings"),
            {"action": "faq_create", "question": "Un parking ?", "answer": "Oui."},
            follow=True,
        )

        self.assertTrue(
            LandingFaq.objects.filter(organization=self.organization).exists()
        )

    # --- Ce qu'il ne peut pas faire ---------------------------------------------

    def test_he_cannot_rename_the_organization(self):
        # Renommer engage toute la marque : cela reste au proprietaire, meme
        # si le commercial retouche la vitrine sur le meme ecran.
        avant = self.organization.name

        self._poster_organisation(name="Nom detourne")

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, avant)

    def test_he_cannot_reach_the_member_list(self):
        self._refuse(reverse("members:member_list"))

    def test_he_cannot_reach_the_cash_register(self):
        self._refuse(reverse("pos:cashier_dashboard"))

    def test_he_cannot_reach_the_reports(self):
        self._refuse(reverse("core:rapport"))

    def test_he_cannot_reach_the_machines(self):
        self._refuse(reverse("machines:list"))

    def test_he_cannot_change_the_maintenance_alert(self):
        avant = self.gym.maintenance_alert_lead_days

        self.client.post(
            reverse("core:settings"),
            {"action": "maintenance", "maintenance_alert_lead_days": "99"},
        )

        self.gym.refresh_from_db()
        self.assertEqual(self.gym.maintenance_alert_lead_days, avant)

    def test_he_cannot_create_an_employee(self):
        avant = UserGymRole.objects.count()

        self.client.post(
            reverse("core:settings"),
            {
                "action": "employee_create",
                "first_name": "Nouvel",
                "last_name": "Employe",
                "role": "cashier",
                "gym": self.gym.id,
            },
        )

        self.assertEqual(UserGymRole.objects.count(), avant)

    # --- Outil -------------------------------------------------------------------

    def _poster_organisation(self, **overrides):
        payload = {
            "action": "organization",
            "address": "", "phone": "", "email": "", "city": "",
            "whatsapp_number": "", "opening_hours": "", "footer_services": "",
            "facebook_url": "", "instagram_url": "", "tiktok_url": "",
            "landing_kicker": "", "landing_title": "", "landing_intro": "",
            "seo_description": "", "seo_keywords": "",
        }
        payload.update(overrides)
        return self.client.post(reverse("core:settings"), payload, follow=True)


class CommercialRoleWiringTests(TestCase):
    """Le role est declare partout ou il doit l'etre."""

    def test_the_role_is_declared_among_the_internal_roles(self):
        valeurs = [valeur for valeur, _ in INTERNAL_ROLE_CHOICES]

        self.assertIn("commercial", valeurs)
        # Le proprietaire ne se cree pas depuis ce formulaire.
        self.assertNotIn("owner", valeurs)

    def test_the_owner_is_actually_offered_the_role_in_the_form(self):
        """
        Verifie la liste **effective** du formulaire, pas la liste declaree.

        Un second filtre restreint les roles selon qui ouvre la page : le
        premier test seul laissait passer un role declare mais jamais propose.
        """
        organization = Organization.objects.create(
            name="Org Offre", slug="org-offre"
        )
        gym = Gym.objects.create(
            organization=organization,
            name="Gym Offre",
            slug="gym-offre",
            subdomain="gym-offre",
        )
        owner = User.objects.create_user(
            username="proprio-offre",
            password="pass12345",
            owned_organization=organization,
        )
        self.client.force_login(owner)
        session = self.client.session
        session["current_gym_id"] = gym.id
        session.save()

        formulaire = InternalEmployeeForm(
            organization=organization,
            gyms=Gym.objects.filter(id=gym.id),
            allowed_roles=list(EMPLOYEE_ROLES_BY_OWNER),
        )
        proposes = [valeur for valeur, _ in formulaire.fields["role"].choices]

        self.assertIn("commercial", proposes)

    def test_a_manager_cannot_create_a_commercial(self):
        """
        On ne delegue pas un droit qu'on n'a pas.

        Le commercial retouche la vitrine, qui vaut pour toute l'organisation.
        Un gerant n'y a pas acces : lui laisser creer un commercial reviendrait
        a lui offrir ce droit par personne interposee.
        """
        self.assertNotIn("commercial", EMPLOYEE_ROLES_BY_MANAGER)
        self.assertIn("commercial", EMPLOYEE_ROLES_BY_OWNER)

    def test_every_internal_role_can_be_created_by_someone(self):
        # Garde-fou pour le prochain role ajoute : declare mais absent des deux
        # listes, il serait invisible et intouchable.
        declares = {valeur for valeur, _ in INTERNAL_ROLE_CHOICES}
        creables = set(EMPLOYEE_ROLES_BY_OWNER) | set(EMPLOYEE_ROLES_BY_MANAGER)

        self.assertEqual(
            declares - creables,
            set(),
            "Ces roles sont declares mais personne ne peut les creer.",
        )

    def test_an_unknown_role_gets_no_permission_at_all(self):
        # C'est ce qui rend l'ajout d'un role sans danger : l'echec est ferme.
        ensembles = [
            DASHBOARD_ROLES, MEMBER_ROLES, POS_CASHIER_ROLES, REPORT_ROLES,
            MACHINE_ROLES, SETTINGS_ORGANIZATION_ROLES,
        ]
        for ensemble in ensembles:
            self.assertNotIn("role_inexistant", ensemble)

    def test_the_commercial_is_absent_from_the_sensitive_sets(self):
        for ensemble in (
            POS_CASHIER_ROLES, POS_HISTORY_ROLES, REPORT_ROLES,
            MEMBER_ROLES, MEMBER_DELETE_ROLES, RH_PAYROLL_ROLES,
            SETTINGS_ORGANIZATION_ROLES,
        ):
            self.assertNotIn("commercial", ensemble)

    def test_the_dashboard_sales_set_keeps_its_former_members(self):
        # Cet ensemble remplace trois listes ecrites en dur : le comportement
        # existant doit etre strictement conserve.
        self.assertEqual(DASHBOARD_SALES_ROLES, {"owner", "manager", "cashier"})


class GymPurgeTests(TestCase):
    """
    Remise a zero d'une salle : ce qui doit disparaitre, et surtout ce qui ne
    doit pas.

    Le geste est irreversible. Chaque garde-fou est verifie separement, parce
    qu'un seul d'entre eux qui cede suffit a detruire le travail d'une annee.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Purge", slug="org-purge"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Royal Gym Purge",
            slug="gym-purge", subdomain="gym-purge",
        )
        self.autre = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-voisine", subdomain="gym-voisine",
        )

        self.owner = User.objects.create_user(username="proprio", password="pass12345")
        UserGymRole.objects.create(
            user=self.owner, gym=self.gym, role="owner", is_active=True
        )

        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        self.member = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243890000001",
        )
        self.compte_membre = User.objects.create_user(
            username="ada-membre", password="pass12345"
        )
        self.member.user = self.compte_membre
        self.member.save(update_fields=["user"])

        MemberSubscription.objects.create(
            gym=self.gym, member=self.member, plan=self.plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="Entree", host="10.0.0.9", password="secret"
        )
        AccessLog.objects.create(gym=self.gym, member=self.member, device=self.device)

        # Une voisine, qui ne doit rien perdre.
        self.membre_voisin = Member.objects.create(
            gym=self.autre, first_name="Voisin", last_name="Intact",
            phone="+243890000002",
        )

        self._connecter(self.owner)

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _effacer(self, **extra):
        charge = {"nom_salle": self.gym.name, "password": "pass12345"}
        charge.update(extra)
        return self.client.post(
            reverse("core:gym_purge"),
            data=json.dumps(charge),
            content_type="application/json",
        )

    # --- Ce qui disparait ------------------------------------------------------

    def test_the_members_are_gone(self):
        self._effacer()

        self.assertFalse(Member.objects.filter(gym=self.gym).exists())

    def test_their_subscriptions_go_with_them(self):
        self._effacer()

        self.assertFalse(MemberSubscription.objects.filter(gym=self.gym).exists())

    def test_the_access_journal_is_emptied(self):
        self._effacer()

        self.assertFalse(AccessLog.objects.filter(gym=self.gym).exists())

    def test_the_member_login_account_is_removed_too(self):
        # Le lien part du membre vers le compte : supprimer la fiche laissait
        # l'identifiant de connexion derriere elle.
        self._effacer()

        self.assertFalse(User.objects.filter(id=self.compte_membre.id).exists())

    # --- Ce qui survit ---------------------------------------------------------

    def test_the_configuration_survives(self):
        self._effacer()

        self.assertTrue(SubscriptionPlan.objects.filter(gym=self.gym).exists())
        self.assertTrue(AccessDevice.objects.filter(gym=self.gym).exists())

    def test_the_owner_keeps_his_access(self):
        # Sans cela, le proprietaire se verrouillerait dehors d'un seul clic.
        self._effacer()

        self.assertTrue(User.objects.filter(id=self.owner.id).exists())
        self.assertTrue(
            UserGymRole.objects.filter(user=self.owner, gym=self.gym).exists()
        )

    def test_the_neighbouring_gym_is_untouched(self):
        # Le pire defaut possible : vider la mauvaise salle.
        self._effacer()

        self.assertTrue(Member.objects.filter(id=self.membre_voisin.id).exists())

    # --- Les garde-fous ---------------------------------------------------------

    def test_a_wrong_gym_name_changes_nothing(self):
        reponse = self._effacer(nom_salle="Royal Gym")

        self.assertEqual(reponse.status_code, 400)
        self.assertTrue(Member.objects.filter(gym=self.gym).exists())

    def test_a_wrong_password_changes_nothing(self):
        reponse = self._effacer(password="pas-le-bon")

        self.assertEqual(reponse.status_code, 400)
        self.assertTrue(Member.objects.filter(gym=self.gym).exists())

    def test_a_manager_cannot_do_it(self):
        # Reserve au proprietaire : un gerant administre, il ne detruit pas.
        gerant = User.objects.create_user(username="gerant-purge", password="pass12345")
        UserGymRole.objects.create(
            user=gerant, gym=self.gym, role="manager", is_active=True
        )
        self._connecter(gerant)

        reponse = self._effacer()

        self.assertEqual(reponse.status_code, 403)
        self.assertTrue(Member.objects.filter(gym=self.gym).exists())

    def test_a_receptionist_cannot_do_it(self):
        accueil = User.objects.create_user(username="accueil-purge", password="pass12345")
        UserGymRole.objects.create(
            user=accueil, gym=self.gym, role="reception", is_active=True
        )
        self._connecter(accueil)

        self.assertEqual(self._effacer().status_code, 403)

    def test_a_get_request_is_refused(self):
        reponse = self.client.get(reverse("core:gym_purge"))

        self.assertEqual(reponse.status_code, 405)
        self.assertTrue(Member.objects.filter(gym=self.gym).exists())

    # --- L'inventaire prealable --------------------------------------------------

    def test_the_preview_counts_what_would_be_lost(self):
        reponse = self.client.get(reverse("core:gym_purge_preview"))

        libelles = {l["libelle"]: l["nombre"] for l in reponse.json()["efface"]}
        self.assertEqual(libelles["Membres"], 1)
        self.assertEqual(libelles["Passages"], 1)

    def test_the_preview_also_says_what_survives(self):
        # Dire ce qui reste rassure autant que dire ce qui meurt.
        reponse = self.client.get(reverse("core:gym_purge_preview"))

        libelles = {l["libelle"] for l in reponse.json()["conserve"]}
        self.assertIn("Formules d'abonnement", libelles)
        self.assertIn("Lecteurs", libelles)

    def test_the_preview_changes_nothing(self):
        self.client.get(reverse("core:gym_purge_preview"))

        self.assertTrue(Member.objects.filter(gym=self.gym).exists())

    def test_the_preview_is_refused_to_a_manager(self):
        gerant = User.objects.create_user(username="gerant-apercu", password="pass12345")
        UserGymRole.objects.create(
            user=gerant, gym=self.gym, role="manager", is_active=True
        )
        self._connecter(gerant)

        self.assertEqual(
            self.client.get(reverse("core:gym_purge_preview")).status_code, 403
        )

    # --- La sauvegarde ------------------------------------------------------------

    def test_the_backup_carries_the_members(self):
        reponse = self.client.post(reverse("core:gym_purge_export"))

        self.assertEqual(reponse.status_code, 200)
        self.assertIn("Ada", reponse.content.decode())

    def test_the_backup_is_offered_as_a_file(self):
        reponse = self.client.post(reverse("core:gym_purge_export"))

        self.assertIn("attachment", reponse["Content-Disposition"])
        self.assertIn("gym-purge", reponse["Content-Disposition"])

    def test_the_backup_changes_nothing(self):
        self.client.post(reverse("core:gym_purge_export"))

        self.assertTrue(Member.objects.filter(gym=self.gym).exists())

    def test_the_backup_is_refused_to_a_manager(self):
        gerant = User.objects.create_user(username="gerant-export", password="pass12345")
        UserGymRole.objects.create(
            user=gerant, gym=self.gym, role="manager", is_active=True
        )
        self._connecter(gerant)

        self.assertEqual(
            self.client.post(reverse("core:gym_purge_export")).status_code, 403
        )

    # --- La trace -------------------------------------------------------------------

    def test_the_erasure_leaves_a_named_trace(self):
        # La trace vit sur l'organisation, pas sur la salle : elle survit a
        # l'effacement, et nomme qui a decide.
        self._effacer()

        trace = SensitiveActivityLog.objects.filter(
            organization=self.organization, action="gym.purged"
        ).first()
        self.assertIsNotNone(trace)
        self.assertEqual(trace.actor, self.owner)

    def test_the_trace_says_how_much_was_destroyed(self):
        self._effacer()

        trace = SensitiveActivityLog.objects.get(
            organization=self.organization, action="gym.purged"
        )
        self.assertGreater(trace.metadata["total"], 0)

    def test_a_refused_attempt_leaves_no_trace_of_erasure(self):
        self._effacer(password="pas-le-bon")

        self.assertFalse(
            SensitiveActivityLog.objects.filter(action="gym.purged").exists()
        )


class MarketingQrTests(TestCase):
    """
    Les QR codes destines au mur de la salle.

    Ils finissent parfois en tres grand format : le rendu doit rester vectoriel,
    et le dessin doit reproduire la grille sans la trahir - un module deplace,
    et le code ne se lit plus.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org QR", slug="org-qr"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym QR",
            slug="gym-qr", subdomain="gym-qr",
        )
        module, _ = Module.objects.get_or_create(
            code="MEMBERS", defaults={"name": "Members"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        # Une salle nait avec son lien : on le retrouve plutot que de le creer.
        self.lien, _ = MemberPreRegistrationLink.objects.get_or_create(gym=self.gym)

        self.gerant = User.objects.create_user(username="gerant-qr", password="pass12345")
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self._connecter(self.gerant)

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    # --- Le rendu vectoriel ----------------------------------------------------

    def test_the_pdf_is_a_real_pdf(self):
        contenu = marketing_qr.en_pdf("https://exemple.test/")

        self.assertTrue(contenu.startswith(b"%PDF-"))
        self.assertTrue(contenu.rstrip().endswith(b"%%EOF"))

    def test_the_cross_reference_table_points_at_each_object(self):
        # Un lecteur PDF refuse un fichier dont la table est decalee d'un octet.
        contenu = marketing_qr.en_pdf("https://exemple.test/")

        debut = int(re.search(rb"startxref\n(\d+)", contenu).group(1))
        positions = re.findall(rb"(\d{10}) 00000 n ", contenu[debut:])
        self.assertEqual(len(positions), 4)
        for position in positions:
            extrait = contenu[int(position):int(position) + 12]
            self.assertRegex(extrait, rb"\d+ 0 obj")

    def test_the_drawing_reproduces_the_grid(self):
        # La verification qui compte : on relit les rectangles du PDF et on
        # reconstruit la grille qu'ils dessinent.
        adresse = "https://exemple.test/preinscription/abc/"
        grille = marketing_qr.matrice(adresse)
        contenu = marketing_qr.en_pdf(adresse)

        total = len(grille)
        module = marketing_qr.COTE_PAGE / total
        relue = [[False] * total for _ in range(total)]
        for x, y, _, _ in re.findall(rb"([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re", contenu):
            colonne = round(float(x) / module)
            rang = round((marketing_qr.COTE_PAGE - float(y)) / module) - 1
            relue[rang][colonne] = True

        self.assertEqual(relue, [[bool(c) for c in ligne] for ligne in grille])

    def test_the_quiet_zone_is_kept(self):
        # Sans les quatre modules blancs de la norme, un scanner ne delimite
        # pas le code sur un mur charge.
        grille = marketing_qr.matrice("https://exemple.test/")

        # Quatre en dur, pas la constante : un test qui lit le reglage qu'il
        # surveille ne surveille rien. C'est la norme qui impose ce chiffre.
        for rang in range(4):
            self.assertFalse(any(grille[rang]), f"ligne {rang} non vide")
            self.assertFalse(any(ligne[rang] for ligne in grille),
                             f"colonne {rang} non vide")
            self.assertFalse(any(grille[-1 - rang]), f"ligne -{rang + 1} non vide")

    def test_two_different_links_give_two_different_codes(self):
        premier = marketing_qr.en_pdf("https://exemple.test/a/")
        second = marketing_qr.en_pdf("https://exemple.test/b/")

        self.assertNotEqual(premier, second)

    # --- Le telechargement -------------------------------------------------------

    def test_the_pre_registration_code_is_downloadable(self):
        reponse = self.client.get(
            reverse("core:marketing_qr_download", args=["preinscription"])
        )

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "application/pdf")
        self.assertIn("attachment", reponse["Content-Disposition"])

    def test_the_site_code_is_downloadable(self):
        reponse = self.client.get(
            reverse("core:marketing_qr_download", args=["site"])
        )

        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.content.startswith(b"%PDF-"))

    def test_png_is_offered_too(self):
        reponse = self.client.get(
            reverse("core:marketing_qr_download", args=["site"]) + "?format=png"
        )

        self.assertEqual(reponse["Content-Type"], "image/png")

    def test_the_pre_registration_code_carries_the_current_token(self):
        reponse = self.client.get(
            reverse("core:marketing_qr_download", args=["preinscription"])
        )

        # Le contenu encode n'est pas lisible dans le PDF : on verifie que
        # regenerer le lien change bien le dessin.
        avant = reponse.content
        self.lien.token = uuid.uuid4()
        self.lien.save(update_fields=["token"])

        apres = self.client.get(
            reverse("core:marketing_qr_download", args=["preinscription"])
        ).content

        self.assertNotEqual(avant, apres)

    def test_an_unknown_support_is_refused(self):
        reponse = self.client.get(
            reverse("core:marketing_qr_download", args=["autre"])
        )

        self.assertEqual(reponse.status_code, 404)

    # --- Qui peut les obtenir -------------------------------------------------------

    def test_a_commercial_can_download_them(self):
        # C'est du marketing : le commercial est concerne au premier chef.
        commercial = User.objects.create_user(
            username="commercial-qr", password="pass12345"
        )
        UserGymRole.objects.create(
            user=commercial, gym=self.gym, role="commercial", is_active=True
        )
        self._connecter(commercial)

        reponse = self.client.get(
            reverse("core:marketing_qr_download", args=["site"])
        )

        self.assertEqual(reponse.status_code, 200)

    def test_a_cashier_cannot(self):
        caissiere = User.objects.create_user(
            username="caisse-qr", password="pass12345"
        )
        UserGymRole.objects.create(
            user=caissiere, gym=self.gym, role="cashier", is_active=True
        )
        self._connecter(caissiere)

        reponse = self.client.get(
            reverse("core:marketing_qr_download", args=["site"])
        )

        self.assertEqual(reponse.status_code, 403)


class ServerLogFilterTests(SimpleTestCase):
    """
    Les sondes de sante ne doivent pas remplir le journal.

    Render interroge /health/ toutes les quatre secondes : vingt mille lignes
    par jour qui ne disent rien, et qui noient celles qui disent quelque chose.
    """

    def test_a_health_probe_is_not_written(self):
        self.assertFalse(doit_journaliser("/health/"))

    def test_the_detailed_probe_is_quiet_too(self):
        self.assertFalse(doit_journaliser("/health/details/"))

    def test_a_real_request_is_still_written(self):
        # Faire taire la sonde ne doit pas rendre le journal aveugle.
        self.assertTrue(doit_journaliser("/members/"))
        self.assertTrue(doit_journaliser("/access/devices/webhook/abc/"))

    def test_an_empty_path_is_written(self):
        # Dans le doute, on ecrit : une ligne de trop se lit, une ligne
        # manquante ne se devine pas.
        self.assertTrue(doit_journaliser(""))
        self.assertTrue(doit_journaliser(None))

    def test_the_server_configuration_uses_this_rule(self):
        # Le fichier de configuration ne s'importe pas sous Windows : on
        # verifie au moins qu'il s'appuie sur la regle testee ici.
        configuration = Path(settings.BASE_DIR, "gunicorn_conf.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("doit_journaliser", configuration)
        self.assertIn("logger_class", configuration)


class DashboardHonestyTests(TestCase):
    """
    Les chiffres du tableau de bord, apres le retour du client.

    Il ne demandait pas des indicateurs de plus : il demandait que ceux
    affiches veuillent dire quelque chose, et qu'ils n'apparaissent qu'une
    fois.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Tableau", slug="org-tableau"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Tableau",
            slug="gym-tableau", subdomain="gym-tableau",
        )
        for code in ("MEMBERS", "SUBSCRIPTIONS", "POS", "ACCESS", "MACHINES", "COACHING"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )

        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        self.gerant = User.objects.create_user(
            username="gerant-tableau", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    # --- Fabriques ---------------------------------------------------------------

    def _membre(self, prenom, abonne=True):
        membre = Member.objects.create(
            gym=self.gym, first_name=prenom, last_name="Tableau",
            phone=f"+24387{Member.objects.count():07d}", status="active",
        )
        if abonne:
            MemberSubscription.objects.create(
                gym=self.gym, member=membre, plan=self.plan,
                start_date=timezone.localdate() - timedelta(days=1),
                end_date=timezone.localdate() + timedelta(days=29),
                is_active=True,
            )
        return membre

    def _passage(self, membre=None, jour=None, is_return=False, accorde=True):
        log = AccessLog.objects.create(
            gym=self.gym, member=membre, access_granted=accorde,
            is_return=is_return,
        )
        if jour is not None:
            AccessLog.objects.filter(pk=log.pk).update(check_in_time=jour)
        return log

    def _vue(self, analytique=False):
        url = reverse("core:gym_dashboard", args=[self.gym.id])
        if analytique:
            url += "?view=analytics"
        return self.client.get(url)

    # --- Chaque information une seule fois ---------------------------------------

    def test_the_overview_shows_the_recent_accesses_once(self):
        # Le bloc de queue avait perdu sa garde de vue : il s'affichait dans
        # les deux vues, et le proprietaire lisait tout deux fois.
        page = self._vue().content.decode("utf-8")

        self.assertEqual(page.count("Derniers acc"), 1)

    def test_the_overview_shows_the_recent_payments_once(self):
        page = self._vue().content.decode("utf-8")

        self.assertEqual(page.count("Derniers paiements"), 1)

    def test_the_month_revenue_left_the_overview(self):
        # Il s'affichait deux fois. La question du proprietaire est "combien
        # avons-nous encaisse aujourd'hui" : le bloc caisse y repond, et le
        # cumul du mois releve de l'analyse.
        self.assertNotContains(self._vue(), "Mois en cours")

    def test_todays_takings_are_stated_once(self):
        page = self._vue().content.decode("utf-8")

        self.assertEqual(page.count("Encaissements"), 1)

    def test_the_duplicate_kpi_card_is_gone(self):
        # Elle ne contenait que des chiffres deja affiches au-dessus.
        self.assertNotContains(self._vue(), "Lecture KPI")
        self.assertNotContains(self._vue(analytique=True), "Lecture KPI")

    # --- Ce qui quitte la vue d'ensemble ------------------------------------------

    def test_machine_and_coaching_charts_leave_the_overview(self):
        # Leurs rubriques les portent deja : les garder ici allongeait la page
        # sans rien apprendre.
        page = self._vue()

        self.assertNotContains(page, "KPI machines")
        self.assertNotContains(page, "KPI coaching")

    def test_they_remain_in_the_analytics_view(self):
        page = self._vue(analytique=True)

        self.assertContains(page, "KPI machines")
        self.assertContains(page, "KPI coaching")

    # --- La moyenne journaliere ----------------------------------------------------

    def test_the_daily_average_divides_by_the_elapsed_days(self):
        # Au 11 du mois, diviser par 30 compterait 19 jours qui n'ont pas eu
        # lieu. C'est ce que le client avait repere.
        aujourd_hui = timezone.localdate()
        membre = self._membre("Ada")
        for _ in range(10):
            self._passage(membre)

        contexte = self._vue().context
        ecoules = (aujourd_hui - aujourd_hui.replace(day=1)).days + 1

        self.assertEqual(contexte["elapsed_days"], ecoules)
        self.assertEqual(contexte["average_daily_visits"], round(10 / ecoules, 1))

    def test_the_elapsed_days_never_exceed_the_period(self):
        contexte = self._vue().context

        self.assertLessEqual(contexte["elapsed_days"], contexte["period_days"])

    def test_a_single_day_period_divides_by_one(self):
        membre = self._membre("Ada")
        self._passage(membre)

        url = reverse("core:gym_dashboard", args=[self.gym.id]) + "?period=day"
        contexte = self.client.get(url).context

        self.assertEqual(contexte["elapsed_days"], 1)
        self.assertEqual(contexte["average_daily_visits"], 1.0)

    # --- L'assiduite remplace l'engagement -----------------------------------------

    def test_the_attendance_rate_never_exceeds_one_hundred(self):
        # L'ancien "engagement" affichait 180 % : il divisait les visiteurs de
        # la periode par les membres actifs du jour, deux populations
        # differentes.
        actif = self._membre("Ada")
        expire = Member.objects.create(
            gym=self.gym, first_name="Bob", last_name="Expire",
            phone="+243870999999", status="active",
        )
        for _ in range(4):
            self._passage(actif)
        self._passage(expire)

        contexte = self._vue().context

        self.assertLessEqual(contexte["attendance_rate"], 100)

    def test_the_attendance_rate_counts_active_members_who_came(self):
        venu = self._membre("Ada")
        self._membre("Bob")
        self._passage(venu)

        contexte = self._vue().context

        self.assertEqual(contexte["active_members_seen"], 1)
        self.assertEqual(contexte["attendance_rate"], 50.0)

    def test_a_member_who_came_twice_counts_once(self):
        venu = self._membre("Ada")
        self._passage(venu)
        self._passage(venu)

        self.assertEqual(self._vue().context["active_members_seen"], 1)

    def test_the_old_engagement_rate_is_gone(self):
        self.assertNotContains(self._vue(), "Engagement ")

    # --- Passages contre personnes ---------------------------------------------------

    def test_passages_and_people_are_counted_separately(self):
        # "15 entrees pour 5 membres actifs" : le mot entrees ne disait pas
        # s'il s'agissait de passages ou de personnes.
        ada = self._membre("Ada")
        bob = self._membre("Bob")
        self._passage(ada)
        self._passage(bob)
        self._passage(ada, is_return=True)

        contexte = self._vue().context

        # Le retour du meme jour n'est pas un passage de plus.
        self.assertEqual(contexte["today_checkins"], 2)
        self.assertEqual(contexte["today_unique_visitors"], 2)

    def test_a_manual_opening_is_a_passage_but_nobody(self):
        # Elle n'a ni membre ni invitation : la compter comme une personne
        # rangeait toutes les ouvertures manuelles sous un seul visiteur.
        self._passage(membre=None)
        self._passage(membre=None)

        contexte = self._vue().context

        self.assertEqual(contexte["today_checkins"], 2)
        self.assertEqual(contexte["today_unique_visitors"], 0)

    def test_the_page_says_how_many_people(self):
        ada = self._membre("Ada")
        self._passage(ada)

        self.assertContains(self._vue(), "Passages aujourd'hui")

    # --- La base de comparaison --------------------------------------------------------

    def test_a_trend_from_nothing_says_new_rather_than_a_hundred_percent(self):
        # "+100 %" est la valeur de repli quand la periode precedente est
        # vide : elle ne se distinguait pas d'un doublement.
        self._membre("Ada")

        contexte = self._vue().context

        self.assertEqual(contexte["new_members_trend"]["display"], "nouveau")
        self.assertIn("Rien", contexte["new_members_trend"]["basis"])

    def test_every_trend_carries_its_comparison_base(self):
        contexte = self._vue().context

        for cle in ("new_members_trend", "renewals_trend", "expirations_trend",
                    "visits_trend", "revenue_trend"):
            with self.subTest(cle=cle):
                self.assertIn("basis", contexte[cle])
                self.assertTrue(contexte[cle]["basis"])

    def test_the_base_is_shown_on_the_page(self):
        self.assertContains(self._vue(), "Periode precedente")

    # --- Les definitions ------------------------------------------------------------------

    def test_the_thresholds_no_longer_overlap(self):
        # Les paliers se recouvraient : un abonnement qui expire demain
        # comptait aussi dans J-3, J-7 et J-15. On les lisait comme quatre
        # personnes. Chaque abonnement ne figure plus que dans une tranche.
        self.assertContains(self._vue(analytique=True), "Tranches exclusives")

    def test_the_overview_states_the_inclusion_in_words(self):
        # La vue d'ensemble ne montre qu'un palier et son sous-ensemble : le
        # mot "dont" dit l'inclusion sans qu'il faille l'expliquer.
        self.assertContains(self._vue(), "dont")

    def test_the_active_member_definition_is_within_reach(self):
        self.assertContains(self._vue(), "photographie d'aujourd'hui")

    def test_the_daily_average_explains_its_divisor(self):
        # La carte est passee en vue analytique avec les autres KPI de
        # periode ; sa definition ne l'a pas quittee.
        self.assertContains(self._vue(analytique=True), "jours deja ecoules")


class MontantFilterTests(SimpleTestCase):
    """
    Le groupement des milliers.

    "1599739 CDF" oblige l'oeil a compter les chiffres pour savoir s'il s'agit
    d'un million ou de cent mille. En francs congolais, ou les sommes
    courantes depassent le million, c'est la difference entre un chiffre qu'on
    verifie et un chiffre qu'on croit.
    """

    def test_a_million_is_grouped(self):
        self.assertEqual(montant(1599739), "1\u00a0599\u00a0739")

    def test_the_separator_is_unbreakable(self):
        # Un montant coupe en fin de ligne se lit comme deux nombres.
        self.assertIn("\u00a0", montant(1599739))
        self.assertNotIn(" ", montant(1599739).replace("\u00a0", ""))

    def test_small_numbers_are_left_alone(self):
        self.assertEqual(montant(999), "999")

    def test_zero_stays_zero(self):
        self.assertEqual(montant(0), "0")

    def test_a_negative_amount_keeps_its_sign(self):
        self.assertEqual(montant(-5000), "-5\u00a0000")

    def test_decimals_are_shown_when_asked(self):
        self.assertEqual(montant("12.5", 2), "12,50")

    def test_an_unreadable_value_is_shown_rather_than_hidden(self):
        # Mieux vaut un affichage brut qu'un montant disparu.
        self.assertEqual(montant("abc"), "abc")

    def test_an_empty_value_reads_as_zero(self):
        self.assertEqual(montant(None), "0")

    def test_an_incoming_amount_carries_its_plus(self):
        self.assertEqual(montant_signe(12000), "+12\u00a0000")

    def test_an_outgoing_amount_keeps_its_minus(self):
        self.assertEqual(montant_signe(-12000), "-12\u00a0000")

    def test_zero_carries_no_sign(self):
        # Un ecart nul n'est ni un excedent ni un deficit.
        self.assertEqual(montant_signe(0), "0")


class DashboardRegisterBlockTests(TestCase):
    """
    La caisse en tete du tableau de bord.

    Le proprietaire y vient pour une question : combien est entre, combien est
    sorti, et le compte est-il bon. Le logiciel savait tout cela sans jamais
    le montrer.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Caisse", slug="org-caisse"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Caisse",
            slug="gym-caisse", subdomain="gym-caisse",
        )
        self.voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-caisse-voisine", subdomain="gym-caisse-voisine",
        )
        for code in ("MEMBERS", "POS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            for salle in (self.gym, self.voisine):
                GymModule.objects.get_or_create(
                    gym=salle, module=module, defaults={"is_active": True}
                )

        self.gerant = User.objects.create_user(
            username="gerant-caisse", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self.caissiere = User.objects.create_user(
            username="ada-caisse", password="pass12345", first_name="Ada",
            last_name="Mbala",
        )
        UserGymRole.objects.create(
            user=self.caissiere, gym=self.gym, role="cashier", is_active=True
        )
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    # --- Fabriques ---------------------------------------------------------------

    def _caisse(self, par=None, fonds="100000", gym=None):
        return CashRegister.objects.create(
            gym=gym or self.gym,
            opened_by=par or self.caissiere,
            opening_amount=Decimal(fonds),
            exchange_rate=Decimal("2800.00"),
        )

    def _mouvement(self, caisse, montant_cdf, sens="in", methode="cash",
                   motif="Abonnement"):
        return record_payment(
            gym=caisse.gym,
            register=caisse,
            amount=Decimal(montant_cdf),
            currency="CDF",
            method=methode,
            transaction_type=sens,
            category="subscription" if sens == "in" else "expense",
            description=motif,
            created_by=self.caissiere,
        )

    def _caisse_du_tableau(self):
        return self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id])
        ).context["caisse"]

    # --- Le statut ------------------------------------------------------------------

    def test_no_register_says_so_plainly(self):
        self.assertContains(
            self.client.get(reverse("core:gym_dashboard", args=[self.gym.id])),
            "Aucune caisse ouverte",
        )

    def test_an_open_register_names_its_holder(self):
        self._caisse()

        caisse = self._caisse_du_tableau()

        self.assertEqual(caisse["ouvertes"], 1)
        self.assertEqual(caisse["sessions"][0]["responsable"], "Ada Mbala")

    def test_the_opening_float_and_hour_are_shown(self):
        registre = self._caisse(fonds="150000")

        ligne = self._caisse_du_tableau()["sessions"][0]

        self.assertEqual(ligne["fonds_ouverture"], Decimal("150000.00"))
        self.assertEqual(ligne["ouverte_a"], registre.opened_at)

    def test_a_deleted_account_does_not_break_the_line(self):
        # opened_by est efface quand un compte disparait : la caisse, elle,
        # reste dans les comptes.
        registre = self._caisse()
        CashRegister.objects.filter(pk=registre.pk).update(opened_by=None)

        self.assertEqual(
            self._caisse_du_tableau()["sessions"][0]["responsable"],
            "Compte supprime",
        )

    # --- Les totaux --------------------------------------------------------------------

    def test_the_entries_and_exits_are_totalled(self):
        registre = self._caisse()
        self._mouvement(registre, "50000")
        self._mouvement(registre, "20000")
        self._mouvement(registre, "8000", sens="out", motif="Achat de savon")

        caisse = self._caisse_du_tableau()

        self.assertEqual(caisse["encaissements"], Decimal("70000.00"))
        self.assertEqual(caisse["decaissements"], Decimal("8000.00"))

    def test_the_expected_balance_is_the_drawer_not_the_revenue(self):
        # Fonds d'ouverture, plus les especes entrees, moins les especes
        # sorties.
        registre = self._caisse(fonds="100000")
        self._mouvement(registre, "50000")
        self._mouvement(registre, "8000", sens="out")

        self.assertEqual(
            self._caisse_du_tableau()["solde_theorique"], Decimal("142000.00")
        )

    def test_mobile_money_never_enters_the_drawer(self):
        # Ces billets ne sont jamais passes entre les mains du caissier : les
        # compter lui reprocherait un ecart sur de l'argent qu'il n'a pas.
        registre = self._caisse(fonds="100000")
        self._mouvement(registre, "50000", methode="mobile_money")

        caisse = self._caisse_du_tableau()

        self.assertEqual(caisse["encaissements"], Decimal("50000.00"))
        self.assertEqual(caisse["solde_theorique"], Decimal("100000.00"))

    def test_the_methods_are_broken_down(self):
        registre = self._caisse()
        self._mouvement(registre, "50000", methode="cash")
        self._mouvement(registre, "30000", methode="mobile_money")

        lignes = {
            ligne["code"]: ligne["total"]
            for ligne in self._caisse_du_tableau()["par_methode"]
        }

        self.assertEqual(lignes["cash"], Decimal("50000.00"))
        self.assertEqual(lignes["mobile_money"], Decimal("30000.00"))

    def test_an_unused_method_is_not_listed(self):
        registre = self._caisse()
        self._mouvement(registre, "50000", methode="cash")

        codes = [
            ligne["code"] for ligne in self._caisse_du_tableau()["par_methode"]
        ]

        self.assertNotIn("check", codes)

    # --- Plusieurs caissiers ------------------------------------------------------------

    def test_two_cashiers_make_two_lines(self):
        # Le systeme autorise une caisse ouverte par utilisateur : "le caissier
        # connecte" n'existe pas au singulier.
        autre = User.objects.create_user(
            username="bob-caisse", password="pass12345", first_name="Bob",
            last_name="Kasa",
        )
        UserGymRole.objects.create(
            user=autre, gym=self.gym, role="cashier", is_active=True
        )
        self._caisse(fonds="100000")
        self._caisse(par=autre, fonds="50000")

        caisse = self._caisse_du_tableau()

        self.assertEqual(len(caisse["sessions"]), 2)
        self.assertEqual(caisse["ouvertes"], 2)
        self.assertEqual(caisse["solde_theorique"], Decimal("150000.00"))

    def test_a_neighbouring_gym_register_stays_out(self):
        self._caisse(gym=self.voisine, fonds="999999")

        caisse = self._caisse_du_tableau()

        self.assertEqual(caisse["sessions"], [])
        self.assertEqual(caisse["solde_theorique"], Decimal("0.00"))

    # --- Les anomalies --------------------------------------------------------------------

    def test_a_register_left_open_since_yesterday_is_flagged(self):
        registre = self._caisse()
        CashRegister.objects.filter(pk=registre.pk).update(
            opened_at=timezone.now() - timedelta(days=1)
        )

        caisse = self._caisse_du_tableau()

        self.assertEqual(caisse["oubliee_depuis_hier"], 1)
        self.assertTrue(caisse["sessions"][0]["oubliee"])

    def test_a_register_opened_today_is_not_flagged(self):
        self._caisse()

        self.assertEqual(self._caisse_du_tableau()["oubliee_depuis_hier"], 0)

    def test_a_closed_register_shows_its_variance(self):
        registre = self._caisse(fonds="100000")
        self._mouvement(registre, "50000")
        registre.closing_amount = Decimal("148000.00")
        registre.difference = Decimal("-2000.00")
        registre.closed_by = self.caissiere
        registre.closed_at = timezone.now()
        registre.is_closed = True
        registre.save()

        caisse = self._caisse_du_tableau()

        self.assertEqual(caisse["ecart"], Decimal("-2000.00"))
        self.assertTrue(caisse["a_un_ecart"])
        self.assertTrue(caisse["sessions"][0]["est_compte"])

    def test_a_balanced_closing_is_not_an_anomaly(self):
        registre = self._caisse(fonds="100000")
        registre.closing_amount = Decimal("100000.00")
        registre.difference = Decimal("0.00")
        registre.closed_by = self.caissiere
        registre.closed_at = timezone.now()
        registre.is_closed = True
        registre.save()

        self.assertFalse(self._caisse_du_tableau()["a_un_ecart"])

    def test_a_forced_closing_is_visible(self):
        # Un gerant qui debloque un poste abandonne n'est pas une faute, mais
        # cela doit se voir.
        registre = self._caisse(fonds="100000")
        registre.closing_amount = Decimal("100000.00")
        registre.difference = Decimal("0.00")
        registre.closed_by = self.gerant
        registre.closed_at = timezone.now()
        registre.is_closed = True
        registre.save()

        self.assertTrue(self._caisse_du_tableau()["sessions"][0]["cloture_forcee"])

    def test_a_register_closed_yesterday_is_out_of_todays_view(self):
        registre = self._caisse(fonds="100000")
        registre.closing_amount = Decimal("100000.00")
        registre.difference = Decimal("0.00")
        registre.closed_by = self.caissiere
        registre.is_closed = True
        registre.save()
        CashRegister.objects.filter(pk=registre.pk).update(
            closed_at=timezone.now() - timedelta(days=1)
        )

        self.assertEqual(self._caisse_du_tableau()["sessions"], [])

    def test_a_negative_drawer_is_flagged(self):
        registre = self._caisse(fonds="1000")
        self._mouvement(registre, "5000", sens="out")

        self.assertTrue(
            self._caisse_du_tableau()["sessions"][0]["tresorerie_negative"]
        )

    # --- Ce que la page montre ---------------------------------------------------------------

    def test_the_amounts_are_grouped_on_the_page(self):
        registre = self._caisse(fonds="0")
        self._mouvement(registre, "1599739")

        page = self.client.get(reverse("core:gym_dashboard", args=[self.gym.id]))

        self.assertContains(page, GROUPE)
        # Et nulle part un montant affiche sans ses milliers. On vise le
        # nombre suivi de sa devise : les donnees des graphiques portent le
        # nombre brut, et c'est normal - le javascript en a besoin.
        self.assertNotContains(page, "1599739 CDF")


# Le bloc caisse affiche le total des "Decaissements" : chercher la sous-chaine
# nue ferait passer n'importe quel test. C'est la ligne qui compte.
# Le montant groupe attendu, separateur insecable compris.
GROUPE = "1" + chr(0xA0) + "599" + chr(0xA0) + "739"

# Le ton est neutre, pas rouge : une sortie d'argent ordinaire n'est pas une
# anomalie, et le rouge est reserve a ce qui appelle un geste aujourd'hui.
MARQUEUR_DECAISSEMENT = '<span class="ton-neutre fw-semibold">Decaissement</span>'


class PaymentOperationColumnTests(TestCase):
    """
    La colonne des dernieres operations.

    Les decaissements s'affichaient sous l'entete "Membre" - et, plus grave,
    le gabarit les reconnaissait a l'absence de membre. Une vente au comptoir
    n'a pas de membre non plus : elle etait etiquetee decaissement.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Operation", slug="org-operation"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Operation",
            slug="gym-operation", subdomain="gym-operation",
        )
        for code in ("MEMBERS", "POS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )
        self.gerant = User.objects.create_user(
            username="gerant-operation", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self.registre = CashRegister.objects.create(
            gym=self.gym, opened_by=self.gerant,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _page(self):
        return self.client.get(reverse("core:gym_dashboard", args=[self.gym.id]))

    def test_the_column_is_no_longer_called_member(self):
        self.assertContains(self._page(), "<th>Operation</th>", html=False)

    def test_a_disbursement_shows_its_reason(self):
        record_payment(
            gym=self.gym, register=self.registre, amount=Decimal("8000"),
            currency="CDF", method="cash", transaction_type="out",
            category="expense", description="Reparation du portail",
            created_by=self.gerant,
        )

        page = self._page()

        self.assertContains(page, "Reparation du portail")
        self.assertContains(page, MARQUEUR_DECAISSEMENT)

    def test_a_counter_sale_is_not_labelled_a_disbursement(self):
        # C'etait le vrai defaut : le gabarit se fiait a l'absence de membre.
        record_payment(
            gym=self.gym, register=self.registre, amount=Decimal("5000"),
            currency="CDF", method="cash", transaction_type="in",
            category="product", description="Bouteille d eau",
            created_by=self.gerant,
        )

        page = self._page()

        self.assertContains(page, "Vente au comptoir")
        # Pas "Decaissement" tout court : le bloc caisse affiche le total des
        # "Decaissements", et la sous-chaine suffirait a faire passer le test.
        self.assertNotContains(page, MARQUEUR_DECAISSEMENT)

    def test_a_member_payment_still_shows_the_member(self):
        membre = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243870112233",
        )
        record_payment(
            gym=self.gym, register=self.registre, member=membre,
            amount=Decimal("30000"), currency="CDF", method="cash",
            transaction_type="in", category="subscription",
            description="Abonnement mensuel", created_by=self.gerant,
        )

        page = self._page()

        self.assertContains(page, "Ada")
        self.assertNotContains(page, MARQUEUR_DECAISSEMENT)

    def test_the_english_method_labels_are_gone(self):
        record_payment(
            gym=self.gym, register=self.registre, amount=Decimal("5000"),
            currency="CDF", method="cash", transaction_type="in",
            category="product", description="Bouteille", created_by=self.gerant,
        )

        page = self._page()

        self.assertContains(page, "Especes")
        self.assertNotContains(page, ">Cash<")


class DashboardLayoutTests(TestCase):
    """
    La vue d'ensemble, reduite aux cinq blocs du client.

    Caisse, activite, membres, alertes, actions - dans cet ordre, et rien
    d'autre avant la ligne de flottaison. Le reste releve de l'analyse.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Disposition", slug="org-disposition"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Disposition",
            slug="gym-disposition", subdomain="gym-disposition",
        )
        for code in ("MEMBERS", "SUBSCRIPTIONS", "POS", "ACCESS", "MACHINES", "PRODUCTS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )
        self.gerant = User.objects.create_user(
            username="gerant-disposition", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _vue(self, analytique=False):
        url = reverse("core:gym_dashboard", args=[self.gym.id])
        if analytique:
            url += "?view=analytics"
        return self.client.get(url)

    # --- Les cinq blocs, dans l'ordre --------------------------------------------

    def test_the_five_blocks_are_present(self):
        page = self._vue()

        for titre in ("Caisse du jour", "Passages aujourd'hui",
                      "Abonnements actifs", "Alertes urgentes",
                      "Inscrire un membre"):
            with self.subTest(titre=titre):
                self.assertContains(page, titre)

    def test_they_come_in_the_order_he_asked_for(self):
        page = self._vue().content.decode("utf-8")

        positions = [
            page.index("Caisse du jour"),
            page.index("Passages aujourd'hui"),
            page.index("Abonnements actifs"),
            page.index("Alertes urgentes"),
            page.index("Inscrire un membre"),
        ]

        self.assertEqual(positions, sorted(positions))

    def test_the_peak_hour_came_back_to_the_overview(self):
        # Elle etait partie en analytique a la passe 1 : il la veut en haut.
        self.assertContains(self._vue(), "Heure de pointe")

    def test_recording_an_expense_is_one_of_the_quick_actions(self):
        self.assertContains(self._vue(), "Enregistrer une depense")

    # --- Ce qui quitte la vue d'ensemble -----------------------------------------

    def test_the_shared_kpi_rows_moved_to_analytics(self):
        page = self._vue()

        self.assertNotContains(page, "Renouvellements")
        self.assertNotContains(page, "Moyenne journalière")

    def test_they_are_still_there_in_analytics(self):
        page = self._vue(analytique=True)

        self.assertContains(page, "Renouvellements")
        self.assertContains(page, "Moyenne journalière")

    def test_the_superseded_member_alerts_card_is_gone(self):
        # Ses paliers vivent dans le bloc Membres, ses impayes aussi.
        self.assertNotContains(self._vue(), "Alertes membres")

    def test_the_expiry_thresholds_are_stated_once(self):
        page = self._vue().content.decode("utf-8")

        self.assertEqual(page.count("Expirent sous 7 jours"), 1)


class DashboardUrgentAlertTests(TestCase):
    """
    Les alertes urgentes.

    Une alerte qui sonne tous les jours ne se lit plus : n'arrive ici que ce
    qui demande un geste aujourd'hui.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Alerte", slug="org-alerte"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Alerte",
            slug="gym-alerte", subdomain="gym-alerte",
        )
        for code in ("MEMBERS", "POS", "ACCESS", "MACHINES", "PRODUCTS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        self.gerant = User.objects.create_user(
            username="gerant-alerte", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _membre(self, prenom="Ada"):
        return Member.objects.create(
            gym=self.gym, first_name=prenom, last_name="Mbala",
            phone=f"+24387{Member.objects.count():07d}", status="active",
        )

    def _alertes(self):
        return self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id])
        ).context["alertes_urgentes"]

    # --- Rien a signaler ----------------------------------------------------------

    def test_a_quiet_day_raises_nothing(self):
        self.assertEqual(self._alertes(), [])

    def test_a_quiet_day_says_so(self):
        self.assertContains(
            self.client.get(reverse("core:gym_dashboard", args=[self.gym.id])),
            "Rien a signaler",
        )

    # --- La caisse -----------------------------------------------------------------

    def test_a_register_left_open_since_yesterday_raises_an_alert(self):
        registre = CashRegister.objects.create(
            gym=self.gym, opened_by=self.gerant,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        CashRegister.objects.filter(pk=registre.pk).update(
            opened_at=timezone.now() - timedelta(days=1)
        )

        titres = [alerte["titre"] for alerte in self._alertes()]

        self.assertTrue(any("non clôturee" in titre for titre in titres))

    def test_a_register_opened_today_raises_nothing(self):
        CashRegister.objects.create(
            gym=self.gym, opened_by=self.gerant,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )

        self.assertEqual(self._alertes(), [])

    # --- Les refus repetes -----------------------------------------------------------

    def test_a_single_refusal_is_not_an_anomaly(self):
        # Un abonnement echu se presente, la porte reste fermee : le
        # dispositif fonctionne.
        membre = self._membre()
        AccessLog.objects.create(gym=self.gym, member=membre, access_granted=False)

        self.assertEqual(self._alertes(), [])

    def test_three_refusals_on_the_same_person_are(self):
        membre = self._membre()
        for _ in range(3):
            AccessLog.objects.create(
                gym=self.gym, member=membre, access_granted=False
            )

        titres = [alerte["titre"] for alerte in self._alertes()]

        self.assertTrue(any("Ada" in titre for titre in titres))

    def test_refusals_spread_over_several_people_are_not(self):
        # Trois personnes refusees une fois chacune, c'est une journee
        # ordinaire dans une salle ou des abonnements expirent.
        for prenom in ("Ada", "Bob", "Zoe"):
            AccessLog.objects.create(
                gym=self.gym, member=self._membre(prenom), access_granted=False
            )

        self.assertEqual(self._alertes(), [])

    def test_yesterdays_refusals_do_not_count(self):
        membre = self._membre()
        for _ in range(3):
            log = AccessLog.objects.create(
                gym=self.gym, member=membre, access_granted=False
            )
            AccessLog.objects.filter(pk=log.pk).update(
                check_in_time=timezone.now() - timedelta(days=1)
            )

        self.assertEqual(self._alertes(), [])

    def test_a_granted_passage_is_not_a_refusal(self):
        membre = self._membre()
        for _ in range(3):
            AccessLog.objects.create(
                gym=self.gym, member=membre, access_granted=True
            )

        self.assertEqual(self._alertes(), [])

    # --- Les echeances ------------------------------------------------------------------

    def test_an_expiry_within_48_hours_is_urgent(self):
        MemberSubscription.objects.create(
            gym=self.gym, member=self._membre(), plan=self.plan,
            start_date=timezone.localdate() - timedelta(days=29),
            end_date=timezone.localdate() + timedelta(days=1),
            is_active=True,
        )

        titres = [alerte["titre"] for alerte in self._alertes()]

        self.assertTrue(any("48 h" in titre for titre in titres))

    def test_an_expiry_in_five_days_is_not_urgent(self):
        # Elle figure dans le bloc Membres : une alerte qui sonne tous les
        # jours ne se lit plus.
        MemberSubscription.objects.create(
            gym=self.gym, member=self._membre(), plan=self.plan,
            start_date=timezone.localdate() - timedelta(days=25),
            end_date=timezone.localdate() + timedelta(days=5),
            is_active=True,
        )

        self.assertEqual(self._alertes(), [])

    # --- Le parc et le stock ----------------------------------------------------------------

    def test_a_broken_machine_is_raised(self):
        Machine.objects.create(
            gym=self.gym, name="Tapis A", status=Machine.STATUS_BROKEN,
        )

        titres = [alerte["titre"] for alerte in self._alertes()]

        self.assertTrue(any("panne" in titre for titre in titres))

    def test_a_working_machine_is_not(self):
        Machine.objects.create(gym=self.gym, name="Tapis A", status=Machine.STATUS_OK)

        self.assertEqual(self._alertes(), [])

    # --- Le cloisonnement -----------------------------------------------------------------

    def test_a_neighbouring_gym_raises_nothing_here(self):
        voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-alerte-voisine", subdomain="gym-alerte-voisine",
        )
        membre = Member.objects.create(
            gym=voisine, first_name="Zoe", last_name="Ailleurs",
            phone="+243879999999", status="active",
        )
        for _ in range(3):
            AccessLog.objects.create(
                gym=voisine, member=membre, access_granted=False
            )

        self.assertEqual(self._alertes(), [])


class BrandIdentityTests(TestCase):
    """
    La marque dans la barre laterale.

    Le client voyait "Royal Gym" ecrit deux fois, l'un sous l'autre, et croyait
    a un defaut de maquette. C'est que l'organisation et la salle portent le
    meme nom chez lui.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Royal Gym", slug="org-marque"
        )
        self.gerant = User.objects.create_user(
            username="gerant-marque", password="pass12345"
        )

    def _connecter(self, gym):
        UserGymRole.objects.get_or_create(
            user=self.gerant, gym=gym, defaults={"role": "manager", "is_active": True}
        )
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = gym.id
        session.save()

    def _marque(self, gym):
        self._connecter(gym)
        module, _ = Module.objects.get_or_create(
            code="MEMBERS", defaults={"name": "MEMBERS"}
        )
        GymModule.objects.get_or_create(
            gym=gym, module=module, defaults={"is_active": True}
        )
        return self.client.get(reverse("members:member_list")).context

    def test_a_gym_named_like_its_organization_is_not_repeated(self):
        gym = Gym.objects.create(
            organization=self.organization, name="Royal Gym",
            slug="gym-marque", subdomain="gym-marque",
        )

        contexte = self._marque(gym)

        self.assertEqual(contexte["organization_brand_name"], "Royal Gym")
        self.assertEqual(contexte["organization_brand_gym_name"], "")

    def test_the_comparison_ignores_case_and_spacing(self):
        gym = Gym.objects.create(
            organization=self.organization, name="  royal gym ",
            slug="gym-marque-casse", subdomain="gym-marque-casse",
        )

        self.assertEqual(self._marque(gym)["organization_brand_gym_name"], "")

    def test_a_gym_with_its_own_name_is_still_shown(self):
        # Une organisation a plusieurs salles : c'est precisement le cas ou la
        # seconde ligne sert a quelque chose.
        gym = Gym.objects.create(
            organization=self.organization, name="Royal Gym Gombe",
            slug="gym-marque-gombe", subdomain="gym-marque-gombe",
        )

        self.assertEqual(
            self._marque(gym)["organization_brand_gym_name"], "Royal Gym Gombe"
        )

    def test_the_initials_keep_both_names(self):
        # Ce sont elles qui distinguent les salles quand le menu est replie.
        gym = Gym.objects.create(
            organization=self.organization, name="Royal Gym",
            slug="gym-marque-initiales", subdomain="gym-marque-initiales",
        )

        self.assertEqual(self._marque(gym)["organization_brand_initials"], "RR")


class HeaderSearchTests(TestCase):
    """
    Retrouver un membre depuis n'importe quel ecran.

    La liste des membres sait deja chercher : l'en-tete lui passe la main
    plutot que d'ouvrir un second point d'entree a securiser.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Recherche", slug="org-recherche"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Recherche",
            slug="gym-recherche", subdomain="gym-recherche",
        )
        for code in ("MEMBERS", "POS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )
        Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243870334455",
        )
        Member.objects.create(
            gym=self.gym, first_name="Bob", last_name="Kasa",
            phone="+243870556677",
        )

    def _connecter(self, role):
        utilisateur = User.objects.create_user(
            username=f"{role}-recherche", password="pass12345"
        )
        UserGymRole.objects.create(
            user=utilisateur, gym=self.gym, role=role, is_active=True
        )
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()
        return utilisateur

    def test_the_search_box_is_in_the_header(self):
        self._connecter("manager")

        reponse = self.client.get(reverse("members:member_list"))

        self.assertContains(reponse, "Rechercher un membre")

    def test_the_header_stays_on_one_line(self):
        # Une premiere version laissait l'en-tete passer a la ligne : le
        # selecteur de salle descendait et la pastille de notification se
        # retrouvait coupee. La recherche retrecit, l'en-tete ne s'enroule pas.
        self._connecter("manager")

        page = self.client.get(reverse("members:member_list")).content.decode("utf-8")

        self.assertIn('class="header-right ms-auto d-flex align-items-center gap-3"', page)
        self.assertNotIn("header-right ms-auto d-flex align-items-center flex-wrap", page)

    def test_it_leads_to_the_member_list(self):
        self._connecter("manager")

        reponse = self.client.get(reverse("members:member_list"), {"search": "Ada"})

        self.assertContains(reponse, "Ada")
        self.assertNotContains(reponse, "Kasa")

    def test_it_also_finds_a_phone_number(self):
        self._connecter("manager")

        reponse = self.client.get(
            reverse("members:member_list"), {"search": "556677"}
        )

        self.assertContains(reponse, "Kasa")

    def test_a_cashier_who_cannot_see_members_gets_no_box(self):
        # Le champ mene a la liste des membres : l'afficher a qui ne peut pas
        # l'ouvrir promettrait une porte fermee.
        self._connecter("cashier")

        reponse = self.client.get(reverse("pos:cashier_dashboard"))

        self.assertNotContains(reponse, "Rechercher un membre")


class SemanticColourTests(TestCase):
    """
    Les couleurs disent quelque chose.

    Vert normal, orange a surveiller, rouge anomalie urgente, or information
    strategique. Un decaissement ordinaire etait affiche en rouge : le rouge
    devenait banal, et les vraies alertes s'y noyaient.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Couleur", slug="org-couleur"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Couleur",
            slug="gym-couleur", subdomain="gym-couleur",
        )
        for code in ("MEMBERS", "POS", "ACCESS", "MACHINES", "PRODUCTS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )
        self.gerant = User.objects.create_user(
            username="gerant-couleur", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self.registre = CashRegister.objects.create(
            gym=self.gym, opened_by=self.gerant,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _page(self):
        return self.client.get(reverse("core:gym_dashboard", args=[self.gym.id]))

    def test_an_ordinary_disbursement_is_not_painted_as_an_anomaly(self):
        record_payment(
            gym=self.gym, register=self.registre, amount=Decimal("8000"),
            currency="CDF", method="cash", transaction_type="out",
            category="expense", description="Achat de savon",
            created_by=self.gerant,
        )

        page = self._page().content.decode("utf-8")

        self.assertIn("ton-neutre", page)
        # Et surtout pas le ton d'urgence : la journee est ordinaire, une
        # depense de savon n'appelle aucun geste. Verifier la seule presence du
        # neutre laissait passer une ligne repeinte en rouge.
        self.assertNotIn("ton-urgent", page)

    def test_a_quiet_day_shows_no_urgent_tone(self):
        page = self._page().content.decode("utf-8")

        self.assertNotIn("ton-urgent", page)

    def test_a_register_left_open_since_yesterday_turns_urgent(self):
        CashRegister.objects.filter(pk=self.registre.pk).update(
            opened_at=timezone.now() - timedelta(days=1)
        )

        page = self._page().content.decode("utf-8")

        self.assertIn("bord-urgent", page)

    def test_a_broken_machine_asks_for_attention_not_urgency(self):
        Machine.objects.create(
            gym=self.gym, name="Tapis A", status=Machine.STATUS_BROKEN
        )

        page = self._page().content.decode("utf-8")

        self.assertIn("bord-attention", page)
        self.assertNotIn("bord-urgent", page)

    def test_the_view_names_the_meaning_not_the_colour(self):
        # La feuille de style decide de la teinte, et elle seule.
        CashRegister.objects.filter(pk=self.registre.pk).update(
            opened_at=timezone.now() - timedelta(days=1)
        )

        tons = {alerte["ton"] for alerte in self._page().context["alertes_urgentes"]}

        self.assertTrue(tons)
        self.assertTrue(tons <= {"urgent", "attention"}, tons)

    def test_the_key_figures_are_set_apart(self):
        self.assertContains(self._page(), "chiffre-cle")

    def _palette(self):
        return (
            Path(settings.BASE_DIR) / "static" / "css" / "palette.css"
        ).read_text(encoding="utf-8")

    def _bloc_racine(self):
        """Le bloc :root seul - le mode sombre redefinit les memes variables."""
        palette = self._palette()
        debut = palette.index(":root {")
        return palette[debut:palette.index("}", debut)]

    def test_the_brand_gold_matches_the_logo(self):
        # L'or du logo est clair et metallique. Celui du theme etait beaucoup
        # plus fonce : ce n'etait pas la marque du client. On lit le bloc
        # :root et non le fichier entier, sinon la ligne du mode sombre - qui
        # porte deja cette valeur - suffirait a faire passer le test.
        self.assertIn("--royal-or: #C9A227;", self._bloc_racine())

    def test_the_readable_gold_is_darker_than_the_logo(self):
        # Sur fond blanc, l'or du logo tombe a 2,3:1 de contraste. Ce qui se
        # lit prend donc le meme or, assombri.
        self.assertIn("--royal-or-texte: #8A6D1D;", self._bloc_racine())
        self.assertIn(".ton-strategique { color: var(--royal-or-texte)", self._palette())

    def test_the_live_templates_no_longer_hardcode_the_gold(self):
        # Il etait recopie a la main : changer la teinte demandait de les
        # retrouver tous. Les couleurs des graphiques restent en dur - un
        # canvas ne lit pas les variables CSS.
        racine = Path(settings.BASE_DIR)
        for chemin in (
            "templates/include/header.html",
            "templates/include/navigation.html",
            "core/templates/core/select_gym.html",
        ):
            with self.subTest(chemin=chemin):
                self.assertNotIn("#8A6D1D", (racine / chemin).read_text(encoding="utf-8"))

    def test_the_palette_is_loaded_after_the_theme(self):
        # Chargee avant, elle perdrait contre le theme et le mode sombre.
        page = self._page().content.decode("utf-8")

        self.assertLess(page.index("theme.min.css"), page.index("palette.css"))
        self.assertLess(page.index("dark-mode-pages.css"), page.index("palette.css"))


class RegisterValidationTests(TestCase):
    """
    La contre-signature d'une clôture.

    Clôturer, c'est compter le tiroir ; valider, c'est qu'une seconde personne
    l'ait regarde. Un caissier qui compte seul et signe seul n'est controle par
    personne.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Validation", slug="org-validation"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Validation",
            slug="gym-validation", subdomain="gym-validation",
        )
        module, _ = Module.objects.get_or_create(code="POS", defaults={"name": "POS"})
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.caissiere = self._utilisateur("ada-validation", "cashier")
        self.gerant = self._utilisateur("gerant-validation", "manager")
        self.proprietaire = self._utilisateur("proprio-validation", "owner")

    def _utilisateur(self, nom, role):
        utilisateur = User.objects.create_user(username=nom, password="pass12345")
        UserGymRole.objects.create(
            user=utilisateur, gym=self.gym, role=role, is_active=True
        )
        return utilisateur

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _caisse_close(self, par=None, ecart="0.00"):
        registre = CashRegister.objects.create(
            gym=self.gym, opened_by=self.caissiere,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        registre.closing_amount = Decimal("100000.00") + Decimal(ecart)
        registre.difference = Decimal(ecart)
        registre.closed_by = par or self.caissiere
        registre.closed_at = timezone.now()
        registre.is_closed = True
        registre.save()
        return registre

    def _valider(self, registre, motif=""):
        return self.client.post(
            reverse("pos:validate_register", args=[registre.id]),
            {"validation_note": motif} if motif else {},
            follow=True,
        )

    # --- Ce que la validation enregistre ------------------------------------------

    def test_a_manager_can_countersign_a_cashiers_closing(self):
        registre = self._caisse_close()
        self._connecter(self.gerant)

        self._valider(registre)

        registre.refresh_from_db()
        self.assertTrue(registre.is_validated)
        self.assertEqual(registre.validated_by, self.gerant)

    def test_an_owner_can_countersign_a_managers_closing(self):
        registre = self._caisse_close(par=self.gerant)
        self._connecter(self.proprietaire)

        self._valider(registre)

        registre.refresh_from_db()
        self.assertEqual(registre.validated_by, self.proprietaire)

    def test_a_closed_register_starts_unvalidated(self):
        registre = self._caisse_close()

        self.assertFalse(registre.is_validated)
        self.assertTrue(registre.needs_validation)

    def test_an_open_register_is_not_waiting_for_a_signature(self):
        # On ne contre-signe pas ce qui n'a pas encore ete compte.
        registre = CashRegister.objects.create(
            gym=self.gym, opened_by=self.caissiere,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )

        self.assertFalse(registre.needs_validation)

    # --- Ce qui est refuse ---------------------------------------------------------

    def test_whoever_closed_cannot_countersign(self):
        # C'est tout le sens du dispositif : deux personnes ont regarde le
        # tiroir.
        registre = self._caisse_close(par=self.gerant)
        self._connecter(self.gerant)

        self._valider(registre)

        registre.refresh_from_db()
        self.assertFalse(registre.is_validated)

    def test_a_cashier_cannot_countersign(self):
        registre = self._caisse_close(par=self.gerant)
        self._connecter(self.caissiere)

        reponse = self.client.post(
            reverse("pos:validate_register", args=[registre.id])
        )

        self.assertEqual(reponse.status_code, 403)

    def test_a_variance_cannot_be_signed_without_a_reason(self):
        # Valider un ecart sans dire pourquoi ne vaut rien : dans six mois,
        # personne ne saura de quoi il s'agissait.
        registre = self._caisse_close(ecart="-2000.00")
        self._connecter(self.gerant)

        self._valider(registre)

        registre.refresh_from_db()
        self.assertFalse(registre.is_validated)

    def test_a_variance_signed_with_a_reason_goes_through(self):
        registre = self._caisse_close(ecart="-2000.00")
        self._connecter(self.gerant)

        self._valider(registre, motif="Rendu de monnaie non enregistre")

        registre.refresh_from_db()
        self.assertTrue(registre.is_validated)
        self.assertEqual(registre.validation_note, "Rendu de monnaie non enregistre")

    def test_a_balanced_register_needs_no_reason(self):
        registre = self._caisse_close(ecart="0.00")
        self._connecter(self.gerant)

        self._valider(registre)

        registre.refresh_from_db()
        self.assertTrue(registre.is_validated)

    def test_signing_twice_keeps_the_first_signature(self):
        registre = self._caisse_close()
        self._connecter(self.gerant)
        self._valider(registre)
        registre.refresh_from_db()
        premier = registre.validated_at

        self._connecter(self.proprietaire)
        self._valider(registre)

        registre.refresh_from_db()
        self.assertEqual(registre.validated_at, premier)
        self.assertEqual(registre.validated_by, self.gerant)

    def test_a_neighbouring_gym_register_cannot_be_signed(self):
        voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-validation-voisine", subdomain="gym-validation-voisine",
        )
        ailleurs = CashRegister.objects.create(
            gym=voisine, opened_by=self.caissiere,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
            is_closed=True, closed_at=timezone.now(), closed_by=self.caissiere,
            closing_amount=Decimal("100000.00"), difference=Decimal("0.00"),
        )
        self._connecter(self.gerant)

        reponse = self.client.post(
            reverse("pos:validate_register", args=[ailleurs.id])
        )

        self.assertEqual(reponse.status_code, 404)

    # --- Ce que le tableau de bord en dit ---------------------------------------------

    def test_an_unsigned_closing_raises_an_alert(self):
        self._caisse_close()
        self._connecter(self.gerant)

        alertes = self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id])
        ).context["alertes_urgentes"]

        self.assertTrue(any("contre-signer" in a["titre"] for a in alertes))

    def test_a_signed_closing_raises_nothing(self):
        registre = self._caisse_close()
        self._connecter(self.gerant)
        self._valider(registre)

        alertes = self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id])
        ).context["alertes_urgentes"]

        self.assertFalse(any("contre-signer" in a["titre"] for a in alertes))


class RegisterMotiveTests(TestCase):
    """
    Les motifs sous le total des decaissements.

    Un total ne dit pas ou l'argent est parti, et c'est pourtant la question
    qu'on se pose en lisant le chiffre.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Motif", slug="org-motif"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Motif",
            slug="gym-motif", subdomain="gym-motif",
        )
        for code in ("MEMBERS", "POS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )
        self.gerant = User.objects.create_user(
            username="gerant-motif", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self.registre = CashRegister.objects.create(
            gym=self.gym, opened_by=self.gerant,
            opening_amount=Decimal("500000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _sortie(self, motif, montant):
        return record_payment(
            gym=self.gym, register=self.registre, amount=Decimal(montant),
            currency="CDF", method="cash", transaction_type="out",
            category="expense", description=motif, created_by=self.gerant,
        )

    def _caisse(self):
        return self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id])
        ).context["caisse"]

    def test_a_disbursement_shows_its_reason_next_to_the_total(self):
        self._sortie("Reparation du portail", "30000")

        motifs = self._caisse()["motifs"]

        self.assertEqual(motifs[0]["motif"], "Reparation du portail")
        self.assertEqual(motifs[0]["montant"], Decimal("30000.00"))

    def test_the_biggest_come_first(self):
        # Ce sont elles qui expliquent l'essentiel du total.
        self._sortie("Savon", "5000")
        self._sortie("Plomberie", "30000")

        motifs = [ligne["motif"] for ligne in self._caisse()["motifs"]]

        self.assertEqual(motifs, ["Plomberie", "Savon"])

    def test_beyond_four_the_rest_is_counted(self):
        for index in range(6):
            self._sortie(f"Depense {index}", str(1000 * (index + 1)))

        caisse = self._caisse()

        self.assertEqual(len(caisse["motifs"]), 4)
        self.assertEqual(caisse["autres_sorties"], 2)

    def test_an_incoming_payment_is_not_a_reason(self):
        record_payment(
            gym=self.gym, register=self.registre, amount=Decimal("30000"),
            currency="CDF", method="cash", transaction_type="in",
            category="subscription", description="Abonnement",
            created_by=self.gerant,
        )

        self.assertEqual(self._caisse()["motifs"], [])

    def test_a_disbursement_without_a_reason_says_so(self):
        self._sortie("", "5000")

        self.assertEqual(self._caisse()["motifs"][0]["motif"], "Sans motif")

    def test_the_reasons_reach_the_page(self):
        self._sortie("Reparation du portail", "30000")

        self.assertContains(
            self.client.get(reverse("core:gym_dashboard", args=[self.gym.id])),
            "Reparation du portail",
        )


class GlobalSearchTests(TestCase):
    """
    La recherche globale.

    Un membre, un abonnement ou un paiement, depuis n'importe quel ecran - et
    chaque rubrique seulement pour qui a le droit de la lire.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Globale", slug="org-globale"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Globale",
            slug="gym-globale", subdomain="gym-globale",
        )
        self.voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-globale-voisine", subdomain="gym-globale-voisine",
        )
        for code in ("MEMBERS", "SUBSCRIPTIONS", "POS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            for salle in (self.gym, self.voisine):
                GymModule.objects.get_or_create(
                    gym=salle, module=module, defaults={"is_active": True}
                )

        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Premium", price=50, duration_days=30
        )
        self.membre = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243870778899",
        )
        MemberSubscription.objects.create(
            gym=self.gym, member=self.membre, plan=self.plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )
        self.gerant = self._utilisateur("gerant-globale", "manager")
        self.registre = CashRegister.objects.create(
            gym=self.gym, opened_by=self.gerant,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        record_payment(
            gym=self.gym, register=self.registre, amount=Decimal("30000"),
            currency="CDF", method="cash", transaction_type="out",
            category="expense", description="Reparation du portail",
            created_by=self.gerant,
        )
        self._connecter(self.gerant)

    def _utilisateur(self, nom, role):
        utilisateur = User.objects.create_user(username=nom, password="pass12345")
        UserGymRole.objects.create(
            user=utilisateur, gym=self.gym, role=role, is_active=True
        )
        return utilisateur

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _chercher(self, requete):
        return self.client.get(reverse("core:global_search"), {"q": requete})

    def _sections(self, requete):
        return {
            section["titre"]: section
            for section in self._chercher(requete).context["sections"]
        }

    # --- Les quatre facons de retrouver un paiement ---------------------------------

    def test_a_payment_is_found_by_the_member_name(self):
        record_payment(
            gym=self.gym, register=self.registre, member=self.membre,
            amount=Decimal("50000"), currency="CDF", method="cash",
            transaction_type="in", category="subscription",
            description="Abonnement Premium", created_by=self.gerant,
        )

        self.assertEqual(self._sections("Mbala")["Paiements"]["total"], 1)

    def test_a_payment_is_found_by_its_reason(self):
        # C'est le seul texte libre d'un decaissement : sans lui, une depense
        # est introuvable.
        self.assertEqual(self._sections("portail")["Paiements"]["total"], 1)

    def test_a_payment_is_found_by_its_amount(self):
        self.assertEqual(self._sections("30000")["Paiements"]["total"], 1)

    def test_a_spaced_amount_is_read_as_a_number(self):
        # On tape "30 000" comme on le lit a l'ecran.
        self.assertEqual(self._sections("30 000")["Paiements"]["total"], 1)

    def test_a_payment_is_found_by_its_session_code(self):
        self.registre.refresh_from_db()

        self.assertEqual(
            self._sections(self.registre.session_code)["Paiements"]["total"], 1
        )

    def test_a_name_is_not_read_as_an_amount(self):
        self.assertEqual(self._sections("Ada")["Paiements"]["total"], 0)

    # --- Les autres rubriques ----------------------------------------------------------

    def test_a_member_is_found_by_name(self):
        self.assertEqual(self._sections("Ada")["Membres"]["total"], 1)

    def test_a_member_is_found_by_phone(self):
        self.assertEqual(self._sections("778899")["Membres"]["total"], 1)

    def test_a_subscription_is_found_by_its_plan(self):
        self.assertEqual(self._sections("Premium")["Abonnements"]["total"], 1)

    def test_a_subscription_is_found_by_the_member(self):
        self.assertEqual(self._sections("Mbala")["Abonnements"]["total"], 1)

    # --- Le cloisonnement et les droits -------------------------------------------------

    def test_a_neighbouring_gym_stays_out(self):
        Member.objects.create(
            gym=self.voisine, first_name="Zoe", last_name="Ailleurs",
            phone="+243870990000",
        )

        self.assertEqual(self._sections("Ailleurs")["Membres"]["total"], 0)

    def test_a_receptionist_sees_members_but_no_payments(self):
        # Les droits ne se relachent pas parce qu'on est passe par la
        # recherche.
        self._connecter(self._utilisateur("accueil-globale", "reception"))

        sections = self._sections("Mbala")

        self.assertIn("Membres", sections)
        self.assertNotIn("Paiements", sections)
        self.assertNotIn("Abonnements", sections)

    def test_a_manager_sees_the_three_sections(self):
        sections = self._sections("Mbala")

        self.assertEqual(
            set(sections), {"Membres", "Abonnements", "Paiements"}
        )

    # --- Les cas vides ------------------------------------------------------------------

    def test_an_empty_query_shows_the_invitation(self):
        reponse = self.client.get(reverse("core:global_search"))

        self.assertEqual(reponse.context["total"], 0)
        self.assertContains(reponse, "Tapez un nom")

    def test_a_query_that_finds_nothing_says_so(self):
        reponse = self._chercher("zzzzzz")

        self.assertEqual(reponse.context["total"], 0)
        self.assertContains(reponse, "Rien ne correspond")

    def test_the_header_leads_to_the_global_search(self):
        page = self.client.get(
            reverse("members:member_list")
        ).content.decode("utf-8")

        self.assertIn(reverse("core:global_search"), page)


class SearchResultDestinationTests(TestCase):
    """
    Ou mene un resultat.

    Renvoyer vers la liste complete obligeait a recommencer la recherche sur
    place : on avait trouve la personne, et il fallait la retrouver.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Destination", slug="org-destination"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Destination",
            slug="gym-destination", subdomain="gym-destination",
        )
        for code in ("MEMBERS", "SUBSCRIPTIONS", "POS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Premium", price=50, duration_days=30
        )
        self.membre = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243870661122",
        )
        MemberSubscription.objects.create(
            gym=self.gym, member=self.membre, plan=self.plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )
        self.gerant = User.objects.create_user(
            username="gerant-destination", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self.registre = CashRegister.objects.create(
            gym=self.gym, opened_by=self.gerant,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.depense = record_payment(
            gym=self.gym, register=self.registre, amount=Decimal("30000"),
            currency="CDF", method="cash", transaction_type="out",
            category="expense", description="Reparation du portail",
            created_by=self.gerant,
        )
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _sections(self, requete, **extra):
        parametres = {"q": requete}
        parametres.update(extra)
        return {
            section["titre"]: section
            for section in self.client.get(
                reverse("core:global_search"), parametres
            ).context["sections"]
        }

    # --- Le membre ------------------------------------------------------------------

    def test_a_member_result_opens_the_member_sheet(self):
        lien = self._sections("Ada")["Membres"]["lignes"][0]["url"]

        self.assertIn(f"membre={self.membre.id}", lien)

    def test_the_list_behind_is_reduced_to_that_person(self):
        # La fiche s'ouvre par-dessus une liste d'une seule ligne, et non sur
        # le fichier entier.
        lien = self._sections("Ada")["Membres"]["lignes"][0]["url"]

        self.assertIn("search=", lien)

    def test_the_member_sheet_really_opens_from_the_url(self):
        lien = self._sections("Ada")["Membres"]["lignes"][0]["url"]

        page = self.client.get(lien).content.decode("utf-8")

        self.assertIn('URLSearchParams(window.location.search).get("membre")', page)
        self.assertIn("Ada", page)

    # --- L'abonnement ------------------------------------------------------------------

    def test_a_subscription_result_opens_its_members_sheet(self):
        # L'onglet Abonnement est celui qui s'affiche par defaut : l'historique
        # complet y est deja.
        lien = self._sections("Premium")["Abonnements"]["lignes"][0]["url"]

        self.assertIn(f"membre={self.membre.id}", lien)

    # --- Le paiement --------------------------------------------------------------------

    def test_a_payment_result_opens_its_register_session(self):
        lien = self._sections("portail")["Paiements"]["lignes"][0]["url"]

        self.assertEqual(
            lien, reverse("pos:register_detail", args=[self.registre.id])
        )

    def test_that_session_really_shows_the_payment(self):
        lien = self._sections("portail")["Paiements"]["lignes"][0]["url"]

        self.assertContains(self.client.get(lien), "Reparation du portail")

    def test_a_payment_without_a_session_falls_back_to_a_filtered_history(self):
        Payment.objects.filter(pk=self.depense.pk).update(cash_register=None)

        lien = self._sections("portail")["Paiements"]["lignes"][0]["url"]

        self.assertIn(reverse("pos:register_history"), lien)
        self.assertIn("search=portail", lien)

    # --- Le depliement ----------------------------------------------------------------

    def test_seeing_them_all_keeps_the_query(self):
        # Renvoyer vers une liste generale ferait perdre la recherche en
        # chemin : on deplie sur place.
        lien = self._sections("Ada")["Membres"]["tout_voir"]

        self.assertIn(reverse("core:global_search"), lien)
        self.assertIn("q=Ada", lien)
        self.assertIn("section=membres", lien)

    def test_expanding_shows_only_that_section(self):
        sections = self._sections("Ada", section="membres")

        self.assertEqual(list(sections), ["Membres"])

    def test_expanding_lifts_the_limit(self):
        for index in range(12):
            Member.objects.create(
                gym=self.gym, first_name="Ada", last_name=f"Numero{index}",
                phone=f"+2438706{index:05d}",
            )

        court = self._sections("Ada")["Membres"]
        long = self._sections("Ada", section="membres")["Membres"]

        self.assertEqual(len(court["lignes"]), 8)
        self.assertEqual(len(long["lignes"]), 13)

    def test_an_unknown_section_shows_nothing_rather_than_everything(self):
        # Un parametre fantaisiste ne doit pas rouvrir les trois rubriques a
        # qui n'y a pas droit.
        reponse = self.client.get(
            reverse("core:global_search"), {"q": "Ada", "section": "n-importe-quoi"}
        )

        self.assertEqual(reponse.context["sections"], [])

    def test_a_receptionist_cannot_expand_the_payments(self):
        accueil = User.objects.create_user(
            username="accueil-destination", password="pass12345"
        )
        UserGymRole.objects.create(
            user=accueil, gym=self.gym, role="reception", is_active=True
        )
        self.client.force_login(accueil)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

        reponse = self.client.get(
            reverse("core:global_search"), {"q": "portail", "section": "paiements"}
        )

        self.assertEqual(reponse.context["sections"], [])


class RegisterValidationRegimeTests(TestCase):
    """
    Qui doit verifier quoi.

    Le proprietaire ne rend de comptes a personne. Le gerant n'ouvre une caisse
    qu'en depannage : le proprietaire en est informe, sans que le poste soit
    bloque. Tous les autres restent contre-signes par un tiers.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Regime", slug="org-regime"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Regime",
            slug="gym-regime", subdomain="gym-regime",
        )
        for code in ("MEMBERS", "POS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )
        self.caissiere = self._role("caisse-regime", "cashier")
        self.gerant = self._role("gerant-regime", "manager")
        self.second_gerant = self._role("gerant2-regime", "manager")
        # Le proprietaire par le chemin du middleware : il possede
        # l'organisation, et n'a aucun role pose sur la salle.
        self.proprietaire = User.objects.create_user(
            username="proprio-regime", password="pass12345"
        )
        self.proprietaire.owned_organization = self.organization
        self.proprietaire.save(update_fields=["owned_organization"])
        # Et le proprietaire par l'autre chemin : un role "owner" sur la salle.
        self.proprietaire_role = self._role("proprio2-regime", "owner")

    def _role(self, nom, role):
        utilisateur = User.objects.create_user(username=nom, password="pass12345")
        UserGymRole.objects.create(
            user=utilisateur, gym=self.gym, role=role, is_active=True
        )
        return utilisateur

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _caisse(self, ouverte_par, fermee_par, ecart="0.00"):
        registre = CashRegister.objects.create(
            gym=self.gym, opened_by=ouverte_par,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        registre.closing_amount = Decimal("100000.00") + Decimal(ecart)
        registre.difference = Decimal(ecart)
        registre.closed_by = fermee_par
        registre.closed_at = timezone.now()
        registre.is_closed = True
        registre.save()
        return registre

    def _signer(self, registre, motif=""):
        return self.client.post(
            reverse("pos:validate_register", args=[registre.id]),
            {"validation_note": motif} if motif else {},
            follow=True,
        )

    # --- Les trois regimes ---------------------------------------------------------

    def test_an_owners_closing_needs_nothing(self):
        registre = self._caisse(self.proprietaire, self.proprietaire)

        self.assertEqual(registre.validation_regime, validation.AUCUN)
        self.assertFalse(registre.needs_validation)

    def test_an_owner_by_gym_role_also_needs_nothing(self):
        # Les deux facons d'etre proprietaire donnent le meme resultat : une
        # seule reconnue, la regle dependrait de la creation du compte.
        registre = self._caisse(self.proprietaire_role, self.proprietaire_role)

        self.assertEqual(registre.validation_regime, validation.AUCUN)

    def test_a_managers_own_closing_only_needs_to_be_seen(self):
        registre = self._caisse(self.gerant, self.gerant)

        self.assertEqual(registre.validation_regime, validation.ACQUITTEMENT)

    def test_a_cashiers_closing_still_needs_a_countersignature(self):
        registre = self._caisse(self.caissiere, self.caissiere)

        self.assertEqual(registre.validation_regime, validation.CONTRESIGNATURE)

    def test_a_manager_closing_someone_elses_drawer_is_countersigned(self):
        # Ce n'est pas son depannage habituel : l'argent a ete compte par une
        # seule personne sur la caisse d'une autre.
        registre = self._caisse(self.caissiere, self.gerant)

        self.assertEqual(registre.validation_regime, validation.CONTRESIGNATURE)

    def test_an_open_register_awaits_nothing(self):
        registre = CashRegister.objects.create(
            gym=self.gym, opened_by=self.caissiere,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )

        self.assertEqual(registre.validation_regime, validation.AUCUN)

    def test_a_deleted_account_falls_back_to_a_countersignature(self):
        # Personne ne peut plus repondre de ce comptage : un tiers doit le
        # reprendre a son compte.
        registre = self._caisse(self.caissiere, self.gerant)
        CashRegister.objects.filter(pk=registre.pk).update(closed_by=None)
        registre.refresh_from_db()

        self.assertEqual(registre.validation_regime, validation.CONTRESIGNATURE)

    # --- Qui peut signer quoi --------------------------------------------------------

    def test_only_the_owner_acknowledges_a_managers_closing(self):
        registre = self._caisse(self.gerant, self.gerant)
        self._connecter(self.second_gerant)

        self._signer(registre)

        registre.refresh_from_db()
        self.assertFalse(registre.is_validated)

    def test_the_owner_acknowledges_a_managers_closing(self):
        registre = self._caisse(self.gerant, self.gerant)
        self._connecter(self.proprietaire)

        self._signer(registre)

        registre.refresh_from_db()
        self.assertTrue(registre.is_validated)
        self.assertEqual(registre.validated_by, self.proprietaire)

    def test_a_manager_cannot_acknowledge_their_own_closing(self):
        registre = self._caisse(self.gerant, self.gerant)
        self._connecter(self.gerant)

        self._signer(registre)

        registre.refresh_from_db()
        self.assertFalse(registre.is_validated)

    def test_an_owners_closing_cannot_be_signed_at_all(self):
        # Il n'y a rien a signer : proposer le geste laisserait croire qu'il
        # manquait quelque chose.
        registre = self._caisse(self.proprietaire, self.proprietaire)
        self._connecter(self.gerant)

        self._signer(registre)

        registre.refresh_from_db()
        self.assertFalse(registre.is_validated)

    def test_a_second_manager_countersigns_a_cashiers_closing(self):
        registre = self._caisse(self.caissiere, self.caissiere)
        self._connecter(self.gerant)

        self._signer(registre)

        registre.refresh_from_db()
        self.assertTrue(registre.is_validated)

    # --- L'ecart, quel que soit l'auteur ------------------------------------------------

    def test_a_managers_variance_still_needs_an_explanation(self):
        # Un ecart non explique ne vaut rien, quel que soit celui qui a compte
        # - et un gerant manie souvent des sommes plus importantes.
        registre = self._caisse(self.gerant, self.gerant, ecart="-5000.00")
        self._connecter(self.proprietaire)

        self._signer(registre)

        registre.refresh_from_db()
        self.assertFalse(registre.is_validated)

    def test_with_an_explanation_the_owner_can_acknowledge(self):
        registre = self._caisse(self.gerant, self.gerant, ecart="-5000.00")
        self._connecter(self.proprietaire)

        self._signer(registre, motif="Avance sur salaire non saisie")

        registre.refresh_from_db()
        self.assertTrue(registre.is_validated)
        self.assertEqual(registre.validation_note, "Avance sur salaire non saisie")

    def test_a_balanced_managers_closing_is_seen_in_one_click(self):
        registre = self._caisse(self.gerant, self.gerant)
        self._connecter(self.proprietaire)

        self._signer(registre)

        registre.refresh_from_db()
        self.assertTrue(registre.is_validated)

    # --- Le bandeau du proprietaire -------------------------------------------------------

    def test_the_owner_is_shown_a_managers_closing(self):
        self._caisse(self.gerant, self.gerant)
        self._connecter(self.proprietaire)

        reponse = self.client.get(reverse("members:member_list"))

        self.assertEqual(
            reponse.context["register_acknowledgements_banner"]["total"], 1
        )

    def test_the_banner_goes_once_seen(self):
        registre = self._caisse(self.gerant, self.gerant)
        self._connecter(self.proprietaire)
        self._signer(registre)

        reponse = self.client.get(reverse("members:member_list"))

        self.assertIsNone(reponse.context["register_acknowledgements_banner"])

    def test_a_cashiers_closing_does_not_reach_the_banner(self):
        # Elle se contre-signe dans l'historique : la faire remonter au
        # proprietaire lui demanderait un geste qui ne lui revient pas.
        self._caisse(self.caissiere, self.caissiere)
        self._connecter(self.proprietaire)

        reponse = self.client.get(reverse("members:member_list"))

        self.assertIsNone(reponse.context["register_acknowledgements_banner"])

    def test_a_manager_sees_no_banner(self):
        self._caisse(self.gerant, self.gerant)
        self._connecter(self.second_gerant)

        reponse = self.client.get(reverse("members:member_list"))

        self.assertIsNone(reponse.context["register_acknowledgements_banner"])

    def test_a_neighbouring_gym_stays_out_of_the_banner(self):
        voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-regime-voisine", subdomain="gym-regime-voisine",
        )
        module = Module.objects.get(code="MEMBERS")
        GymModule.objects.get_or_create(
            gym=voisine, module=module, defaults={"is_active": True}
        )
        self._caisse(self.gerant, self.gerant)

        self.client.force_login(self.proprietaire)
        session = self.client.session
        session["current_gym_id"] = voisine.id
        session.save()

        reponse = self.client.get(reverse("members:member_list"))

        self.assertIsNone(reponse.context["register_acknowledgements_banner"])

    # --- L'alerte du tableau de bord ----------------------------------------------------

    def test_a_managers_closing_is_not_counted_twice(self):
        # Elle remonte par le bandeau : la compter aussi dans les alertes
        # ferait chercher un geste deja demande ailleurs.
        self._caisse(self.gerant, self.gerant)
        self._connecter(self.proprietaire)

        alertes = self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id])
        ).context["alertes_urgentes"]

        self.assertFalse(any("contre-signer" in a["titre"] for a in alertes))

    def test_a_cashiers_closing_is_counted_in_the_alerts(self):
        self._caisse(self.caissiere, self.caissiere)
        self._connecter(self.proprietaire)

        alertes = self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id])
        ).context["alertes_urgentes"]

        self.assertTrue(any("contre-signer" in a["titre"] for a in alertes))

    def test_an_owners_closing_raises_no_alert(self):
        self._caisse(self.proprietaire, self.proprietaire)
        self._connecter(self.proprietaire)

        alertes = self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id])
        ).context["alertes_urgentes"]

        self.assertFalse(any("contre-signer" in a["titre"] for a in alertes))


class IndicatorHelpTests(TestCase):
    """
    Les definitions d'indicateurs.

    Le texte etait la, porte par l'attribut `title` du navigateur. Mais rien
    n'annoncait sa presence, il mettait une seconde a paraitre au survol, et
    sur un ecran tactile il n'existait pas du tout - or la salle travaille sur
    tablette.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Aide", slug="org-aide"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Aide",
            slug="gym-aide", subdomain="gym-aide",
        )
        for code in ("MEMBERS", "POS", "ACCESS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )
        self.gerant = User.objects.create_user(
            username="gerant-aide", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _page(self):
        return self.client.get(reverse("core:gym_dashboard", args=[self.gym.id]))

    # --- Le texte est toujours la -------------------------------------------------

    def test_the_definitions_are_still_carried(self):
        page = self._page()

        self.assertContains(page, "photographie d'aujourd'hui")
        self.assertContains(page, "n'est pas recompte")
        self.assertContains(page, "jamais passes entre ses mains")

    # --- Elles se signalent ---------------------------------------------------------

    def test_a_label_that_carries_a_definition_is_marked(self):
        # Sans repere, personne ne devine qu'il y a quelque chose a lire.
        self.assertContains(self._page(), 'text-muted aide"')

    def test_every_written_definition_is_marked(self):
        # Une seule oubliee, et l'indicateur reste muet.
        page = self._page().content.decode("utf-8")

        definitions = page.count('title="Membres au statut actif')
        marquees = page.count('aide"\n')

        self.assertTrue(definitions >= 1)
        self.assertTrue(marquees >= 10, f"{marquees} definitions marquees")

    def test_a_calculated_title_is_left_alone(self):
        # La base de comparaison d'une tendance est deja ecrite sous le badge :
        # un second repere ne ferait que du bruit.
        page = self._page().content.decode("utf-8")

        self.assertIn("Periode precedente", page)
        self.assertNotIn('class="badge bg-soft-secondary text-secondary aide"', page)

    # --- Elles s'ouvrent au doigt ------------------------------------------------------

    def test_the_page_turns_them_into_reachable_tooltips(self):
        # L'attribut title du navigateur n'existe pas sur un ecran tactile :
        # c'est l'infobulle de Bootstrap, declenchee aussi au focus, qui le
        # remplace.
        page = self._page().content.decode("utf-8")

        self.assertIn(".aide[title]", page)
        # Au survol avec une souris, a la tape sur un ecran tactile. Le
        # declenchement au focus laissait des bulles ouvertes s'accumuler.
        self.assertIn('matchMedia("(hover: hover)")', page)
        self.assertIn('avecSouris ? "hover" : "click"', page)
        self.assertNotIn('trigger: "hover focus"', page)

    def test_only_one_bubble_is_open_at_a_time(self):
        page = self._page().content.decode("utf-8")

        self.assertIn("show.bs.tooltip", page)
        self.assertIn("autre.hide()", page)

    def test_the_bubble_never_catches_the_cursor(self):
        # Posee sous la souris, elle retirait le survol a son element : elle
        # clignotait.
        palette = (
            Path(settings.BASE_DIR) / "static" / "css" / "palette.css"
        ).read_text(encoding="utf-8")

        debut = palette.index(".tooltip.aide-bulle {")
        regle = palette[debut:palette.index("}", debut)]
        self.assertIn("pointer-events: none", regle)
        self.assertIn("text-transform: none", regle)

    def test_the_marker_is_styled_by_the_palette(self):
        palette = (
            Path(settings.BASE_DIR) / "static" / "css" / "palette.css"
        ).read_text(encoding="utf-8")

        self.assertIn(".aide::after", palette)
        self.assertIn("aide-bulle", palette)


class CashReturnTests(TestCase):
    """
    L'argent qui revient dans le tiroir.

    Une course qui n'a pas eu lieu, un reste non depense, un renfort de fonds :
    trois facons de remplir la caisse sans que la salle ait rien gagne. Tout le
    dispositif tient a cette distinction.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Retour", slug="org-retour"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Retour",
            slug="gym-retour", subdomain="gym-retour",
        )
        for code in ("MEMBERS", "POS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )
        self.caissiere = self._utilisateur("caisse-retour", "cashier")
        self.gerant = self._utilisateur("gerant-retour", "manager")
        self.registre = CashRegister.objects.create(
            gym=self.gym, opened_by=self.caissiere,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )

    def _utilisateur(self, nom, role):
        utilisateur = User.objects.create_user(username=nom, password="pass12345")
        UserGymRole.objects.create(
            user=utilisateur, gym=self.gym, role=role, is_active=True
        )
        return utilisateur

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _depense(self, montant="50000", motif="Plomberie"):
        return record_expense(
            gym=self.gym, amount=Decimal(montant), currency="CDF",
            method="cash", category="expense", description=motif,
            created_by=self.caissiere, source_app="pos",
            source_model="ManualExpense",
        )

    def _rendre(self, depense, montant):
        return record_expense_refund(
            gym=self.gym, expense=depense, amount=Decimal(montant),
            currency="CDF", created_by=self.caissiere,
        )

    # --- Le tiroir -------------------------------------------------------------------

    def test_a_return_fills_the_drawer_back(self):
        depense = self._depense("50000")
        self.registre.refresh_from_db()
        avant = self.registre.expected_total()

        self._rendre(depense, "20000")

        self.registre.refresh_from_db()
        self.assertEqual(self.registre.expected_total(), avant + Decimal("20000.00"))

    def test_an_injection_fills_the_drawer_too(self):
        avant = self.registre.expected_total()

        record_cash_injection(
            gym=self.gym, amount=Decimal("200000"), currency="CDF",
            description="Renfort de fonds", created_by=self.gerant,
        )

        self.registre.refresh_from_db()
        self.assertEqual(
            self.registre.expected_total(), avant + Decimal("200000.00")
        )

    # --- Mais ce n'est pas une recette -------------------------------------------------

    def test_a_return_is_never_revenue(self):
        # Le piege du dispositif : 50 000 sortis puis rendus afficheraient
        # +50 000 de recette et -50 000 de depense la ou il ne s'est rien passe.
        depense = self._depense("50000")

        self._rendre(depense, "50000")

        self.assertEqual(
            Payment.objects.filter(gym=self.gym).recettes().count(), 0
        )

    def test_an_injection_is_never_revenue(self):
        record_cash_injection(
            gym=self.gym, amount=Decimal("200000"), currency="CDF",
            description="Renfort de fonds", created_by=self.gerant,
        )

        self.assertEqual(
            Payment.objects.filter(gym=self.gym).recettes().count(), 0
        )

    def test_a_real_sale_is_still_revenue(self):
        record_payment(
            gym=self.gym, register=self.registre, amount=Decimal("30000"),
            currency="CDF", method="cash", transaction_type="in",
            category="subscription", description="Abonnement",
            created_by=self.caissiere,
        )

        self.assertEqual(
            Payment.objects.filter(gym=self.gym).recettes().count(), 1
        )

    def test_the_dashboard_revenue_ignores_a_return(self):
        depense = self._depense("50000")
        self._rendre(depense, "50000")
        self._connecter(self.gerant)

        contexte = self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id])
        ).context

        self.assertEqual(contexte["daily_revenue"], 0)

    def test_the_register_block_separates_the_three(self):
        record_payment(
            gym=self.gym, register=self.registre, amount=Decimal("30000"),
            currency="CDF", method="cash", transaction_type="in",
            category="subscription", description="Abonnement",
            created_by=self.caissiere,
        )
        depense = self._depense("50000")
        self._rendre(depense, "20000")
        record_cash_injection(
            gym=self.gym, amount=Decimal("10000"), currency="CDF",
            description="Renfort", created_by=self.gerant,
        )
        self._connecter(self.gerant)

        caisse = self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id])
        ).context["caisse"]

        self.assertEqual(caisse["encaissements"], Decimal("30000.00"))
        self.assertEqual(caisse["retours"], Decimal("20000.00"))
        self.assertEqual(caisse["apports"], Decimal("10000.00"))
        # La depense reelle : 50 000 sortis, 20 000 revenus.
        self.assertEqual(caisse["decaissements"], Decimal("30000.00"))

    def test_the_block_still_reconciles_with_the_drawer(self):
        # ouverture + encaisse + apports - depense reelle = solde theorique.
        record_payment(
            gym=self.gym, register=self.registre, amount=Decimal("30000"),
            currency="CDF", method="cash", transaction_type="in",
            category="subscription", description="Abonnement",
            created_by=self.caissiere,
        )
        depense = self._depense("50000")
        self._rendre(depense, "20000")
        record_cash_injection(
            gym=self.gym, amount=Decimal("10000"), currency="CDF",
            description="Renfort", created_by=self.gerant,
        )
        self._connecter(self.gerant)

        caisse = self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id])
        ).context["caisse"]

        attendu = (
            Decimal("100000.00")
            + caisse["encaissements"]
            + caisse["apports"]
            - caisse["decaissements"]
        )
        self.assertEqual(caisse["solde_theorique"], attendu)

    # --- Ce que la depense devient ------------------------------------------------------

    def test_the_original_disbursement_is_left_untouched(self):
        # Ces 50 000 sont bien sortis du tiroir : un comptage intermediaire
        # deja contre-signe les retrouverait.
        depense = self._depense("50000")

        self._rendre(depense, "20000")

        depense.refresh_from_db()
        self.assertEqual(depense.amount_cdf, Decimal("50000.00"))

    def test_the_net_says_what_it_really_cost(self):
        depense = self._depense("50000")

        self._rendre(depense, "20000")

        self.assertEqual(depense.montant_rendu, Decimal("20000.00"))
        self.assertEqual(depense.montant_net, Decimal("30000.00"))

    def test_several_partial_returns_add_up(self):
        depense = self._depense("50000")

        self._rendre(depense, "20000")
        self._rendre(depense, "5000")

        self.assertEqual(depense.montant_net, Decimal("25000.00"))

    def test_the_return_is_linked_to_its_disbursement(self):
        depense = self._depense("50000")

        retour = self._rendre(depense, "20000")

        self.assertEqual(retour.refund_of, depense)

    # --- Ce qui est refuse ------------------------------------------------------------------

    def test_returning_more_than_was_taken_is_refused(self):
        # Au-dela, ce n'est plus un retour : c'est un apport, et il ne se
        # justifie pas de la meme facon.
        depense = self._depense("50000")

        with self.assertRaises(ValidationError) as capture:
            self._rendre(depense, "60000")

        self.assertIn("apport en caisse", str(capture.exception))

    def test_returning_more_than_what_is_left_is_refused(self):
        depense = self._depense("50000")
        self._rendre(depense, "40000")

        with self.assertRaises(ValidationError):
            self._rendre(depense, "20000")

    def test_a_zero_return_is_refused(self):
        depense = self._depense("50000")

        with self.assertRaises(ValidationError):
            self._rendre(depense, "0")

    def test_an_incoming_payment_cannot_be_returned(self):
        recette = record_payment(
            gym=self.gym, register=self.registre, amount=Decimal("30000"),
            currency="CDF", method="cash", transaction_type="in",
            category="subscription", description="Abonnement",
            created_by=self.caissiere,
        )

        with self.assertRaises(ValidationError) as capture:
            self._rendre(recette, "10000")

        self.assertIn("sorti de la caisse", str(capture.exception))

    def test_a_neighbouring_gym_disbursement_cannot_be_returned(self):
        voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-retour-voisine", subdomain="gym-retour-voisine",
        )
        CashRegister.objects.create(
            gym=voisine, opened_by=self.gerant,
            opening_amount=Decimal("0.00"), exchange_rate=Decimal("2800.00"),
        )
        ailleurs = record_expense(
            gym=voisine, amount=Decimal("10000"), currency="CDF",
            method="cash", category="expense", description="Ailleurs",
            created_by=self.gerant, source_app="pos",
            source_model="ManualExpense",
        )

        with self.assertRaises(ValidationError):
            self._rendre(ailleurs, "5000")

    def test_an_injection_without_a_reason_is_refused(self):
        # Un apport augmente ce que le caissier devra retrouver dans le
        # tiroir : sans motif, l'ecart serait inexplicable.
        with self.assertRaises(ValidationError) as capture:
            record_cash_injection(
                gym=self.gym, amount=Decimal("50000"), currency="CDF",
                description="  ", created_by=self.gerant,
            )

        self.assertIn("motif", str(capture.exception).lower())

    # --- La caisse d'hier ---------------------------------------------------------------------

    def test_a_return_lands_in_todays_register(self):
        # L'argent arrive physiquement aujourd'hui : la clôture d'hier avait
        # ete comptee correctement, on n'y touche pas.
        depense = self._depense("50000")
        ancienne = self.registre
        ancienne.closing_amount = ancienne.expected_total()
        ancienne.difference = Decimal("0.00")
        ancienne.closed_by = self.gerant
        ancienne.closed_at = timezone.now()
        ancienne.is_closed = True
        ancienne.save()
        nouvelle = CashRegister.objects.create(
            gym=self.gym, opened_by=self.caissiere,
            opening_amount=Decimal("0.00"), exchange_rate=Decimal("2800.00"),
        )

        retour = self._rendre(depense, "20000")

        self.assertEqual(retour.cash_register, nouvelle)
        ancienne.refresh_from_db()
        self.assertEqual(ancienne.difference, Decimal("0.00"))

    # --- Qui a le droit --------------------------------------------------------------------------

    def test_a_cashier_can_return_money(self):
        depense = self._depense("50000")
        self._connecter(self.caissiere)

        self.client.post(
            reverse("pos:refund_expense", args=[depense.id]),
            {"amount": "20000", "currency": "CDF"},
        )

        self.assertEqual(depense.montant_rendu, Decimal("20000.00"))

    def test_a_cashier_cannot_inject_money(self):
        # Faire entrer de l'argent neuf augmente le solde theorique attendu :
        # cela releve de la gestion.
        self._connecter(self.caissiere)

        reponse = self.client.post(
            reverse("pos:inject_cash"),
            {"amount": "50000", "currency": "CDF", "description": "Renfort"},
        )

        self.assertEqual(reponse.status_code, 403)

    def test_a_manager_injects_into_the_open_drawer(self):
        # Un gerant n'a pas de caisse a lui : l'argent va dans celle qui est
        # ouverte. Sans cela, l'apport echouait faute de session.
        apport = record_cash_injection(
            gym=self.gym, amount=Decimal("50000"), currency="CDF",
            description="Renfort de fonds", created_by=self.gerant,
        )

        self.assertEqual(apport.cash_register, self.registre)

    def test_with_two_drawers_open_the_choice_is_asked(self):
        # Personne ne peut deviner dans quel tiroir les billets sont entres :
        # en tirer un au hasard fausserait deux comptages.
        CashRegister.objects.create(
            gym=self.gym, opened_by=self._utilisateur("caisse2-retour", "cashier"),
            opening_amount=Decimal("0.00"), exchange_rate=Decimal("2800.00"),
        )

        with self.assertRaises(ValidationError) as capture:
            record_cash_injection(
                gym=self.gym, amount=Decimal("50000"), currency="CDF",
                description="Renfort", created_by=self.gerant,
            )

        self.assertIn("Plusieurs caisses", str(capture.exception))

    def test_a_manager_can_inject_money(self):
        CashRegister.objects.create(
            gym=self.gym, opened_by=self.gerant,
            opening_amount=Decimal("0.00"), exchange_rate=Decimal("2800.00"),
        )
        self._connecter(self.gerant)

        self.client.post(
            reverse("pos:inject_cash"),
            {"amount": "50000", "currency": "CDF", "description": "Renfort"},
        )

        self.assertEqual(
            Payment.objects.filter(
                gym=self.gym, category="cash_injection"
            ).count(),
            1,
        )


class AnalyticsRevenueGridTests(TestCase):
    """
    Le revenu de la periode, detaille comme la caisse du jour.

    Encaissements, decaissements, resultat, ecart - pour le jour, la semaine,
    le mois ou l'annee choisis. Et un seul chiffre de revenu dans la vue : celui
    de la grille.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Bilan", slug="org-bilan"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Bilan",
            slug="gym-bilan", subdomain="gym-bilan",
        )
        self.voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-bilan-voisine", subdomain="gym-bilan-voisine",
        )
        for code in ("MEMBERS", "POS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            for salle in (self.gym, self.voisine):
                GymModule.objects.get_or_create(
                    gym=salle, module=module, defaults={"is_active": True}
                )
        self.gerant = User.objects.create_user(
            username="gerant-bilan", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self.registre = CashRegister.objects.create(
            gym=self.gym, opened_by=self.gerant,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    # --- Fabriques ---------------------------------------------------------------

    def _vente(self, montant, gym=None, registre=None):
        return record_payment(
            gym=gym or self.gym, register=registre or self.registre,
            amount=Decimal(montant), currency="CDF", method="cash",
            transaction_type="in", category="subscription",
            description="Abonnement", created_by=self.gerant,
        )

    def _depense(self, montant, motif="Plomberie"):
        return record_expense(
            gym=self.gym, amount=Decimal(montant), currency="CDF",
            method="cash", category="expense", description=motif,
            created_by=self.gerant, source_app="pos",
            source_model="ManualExpense",
        )

    def _dater(self, paiement, jour):
        Payment.objects.filter(pk=paiement.pk).update(
            created_at=timezone.make_aware(datetime.combine(jour, time(12, 0)))
        )

    def _page(self, periode="month", vue="analytics"):
        return self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id]),
            {"view": vue, "period": periode},
        )

    def _bilan(self, periode="month"):
        return self._page(periode).context["bilan_periode"]

    # --- La place de la grille ------------------------------------------------------

    def test_the_grid_opens_the_analytics_view(self):
        page = self._page().content.decode("utf-8")

        self.assertIn("Revenus de la periode", page)
        self.assertLess(page.index("Revenus de la periode"), page.index("Renouvellements"))

    def test_the_overview_does_not_carry_it(self):
        # La vue d'ensemble a sa caisse du jour : la grille de periode releve
        # de l'analyse.
        self.assertNotContains(self._page(vue="dashboard"), "Revenus de la periode")

    def test_the_revenue_is_stated_once_in_analytics(self):
        # Les deux cartes qui repetaient ce chiffre ont disparu : la grille est
        # sa seule place.
        page = self._page().content.decode("utf-8")

        self.assertEqual(page.count("Revenus de la periode"), 1)
        self.assertNotIn("Revenus periode", page)

    # --- Le revenu reflete le total ----------------------------------------------------

    def test_the_takings_equal_the_period_revenue(self):
        self._vente("30000")
        self._vente("20000")

        contexte = self._page().context

        self.assertEqual(contexte["bilan_periode"]["encaissements"], Decimal("50000.00"))
        self.assertEqual(
            contexte["bilan_periode"]["encaissements"], contexte["period_revenue"]
        )

    def test_they_agree_for_every_filter(self):
        self._vente("30000")

        for periode in ("day", "week", "month", "year"):
            with self.subTest(periode=periode):
                contexte = self._page(periode).context
                self.assertEqual(
                    contexte["bilan_periode"]["encaissements"],
                    contexte["period_revenue"],
                )

    def test_the_previous_period_is_its_comparison_base(self):
        fenetre = _get_period_window("month", timezone.localdate())
        ancienne = self._vente("40000")
        self._dater(ancienne, fenetre["previous_start"])
        self._vente("10000")

        bilan = self._bilan("month")

        self.assertEqual(bilan["encaissements"], Decimal("10000.00"))
        self.assertEqual(bilan["encaissements_precedents"], Decimal("40000.00"))

    # --- Ce qui n'est pas une recette ---------------------------------------------------

    def test_a_return_is_not_counted_as_takings(self):
        depense = self._depense("50000")
        record_expense_refund(
            gym=self.gym, expense=depense, amount=Decimal("20000"),
            currency="CDF", created_by=self.gerant,
        )

        self.assertEqual(self._bilan()["encaissements"], Decimal("0.00"))

    def test_an_injection_is_shown_apart(self):
        # Un renfort de 500 000 ressemblerait sinon a un bon mois.
        record_cash_injection(
            gym=self.gym, amount=Decimal("500000"), currency="CDF",
            description="Renfort de fonds", created_by=self.gerant,
        )

        bilan = self._bilan()

        self.assertEqual(bilan["apports"], Decimal("500000.00"))
        self.assertEqual(bilan["encaissements"], Decimal("0.00"))
        self.assertEqual(bilan["resultat"], Decimal("0.00"))

    # --- Les decaissements et le resultat -------------------------------------------------

    def test_the_disbursements_are_net_of_returns(self):
        depense = self._depense("50000")
        record_expense_refund(
            gym=self.gym, expense=depense, amount=Decimal("20000"),
            currency="CDF", created_by=self.gerant,
        )

        bilan = self._bilan()

        self.assertEqual(bilan["sorties_brutes"], Decimal("50000.00"))
        self.assertEqual(bilan["retours"], Decimal("20000.00"))
        self.assertEqual(bilan["decaissements"], Decimal("30000.00"))

    def test_the_result_is_takings_minus_real_spending(self):
        self._vente("80000")
        depense = self._depense("50000")
        record_expense_refund(
            gym=self.gym, expense=depense, amount=Decimal("20000"),
            currency="CDF", created_by=self.gerant,
        )

        self.assertEqual(self._bilan()["resultat"], Decimal("50000.00"))

    def test_a_losing_period_shows_a_negative_result(self):
        self._depense("30000")

        page = self._page()

        self.assertEqual(page.context["bilan_periode"]["resultat"], Decimal("-30000.00"))
        self.assertContains(page, "ton-urgent")

    def test_a_late_return_is_deducted_in_the_month_of_the_expense(self):
        # C'est la regle du registre des decaissements : les deux ecrans
        # doivent donner le meme chiffre.
        fenetre = _get_period_window("month", timezone.localdate())
        depense = self._depense("50000")
        self._dater(depense, fenetre["previous_start"])
        record_expense_refund(
            gym=self.gym, expense=depense, amount=Decimal("20000"),
            currency="CDF", created_by=self.gerant,
        )

        bilan = self._bilan("month")

        # Le mois courant n'a aucune depense, donc rien a deduire.
        self.assertEqual(bilan["decaissements"], Decimal("0.00"))
        # Le mois precedent a coute 30 000, et non 50 000.
        self.assertEqual(bilan["resultat_precedent"], Decimal("-30000.00"))

    # --- L'ecart de caisse ----------------------------------------------------------------

    def test_the_variance_adds_up_the_closings_of_the_period(self):
        self.registre.closing_amount = Decimal("98000.00")
        self.registre.difference = Decimal("-2000.00")
        self.registre.closed_by = self.gerant
        self.registre.closed_at = timezone.now()
        self.registre.is_closed = True
        self.registre.save()

        bilan = self._bilan()

        self.assertEqual(bilan["ecart"], Decimal("-2000.00"))
        self.assertTrue(bilan["a_un_ecart"])

    # --- Le detail ---------------------------------------------------------------------------

    def test_the_summary_lines_gave_way_to_the_table(self):
        # "Especes : ..." et "Sorties : ..." repetaient ce que le tableau des
        # operations detaille desormais ligne a ligne.
        self._vente("30000")
        self._depense("5000", motif="Savon")

        reponse = self._page()

        self.assertNotIn("par_methode", reponse.context["bilan_periode"])
        self.assertNotIn("motifs", reponse.context["bilan_periode"])
        self.assertNotContains(reponse, '<span class="fw-semibold">Sorties :</span>')

    def test_the_reasons_of_the_spending_are_listed(self):
        self._depense("30000", motif="Reparation du portail")

        self.assertContains(self._page(), "Reparation du portail")

    def test_the_amounts_are_grouped(self):
        self._vente("1599739")

        self.assertContains(self._page(), GROUPE)

    # --- Le cloisonnement ----------------------------------------------------------------------

    def test_a_neighbouring_gym_stays_out(self):
        registre_voisin = CashRegister.objects.create(
            gym=self.voisine, opened_by=self.gerant,
            opening_amount=Decimal("0.00"), exchange_rate=Decimal("2800.00"),
        )
        self._vente("999999", gym=self.voisine, registre=registre_voisin)

        self.assertEqual(self._bilan()["encaissements"], Decimal("0.00"))


class AnalyticsOperationsTableTests(TestCase):
    """
    Les operations de la periode, ligne a ligne, sous la grille du revenu.

    Deux onglets, tries par date la plus recente, pagines par 25. Le tableau
    doit permettre de retrouver chaque franc que la grille additionne.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Operations", slug="org-operations"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Operations",
            slug="gym-operations", subdomain="gym-operations",
        )
        self.voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-operations-voisine", subdomain="gym-operations-voisine",
        )
        for code in ("MEMBERS", "POS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            for salle in (self.gym, self.voisine):
                GymModule.objects.get_or_create(
                    gym=salle, module=module, defaults={"is_active": True}
                )
        self.gerant = User.objects.create_user(
            username="gerant-operations", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self.registre = CashRegister.objects.create(
            gym=self.gym, opened_by=self.gerant,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    # --- Fabriques ----------------------------------------------------------------

    def _vente(self, montant, motif="Abonnement", gym=None, registre=None):
        return record_payment(
            gym=gym or self.gym, register=registre or self.registre,
            amount=Decimal(montant), currency="CDF", method="cash",
            transaction_type="in", category="subscription",
            description=motif, created_by=self.gerant,
        )

    def _depense(self, montant, motif="Plomberie"):
        return record_expense(
            gym=self.gym, amount=Decimal(montant), currency="CDF",
            method="cash", category="expense", description=motif,
            created_by=self.gerant, source_app="pos",
            source_model="ManualExpense",
        )

    def _a_heure(self, paiement, jour, heure):
        Payment.objects.filter(pk=paiement.pk).update(
            created_at=timezone.make_aware(datetime.combine(jour, time(heure, 0)))
        )

    def _page(self, vue="analytics", **parametres):
        parametres.setdefault("period", "month")
        parametres["view"] = vue
        return self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id]), parametres
        )

    def _lignes(self, cle, **parametres):
        return list(
            self._page(**parametres).context["operations_periode"][cle]["page"]
        )

    # --- La place du tableau --------------------------------------------------------

    def test_the_table_sits_inside_the_revenue_grid(self):
        page = self._page().content.decode("utf-8")

        position = page.index('id="operations"')
        self.assertLess(page.index("Revenus de la periode"), position)
        self.assertLess(position, page.index("Renouvellements"))

    def test_the_overview_computes_no_table(self):
        # La vue d'ensemble n'a pas a payer deux listes qu'elle ne montre pas.
        reponse = self._page(vue="dashboard")

        self.assertIsNone(reponse.context["operations_periode"])
        self.assertNotContains(reponse, 'id="operations"')

    # --- Ce qui est liste ------------------------------------------------------------

    def test_the_takings_are_listed(self):
        self._vente("30000", motif="Abonnement mensuel")

        lignes = self._lignes("encaissements")

        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes[0].description, "Abonnement mensuel")

    def test_returns_and_injections_are_not_takings(self):
        # Le tableau doit retomber sur le total de la grille : ni l'argent rendu
        # ni les apports n'y figurent.
        depense = self._depense("50000")
        record_expense_refund(
            gym=self.gym, expense=depense, amount=Decimal("20000"),
            currency="CDF", created_by=self.gerant,
        )
        record_cash_injection(
            gym=self.gym, amount=Decimal("100000"), currency="CDF",
            description="Renfort", created_by=self.gerant,
        )

        self.assertEqual(self._lignes("encaissements"), [])

    def test_a_disbursement_shows_what_came_back(self):
        depense = self._depense("50000")
        record_expense_refund(
            gym=self.gym, expense=depense, amount=Decimal("20000"),
            currency="CDF", created_by=self.gerant,
        )

        ligne = self._lignes("decaissements")[0]

        self.assertEqual(ligne.rendu_cdf, Decimal("20000.00"))
        self.assertEqual(ligne.net_cdf, Decimal("30000.00"))

    def test_the_takings_add_up_to_the_grid(self):
        self._vente("30000")
        self._vente("12500")

        reponse = self._page()
        lignes = list(reponse.context["operations_periode"]["encaissements"]["page"])

        self.assertEqual(
            sum(ligne.amount_cdf for ligne in lignes),
            reponse.context["bilan_periode"]["encaissements"],
        )

    def test_the_period_filter_applies(self):
        fenetre = _get_period_window("month", timezone.localdate())
        ancienne = self._vente("40000", motif="Mois dernier")
        Payment.objects.filter(pk=ancienne.pk).update(
            created_at=timezone.make_aware(
                datetime.combine(fenetre["previous_start"], time(12, 0))
            )
        )

        self.assertEqual(self._lignes("encaissements"), [])

    def test_a_neighbouring_gym_stays_out(self):
        registre_voisin = CashRegister.objects.create(
            gym=self.voisine, opened_by=self.gerant,
            opening_amount=Decimal("0.00"), exchange_rate=Decimal("2800.00"),
        )
        self._vente("999999", gym=self.voisine, registre=registre_voisin)

        self.assertEqual(self._lignes("encaissements"), [])

    # --- Le tri ----------------------------------------------------------------------

    def test_the_newest_comes_first(self):
        aujourd_hui = timezone.localdate()
        matin = self._vente("10000", motif="Matin")
        soir = self._vente("20000", motif="Soir")
        self._a_heure(matin, aujourd_hui, 9)
        self._a_heure(soir, aujourd_hui, 15)

        lignes = self._lignes("encaissements", period="year")

        self.assertEqual([l.description for l in lignes], ["Soir", "Matin"])

    def test_sorting_by_amount(self):
        self._vente("10000", motif="Petit")
        self._vente("90000", motif="Gros")

        lignes = self._lignes("encaissements", enc_tri="-montant")

        self.assertEqual(lignes[0].description, "Gros")

    def test_clicking_the_sorted_column_reverses_it(self):
        liste = self._page(enc_tri="-montant").context["operations_periode"]["encaissements"]

        self.assertIn("enc_tri=montant", liste["tri_montant"])

    def test_an_unknown_sort_falls_back_to_the_date(self):
        # L'URL est modifiable a la main : order_by ne recoit jamais n'importe
        # quoi.
        liste = self._page(enc_tri="drop_table").context["operations_periode"]["encaissements"]

        self.assertEqual(liste["tri"], "-date")

    # --- La pagination ----------------------------------------------------------------

    def test_twenty_five_lines_a_page(self):
        for index in range(30):
            self._vente(str(1000 + index), motif=f"Vente {index}")

        self.assertEqual(len(self._lignes("encaissements")), 25)
        self.assertEqual(len(self._lignes("encaissements", enc_page=2)), 5)

    def test_the_total_covers_every_page(self):
        for index in range(30):
            self._vente("1000")

        bilan = self._page(enc_page=2).context["bilan_periode"]

        self.assertEqual(bilan["encaissements"], Decimal("30000.00"))

    def test_turning_one_page_keeps_the_rest_of_the_view(self):
        # Tourner la page des encaissements ne remet a zero ni le tri des
        # decaissements, ni la periode, ni la vue.
        for index in range(30):
            self._vente("1000")

        liste = self._page(period="year", dec_tri="montant").context["operations_periode"]["encaissements"]

        self.assertIn("enc_page=2", liste["suivante"])
        self.assertIn("dec_tri=montant", liste["suivante"])
        self.assertIn("period=year", liste["suivante"])
        self.assertIn("view=analytics", liste["suivante"])
        self.assertTrue(liste["suivante"].endswith("#operations"))

    def test_the_open_tab_is_remembered(self):
        reponse = self._page(onglet="decaissements")

        self.assertEqual(reponse.context["operations_periode"]["onglet"], "decaissements")
        self.assertContains(reponse, 'tab-pane fade show active"\n                             id="liste-decaissements"')

    def test_an_unknown_tab_opens_the_takings(self):
        reponse = self._page(onglet="nimporte")

        self.assertEqual(reponse.context["operations_periode"]["onglet"], "encaissements")



class RapportsHonnetesTests(TestCase):
    """
    La page des rapports montre un extrait, et le dit.

    Elle affichait "Total : 50 transactions" alors que la periode en comptait
    des centaines : le chiffre du bas contredisait celui du haut.
    """

    def setUp(self):
        from decimal import Decimal as _Decimal

        from pos.models import CashRegister, Payment

        self.Payment = Payment
        self.organisation = Organization.objects.create(name="Org Rapport", slug="org-rapport")
        self.gym = Gym.objects.create(
            organization=self.organisation, name="Gym Rapport",
            slug="gym-rapport", subdomain="gym-rapport",
        )
        for code in ("POS", "MEMBERS"):
            module, _ = Module.objects.get_or_create(code=code, defaults={"name": code})
            GymModule.objects.get_or_create(gym=self.gym, module=module, defaults={"is_active": True})

        self.proprietaire = User.objects.create_user(username="proprio-rapport", password="pass12345")
        UserGymRole.objects.create(
            user=self.proprietaire, gym=self.gym, role="owner", is_active=True
        )
        self.caisse = CashRegister.objects.create(
            gym=self.gym, opened_by=self.proprietaire,
            opening_amount=_Decimal("1000.00"), exchange_rate=_Decimal("2800.00"),
        )
        self.client.force_login(self.proprietaire)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _paiements(self, combien):
        from decimal import Decimal as _Decimal

        for _ in range(combien):
            self.Payment.objects.create(
                gym=self.gym, cash_register=self.caisse, amount=_Decimal("1000.00"),
                currency="CDF", method="cash", type="in", status="success",
                category="product",
            )

    def test_the_page_says_how_many_it_shows(self):
        self._paiements(60)

        reponse = self.client.get(reverse("core:rapport"))

        self.assertEqual(reponse.context["transactions_total"], 60)
        self.assertEqual(len(reponse.context["transactions"]), 50)
        self.assertContains(reponse, "sur 60 transactions de la période")
        self.assertContains(reponse, "Voir la liste complète")

    def test_a_short_period_says_the_plain_total(self):
        self._paiements(3)

        reponse = self.client.get(reverse("core:rapport"))

        self.assertEqual(reponse.context["transactions_total"], 3)
        self.assertContains(reponse, "Total : 3 transactions")
        self.assertNotContains(reponse, "Voir la liste complète")



class TranchesDExpirationTests(TestCase):
    """
    Chaque abonnement figure dans une seule tranche d'echeance.

    Les paliers cumulatifs comptaient la meme personne jusqu'a quatre fois :
    on additionnait des chiffres qui se recouvraient.
    """

    def setUp(self):
        self.organisation = Organization.objects.create(name="Org Tranches", slug="org-tranches")
        self.gym = Gym.objects.create(
            organization=self.organisation, name="Gym Tranches",
            slug="gym-tranches", subdomain="gym-tranches",
        )
        for code in ("MEMBERS", "SUBSCRIPTIONS"):
            module, _ = Module.objects.get_or_create(code=code, defaults={"name": code})
            GymModule.objects.get_or_create(gym=self.gym, module=module, defaults={"is_active": True})
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        self.today = timezone.localdate()
        self.proprietaire = User.objects.create_user(
            username="proprio-tranches", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.proprietaire, gym=self.gym, role="owner", is_active=True
        )
        self.client.force_login(self.proprietaire)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _abonne(self, fin_dans, nom="Membre"):
        membre = Member.objects.create(
            gym=self.gym, first_name=nom, last_name=str(fin_dans),
            phone=f"+2438900{fin_dans:05d}",
        )
        MemberSubscription.objects.create(
            gym=self.gym, member=membre, plan=self.plan,
            start_date=self.today - timedelta(days=1),
            end_date=self.today + timedelta(days=fin_dans),
            is_active=True,
        )
        return membre

    def _tranches(self):
        from core.views import _expirations_par_tranche

        return {
            tranche["libelle"]: tranche["nombre"]
            for tranche in _expirations_par_tranche(self.gym, self.today)
        }

    def test_each_subscription_falls_in_one_bucket_only(self):
        self._abonne(0)
        self._abonne(1)
        self._abonne(5)
        self._abonne(12)
        self._abonne(40)

        tranches = self._tranches()

        self.assertEqual(tranches["Aujourd'hui ou demain"], 2)
        self.assertEqual(tranches["Dans 2 a 7 jours"], 1)
        self.assertEqual(tranches["Dans 8 a 15 jours"], 1)
        self.assertEqual(tranches["Au-dela de 15 jours"], 1)

    def test_the_buckets_add_up_to_the_active_subscriptions(self):
        for fin in (0, 2, 9, 20, 31):
            self._abonne(fin)

        self.assertEqual(sum(self._tranches().values()), 5)

    def test_the_boundaries_are_where_they_are_said_to_be(self):
        self._abonne(2)
        self._abonne(7)
        self._abonne(8)
        self._abonne(15)
        self._abonne(16)

        tranches = self._tranches()

        self.assertEqual(tranches["Dans 2 a 7 jours"], 2)
        self.assertEqual(tranches["Dans 8 a 15 jours"], 2)
        self.assertEqual(tranches["Au-dela de 15 jours"], 1)

    def test_an_ended_subscription_is_in_no_bucket(self):
        membre = self._abonne(5)
        MemberSubscription.objects.filter(member=membre).update(
            end_date=self.today - timedelta(days=1)
        )

        self.assertEqual(sum(self._tranches().values()), 0)

    def test_the_member_list_shows_exactly_one_bucket(self):
        # Le chiffre clique et la liste ouverte doivent dire la meme chose.
        self._abonne(1, nom="Urgent")
        self._abonne(12, nom="Plus tard")

        reponse = self.client.get(
            reverse("members:member_list"),
            {"status": "expiring", "expiring_days": "15", "expiring_from": "8"},
        )

        self.assertContains(reponse, "Plus tard")
        self.assertNotContains(reponse, "Urgent")


class VocabulaireDeLaTresorerieTests(TestCase):
    """
    Encaissements moins decaissements n'est pas un benefice.

    Le mot "resultat" laissait croire a un benefice comptable, alors que ni
    les charges a payer, ni les salaires a venir, ni l'amortissement n'y
    figurent.
    """

    def setUp(self):
        self.organisation = Organization.objects.create(name="Org Tresorerie", slug="org-tresorerie")
        self.gym = Gym.objects.create(
            organization=self.organisation, name="Gym Tresorerie",
            slug="gym-tresorerie", subdomain="gym-tresorerie",
        )
        for code in ("MEMBERS", "POS"):
            module, _ = Module.objects.get_or_create(code=code, defaults={"name": code})
            GymModule.objects.get_or_create(gym=self.gym, module=module, defaults={"is_active": True})
        self.proprietaire = User.objects.create_user(
            username="proprio-tresorerie", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.proprietaire, gym=self.gym, role="owner", is_active=True
        )
        self.client.force_login(self.proprietaire)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _analytique(self):
        return self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id]), {"view": "analytics"}
        )

    def test_the_card_is_named_a_cash_flow(self):
        reponse = self._analytique()

        self.assertContains(reponse, "Flux net de tresorerie")
        self.assertNotContains(reponse, ">Resultat<")

    def test_the_definition_says_what_it_leaves_out(self):
        reponse = self._analytique()

        self.assertContains(reponse, "Ce n'est pas un benefice")
        self.assertContains(reponse, "amortissement")


class CouleurDesExpirationsTests(TestCase):
    """Une expiration de plus n'est jamais une bonne nouvelle."""

    def test_a_rise_in_expirations_is_never_green(self):
        from core.views import _build_trend

        tendance = _build_trend(5, 2, hausse_favorable=False)

        self.assertEqual(tendance["badge_class"], "warning")

    def test_a_fall_in_expirations_is_not_red(self):
        from core.views import _build_trend

        tendance = _build_trend(1, 4, hausse_favorable=False)

        self.assertEqual(tendance["badge_class"], "secondary")

    def test_revenue_keeps_its_own_reading(self):
        from core.views import _build_trend

        self.assertEqual(_build_trend(10, 5)["badge_class"], "success")
        self.assertEqual(_build_trend(5, 10)["badge_class"], "danger")



class LibellesDuStockTests(TestCase):
    """
    Trois nombres justes qui semblaient se contredire.

    1 103 entrees, 62 sorties et 58 mouvements : les deux premiers comptent des
    unites, le troisieme des operations. Rien ne le disait, et la valeur du
    stock ne disait pas non plus a quel prix elle etait comptee.
    """

    def setUp(self):
        self.organisation = Organization.objects.create(
            name="Org Stock", slug="org-stock-libelles"
        )
        self.gym = Gym.objects.create(
            organization=self.organisation,
            name="Gym Stock",
            slug="gym-stock-libelles",
            subdomain="gym-stock-libelles",
        )
        for code in ("MEMBERS", "PRODUCTS"):
            module, _ = Module.objects.get_or_create(code=code, defaults={"name": code})
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )
        self.proprietaire = User.objects.create_user(
            username="proprio-stock-libelles", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.proprietaire, gym=self.gym, role="owner", is_active=True
        )
        self.client.force_login(self.proprietaire)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _analytique(self):
        return self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id]), {"view": "analytics"}
        )

    def test_the_stock_value_says_which_price_it_uses(self):
        reponse = self._analytique()

        self.assertContains(reponse, "(prix de vente)")

    def test_units_and_operations_are_named(self):
        reponse = self._analytique()

        self.assertContains(reponse, "unités")
        self.assertContains(reponse, "opérations")
        self.assertContains(reponse, "ne se comparent pas entre eux")

    def test_the_almost_always_green_pie_is_gone(self):
        # Un camembert vert a nonante-huit pour cent ne demande aucune
        # decision ; les produits qui manquent en demandent une.
        reponse = self._analytique()

        self.assertNotContains(reponse, "stockStatusChart")

    def test_the_products_running_out_are_named(self):
        Product.objects.create(
            gym=self.gym, name="Whey rupture", price=20, quantity=0, is_active=True
        )
        Product.objects.create(
            gym=self.gym, name="Barre presque finie", price=2, quantity=3, is_active=True
        )
        Product.objects.create(
            gym=self.gym, name="Eau bien fournie", price=1, quantity=200, is_active=True
        )

        reponse = self._analytique()

        self.assertContains(reponse, "Whey rupture")
        self.assertContains(reponse, "Barre presque finie")
        self.assertContains(reponse, "Proches de la rupture")

    def test_a_full_stock_says_so_plainly(self):
        Product.objects.create(
            gym=self.gym, name="Eau bien fournie", price=1, quantity=200, is_active=True
        )

        self.assertContains(self._analytique(), "Aucun produit proche de la rupture")

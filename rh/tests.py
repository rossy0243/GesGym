from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from compte.models import User, UserGymRole
from organizations.models import Gym, GymModule, Module, Organization
from pos.models import CashRegister, Payment

from .models import (
    Attendance,
    Employee,
    LeaveRequest,
    OvertimeEntry,
    PayrollContributionRule,
    PaymentRecord,
    PayrollAdjustment,
    PayrollSlip,
)


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
            opened_by=self.user,
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

    def test_general_dashboard_includes_scoped_rh_kpis(self):
        response = self.client.get(
            reverse("core:gym_dashboard", args=[self.gym_a.id]),
            {"view": "analytics"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "KPI RH")
        self.assertContains(response, "Presence aujourd'hui")
        self.assertContains(response, "100,0%")
        self.assertContains(response, "100 CDF")
        self.assertNotContains(response, "999 CDF")

    def test_payment_cannot_target_other_gym_employee(self):
        response = self.client.get(reverse("rh:process_payment", args=[self.employee_b.id, self.today.year, self.today.month]))

        self.assertEqual(response.status_code, 404)

    def test_payroll_action_endpoints_require_post(self):
        rule = PayrollContributionRule.objects.create(
            gym=self.gym_a,
            name="CNSS",
            party=PayrollContributionRule.PARTY_EMPLOYEE_CONTRIBUTION,
            calculation_type=PayrollContributionRule.CALC_PERCENTAGE,
            rate_percent=Decimal("5.00"),
        )

        endpoints = [
            reverse("rh:add_contribution_rule"),
            reverse("rh:toggle_contribution_rule", args=[rule.id]),
            reverse("rh:add_adjustment", args=[self.employee_a.id, self.today.year, self.today.month]),
            reverse("rh:add_leave_request", args=[self.employee_a.id, self.today.year, self.today.month]),
            reverse("rh:add_overtime_entry", args=[self.employee_a.id, self.today.year, self.today.month]),
            reverse("rh:review_payroll_slip", args=[self.employee_a.id, self.today.year, self.today.month]),
            reverse("rh:approve_payroll_slip", args=[self.employee_a.id, self.today.year, self.today.month]),
        ]

        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(endpoint)
                self.assertEqual(response.status_code, 405)

        rule.refresh_from_db()
        self.assertTrue(rule.is_active)
        self.assertFalse(
            PayrollAdjustment.objects.filter(
                employee=self.employee_a,
                year=self.today.year,
                month=self.today.month,
            ).exists()
        )

    def test_salary_payment_creates_pos_expense(self):
        self.client.post(reverse("rh:review_payroll_slip", args=[self.employee_a.id, self.today.year, self.today.month]))
        self.client.post(reverse("rh:approve_payroll_slip", args=[self.employee_a.id, self.today.year, self.today.month]))
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

    def test_paid_slip_blocks_new_adjustments(self):
        self.client.post(reverse("rh:review_payroll_slip", args=[self.employee_a.id, self.today.year, self.today.month]))
        self.client.post(reverse("rh:approve_payroll_slip", args=[self.employee_a.id, self.today.year, self.today.month]))
        self.client.post(
            reverse("rh:process_payment", args=[self.employee_a.id, self.today.year, self.today.month]),
            {"payment_method": "cash", "reference": "SAL-002", "notes": ""},
        )

        response = self.client.post(
            reverse("rh:add_adjustment", args=[self.employee_a.id, self.today.year, self.today.month]),
            {"adjustment_type": "bonus", "label": "Prime tardive", "amount": "50", "notes": ""},
            follow=True,
        )

        slip = PayrollSlip.objects.get(employee=self.employee_a, year=self.today.year, month=self.today.month)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce bulletin est deja paye via POS.")
        self.assertFalse(
            PayrollAdjustment.objects.filter(
                employee=self.employee_a,
                year=self.today.year,
                month=self.today.month,
                label="Prime tardive",
            ).exists()
        )
        self.assertEqual(slip.net_salary, Decimal("100.00"))

    def test_paid_slip_blocks_leave_and_overtime_changes(self):
        self.client.post(reverse("rh:review_payroll_slip", args=[self.employee_a.id, self.today.year, self.today.month]))
        self.client.post(reverse("rh:approve_payroll_slip", args=[self.employee_a.id, self.today.year, self.today.month]))
        self.client.post(
            reverse("rh:process_payment", args=[self.employee_a.id, self.today.year, self.today.month]),
            {"payment_method": "cash", "reference": "SAL-003", "notes": ""},
        )

        leave_response = self.client.post(
            reverse("rh:add_leave_request", args=[self.employee_a.id, self.today.year, self.today.month]),
            {
                "leave_type": "unpaid",
                "start_date": self.today.isoformat(),
                "end_date": self.today.isoformat(),
                "reason": "Absence tardive",
                "status": "approved",
            },
            follow=True,
        )
        overtime_response = self.client.post(
            reverse("rh:add_overtime_entry", args=[self.employee_a.id, self.today.year, self.today.month]),
            {
                "work_date": self.today.isoformat(),
                "hours": "2",
                "rate_multiplier": "1.50",
                "reason": "Fermeture tardive",
                "status": "approved",
            },
            follow=True,
        )

        slip = PayrollSlip.objects.get(employee=self.employee_a, year=self.today.year, month=self.today.month)
        self.assertContains(leave_response, "Ce bulletin est deja paye via POS.")
        self.assertContains(overtime_response, "Ce bulletin est deja paye via POS.")
        self.assertFalse(
            LeaveRequest.objects.filter(
                employee=self.employee_a,
                reason="Absence tardive",
                start_date=self.today,
            ).exists()
        )
        self.assertFalse(
            OvertimeEntry.objects.filter(
                employee=self.employee_a,
                reason="Fermeture tardive",
                work_date=self.today,
            ).exists()
        )
        self.assertEqual(slip.net_salary, Decimal("100.00"))

    def test_paid_slip_hides_adjustment_forms_in_employee_detail(self):
        self.client.post(reverse("rh:review_payroll_slip", args=[self.employee_a.id, self.today.year, self.today.month]))
        self.client.post(reverse("rh:approve_payroll_slip", args=[self.employee_a.id, self.today.year, self.today.month]))
        self.client.post(
            reverse("rh:process_payment", args=[self.employee_a.id, self.today.year, self.today.month]),
            {"payment_method": "cash", "reference": "SAL-004", "notes": ""},
        )

        response = self.client.get(
            reverse("rh:detail", args=[self.employee_a.id]),
            {"year": self.today.year, "month": self.today.month},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce bulletin a deja ete paye via POS.")
        self.assertNotContains(response, "Ajouter une prime / avance / retenue")
        self.assertNotContains(response, "Ajouter un conge")
        self.assertNotContains(response, "Ajouter des heures sup")

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

    def test_payroll_slip_starts_as_draft_then_can_be_approved(self):
        detail_response = self.client.get(
            reverse("rh:detail", args=[self.employee_a.id]),
            {"year": self.today.year, "month": self.today.month},
        )

        self.assertEqual(detail_response.status_code, 200)
        slip = PayrollSlip.objects.get(employee=self.employee_a, year=self.today.year, month=self.today.month)
        self.assertEqual(slip.status, PayrollSlip.STATUS_DRAFT)

        review_response = self.client.post(
            reverse("rh:review_payroll_slip", args=[self.employee_a.id, self.today.year, self.today.month]),
        )

        self.assertRedirects(
            review_response,
            f'{reverse("rh:detail", args=[self.employee_a.id])}?year={self.today.year}&month={self.today.month}',
            fetch_redirect_response=False,
        )
        slip.refresh_from_db()
        self.assertEqual(slip.status, PayrollSlip.STATUS_REVIEWED)

        approve_response = self.client.post(
            reverse("rh:approve_payroll_slip", args=[self.employee_a.id, self.today.year, self.today.month]),
        )

        self.assertRedirects(
            approve_response,
            f'{reverse("rh:detail", args=[self.employee_a.id])}?year={self.today.year}&month={self.today.month}',
            fetch_redirect_response=False,
        )
        slip.refresh_from_db()
        self.assertEqual(slip.status, PayrollSlip.STATUS_APPROVED)

    def test_pdf_download_returns_pdf_response(self):
        response = self.client.get(
            reverse("rh:download_payslip_pdf", args=[self.employee_a.id, self.today.year, self.today.month])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_adjustment_bonus_changes_net_salary(self):
        response = self.client.post(
            reverse("rh:add_adjustment", args=[self.employee_a.id, self.today.year, self.today.month]),
            {"adjustment_type": "bonus", "label": "Prime test", "amount": "50", "notes": ""},
        )

        self.assertRedirects(
            response,
            f'{reverse("rh:detail", args=[self.employee_a.id])}?year={self.today.year}&month={self.today.month}',
            fetch_redirect_response=False,
        )
        slip = PayrollSlip.objects.get(employee=self.employee_a, year=self.today.year, month=self.today.month)
        self.assertEqual(slip.bonus_total, Decimal("50.00"))
        self.assertEqual(slip.net_salary, Decimal("150.00"))

    def test_unpaid_leave_creates_leave_deduction(self):
        response = self.client.post(
            reverse("rh:add_leave_request", args=[self.employee_a.id, self.today.year, self.today.month]),
            {
                "leave_type": "unpaid",
                "start_date": self.today.isoformat(),
                "end_date": self.today.isoformat(),
                "reason": "Absence",
                "status": "approved",
            },
        )

        self.assertEqual(response.status_code, 302)
        slip = PayrollSlip.objects.get(employee=self.employee_a, year=self.today.year, month=self.today.month)
        self.assertEqual(slip.unpaid_leave_days, 1)
        self.assertEqual(slip.leave_deduction_total, Decimal("100.00"))
        self.assertEqual(slip.net_salary, Decimal("0.00"))

    def test_overtime_entry_increases_net_salary(self):
        response = self.client.post(
            reverse("rh:add_overtime_entry", args=[self.employee_a.id, self.today.year, self.today.month]),
            {
                "work_date": self.today.isoformat(),
                "hours": "2",
                "rate_multiplier": "1.50",
                "reason": "Fermeture tardive",
                "status": "approved",
            },
        )

        self.assertEqual(response.status_code, 302)
        slip = PayrollSlip.objects.get(employee=self.employee_a, year=self.today.year, month=self.today.month)
        self.assertEqual(slip.overtime_total, Decimal("37.50"))
        self.assertEqual(slip.net_salary, Decimal("137.50"))

    def test_attendance_rejects_cross_gym_employee(self):
        with self.assertRaises(ValidationError):
            Attendance.objects.create(
                gym=self.gym_a,
                employee=self.employee_b,
                date=self.today + timedelta(days=1),
                status="present",
            )

    def test_leave_rejects_cross_gym_employee(self):
        with self.assertRaises(ValidationError):
            LeaveRequest.objects.create(
                gym=self.gym_a,
                employee=self.employee_b,
                leave_type="paid",
                start_date=self.today,
                end_date=self.today,
                status="approved",
            )

    def test_adjustment_rejects_cross_gym_employee(self):
        with self.assertRaises(ValidationError):
            PayrollAdjustment.objects.create(
                gym=self.gym_a,
                employee=self.employee_b,
                year=self.today.year,
                month=self.today.month,
                adjustment_type="bonus",
                label="Leak",
                amount="10",
            )

    def test_monthly_salary_employee_uses_fixed_base(self):
        employee = Employee.objects.create(
            gym=self.gym_a,
            name="Marc Fixe",
            role="coach",
            compensation_type=Employee.COMPENSATION_MONTHLY,
            monthly_salary=Decimal("1200.00"),
        )
        Attendance.objects.create(gym=self.gym_a, employee=employee, date=self.today, status="present")
        slip = PayrollSlip.ensure_for_period(employee, self.today.year, self.today.month)
        self.assertEqual(slip.base_salary, Decimal("1200.00"))
        self.assertEqual(slip.net_salary, Decimal("1200.00"))

    def test_employee_tax_rule_reduces_net_salary(self):
        PayrollContributionRule.objects.create(
            gym=self.gym_a,
            name="IPR",
            party=PayrollContributionRule.PARTY_EMPLOYEE_TAX,
            calculation_type=PayrollContributionRule.CALC_PERCENTAGE,
            rate_percent=Decimal("10.00"),
        )

        slip = PayrollSlip.ensure_for_period(self.employee_a, self.today.year, self.today.month)

        self.assertEqual(slip.employee_tax_total, Decimal("10.00"))
        self.assertEqual(slip.net_salary, Decimal("90.00"))

    def test_employer_contribution_does_not_reduce_net_salary(self):
        PayrollContributionRule.objects.create(
            gym=self.gym_a,
            name="INSS employeur",
            party=PayrollContributionRule.PARTY_EMPLOYER_CONTRIBUTION,
            calculation_type=PayrollContributionRule.CALC_PERCENTAGE,
            rate_percent=Decimal("5.00"),
        )

        slip = PayrollSlip.ensure_for_period(self.employee_a, self.today.year, self.today.month)

        self.assertEqual(slip.employer_contribution_total, Decimal("5.00"))
        self.assertEqual(slip.net_salary, Decimal("100.00"))

    def test_fixed_employee_contribution_rule_reduces_net_salary(self):
        PayrollContributionRule.objects.create(
            gym=self.gym_a,
            name="Mutuelle",
            party=PayrollContributionRule.PARTY_EMPLOYEE_CONTRIBUTION,
            calculation_type=PayrollContributionRule.CALC_FIXED,
            fixed_amount=Decimal("12.50"),
        )

        slip = PayrollSlip.ensure_for_period(self.employee_a, self.today.year, self.today.month)

        self.assertEqual(slip.employee_contribution_total, Decimal("12.50"))
        self.assertEqual(slip.employee_withholding_total, Decimal("12.50"))
        self.assertEqual(slip.net_salary, Decimal("87.50"))

    def test_contribution_rule_can_be_added_from_dashboard(self):
        response = self.client.post(
            reverse("rh:add_contribution_rule"),
            {
                "year": self.today.year,
                "month": self.today.month,
                "name": "CNSS",
                "party": PayrollContributionRule.PARTY_EMPLOYEE_CONTRIBUTION,
                "calculation_type": PayrollContributionRule.CALC_PERCENTAGE,
                "rate_percent": "3.50",
                "fixed_amount": "0",
                "display_order": "1",
                "is_active": "on",
            },
        )

        self.assertRedirects(
            response,
            f'{reverse("rh:payroll_dashboard")}?year={self.today.year}&month={self.today.month}',
            fetch_redirect_response=False,
        )
        self.assertTrue(PayrollContributionRule.objects.filter(gym=self.gym_a, name="CNSS").exists())

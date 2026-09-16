from datetime import datetime, time as dt_time, timedelta
from decimal import Decimal

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
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

        # La paie est reservee au proprietaire : c'est donc lui qui mene ces
        # tests, qui couvrent surtout les bulletins et les paiements.
        self.user = User.objects.create_user(username="rh-proprietaire", password="test-pass")
        UserGymRole.objects.create(user=self.user, gym=self.gym_a, role="owner")
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
        self.client.login(username="rh-proprietaire", password="test-pass")

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
        """
        La carte intitulee « KPI RH » a ete remplacee par « Expirations
        proches » sur la vue analytique ; les indicateurs RH vivent desormais
        sur la vue d'ensemble. Ce qui compte reste le cloisonnement : la masse
        salariale d'une autre salle ne doit jamais apparaitre.
        """
        response = self.client.get(reverse("core:gym_dashboard", args=[self.gym_a.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_employees"], 1)
        # La masse salariale de la salle A doit etre presente et non nulle.
        self.assertGreater(response.context["monthly_payroll"], 0)
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

    @override_settings(DEFAULT_FROM_EMAIL="noreply@smartclubpro.org")
    def test_employee_create_sends_coordinates_email(self):
        response = self.client.post(
            reverse("rh:create"),
            {
                "name": "Eve Coach",
                "role": "coach",
                "phone": "+243810000220",
                "email": "eve.coach@example.com",
                "compensation_type": Employee.COMPENSATION_DAILY,
                "daily_salary": "150.00",
                "monthly_salary": "0",
                "is_active": "on",
            },
        )

        employee = Employee.objects.get(email="eve.coach@example.com")
        self.assertRedirects(response, reverse("rh:detail", args=[employee.id]), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.from_email, "Org A <noreply@smartclubpro.org>")
        self.assertEqual(message.to, ["eve.coach@example.com"])
        self.assertIn("Org A - Vos coordonnees employe", message.subject)
        self.assertIn("Eve Coach", message.body)
        self.assertIn("+243810000220", message.body)
        self.assertIn("Salaire journalier : 150.00 CDF", message.body)

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



class PaieReserveeAuProprietaireTests(TestCase):
    """
    La paie appartient au proprietaire.

    Le gerant continue de tenir les employes et les presences : c'est le
    travail quotidien de la salle. Mais l'argent des salaires sort de la poche
    du proprietaire, et lui seul le decide.
    """

    def setUp(self):
        self.organisation = Organization.objects.create(name="Org Paie", slug="org-paie")
        self.gym = Gym.objects.create(
            organization=self.organisation, name="Gym Paie",
            slug="gym-paie", subdomain="gym-paie",
        )
        module, _ = Module.objects.get_or_create(code="RH", defaults={"name": "RH"})
        GymModule.objects.get_or_create(gym=self.gym, module=module, defaults={"is_active": True})

        self.proprietaire = User.objects.create_user(username="proprio-paie", password="pass12345")
        UserGymRole.objects.create(user=self.proprietaire, gym=self.gym, role="owner", is_active=True)
        self.gerant = User.objects.create_user(username="gerant-paie", password="pass12345")
        UserGymRole.objects.create(user=self.gerant, gym=self.gym, role="manager", is_active=True)

        self.employe = Employee.objects.create(
            gym=self.gym, name="Alice Paie", role="coach", daily_salary=Decimal("100.00"),
        )
        self.today = timezone.localdate()

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _adresses_de_paie(self):
        return [
            reverse("rh:payroll_dashboard"),
            reverse("rh:process_payment", args=[self.employe.id, self.today.year, self.today.month]),
            reverse("rh:download_payslip_pdf", args=[self.employe.id, self.today.year, self.today.month]),
        ]

    # --- Ce que le gerant ne peut plus faire ---------------------------------------------------

    def test_a_manager_no_longer_reaches_payroll(self):
        self._connecter(self.gerant)

        for adresse in self._adresses_de_paie():
            with self.subTest(adresse=adresse):
                self.assertIn(self.client.get(adresse).status_code, (302, 403))

    def test_a_manager_cannot_approve_or_pay(self):
        self._connecter(self.gerant)

        for adresse in (
            reverse("rh:review_payroll_slip", args=[self.employe.id, self.today.year, self.today.month]),
            reverse("rh:approve_payroll_slip", args=[self.employe.id, self.today.year, self.today.month]),
            reverse("rh:add_adjustment", args=[self.employe.id, self.today.year, self.today.month]),
        ):
            with self.subTest(adresse=adresse):
                self.assertIn(self.client.post(adresse).status_code, (302, 403))

    def test_the_payroll_menu_is_hidden_from_a_manager(self):
        self._connecter(self.gerant)

        reponse = self.client.get(reverse("rh:list"))

        self.assertEqual(reponse.status_code, 200)
        self.assertNotContains(reponse, reverse("rh:payroll_dashboard"))

    # --- Ce que le gerant garde ------------------------------------------------------------------

    def test_a_manager_still_manages_employees(self):
        self._connecter(self.gerant)

        self.assertEqual(self.client.get(reverse("rh:list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("rh:create")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("rh:detail", args=[self.employe.id])).status_code, 200
        )

    def test_a_manager_still_records_attendance(self):
        self._connecter(self.gerant)

        self.assertEqual(self.client.get(reverse("rh:attendance_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("rh:attendance_create")).status_code, 200)

    # --- Ce que le proprietaire peut ----------------------------------------------------------------

    def test_the_owner_reaches_payroll(self):
        self._connecter(self.proprietaire)

        for adresse in (reverse("rh:payroll_dashboard"),
                        reverse("rh:process_payment", args=[self.employe.id, self.today.year, self.today.month])):
            with self.subTest(adresse=adresse):
                self.assertEqual(self.client.get(adresse).status_code, 200)

    def test_the_payroll_menu_is_offered_to_the_owner(self):
        self._connecter(self.proprietaire)

        self.assertContains(self.client.get(reverse("rh:list")), reverse("rh:payroll_dashboard"))

    def test_the_rule_is_written_once(self):
        from smartclub.access_control import RH_ATTENDANCE_ROLES, RH_EMPLOYEE_ROLES, RH_PAYROLL_ROLES

        self.assertEqual(RH_PAYROLL_ROLES, {"owner"})
        # Le reste du module RH ne bouge pas.
        self.assertIn("manager", RH_EMPLOYEE_ROLES)
        self.assertIn("manager", RH_ATTENDANCE_ROLES)



class PresenceParLeLecteurTests(TestCase):
    """
    Le passage a la porte vaut pointage, la main garde le dernier mot.

    Pointer a la main un employe qui vient de passer devant le lecteur
    n'apprenait rien a personne ; mais un badge oublie, une journee en course
    ou un employe envoye ailleurs ne se lisent pas a la porte.
    """

    def setUp(self):
        from rh.models import Attendance

        self.Attendance = Attendance
        self.organisation = Organization.objects.create(name="Org Presence", slug="org-presence")
        self.gym = Gym.objects.create(
            organization=self.organisation, name="Gym Presence",
            slug="gym-presence", subdomain="gym-presence",
        )
        module, _ = Module.objects.get_or_create(code="RH", defaults={"name": "RH"})
        GymModule.objects.get_or_create(gym=self.gym, module=module, defaults={"is_active": True})

        self.employe = Employee.objects.create(
            gym=self.gym, name="Paul Gardien", role="cleaner", daily_salary=Decimal("100.00"),
        )
        self.gerant = User.objects.create_user(username="gerant-presence", password="pass12345")
        UserGymRole.objects.create(user=self.gerant, gym=self.gym, role="manager", is_active=True)
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()
        self.today = timezone.localdate()

    def _moment(self, heure, minute=0):
        return timezone.make_aware(
            datetime.combine(self.today, dt_time(heure, minute)),
            timezone.get_current_timezone(),
        )

    # --- Le passage vaut presence -----------------------------------------------------------

    def test_a_passage_marks_the_day_present(self):
        from rh import presence

        presence.noter_passage(self.employe, self._moment(8, 5))

        pointage = self.Attendance.objects.get(employee=self.employe, date=self.today)
        self.assertEqual(pointage.status, "present")
        self.assertEqual(pointage.source, self.Attendance.SOURCE_LECTEUR)
        self.assertEqual(pointage.heure_arrivee.strftime("%H:%M"), "08:05")

    def test_the_arrival_time_is_the_first_passage(self):
        from rh import presence

        presence.noter_passage(self.employe, self._moment(8, 5))
        presence.noter_passage(self.employe, self._moment(13, 40))

        pointage = self.Attendance.objects.get(employee=self.employe, date=self.today)
        self.assertEqual(pointage.heure_arrivee.strftime("%H:%M"), "08:05")
        self.assertEqual(self.Attendance.objects.count(), 1)

    def test_an_earlier_passage_moves_the_arrival_time(self):
        from rh import presence

        presence.noter_passage(self.employe, self._moment(9, 0))
        presence.noter_passage(self.employe, self._moment(7, 30))

        pointage = self.Attendance.objects.get(employee=self.employe, date=self.today)
        self.assertEqual(pointage.heure_arrivee.strftime("%H:%M"), "07:30")

    # --- La main tranche ----------------------------------------------------------------------

    def test_a_hand_written_absence_is_never_overwritten(self):
        from rh import presence

        self.Attendance.objects.create(
            gym=self.gym, employee=self.employe, date=self.today,
            status="absent", source=self.Attendance.SOURCE_MANUELLE,
        )

        presence.noter_passage(self.employe, self._moment(8, 5))

        pointage = self.Attendance.objects.get(employee=self.employe, date=self.today)
        self.assertEqual(pointage.status, "absent")
        self.assertEqual(pointage.source, self.Attendance.SOURCE_MANUELLE)

    def test_the_form_records_a_hand_written_presence(self):
        self.client.post(
            reverse("rh:attendance_create"),
            {"employee": self.employe.id, "date": self.today.isoformat(), "status": "present"},
        )

        pointage = self.Attendance.objects.get(employee=self.employe, date=self.today)
        self.assertEqual(pointage.source, self.Attendance.SOURCE_MANUELLE)

    def test_the_bulk_screen_records_hand_written_presences(self):
        self.client.post(
            reverse("rh:attendance_bulk"),
            {"date": self.today.isoformat(), f"attendance_{self.employe.id}": "absent"},
        )

        pointage = self.Attendance.objects.get(employee=self.employe, date=self.today)
        self.assertEqual(pointage.status, "absent")
        self.assertEqual(pointage.source, self.Attendance.SOURCE_MANUELLE)

    def test_a_correction_survives_a_later_passage(self):
        from rh import presence

        presence.noter_passage(self.employe, self._moment(8, 5))
        self.client.post(
            reverse("rh:attendance_create"),
            {"employee": self.employe.id, "date": self.today.isoformat(), "status": "absent"},
        )

        presence.noter_passage(self.employe, self._moment(18, 0))

        self.assertEqual(
            self.Attendance.objects.get(employee=self.employe, date=self.today).status, "absent"
        )

    # --- Les ecrans -----------------------------------------------------------------------------

    def test_the_attendance_screen_shows_the_hour_and_its_origin(self):
        from rh import presence

        presence.noter_passage(self.employe, self._moment(8, 5))

        reponse = self.client.get(reverse("rh:attendance_list"))

        self.assertContains(reponse, "Arrivée")
        self.assertContains(reponse, "08:05")
        self.assertContains(reponse, "Passage au lecteur")

    def test_the_employee_sheet_shows_the_hour(self):
        from rh import presence

        presence.noter_passage(self.employe, self._moment(8, 5))

        reponse = self.client.get(reverse("rh:detail", args=[self.employe.id]))

        self.assertContains(reponse, "08:05")

    # --- La paie ----------------------------------------------------------------------------------

    def test_a_passage_counts_as_a_worked_day(self):
        from rh import presence
        from rh.models import PayrollSlip

        presence.noter_passage(self.employe, self._moment(8, 5))

        bulletin = PayrollSlip.ensure_for_period(self.employe, self.today.year, self.today.month)

        self.assertEqual(bulletin.present_days, 1)



class HeureDeDepartTests(TestCase):
    """L'heure de sortie et la duree, quand le depart est connu."""

    def setUp(self):
        from rh.models import Attendance

        self.Attendance = Attendance
        self.organisation = Organization.objects.create(name="Org Depart", slug="org-depart")
        self.gym = Gym.objects.create(
            organization=self.organisation, name="Gym Depart",
            slug="gym-depart", subdomain="gym-depart",
        )
        module, _ = Module.objects.get_or_create(code="RH", defaults={"name": "RH"})
        GymModule.objects.get_or_create(gym=self.gym, module=module, defaults={"is_active": True})
        self.employe = Employee.objects.create(
            gym=self.gym, name="Paul Gardien", role="cleaner", daily_salary=Decimal("100.00"),
        )
        self.gerant = User.objects.create_user(username="gerant-depart", password="pass12345")
        UserGymRole.objects.create(user=self.gerant, gym=self.gym, role="manager", is_active=True)
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()
        self.today = timezone.localdate()

    def _moment(self, heure, minute=0):
        return timezone.make_aware(
            datetime.combine(self.today, dt_time(heure, minute)),
            timezone.get_current_timezone(),
        )

    def _pointer(self, heure, minute=0, sens="entree"):
        from rh import presence

        return presence.noter_passage(self.employe, self._moment(heure, minute), sens=sens)

    def test_an_exit_fills_the_departure_hour(self):
        self._pointer(8, 0)
        self._pointer(17, 30, sens="sortie")

        pointage = self.Attendance.objects.get(employee=self.employe)
        self.assertEqual(pointage.heure_depart.strftime("%H:%M"), "17:30")

    def test_the_last_exit_is_the_one_kept(self):
        self._pointer(8, 0)
        self._pointer(12, 0, sens="sortie")
        self._pointer(17, 30, sens="sortie")

        self.assertEqual(
            self.Attendance.objects.get(employee=self.employe).heure_depart.strftime("%H:%M"),
            "17:30",
        )

    def test_an_exit_alone_still_marks_the_day(self):
        # Badge oublie le matin : le depart existe, l'arrivee reste inconnue.
        self._pointer(17, 30, sens="sortie")

        pointage = self.Attendance.objects.get(employee=self.employe)
        self.assertEqual(pointage.status, "present")
        self.assertIsNone(pointage.heure_arrivee)
        self.assertEqual(pointage.duree_affichee, "")

    def test_the_duration_is_the_time_between_the_two(self):
        self._pointer(8, 5)
        self._pointer(17, 30, sens="sortie")

        self.assertEqual(
            self.Attendance.objects.get(employee=self.employe).duree_affichee, "9 h 25"
        )

    def test_a_departure_before_the_arrival_gives_no_duration(self):
        pointage = self.Attendance.objects.create(
            gym=self.gym, employee=self.employe, date=self.today, status="present",
            heure_arrivee=dt_time(17, 0), heure_depart=dt_time(8, 0),
        )

        self.assertIsNone(pointage.duree_presence)
        self.assertEqual(pointage.duree_affichee, "")

    def test_a_hand_written_presence_is_not_touched_by_an_exit(self):
        self.Attendance.objects.create(
            gym=self.gym, employee=self.employe, date=self.today,
            status="absent", source=self.Attendance.SOURCE_MANUELLE,
        )

        self._pointer(17, 30, sens="sortie")

        pointage = self.Attendance.objects.get(employee=self.employe)
        self.assertEqual(pointage.status, "absent")
        self.assertIsNone(pointage.heure_depart)

    def test_the_screens_show_the_departure_and_the_duration(self):
        self._pointer(8, 5)
        self._pointer(17, 30, sens="sortie")

        liste = self.client.get(reverse("rh:attendance_list"))
        fiche = self.client.get(reverse("rh:detail", args=[self.employe.id]))

        for reponse in (liste, fiche):
            self.assertContains(reponse, "17:30")
            self.assertContains(reponse, "9 h 25")
        self.assertContains(liste, "Départ")
        self.assertContains(liste, "Durée")

    def test_without_an_exit_reader_nothing_is_invented(self):
        self._pointer(8, 5)

        pointage = self.Attendance.objects.get(employee=self.employe)
        self.assertIsNone(pointage.heure_depart)
        self.assertEqual(pointage.duree_affichee, "")

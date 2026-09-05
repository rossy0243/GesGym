from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from compte.models import User, UserGymRole
from members.models import Member
from organizations.models import Gym, GymModule, Module, Organization, SensitiveActivityLog
from products.models import Product, StockMovement
from subscriptions.models import MemberSubscription, SubscriptionPlan
from .models import CashRegister, ExchangeRate, Payment
from .views import MEMBER_SEARCH_LIMIT
from .services import (
    record_expense,
    record_payment,
    record_product_sale,
    record_subscription_payment,
)


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
        # Une date relative, et non figee : posee dans le passe, elle finirait
        # par designer une periode deja close, que la caisse refuse desormais.
        start_date = timezone.localdate() + timedelta(days=3)

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
        self.assertEqual(subscription.end_date, start_date + timedelta(days=30))
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

    def test_each_user_can_have_their_own_open_register(self):
        cashier_register = CashRegister.objects.create(
            gym=self.gym_a,
            opened_by=self.cashier,
            opening_amount=Decimal("100.00"),
            exchange_rate=Decimal("2800.00"),
        )
        manager_register = CashRegister.objects.create(
            gym=self.gym_a,
            opened_by=self.manager,
            opening_amount=Decimal("200.00"),
            exchange_rate=Decimal("2800.00"),
        )

        self.assertNotEqual(cashier_register.id, manager_register.id)
        with self.assertRaises(ValidationError):
            CashRegister.objects.create(
                gym=self.gym_a,
                opened_by=self.cashier,
                opening_amount=Decimal("300.00"),
                exchange_rate=Decimal("2800.00"),
            )

    def test_cashier_dashboard_uses_only_current_users_register(self):
        cashier_register = CashRegister.objects.create(
            gym=self.gym_a,
            opened_by=self.cashier,
            opening_amount=Decimal("100.00"),
            exchange_rate=Decimal("2800.00"),
        )
        manager_register = CashRegister.objects.create(
            gym=self.gym_a,
            opened_by=self.manager,
            opening_amount=Decimal("200.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.client.login(username="cashier-pos", password="test-pass")

        response = self.client.get(reverse("pos:cashier_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["register"], cashier_register)
        self.assertContains(response, cashier_register.session_code)
        self.assertNotContains(response, manager_register.session_code)

    def test_pos_payment_uses_current_users_register(self):
        CashRegister.objects.create(
            gym=self.gym_a,
            opened_by=self.cashier,
            opening_amount=Decimal("100.00"),
            exchange_rate=Decimal("2800.00"),
        )
        manager_register = CashRegister.objects.create(
            gym=self.gym_a,
            opened_by=self.manager,
            opening_amount=Decimal("200.00"),
            exchange_rate=Decimal("2800.00"),
        )
        product = Product.objects.create(
            gym=self.gym_a,
            name="Energy Drink",
            price=Decimal("3.00"),
            quantity=5,
        )

        payment = record_product_sale(
            gym=self.gym_a,
            product=product,
            quantity=1,
            currency="USD",
            method="cash",
            created_by=self.manager,
        )

        self.assertEqual(payment.cash_register_id, manager_register.id)
        self.assertEqual(payment.created_by_id, self.manager.id)

    def test_manager_can_force_close_another_users_register(self):
        """
        Regle revue : une caisse laissee ouverte par quelqu'un qui a quitte son
        poste bloquait tout, personne ne pouvant la fermer. Gerants et
        proprietaires peuvent desormais la cloturer d'autorite ; l'ecart reste
        attribue a son titulaire et l'operation est tracee.
        """
        cashier_register = CashRegister.objects.create(
            gym=self.gym_a,
            opened_by=self.cashier,
            opening_amount=Decimal("100.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.client.login(username="manager-pos", password="test-pass")

        response = self.client.post(
            reverse("pos:close_register", args=[cashier_register.id]),
            {"real_amount": "100.00"},
        )

        self.assertEqual(response.status_code, 302)
        cashier_register.refresh_from_db()
        self.assertTrue(cashier_register.is_closed)
        self.assertEqual(cashier_register.opened_by, self.cashier)
        self.assertTrue(cashier_register.was_force_closed)

    def test_manager_can_supervise_register_history(self):
        cashier_register = CashRegister.objects.create(
            gym=self.gym_a,
            opened_by=self.cashier,
            opening_amount=Decimal("100.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.client.login(username="manager-pos", password="test-pass")

        response = self.client.get(reverse("pos:register_history"), {"status": "open"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, cashier_register.session_code)

    def test_cashier_dashboard_labels_machine_maintenance_payments(self):
        register = CashRegister.objects.create(
            gym=self.gym_a,
            opened_by=self.cashier,
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
            opened_by=self.cashier,
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


class ForcedRegisterClosureTests(TestCase):
    """Une caisse laissee ouverte ne doit pas rester bloquee indefiniment."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Caisse", slug="org-caisse"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Caisse",
            slug="gym-caisse",
            subdomain="gym-caisse",
        )
        module, _ = Module.objects.get_or_create(code="POS", defaults={"name": "POS"})
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.owner = User.objects.create_user(
            username="owner-caisse",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.manager = User.objects.create_user(
            username="manager-caisse", password="pass12345"
        )
        self.cashier = User.objects.create_user(
            username="cashier-caisse", password="pass12345"
        )
        self.other_cashier = User.objects.create_user(
            username="cashier-voisin", password="pass12345"
        )
        for user, role in [
            (self.manager, "manager"),
            (self.cashier, "cashier"),
            (self.other_cashier, "cashier"),
        ]:
            UserGymRole.objects.create(
                user=user, gym=self.gym, role=role, is_active=True
            )

        self.register = CashRegister.objects.create(
            gym=self.gym,
            opened_by=self.cashier,
            opening_amount=Decimal("10000.00"),
            exchange_rate=Decimal("2800.00"),
        )

    def _as(self, user):
        client = Client()
        client.force_login(user)
        return client

    def _close(self, user, amount="10000"):
        return self._as(user).post(
            reverse("pos:close_register", args=[self.register.id]),
            {"real_amount": amount},
            follow=True,
        )

    # --- Cloture d'autorite ---------------------------------------------------

    def test_owner_can_close_a_register_left_open(self):
        response = self._close(self.owner)

        self.register.refresh_from_db()
        self.assertTrue(self.register.is_closed)
        self.assertEqual(self.register.closed_by, self.owner)
        self.assertIn(
            "cloturee d'autorite", str(list(response.context["messages"])[0])
        )

    def test_manager_can_close_a_register_left_open(self):
        self._close(self.manager)

        self.register.refresh_from_db()
        self.assertTrue(self.register.is_closed)
        self.assertEqual(self.register.closed_by, self.manager)

    def test_the_difference_stays_attached_to_the_original_holder(self):
        self._close(self.owner, amount="12000")

        self.register.refresh_from_db()
        self.assertEqual(self.register.opened_by, self.cashier)
        self.assertEqual(self.register.difference, Decimal("2000.00"))
        self.assertTrue(self.register.was_force_closed)

    def test_a_forced_closure_is_audited_as_such(self):
        self._close(self.owner)

        entry = SensitiveActivityLog.objects.filter(
            action="pos.register_closed"
        ).latest("id")
        self.assertTrue(entry.metadata["forced"])
        self.assertEqual(entry.metadata["opened_by"], self.cashier.username)

    def test_the_page_warns_before_a_forced_closure(self):
        response = self._as(self.owner).get(
            reverse("pos:close_register", args=[self.register.id])
        )

        self.assertTrue(response.context["is_forced_closure"])
        self.assertContains(response, "Clôture d'autorité")

    def test_the_holder_can_open_a_new_register_afterwards(self):
        self._close(self.owner)

        response = self._as(self.cashier).post(
            reverse("pos:open_register"),
            {"opening_amount": "5000", "exchange_rate": "2800"},
            follow=True,
        )

        self.assertIn("Caisse ouverte", str(list(response.context["messages"])[0]))
        self.assertTrue(
            CashRegister.objects.filter(
                gym=self.gym, opened_by=self.cashier, is_closed=False
            ).exists()
        )

    # --- Ce qui reste interdit -------------------------------------------------

    def test_a_cashier_still_cannot_close_someone_else_register(self):
        response = self._as(self.other_cashier).post(
            reverse("pos:close_register", args=[self.register.id]),
            {"real_amount": "10000"},
        )

        self.register.refresh_from_db()
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.register.is_closed)

    def test_a_normal_closure_is_not_flagged_as_forced(self):
        response = self._close(self.cashier)

        self.register.refresh_from_db()
        self.assertFalse(self.register.was_force_closed)
        self.assertNotIn(
            "autorite", str(list(response.context["messages"])[0])
        )

    def test_another_gym_register_stays_out_of_reach(self):
        other_organization = Organization.objects.create(
            name="Org Voisine Caisse", slug="org-voisine-caisse"
        )
        other_gym = Gym.objects.create(
            organization=other_organization,
            name="Gym Voisin Caisse",
            slug="gym-voisin-caisse",
            subdomain="gym-voisin-caisse",
        )
        GymModule.objects.get_or_create(
            gym=other_gym,
            module=Module.objects.get(code="POS"),
            defaults={"is_active": True},
        )
        intruder = User.objects.create_user(
            username="owner-voisin-caisse",
            password="pass12345",
            owned_organization=other_organization,
        )

        response = self._as(intruder).post(
            reverse("pos:close_register", args=[self.register.id]),
            {"real_amount": "0"},
        )

        self.register.refresh_from_db()
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.register.is_closed)


class CashDrawerSeparationTests(TestCase):
    """Le tiroir ne contient que des especes ; le reste se rapproche ailleurs."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Tiroir", slug="org-tiroir"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Tiroir",
            slug="gym-tiroir",
            subdomain="gym-tiroir",
        )
        self.user = User.objects.create_user(username="caissier-tiroir", password="pass12345")
        self.register = CashRegister.objects.create(
            gym=self.gym,
            opened_by=self.user,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )

    def _movement(self, amount, transaction_type, method):
        return Payment.objects.create(
            gym=self.gym,
            cash_register=self.register,
            amount=Decimal(amount),
            currency="CDF",
            amount_cdf=Decimal(amount),
            exchange_rate=Decimal("2800.00"),
            method=method,
            type=transaction_type,
            category="subscription" if transaction_type == "in" else "expense",
            status="success",
            created_by=self.user,
        )

    # --- Ce que le caissier doit compter --------------------------------------

    def test_only_cash_counts_towards_the_expected_drawer(self):
        self._movement("50000.00", "in", "cash")
        self._movement("70000.00", "in", "mobile_money")

        self.assertEqual(self.register.expected_total(), Decimal("150000.00"))

    def test_a_bank_transfer_never_touches_the_drawer(self):
        before = self.register.expected_total()

        self._movement("50000.00", "out", "bank_transfer")

        self.assertEqual(self.register.expected_total(), before)

    def test_a_card_payment_never_touches_the_drawer(self):
        before = self.register.expected_total()

        self._movement("30000.00", "in", "card")

        self.assertEqual(self.register.expected_total(), before)

    def test_cash_movements_still_move_the_drawer(self):
        self._movement("20000.00", "in", "cash")
        self._movement("5000.00", "out", "cash")

        self.assertEqual(self.register.expected_total(), Decimal("115000.00"))

    # --- Ce qui reste a rapprocher ---------------------------------------------

    def test_non_cash_movements_are_tracked_apart(self):
        self._movement("70000.00", "in", "mobile_money")
        self._movement("20000.00", "out", "bank_transfer")
        self._movement("40000.00", "in", "cash")

        self.assertEqual(self.register.non_cash_entries(), Decimal("70000.00"))
        self.assertEqual(self.register.non_cash_exits(), Decimal("20000.00"))
        self.assertEqual(self.register.non_cash_balance(), Decimal("50000.00"))

    def test_global_totals_still_cover_every_method(self):
        """Les rapports comptables continuent de tout voir."""
        self._movement("40000.00", "in", "cash")
        self._movement("70000.00", "in", "mobile_money")
        self._movement("10000.00", "out", "cash")
        self._movement("20000.00", "out", "bank_transfer")

        self.assertEqual(self.register.total_entries(), Decimal("110000.00"))
        self.assertEqual(self.register.total_exits(), Decimal("30000.00"))

    # --- Solde negatif : signale, jamais bloque ---------------------------------

    def test_a_negative_cash_balance_is_allowed_but_flagged(self):
        self._movement("300000.00", "out", "cash")

        self.assertEqual(self.register.expected_total(), Decimal("-200000.00"))
        self.assertTrue(self.register.has_negative_cash())

    def test_a_healthy_balance_is_not_flagged(self):
        self._movement("10000.00", "out", "cash")

        self.assertFalse(self.register.has_negative_cash())

    def test_non_cash_exits_cannot_make_the_drawer_negative(self):
        """Un virement important ne doit pas declencher une fausse alerte."""
        self._movement("900000.00", "out", "bank_transfer")

        self.assertEqual(self.register.expected_total(), Decimal("100000.00"))
        self.assertFalse(self.register.has_negative_cash())

    # --- Ce que voit le caissier -------------------------------------------------

    def test_the_close_page_separates_both_natures(self):
        self._movement("70000.00", "in", "mobile_money")
        client = Client()
        client.force_login(self.user)
        UserGymRole.objects.create(
            user=self.user, gym=self.gym, role="cashier", is_active=True
        )
        module, _ = Module.objects.get_or_create(code="POS", defaults={"name": "POS"})
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )

        response = client.get(reverse("pos:close_register", args=[self.register.id]))

        self.assertEqual(response.context["expected_total"], Decimal("100000.00"))
        self.assertEqual(response.context["non_cash_entries"], Decimal("70000.00"))
        self.assertContains(response, "hors tiroir-caisse")


class ExpenseCurrencyTests(TestCase):
    """Le decaissement se saisit dans la devise reellement sortie du tiroir."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Devise", slug="org-devise"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Devise",
            slug="gym-devise",
            subdomain="gym-devise",
        )
        self.user = User.objects.create_user(username="caissier-devise", password="pass12345")
        UserGymRole.objects.create(
            user=self.user, gym=self.gym, role="cashier", is_active=True
        )
        module, _ = Module.objects.get_or_create(code="POS", defaults={"name": "POS"})
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.register = CashRegister.objects.create(
            gym=self.gym,
            opened_by=self.user,
            opening_amount=Decimal("500000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _decaisser(self, **overrides):
        payload = {
            "type": "out",
            "amount": "10.00",
            "expense_currency": "USD",
            "description": "Achat fournitures",
        }
        payload.update(overrides)
        return self.client.post(reverse("pos:cashier_dashboard"), payload, follow=True)

    def test_an_expense_in_usd_is_converted_at_the_session_rate(self):
        self._decaisser()

        depense = Payment.objects.get(gym=self.gym, type="out")
        self.assertEqual(depense.currency, "USD")
        self.assertEqual(depense.amount, Decimal("10.00"))
        self.assertEqual(depense.amount_cdf, Decimal("28000.00"))
        self.assertEqual(self.register.expected_total(), Decimal("472000.00"))

    def test_an_expense_in_cdf_stays_in_cdf(self):
        self._decaisser(amount="28000.00", expense_currency="CDF")

        depense = Payment.objects.get(gym=self.gym, type="out")
        self.assertEqual(depense.currency, "CDF")
        self.assertEqual(depense.amount_cdf, Decimal("28000.00"))

    def test_the_currency_defaults_to_cdf_when_absent(self):
        response = self.client.post(
            reverse("pos:cashier_dashboard"),
            {"type": "out", "amount": "5000.00", "description": "Taxi"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        depense = Payment.objects.get(gym=self.gym, type="out")
        self.assertEqual(depense.currency, "CDF")

    def test_an_unknown_currency_is_refused(self):
        self._decaisser(expense_currency="EUR")

        self.assertFalse(Payment.objects.filter(gym=self.gym, type="out").exists())

    def test_the_sensitive_log_keeps_both_amounts(self):
        self._decaisser()

        trace = SensitiveActivityLog.objects.get(action="pos.expense_recorded")
        self.assertEqual(trace.metadata["devise"], "USD")
        self.assertEqual(trace.metadata["montant_saisi"], "10.00")
        self.assertEqual(trace.metadata["amount_cdf"], "28000.00")


class CashierMemberSearchTests(TestCase):
    """
    Le caissier cherche son client au lieu de faire defiler la liste.

    La liste complete n'est plus rendue dans la page : une salle qui grandit
    faisait grossir la caisse a chaque ouverture.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Recherche", slug="org-recherche"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Recherche",
            slug="gym-recherche",
            subdomain="gym-recherche",
        )
        self.autre_gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Voisin",
            slug="gym-voisin-recherche",
            subdomain="gym-voisin-recherche",
        )
        module, _ = Module.objects.get_or_create(code="POS", defaults={"name": "POS"})
        for salle in (self.gym, self.autre_gym):
            GymModule.objects.get_or_create(
                gym=salle, module=module, defaults={"is_active": True}
            )

        self.caissier = User.objects.create_user(
            username="caissier-recherche", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.caissier, gym=self.gym, role="cashier", is_active=True
        )
        self.client.force_login(self.caissier)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

        self.bruno = Member.objects.create(
            gym=self.gym, first_name="Bruno", last_name="Kalala",
            phone="+243840000001",
        )
        self.sarah = Member.objects.create(
            gym=self.gym, first_name="Sarah", last_name="Nkosi",
            phone="+243850000002",
        )
        self.url = reverse("pos:search_members")

    def _chercher(self, q):
        return self.client.get(self.url, {"q": q}).json()

    # --- Ce que la recherche trouve --------------------------------------------

    def test_a_member_is_found_by_last_name(self):
        noms = [m["name"] for m in self._chercher("kalala")["members"]]

        self.assertIn("Bruno Kalala", noms)
        self.assertNotIn("Sarah Nkosi", noms)

    def test_a_member_is_found_by_first_name(self):
        noms = [m["name"] for m in self._chercher("sarah")["members"]]

        self.assertEqual(noms, ["Sarah Nkosi"])

    def test_a_member_is_found_by_phone_fragment(self):
        # Au comptoir, le client donne souvent son numero plutot que son nom.
        noms = [m["name"] for m in self._chercher("840000001")["members"]]

        self.assertEqual(noms, ["Bruno Kalala"])

    def test_the_search_ignores_the_case(self):
        self.assertTrue(self._chercher("KALALA")["members"])

    def test_a_search_matching_nothing_returns_an_empty_list(self):
        reponse = self._chercher("zzzzzz")

        self.assertEqual(reponse["members"], [])
        self.assertEqual(reponse["total"], 0)

    # --- Ce que la recherche ne doit jamais renvoyer ------------------------------

    def test_a_member_of_another_gym_is_never_returned(self):
        Member.objects.create(
            gym=self.autre_gym, first_name="Bruno", last_name="Kalala",
            phone="+243860000003",
        )

        resultats = self._chercher("kalala")["members"]

        self.assertEqual(len(resultats), 1)
        self.assertEqual(resultats[0]["id"], self.bruno.id)

    def test_an_inactive_member_is_never_returned(self):
        self.bruno.is_active = False
        self.bruno.save(update_fields=["is_active"])

        self.assertEqual(self._chercher("kalala")["members"], [])

    # --- Ce que chaque ligne porte -------------------------------------------------

    def test_each_result_carries_what_the_counter_needs(self):
        resultat = self._chercher("kalala")["members"][0]

        self.assertEqual(resultat["id"], self.bruno.id)
        self.assertEqual(resultat["name"], "Bruno Kalala")
        self.assertEqual(resultat["phone"], "+243840000001")
        # Le statut evite d'encaisser pour quelqu'un qui vient de resilier.
        self.assertIn(resultat["status"], ("active", "expired", "suspended"))
        self.assertTrue(resultat["photo"])

    def test_the_status_follows_the_subscription(self):
        plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        today = timezone.localdate()
        MemberSubscription.objects.create(
            gym=self.gym, member=self.bruno, plan=plan,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=29),
            is_active=True,
        )

        resultat = self._chercher("kalala")["members"][0]

        self.assertEqual(resultat["status"], "active")

    # --- Bornage --------------------------------------------------------------------

    def test_the_results_are_capped_and_the_page_says_so(self):
        # Sans bornage, une recherche trop courte deverserait tout le fichier.
        for i in range(MEMBER_SEARCH_LIMIT + 5):
            Member.objects.create(
                gym=self.gym, first_name="Homonyme", last_name=f"Numero{i}",
                phone=f"+24387000{i:04d}",
            )

        reponse = self._chercher("homonyme")

        self.assertEqual(len(reponse["members"]), MEMBER_SEARCH_LIMIT)
        self.assertEqual(reponse["total"], MEMBER_SEARCH_LIMIT + 5)
        self.assertTrue(reponse["tronque"])

    def test_a_complete_result_is_not_flagged_as_truncated(self):
        reponse = self._chercher("kalala")

        self.assertFalse(reponse["tronque"])

    def test_the_order_is_stable_between_two_identical_searches(self):
        # Sans ordre explicite, deux appels peuvent rendre les memes lignes
        # dans un ordre different et la selection au clavier devient hasardeuse.
        for i in range(6):
            Member.objects.create(
                gym=self.gym, first_name="Homonyme", last_name=f"Numero{i}",
                phone=f"+24388000{i:04d}",
            )

        premier = [m["id"] for m in self._chercher("homonyme")["members"]]
        second = [m["id"] for m in self._chercher("homonyme")["members"]]

        self.assertEqual(premier, second)

    # --- Acces -----------------------------------------------------------------------

    def test_a_coach_cannot_search_the_clients(self):
        coach = User.objects.create_user(username="coach-recherche", password="pass12345")
        UserGymRole.objects.create(
            user=coach, gym=self.gym, role="coach", is_active=True
        )
        self.client.force_login(coach)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

        reponse = self.client.get(self.url, {"q": "kalala"})

        self.assertIn(reponse.status_code, (302, 403))

    # --- La page de caisse -------------------------------------------------------------

    def test_the_cashier_page_no_longer_renders_the_whole_list(self):
        html = self.client.get(reverse("pos:cashier_dashboard")).content.decode(
            "utf-8", "replace"
        )

        self.assertIn("memberSearchInput", html)
        # Aucune option de client pre-rendue : c'est tout l'interet du changement.
        self.assertNotIn("Bruno Kalala", html)
        self.assertNotIn("Sarah Nkosi", html)

    def test_the_hidden_field_still_carries_the_submitted_member(self):
        # Le formulaire envoie toujours "member" : le champ de recherche n'est
        # qu'une facade, la valeur postee n'a pas change de nom.
        html = self.client.get(reverse("pos:cashier_dashboard")).content.decode(
            "utf-8", "replace"
        )

        self.assertIn('name="member" id="memberSelect"', html)


class FutureStartDateTests(TestCase):
    """
    Un abonnement peut se payer d'avance pour demarrer plus tard.

    Cas reel : le membre paie aujourd'hui mais ne commencera qu'au mois
    prochain.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Avance", slug="org-avance"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Avance",
            slug="gym-avance",
            subdomain="gym-avance",
        )
        self.caissier = User.objects.create_user(
            username="caissier-avance", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.caissier, gym=self.gym, role="cashier", is_active=True
        )
        self.register = CashRegister.objects.create(
            gym=self.gym,
            opened_by=self.caissier,
            opening_amount=Decimal("0.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Ada",
            last_name="Mbala",
            phone="+243900000001",
        )
        self.today = timezone.localdate()

    def _encaisser(self, start_date=None):
        return record_subscription_payment(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            currency="USD",
            method="cash",
            start_date=start_date,
            created_by=self.caissier,
        )

    def _abonnement(self, debut, fin):
        return MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=debut,
            end_date=fin,
            is_active=True,
        )

    # --- Payer d'avance --------------------------------------------------------

    def test_a_start_date_next_month_is_accepted(self):
        debut = self.today + timedelta(days=30)

        abonnement, _ = self._encaisser(start_date=debut)

        self.assertEqual(abonnement.start_date, debut)
        self.assertEqual(abonnement.end_date, debut + timedelta(days=30))

    def test_a_subscription_starting_later_is_not_active_yet(self):
        # La porte doit rester fermee jusqu'a la date de debut.
        self._encaisser(start_date=self.today + timedelta(days=30))

        self.assertIsNone(self.member.active_subscription)
        self.assertEqual(self.member.computed_status, "expired")

    def test_the_team_sees_that_it_is_paid_and_when_it_starts(self):
        # Sans cette mention, l'accueil relancerait un membre a jour.
        debut = self.today + timedelta(days=30)
        self._encaisser(start_date=debut)

        a_venir = self.member.upcoming_subscription
        self.assertIsNotNone(a_venir)
        self.assertEqual(a_venir.start_date, debut)

    def test_a_date_in_the_past_stays_allowed(self):
        """
        Rattraper un abonnement oublie reste possible.

        La demande portait sur l'ouverture des dates futures ; fermer le passe
        au passage aurait empeche de saisir un abonnement commence la semaine
        derniere et jamais enregistre.
        """
        debut = self.today - timedelta(days=5)

        abonnement, _ = self._encaisser(start_date=debut)

        self.assertEqual(abonnement.start_date, debut)

    def test_a_date_beyond_three_months_is_refused_as_a_typo(self):
        # Une annee mal saisie creerait un abonnement fantome que personne ne
        # remarquerait avant des mois.
        with self.assertRaises(ValidationError) as capture:
            self._encaisser(start_date=self.today + timedelta(days=400))

        self.assertIn("Verifiez l'annee", str(capture.exception))

    # --- Ne pas payer deux fois les memes jours ----------------------------------

    def test_a_date_inside_the_running_subscription_is_refused(self):
        self._abonnement(self.today, self.today + timedelta(days=19))

        with self.assertRaises(ValidationError) as capture:
            self._encaisser(start_date=self.today + timedelta(days=10))

        message = str(capture.exception)
        self.assertIn("court jusqu'au", message)

    def test_the_refusal_names_the_first_free_date(self):
        fin = self.today + timedelta(days=19)
        self._abonnement(self.today, fin)

        with self.assertRaises(ValidationError) as capture:
            self._encaisser(start_date=self.today + timedelta(days=10))

        libre = (fin + timedelta(days=1)).strftime("%d/%m/%Y")
        self.assertIn(libre, str(capture.exception))

    def test_the_refusal_explains_how_to_extend_instead(self):
        self._abonnement(self.today, self.today + timedelta(days=19))

        with self.assertRaises(ValidationError) as capture:
            self._encaisser(start_date=self.today + timedelta(days=10))

        self.assertIn("laissez la date vide", str(capture.exception))

    def test_the_day_after_the_current_one_ends_is_accepted(self):
        fin = self.today + timedelta(days=19)
        self._abonnement(self.today, fin)

        abonnement, _ = self._encaisser(start_date=fin + timedelta(days=1))

        self.assertEqual(abonnement.start_date, fin + timedelta(days=1))

    # --- Le membre ne doit jamais se retrouver a la porte -------------------------

    def test_the_running_subscription_survives_a_future_purchase(self):
        # Le desactiver laisserait le membre dehors jusqu'a la date de debut.
        fin = self.today + timedelta(days=19)
        en_cours = self._abonnement(self.today, fin)

        self._encaisser(start_date=fin + timedelta(days=1))

        en_cours.refresh_from_db()
        self.assertTrue(en_cours.is_active)
        self.assertIsNotNone(self.member.active_subscription)

    def test_the_member_stays_active_today(self):
        fin = self.today + timedelta(days=19)
        self._abonnement(self.today, fin)

        self._encaisser(start_date=fin + timedelta(days=1))

        self.assertEqual(self.member.computed_status, "active")

    # --- Le renouvellement anticipe, inchange --------------------------------------

    def test_paying_without_a_date_extends_the_running_subscription(self):
        fin = self.today + timedelta(days=19)
        self._abonnement(self.today, fin)

        abonnement, _ = self._encaisser()

        # Les 19 jours restants sont reportes : la nouvelle echeance vaut
        # l'ancienne plus la duree de la formule.
        self.assertEqual(abonnement.end_date, fin + timedelta(days=30))

    def test_extending_closes_the_previous_subscription(self):
        fin = self.today + timedelta(days=19)
        en_cours = self._abonnement(self.today, fin)

        self._encaisser()

        en_cours.refresh_from_db()
        self.assertFalse(en_cours.is_active)

    def test_a_member_without_subscription_starts_today(self):
        abonnement, _ = self._encaisser()

        self.assertEqual(abonnement.start_date, self.today)
        self.assertEqual(abonnement.end_date, self.today + timedelta(days=30))


class DisbursementReasonTests(TestCase):
    """
    Le motif d'un decaissement doit se lire dans les listes.

    Il etait saisi au comptoir, stocke, puis affiche pour la maintenance et
    les salaires - mais une depense ordinaire tombait dans le cas par defaut
    et n'affichait que le mot « Decaissement ». L'argent sortait sans qu'on
    sache pourquoi.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Motif", slug="org-motif"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Motif",
            slug="gym-motif", subdomain="gym-motif",
        )
        module, _ = Module.objects.get_or_create(
            code="POS", defaults={"name": "POS"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.caissier = User.objects.create_user(
            username="caissier-motif", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.caissier, gym=self.gym, role="cashier", is_active=True
        )
        self.register = CashRegister.objects.create(
            gym=self.gym,
            opened_by=self.caissier,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.client.force_login(self.caissier)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _decaisser(self, motif="Achat de fournitures"):
        return record_expense(
            gym=self.gym,
            amount=Decimal("5000"),
            currency="CDF",
            method="cash",
            category="expense",
            description=motif,
            created_by=self.caissier,
            source_app="pos",
            source_model="ManualExpense",
        )

    # --- Ce qui doit se lire ---------------------------------------------------

    def test_the_cashier_list_shows_the_reason(self):
        self._decaisser()

        reponse = self.client.get(reverse("pos:cashier_dashboard"))

        self.assertContains(reponse, "Achat de fournitures")

    def test_the_session_detail_shows_the_reason(self):
        # Le detail d'une session est reserve au gerant : la caissiere tient la
        # caisse, elle ne relit pas les sessions passees.
        self._decaisser("Reparation plomberie")
        gerant = User.objects.create_user(
            username="gerant-motif", password="pass12345"
        )
        UserGymRole.objects.create(
            user=gerant, gym=self.gym, role="manager", is_active=True
        )
        self.client.force_login(gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

        reponse = self.client.get(
            reverse("pos:register_detail", args=[self.register.id])
        )

        self.assertContains(reponse, "Reparation plomberie")

    def test_a_disbursement_without_a_reason_still_reads(self):
        # Le motif est facultatif cote formulaire : son absence ne doit pas
        # laisser une ligne muette.
        self._decaisser(motif="")

        reponse = self.client.get(reverse("pos:cashier_dashboard"))

        self.assertContains(reponse, "Décaissement")

    def test_an_incoming_payment_is_untouched(self):
        # La colonne Nature d'une entree ne doit pas se mettre a repeter la
        # description : elle porte deja la formule ou le produit vendu.
        record_payment(
            gym=self.gym,
            register=self.register,
            amount=Decimal("10000"),
            currency="CDF",
            method="cash",
            transaction_type="in",
            category="other",
            description="Ne doit pas apparaitre en nature",
            created_by=self.caissier,
        )

        reponse = self.client.get(reverse("pos:cashier_dashboard"))
        page = reponse.content.decode()

        self.assertEqual(page.count("Ne doit pas apparaitre en nature"), 0)


class ExpenseRegisterTests(TestCase):
    """
    Le registre des decaissements : toutes les sorties au meme endroit.

    Elles etaient dispersees - melees aux encaissements dans la table de la
    caisse, reparties session par session, agregees en totaux dans les
    rapports. Relire les depenses d'un mois demandait de les reperer a l'oeil.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Registre", slug="org-registre"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Registre",
            slug="gym-registre", subdomain="gym-registre",
        )
        self.voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-registre-voisine", subdomain="gym-registre-voisine",
        )
        module, _ = Module.objects.get_or_create(
            code="POS", defaults={"name": "POS"}
        )
        for salle in (self.gym, self.voisine):
            GymModule.objects.get_or_create(
                gym=salle, module=module, defaults={"is_active": True}
            )

        self.gerant = User.objects.create_user(
            username="gerant-registre", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self.register = CashRegister.objects.create(
            gym=self.gym, opened_by=self.gerant,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self._connecter(self.gerant)

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _sortie(self, motif="Achat fournitures", categorie="expense",
                methode="cash", gym=None, montant="5000"):
        return record_expense(
            gym=gym or self.gym,
            amount=Decimal(montant),
            currency="CDF",
            method=methode,
            category=categorie,
            description=motif,
            created_by=self.gerant,
            source_app="pos",
            source_model="ManualExpense",
        )

    def _registre(self, **filtres):
        url = reverse("pos:expense_register")
        if filtres:
            url += "?" + "&".join(f"{k}={v}" for k, v in filtres.items())
        return self.client.get(url)

    # --- Ce que le registre montre ---------------------------------------------

    def test_a_disbursement_appears_with_its_reason(self):
        self._sortie("Reparation plomberie")

        reponse = self._registre()

        self.assertContains(reponse, "Reparation plomberie")

    def test_an_incoming_payment_never_appears(self):
        # C'est un registre des sorties : une recette n'y a rien a faire.
        record_payment(
            gym=self.gym, register=self.register, amount=Decimal("10000"),
            currency="CDF", method="cash", transaction_type="in",
            category="subscription", description="Encaissement abonnement",
            created_by=self.gerant,
        )

        reponse = self._registre()

        self.assertNotContains(reponse, "Encaissement abonnement")

    def test_the_total_sums_the_period(self):
        self._sortie(montant="5000")
        self._sortie(montant="3000")

        reponse = self._registre()

        self.assertEqual(reponse.context["total_count"], 2)
        self.assertEqual(reponse.context["total_cdf"], Decimal("8000.00"))

    def test_the_breakdown_says_where_the_money_went(self):
        self._sortie(categorie="salary", montant="50000")
        self._sortie(categorie="expense", montant="5000")

        lignes = {l["code"]: l["total"] for l in self._registre().context["by_category"]}

        self.assertEqual(lignes["salary"], Decimal("50000.00"))
        self.assertEqual(lignes["expense"], Decimal("5000.00"))

    def test_a_neighbouring_gym_stays_out(self):
        # Une depense ne peut naitre que dans une caisse ouverte : la voisine
        # doit avoir la sienne pour que le cas soit realiste.
        CashRegister.objects.create(
            gym=self.voisine, opened_by=self.gerant,
            opening_amount=Decimal("50000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self._sortie("Depense de la voisine", gym=self.voisine)

        self.assertNotContains(self._registre(), "Depense de la voisine")

    # --- Les filtres ---------------------------------------------------------------

    def test_filtering_by_category(self):
        self._sortie("Salaire du gardien", categorie="salary")
        self._sortie("Achat de savon", categorie="expense")

        reponse = self._registre(category="salary")

        self.assertContains(reponse, "Salaire du gardien")
        self.assertNotContains(reponse, "Achat de savon")

    def test_filtering_by_method(self):
        self._sortie("Paye en especes", methode="cash")
        self._sortie("Paye par virement", methode="bank_transfer")

        reponse = self._registre(method="bank_transfer")

        self.assertContains(reponse, "Paye par virement")
        self.assertNotContains(reponse, "Paye en especes")

    def test_searching_by_reason(self):
        # Le motif est le seul texte libre : c'est par lui qu'on retrouve une
        # depense dont on ne se rappelle que l'objet.
        self._sortie("Reparation du portail")
        self._sortie("Achat de savon")

        reponse = self._registre(search="portail")

        self.assertContains(reponse, "Reparation du portail")
        self.assertNotContains(reponse, "Achat de savon")

    def test_an_old_disbursement_is_outside_the_default_period(self):
        # Le registre s'ouvre sur le mois courant : une depense de l'an dernier
        # ne doit pas s'y inviter.
        ancienne = self._sortie("Depense de l an dernier")
        Payment.objects.filter(pk=ancienne.pk).update(
            created_at=timezone.now() - timedelta(days=400)
        )

        self.assertNotContains(self._registre(), "Depense de l an dernier")

    def test_widening_the_dates_brings_it_back(self):
        ancienne = self._sortie("Depense de l an dernier")
        vieille_date = timezone.now() - timedelta(days=400)
        Payment.objects.filter(pk=ancienne.pk).update(created_at=vieille_date)

        reponse = self._registre(
            date_from=vieille_date.date().isoformat(),
            date_to=timezone.localdate().isoformat(),
        )

        self.assertContains(reponse, "Depense de l an dernier")

    # --- Qui y a droit ---------------------------------------------------------------

    def test_a_cashier_cannot_open_it(self):
        # La caissiere tient la caisse ; relire les depenses du mois releve de
        # la gestion.
        caissiere = User.objects.create_user(
            username="caisse-registre", password="pass12345"
        )
        UserGymRole.objects.create(
            user=caissiere, gym=self.gym, role="cashier", is_active=True
        )
        self._connecter(caissiere)

        self.assertEqual(self._registre().status_code, 403)

    def test_an_owner_can_open_it(self):
        proprietaire = User.objects.create_user(
            username="proprio-registre", password="pass12345"
        )
        UserGymRole.objects.create(
            user=proprietaire, gym=self.gym, role="owner", is_active=True
        )
        self._connecter(proprietaire)

        self.assertEqual(self._registre().status_code, 200)


class ClosedPeriodSaleTests(TestCase):
    """
    Vendre une periode deja terminee.

    L'incident d'origine : une date de debut anterieure, une periode close le
    jour meme de la vente. Le membre paie et n'a aucun acces, et rien ne l'a
    signale.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Periode", slug="org-periode"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Periode",
            slug="gym-periode", subdomain="gym-periode",
        )
        self.caissiere = User.objects.create_user(
            username="caisse-periode", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.caissiere, gym=self.gym, role="cashier", is_active=True
        )
        CashRegister.objects.create(
            gym=self.gym, opened_by=self.caissiere,
            opening_amount=Decimal("100000.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        self.member = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243870005555",
        )

    def _vendre(self, debut, confirme=False):
        return record_subscription_payment(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            currency="USD",
            method="cash",
            start_date=debut,
            confirm_closed_period=confirme,
            created_by=self.caissiere,
        )

    def test_a_closed_period_is_refused_without_confirmation(self):
        with self.assertRaises(ValidationError) as capture:
            self._vendre(timezone.localdate() - timedelta(days=60))

        self.assertIn("aucun acces", str(capture.exception))

    def test_the_refusal_says_when_the_period_ended(self):
        debut = timezone.localdate() - timedelta(days=60)

        with self.assertRaises(ValidationError) as capture:
            self._vendre(debut)

        fin = debut + timedelta(days=30)
        self.assertIn(fin.strftime("%d/%m/%Y"), str(capture.exception))

    def test_nothing_is_recorded_when_refused(self):
        # Le refus doit etre total : ni abonnement fantome, ni recette.
        with self.assertRaises(ValidationError):
            self._vendre(timezone.localdate() - timedelta(days=60))

        self.assertEqual(MemberSubscription.objects.filter(gym=self.gym).count(), 0)
        self.assertEqual(Payment.objects.filter(gym=self.gym).count(), 0)

    def test_confirming_lets_the_regularisation_through(self):
        # Regulariser une vente ancienne reste legitime : on fait assumer, on
        # n'interdit pas.
        abonnement, _ = self._vendre(
            timezone.localdate() - timedelta(days=60), confirme=True
        )

        self.assertIsNotNone(abonnement.pk)

    def test_a_recent_past_date_passes_without_a_word(self):
        # Interdire toutes les dates passees a deja casse le renouvellement
        # anticipe dans ce projet : seule la periode close doit alerter.
        abonnement, _ = self._vendre(timezone.localdate() - timedelta(days=5))

        self.assertIsNotNone(abonnement.pk)

    def test_today_passes_without_a_word(self):
        abonnement, _ = self._vendre(timezone.localdate())

        self.assertIsNotNone(abonnement.pk)

    def test_a_future_date_passes_without_a_word(self):
        abonnement, _ = self._vendre(timezone.localdate() + timedelta(days=10))

        self.assertIsNotNone(abonnement.pk)

    def test_the_cashier_screen_refuses_it_too(self):
        self.client.force_login(self.caissiere)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()
        module, _ = Module.objects.get_or_create(code="POS", defaults={"name": "POS"})
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )

        self.client.post(
            reverse("pos:cashier_dashboard"),
            {
                "action": "record_payment",
                "sale_type": "subscription",
                "member": self.member.id,
                "plan": self.plan.id,
                "currency": "USD",
                "method": "cash",
                "start_date": (
                    timezone.localdate() - timedelta(days=60)
                ).isoformat(),
            },
            follow=True,
        )

        self.assertEqual(MemberSubscription.objects.filter(gym=self.gym).count(), 0)

    def test_the_cashier_screen_accepts_a_confirmed_regularisation(self):
        self.client.force_login(self.caissiere)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()
        module, _ = Module.objects.get_or_create(code="POS", defaults={"name": "POS"})
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )

        self.client.post(
            reverse("pos:cashier_dashboard"),
            {
                "action": "record_payment",
                "sale_type": "subscription",
                "member": self.member.id,
                "plan": self.plan.id,
                "currency": "USD",
                "method": "cash",
                "start_date": (
                    timezone.localdate() - timedelta(days=60)
                ).isoformat(),
                "confirm_closed_period": "on",
            },
            follow=True,
        )

        self.assertEqual(MemberSubscription.objects.filter(gym=self.gym).count(), 1)

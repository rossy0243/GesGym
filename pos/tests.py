from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
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

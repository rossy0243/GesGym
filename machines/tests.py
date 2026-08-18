from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from compte.models import User, UserGymRole
from organizations.models import Gym, GymModule, Module, Organization
from pos.models import CashRegister, Payment

from .alerts import maintenance_alert_summary
from .models import Machine, MaintenanceLog


class MachinesTenantTests(TestCase):
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
        module, _ = Module.objects.get_or_create(
            code="MACHINES",
            defaults={"name": "Machines"},
        )
        GymModule.objects.create(gym=self.gym_a, module=module, is_active=True)
        GymModule.objects.create(gym=self.gym_b, module=module, is_active=True)

        self.user = User.objects.create_user(username="manager-a", password="test-pass")
        UserGymRole.objects.create(user=self.user, gym=self.gym_a, role="manager")
        self.register_a = CashRegister.objects.create(
            gym=self.gym_a,
            # La caisse doit appartenir a l'utilisateur qui enregistre le
            # mouvement : get_open_register filtre sur opened_by.
            opened_by=self.user,
            opening_amount=Decimal("0.00"),
            exchange_rate=Decimal("2800.00"),
        )

        self.machine_a = Machine.objects.create(gym=self.gym_a, name="Tapis A", status="ok")
        self.machine_b = Machine.objects.create(gym=self.gym_b, name="Tapis B", status="broken")
        MaintenanceLog.objects.create(
            machine=self.machine_a,
            description="Courroie remplacee",
            cost=75,
        )
        MaintenanceLog.objects.create(
            machine=self.machine_b,
            description="Intervention autre salle",
            cost=999,
        )
        self.client.login(username="manager-a", password="test-pass")

    def test_machine_list_is_scoped_to_current_gym(self):
        response = self.client.get(reverse("machines:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tapis A")
        self.assertNotContains(response, "Tapis B")
        self.assertContains(response, "Total machines")

    def test_other_gym_machine_detail_is_not_accessible(self):
        response = self.client.get(reverse("machines:detail", args=[self.machine_b.id]))

        self.assertEqual(response.status_code, 404)

    def test_other_gym_machine_update_is_not_accessible(self):
        response = self.client.post(
            reverse("machines:update", args=[self.machine_b.id]),
            {"name": "Leak", "status": "ok", "purchase_date": ""},
        )

        self.assertEqual(response.status_code, 404)
        self.machine_b.refresh_from_db()
        self.assertEqual(self.machine_b.name, "Tapis B")
        self.assertEqual(self.machine_b.status, "broken")

    def test_maintenance_history_is_scoped_to_current_gym(self):
        response = self.client.get(reverse("machines:maintenance_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Courroie remplacee")
        self.assertNotContains(response, "Intervention autre salle")
        self.assertContains(response, "75")

    def test_dashboard_kpis_are_scoped_to_current_gym(self):
        response = self.client.get(reverse("machines:maintenance_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard machines")
        self.assertContains(response, "Tapis A")
        self.assertNotContains(response, "Tapis B")
        self.assertContains(response, "75 CDF")
        self.assertNotContains(response, "999 CDF")

    def test_general_dashboard_includes_scoped_machine_kpis(self):
        response = self.client.get(reverse("core:gym_dashboard", args=[self.gym_a.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "KPI machines")
        self.assertContains(response, "Disponibilite du parc")
        self.assertContains(response, "1 / 1")
        self.assertContains(response, "75 CDF")
        self.assertNotContains(response, "999 CDF")

    def test_create_maintenance_uses_current_gym_machine(self):
        response = self.client.post(
            reverse("machines:add_maintenance", args=[self.machine_a.id]),
            {
                "description": "Graissage complet",
                "cost": "25.00",
                "change_status": "on",
                "status": "maintenance",
            },
        )

        self.assertRedirects(response, reverse("machines:detail", args=[self.machine_a.id]))
        self.machine_a.refresh_from_db()
        self.assertEqual(self.machine_a.status, "maintenance")
        self.assertTrue(
            MaintenanceLog.objects.filter(
                machine=self.machine_a,
                description="Graissage complet",
                cost="25.00",
                pos_payment__isnull=False,
            ).exists()
        )
        self.assertTrue(
            Payment.objects.filter(
                gym=self.gym_a,
                cash_register=self.register_a,
                type="out",
                category="maintenance",
                amount_cdf=Decimal("25.00"),
            ).exists()
        )

    def test_cannot_delete_maintenance_linked_to_pos_payment(self):
        response = self.client.post(
            reverse("machines:add_maintenance", args=[self.machine_a.id]),
            {
                "description": "Remplacement moteur",
                "cost": "55.00",
            },
            follow=True,
        )

        log = MaintenanceLog.objects.get(
            machine=self.machine_a,
            description="Remplacement moteur",
        )

        delete_response = self.client.post(
            reverse("machines:maintenance_delete", args=[log.id]),
            follow=True,
        )

        self.assertEqual(delete_response.status_code, 200)
        self.assertContains(
            delete_response,
            "Impossible de supprimer cette maintenance car elle est deja liee a un paiement POS.",
        )
        self.assertTrue(MaintenanceLog.objects.filter(id=log.id).exists())
        self.assertTrue(Payment.objects.filter(id=log.pos_payment_id).exists())

    def test_cannot_delete_machine_when_paid_maintenance_exists(self):
        self.client.post(
            reverse("machines:add_maintenance", args=[self.machine_a.id]),
            {
                "description": "Graissage securise",
                "cost": "30.00",
            },
            follow=True,
        )

        response = self.client.post(
            reverse("machines:delete", args=[self.machine_a.id]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Impossible de supprimer cette machine car certaines maintenances sont deja liees a des paiements POS.",
        )
        self.assertTrue(Machine.objects.filter(id=self.machine_a.id).exists())

    def test_can_delete_maintenance_without_pos_payment(self):
        log = MaintenanceLog.objects.create(
            machine=self.machine_a,
            description="Controle visuel",
            cost=None,
        )

        response = self.client.post(
            reverse("machines:maintenance_delete", args=[log.id]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(MaintenanceLog.objects.filter(id=log.id).exists())


class MaintenanceAlertTests(TestCase):
    """Une maintenance periodique doit se signaler avant la panne."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Entretien", slug="org-entretien"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Entretien",
            slug="gym-entretien",
            subdomain="gym-entretien",
        )
        module, _ = Module.objects.get_or_create(code="MACHINES", defaults={"name": "Machines"})
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.manager = User.objects.create_user(username="gerant-entretien", password="pass12345")
        UserGymRole.objects.create(
            user=self.manager, gym=self.gym, role="manager", is_active=True
        )
        self.aujourdhui = timezone.localdate()

    def _machine(self, nom, intervalle, achat_il_y_a):
        return Machine.objects.create(
            gym=self.gym,
            name=nom,
            purchase_date=self.aujourdhui - timedelta(days=achat_il_y_a),
            maintenance_interval_days=intervalle,
        )

    # --- Calcul de l'echeance ------------------------------------------------

    def test_a_machine_without_interval_has_no_deadline(self):
        machine = Machine.objects.create(
            gym=self.gym, name="Banc libre", purchase_date=self.aujourdhui
        )

        self.assertIsNone(machine.next_maintenance_on())
        self.assertIsNone(machine.days_until_maintenance())

    def test_the_deadline_starts_from_the_purchase_date(self):
        machine = self._machine("Tapis", intervalle=90, achat_il_y_a=80)

        self.assertEqual(machine.days_until_maintenance(), 10)

    def test_the_last_maintenance_resets_the_cycle(self):
        machine = self._machine("Velo", intervalle=90, achat_il_y_a=200)
        MaintenanceLog.objects.create(machine=machine, description="Revision complete")

        self.assertEqual(machine.days_until_maintenance(), 90)

    def test_an_interval_below_one_day_is_refused(self):
        machine = Machine(
            gym=self.gym, name="Rameur", maintenance_interval_days=0
        )

        with self.assertRaises(ValidationError):
            machine.full_clean()

    # --- Ce que voit le gerant -----------------------------------------------

    def test_a_deadline_two_weeks_away_is_announced(self):
        self._machine("Tapis", intervalle=90, achat_il_y_a=80)

        resume = maintenance_alert_summary(self.gym)

        self.assertEqual(resume["total"], 1)
        self.assertEqual(resume["overdue_count"], 0)
        self.assertEqual(resume["lead_days"], 14)
        self.assertEqual(resume["most_urgent"]["days_left"], 10)

    def test_a_deadline_beyond_the_lead_time_stays_quiet(self):
        self._machine("Tapis", intervalle=90, achat_il_y_a=60)

        self.assertIsNone(maintenance_alert_summary(self.gym))

    def test_a_passed_deadline_is_reported_as_overdue(self):
        self._machine("Velo", intervalle=30, achat_il_y_a=45)

        resume = maintenance_alert_summary(self.gym)

        self.assertEqual(resume["overdue_count"], 1)
        self.assertTrue(resume["most_urgent"]["is_overdue"])
        self.assertEqual(resume["most_urgent"]["days_left"], -15)

    def test_the_most_urgent_machine_comes_first(self):
        self._machine("Tapis", intervalle=90, achat_il_y_a=80)
        self._machine("Velo", intervalle=30, achat_il_y_a=45)

        resume = maintenance_alert_summary(self.gym)

        self.assertEqual(resume["total"], 2)
        self.assertEqual(resume["most_urgent"]["machine"].name, "Velo")

    def test_another_gym_machines_are_never_counted(self):
        autre = Gym.objects.create(
            organization=self.organization,
            name="Gym Voisin Entretien",
            slug="gym-voisin-entretien",
            subdomain="gym-voisin-entretien",
        )
        Machine.objects.create(
            gym=autre,
            name="Tapis voisin",
            purchase_date=self.aujourdhui - timedelta(days=80),
            maintenance_interval_days=90,
        )

        self.assertIsNone(maintenance_alert_summary(self.gym))

    # --- Delai parametrable ---------------------------------------------------

    def test_the_lead_time_is_configurable_per_gym(self):
        self._machine("Tapis", intervalle=90, achat_il_y_a=60)

        self.gym.maintenance_alert_lead_days = 45
        self.gym.save()

        resume = maintenance_alert_summary(self.gym)
        self.assertEqual(resume["total"], 1)
        self.assertEqual(resume["lead_days"], 45)

    def test_the_settings_page_saves_the_new_lead_time(self):
        client = Client()
        client.force_login(self.manager)
        session = client.session
        session["current_gym_id"] = self.gym.id
        session.save()

        response = client.post(
            reverse("core:settings"),
            {"action": "maintenance", "maintenance_alert_lead_days": "30"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.gym.refresh_from_db()
        self.assertEqual(self.gym.maintenance_alert_lead_days, 30)

    def test_an_absurd_lead_time_is_refused(self):
        client = Client()
        client.force_login(self.manager)
        session = client.session
        session["current_gym_id"] = self.gym.id
        session.save()

        client.post(
            reverse("core:settings"),
            {"action": "maintenance", "maintenance_alert_lead_days": "0"},
            follow=True,
        )

        self.gym.refresh_from_db()
        self.assertEqual(self.gym.maintenance_alert_lead_days, 14)

    # --- Le bandeau suit le gerant --------------------------------------------

    def test_the_banner_follows_the_manager_on_every_page(self):
        self._machine("Tapis", intervalle=90, achat_il_y_a=85)
        client = Client()
        client.force_login(self.manager)
        session = client.session
        session["current_gym_id"] = self.gym.id
        session.save()

        response = client.get(reverse("machines:list"))

        self.assertContains(response, "maintenance(s) dans les 14 prochains jours")
        self.assertContains(response, "Tapis")

    def test_a_cashier_never_sees_the_maintenance_banner(self):
        self._machine("Tapis", intervalle=90, achat_il_y_a=85)
        caissier = User.objects.create_user(username="caissier-entretien", password="pass12345")
        UserGymRole.objects.create(
            user=caissier, gym=self.gym, role="cashier", is_active=True
        )
        pos, _ = Module.objects.get_or_create(code="POS", defaults={"name": "POS"})
        GymModule.objects.get_or_create(
            gym=self.gym, module=pos, defaults={"is_active": True}
        )
        client = Client()
        client.force_login(caissier)
        session = client.session
        session["current_gym_id"] = self.gym.id
        session.save()

        response = client.get(reverse("pos:cashier_dashboard"))

        self.assertNotContains(response, "prochains jours")

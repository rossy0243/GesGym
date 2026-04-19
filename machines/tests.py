from django.test import TestCase
from django.urls import reverse
from decimal import Decimal

from compte.models import User, UserGymRole
from organizations.models import Gym, GymModule, Module, Organization
from pos.models import CashRegister, Payment

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

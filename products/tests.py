from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from compte.models import User, UserGymRole
from organizations.models import Gym, GymModule, Module, Organization

from .models import Product, StockMovement


class ProductsTenantTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Org A", slug="products-org-a")
        self.org_b = Organization.objects.create(name="Org B", slug="products-org-b")
        self.gym_a = Gym.objects.create(
            organization=self.org_a,
            name="Gym A",
            slug="products-gym-a",
            subdomain="products-gym-a",
        )
        self.gym_b = Gym.objects.create(
            organization=self.org_b,
            name="Gym B",
            slug="products-gym-b",
            subdomain="products-gym-b",
        )
        module, _ = Module.objects.get_or_create(code="PRODUCTS", defaults={"name": "Products"})
        GymModule.objects.create(gym=self.gym_a, module=module, is_active=True)
        GymModule.objects.create(gym=self.gym_b, module=module, is_active=True)

        self.user = User.objects.create_user(username="product-manager", password="test-pass")
        UserGymRole.objects.create(user=self.user, gym=self.gym_a, role="manager")

        self.product_a = Product.objects.create(
            gym=self.gym_a,
            name="Water A",
            price=100,
            quantity=10,
        )
        self.product_b = Product.objects.create(
            gym=self.gym_b,
            name="Water B",
            price=999,
            quantity=7,
        )
        StockMovement.objects.create(
            gym=self.gym_a,
            product=self.product_a,
            quantity=10,
            movement_type="in",
            reason="Initial A",
        )
        StockMovement.objects.create(
            gym=self.gym_b,
            product=self.product_b,
            quantity=7,
            movement_type="in",
            reason="Initial B",
        )
        self.client.login(username="product-manager", password="test-pass")

    def test_product_list_is_scoped_to_current_gym(self):
        response = self.client.get(reverse("products:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Water A")
        self.assertNotContains(response, "Water B")
        self.assertContains(response, "Valeur du stock")

    def test_other_gym_product_detail_is_not_accessible(self):
        response = self.client.get(reverse("products:detail", args=[self.product_b.id]))

        self.assertEqual(response.status_code, 404)

    def test_stock_movement_list_is_scoped_to_current_gym(self):
        response = self.client.get(reverse("products:movement_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Initial A")
        self.assertNotContains(response, "Initial B")

    def test_stock_dashboard_kpis_are_scoped_to_current_gym(self):
        response = self.client.get(reverse("products:stock_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Water A")
        self.assertNotContains(response, "Water B")
        self.assertContains(response, "1000,00 USD")
        self.assertNotContains(response, "6993,00 USD")

    def test_general_dashboard_includes_scoped_product_kpis(self):
        response = self.client.get(reverse("core:gym_dashboard", args=[self.gym_a.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "KPI produits")
        self.assertContains(response, "Graphique du stock")
        self.assertContains(response, "Valeur du stock")
        self.assertContains(response, "1000 USD")
        self.assertContains(response, "stockValueChart")

    def test_movement_cannot_target_other_gym_product(self):
        response = self.client.get(reverse("products:add_movement", args=[self.product_b.id]))

        self.assertEqual(response.status_code, 404)

    def test_stock_movement_rejects_cross_gym_product(self):
        with self.assertRaises(ValidationError):
            StockMovement.objects.create(
                gym=self.gym_a,
                product=self.product_b,
                quantity=1,
                movement_type="in",
            )

    def test_stock_out_updates_quantity_and_creates_scoped_movement(self):
        response = self.client.post(
            reverse("products:add_movement", args=[self.product_a.id]),
            {"quantity": 3, "movement_type": "out", "reason": "Sale"},
        )

        self.assertRedirects(response, reverse("products:detail", args=[self.product_a.id]))
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.quantity, 7)
        self.assertTrue(
            StockMovement.objects.filter(
                gym=self.gym_a,
                product=self.product_a,
                quantity=3,
                movement_type="out",
                reason="Sale",
            ).exists()
        )

    def test_form_pages_render_without_gym_id_urls(self):
        urls = [
            reverse("products:create"),
            reverse("products:update", args=[self.product_a.id]),
            reverse("products:add_movement", args=[self.product_a.id]),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from compte.models import User, UserGymRole
from organizations.models import (
    Gym,
    GymModule,
    Module,
    Organization,
    SensitiveActivityLog,
)
from pos.models import CashRegister
from pos.services import record_product_sale

from .kpis import build_product_kpis, stock_value
from .models import Product, StockMovement
from .pricing import gym_exchange_rate


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
        response = self.client.get(
            reverse("core:gym_dashboard", args=[self.gym_a.id]),
            {"view": "analytics"},
        )

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

    def test_manual_movement_is_always_an_entry(self):
        # La sortie manuelle a ete retiree du formulaire : elle permettait de
        # sortir deux fois le meme produit, une fois a la vente en caisse et
        # une fois a la main. Une sortie envoyee de force reste sans effet.
        avant = self.product_a.quantity

        response = self.client.post(
            reverse("products:add_movement", args=[self.product_a.id]),
            {"quantity": 3, "movement_type": "out", "reason": "Livraison"},
        )

        self.assertRedirects(response, reverse("products:detail", args=[self.product_a.id]))
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.quantity, avant + 3)
        self.assertTrue(
            StockMovement.objects.filter(
                gym=self.gym_a,
                product=self.product_a,
                quantity=3,
                movement_type="in",
                reason="Livraison",
            ).exists()
        )
        self.assertFalse(
            StockMovement.objects.filter(
                product=self.product_a, movement_type="out"
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


class ProductCurrencyTests(TestCase):
    """Un produit peut etre price en francs ou en dollars."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Devise Produit", slug="org-devise-produit"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Devise Produit",
            slug="gym-devise-produit",
            subdomain="gym-devise-produit",
        )
        self.user = User.objects.create_user(username="caissier-produit", password="test-pass")
        UserGymRole.objects.create(user=self.user, gym=self.gym, role="cashier", is_active=True)
        self.register = CashRegister.objects.create(
            gym=self.gym,
            opened_by=self.user,
            opening_amount=Decimal("0.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.eau_cdf = Product.objects.create(
            gym=self.gym,
            name="Eau 50cl",
            price=Decimal("2000.00"),
            currency=Product.CURRENCY_CDF,
            quantity=20,
        )
        self.proteine_usd = Product.objects.create(
            gym=self.gym,
            name="Proteine",
            price=Decimal("30.00"),
            currency=Product.CURRENCY_USD,
            quantity=5,
        )

    # --- Conversion du prix -------------------------------------------------

    def test_a_product_keeps_its_own_price_in_its_own_currency(self):
        self.assertEqual(
            self.eau_cdf.price_in("CDF", Decimal("2800.00")), Decimal("2000.00")
        )
        self.assertEqual(
            self.proteine_usd.price_in("USD", Decimal("2800.00")), Decimal("30.00")
        )

    def test_a_cdf_product_is_converted_to_usd_at_the_session_rate(self):
        self.assertEqual(
            self.eau_cdf.price_in("USD", Decimal("2800.00")), Decimal("0.71")
        )

    def test_a_usd_product_is_converted_to_cdf_at_the_session_rate(self):
        self.assertEqual(
            self.proteine_usd.price_in("CDF", Decimal("2800.00")), Decimal("84000.00")
        )

    def test_converting_without_a_rate_is_refused(self):
        with self.assertRaises(ValueError):
            self.eau_cdf.price_in("USD", None)

    # --- Vente en caisse ----------------------------------------------------

    def test_selling_a_cdf_product_in_cdf_charges_the_shelf_price(self):
        paiement = record_product_sale(
            gym=self.gym,
            product=self.eau_cdf,
            quantity=3,
            currency="CDF",
            method="cash",
            created_by=self.user,
        )

        self.assertEqual(paiement.amount, Decimal("6000.00"))
        self.assertEqual(paiement.amount_cdf, Decimal("6000.00"))

    def test_selling_a_cdf_product_in_usd_converts_at_the_session_rate(self):
        paiement = record_product_sale(
            gym=self.gym,
            product=self.eau_cdf,
            quantity=1,
            currency="USD",
            method="cash",
            created_by=self.user,
        )

        self.assertEqual(paiement.amount, Decimal("0.71"))
        self.assertEqual(paiement.currency, "USD")

    def test_selling_a_usd_product_is_unchanged(self):
        paiement = record_product_sale(
            gym=self.gym,
            product=self.proteine_usd,
            quantity=2,
            currency="USD",
            method="cash",
            created_by=self.user,
        )

        self.assertEqual(paiement.amount, Decimal("60.00"))
        self.assertEqual(paiement.amount_cdf, Decimal("168000.00"))

    # --- Valeur du stock ----------------------------------------------------

    def test_stock_value_converts_cdf_products_to_usd(self):
        # 20 x 2000 CDF = 40 000 CDF, soit 0,71 USD l'unite au taux de 2800.
        self.assertEqual(
            stock_value(self.eau_cdf, Decimal("2800.00")), Decimal("14.20")
        )

    def test_stock_value_ignores_cdf_products_when_no_rate_is_known(self):
        self.assertEqual(stock_value(self.eau_cdf, None), Decimal("0"))
        self.assertEqual(stock_value(self.proteine_usd, None), Decimal("150.00"))

    def test_the_open_register_rate_is_used_for_stock_indicators(self):
        self.assertEqual(gym_exchange_rate(self.gym), Decimal("2800.00"))

    def test_products_without_rate_are_counted_rather_than_hidden(self):
        self.register.is_closed = True
        self.register.save()

        kpis = build_product_kpis(self.gym)

        self.assertIsNone(kpis["stock_exchange_rate"])
        self.assertEqual(kpis["products_without_rate"], 1)
        self.assertEqual(kpis["stock_value_total"], Decimal("150.00"))


class ProductAuditTests(TestCase):
    """
    Le catalogue doit se relire.

    Modifier et supprimer un produit laissaient une trace, pas le creer. Un
    catalogue qui s'enrichit sans qu'on sache par qui est aussi difficile a
    relire qu'un catalogue qui se vide - et l'interim ouvrira ce geste a
    d'autres que le gerant.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Audit", slug="products-org-audit"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Audit",
            slug="products-gym-audit", subdomain="products-gym-audit",
        )
        module, _ = Module.objects.get_or_create(
            code="PRODUCTS", defaults={"name": "Products"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.gerant = User.objects.create_user(
            username="gerant-audit", password="test-pass"
        )
        UserGymRole.objects.create(user=self.gerant, gym=self.gym, role="manager")

        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _creer(self, nom="Eau minerale", quantite=12):
        return self.client.post(
            reverse("products:create"),
            {"name": nom, "price": "1.50", "quantity": quantite, "currency": "USD"},
        )

    def test_creating_a_product_leaves_a_trace(self):
        self._creer()

        self.assertTrue(
            SensitiveActivityLog.objects.filter(
                organization=self.organization, action="products.product_created"
            ).exists()
        )

    def test_the_trace_names_who_did_it(self):
        self._creer()

        trace = SensitiveActivityLog.objects.get(action="products.product_created")
        self.assertEqual(trace.actor, self.gerant)
        self.assertEqual(trace.target_label, "Eau minerale")

    def test_the_trace_keeps_the_initial_stock(self):
        # Sans lui, un stock initial genereux serait indistinguable d'une
        # correction ulterieure.
        self._creer(quantite=40)

        trace = SensitiveActivityLog.objects.get(action="products.product_created")
        self.assertEqual(trace.metadata["stock_initial"], 40)

    def test_a_refused_creation_leaves_no_trace(self):
        self.client.post(reverse("products:create"), {"name": "", "price": "1.50"})

        self.assertFalse(
            SensitiveActivityLog.objects.filter(
                action="products.product_created"
            ).exists()
        )



class ListesDuStockTests(TestCase):
    """
    Le tableau de bord du stock montre un apercu, pas tout le catalogue.

    Une salle qui vend deroulait des centaines de lignes sur une page faite
    pour se lire d'un coup d'oeil, et la liste complete n'etait pas paginee.
    """

    def setUp(self):
        self.organisation = Organization.objects.create(name="Org Stock", slug="org-stock")
        self.gym = Gym.objects.create(
            organization=self.organisation, name="Gym Stock",
            slug="gym-stock", subdomain="gym-stock",
        )
        module, _ = Module.objects.get_or_create(code="PRODUCTS", defaults={"name": "Products"})
        GymModule.objects.get_or_create(gym=self.gym, module=module, defaults={"is_active": True})

        self.gerant = User.objects.create_user(username="gerant-stock", password="pass12345")
        UserGymRole.objects.create(user=self.gerant, gym=self.gym, role="manager", is_active=True)
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _produits(self, combien, quantite, prefixe):
        for numero in range(combien):
            Product.objects.create(
                gym=self.gym, name=f"{prefixe} {numero:03d}",
                price=Decimal("1000.00"), currency="CDF", quantity=quantite,
            )

    # --- Le tableau de bord ---------------------------------------------------------------

    def test_the_dashboard_shows_only_a_preview(self):
        self._produits(20, 2, "Bas")

        reponse = self.client.get(reverse("products:stock_dashboard"))

        self.assertEqual(len(reponse.context["low_stock_apercu"]), 8)
        self.assertEqual(reponse.context["low_stock_count"], 20)

    def test_the_dashboard_leads_to_the_whole_list(self):
        self._produits(20, 2, "Bas")
        self._produits(12, 0, "Rupture")

        reponse = self.client.get(reverse("products:stock_dashboard"))

        self.assertContains(reponse, "Voir les 20 produits en stock bas")
        self.assertContains(reponse, "Voir les 12 produits en rupture")
        self.assertContains(reponse, "?low_stock=1")
        self.assertContains(reponse, "?out_of_stock=1")

    def test_a_short_list_needs_no_link(self):
        self._produits(3, 2, "Bas")

        reponse = self.client.get(reverse("products:stock_dashboard"))

        self.assertEqual(len(reponse.context["low_stock_apercu"]), 3)
        self.assertNotContains(reponse, "Voir les 3 produits en stock bas")

    def test_the_counters_still_count_everything(self):
        self._produits(20, 2, "Bas")
        self._produits(12, 0, "Rupture")

        reponse = self.client.get(reverse("products:stock_dashboard"))

        self.assertEqual(reponse.context["low_stock_count"], 20)
        self.assertEqual(reponse.context["out_of_stock_count"], 12)

    # --- La liste des produits ---------------------------------------------------------------

    def test_the_product_list_is_cut_into_pages(self):
        self._produits(55, 10, "Article")

        reponse = self.client.get(reverse("products:list"))

        self.assertEqual(len(reponse.context["products"]), 50)
        self.assertEqual(reponse.context["produits_trouves"], 55)
        self.assertContains(reponse, "Suivante")

    def test_the_next_page_shows_the_rest(self):
        self._produits(55, 10, "Article")

        reponse = self.client.get(reverse("products:list"), {"page": "2"})

        self.assertEqual(len(reponse.context["products"]), 5)

    def test_turning_the_page_keeps_the_filter(self):
        self._produits(55, 2, "Bas")
        self._produits(5, 10, "Plein")

        reponse = self.client.get(reverse("products:list"), {"low_stock": "1"})

        self.assertEqual(reponse.context["produits_trouves"], 55)
        self.assertIn("low_stock=1", reponse.context["filtres_conserves"])
        self.assertNotIn("page=", reponse.context["filtres_conserves"])
        self.assertContains(reponse, "?low_stock=1&page=2")

    def test_a_short_catalogue_shows_no_pagination(self):
        self._produits(4, 10, "Article")

        reponse = self.client.get(reverse("products:list"))

        self.assertNotContains(reponse, "Suivante")

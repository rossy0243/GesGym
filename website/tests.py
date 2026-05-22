from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from compte.models import User


class PublicRouteTests(TestCase):
    def test_root_route_displays_landing_page(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SmartClub")
        self.assertContains(response, "Espace membre PWA")
        self.assertContains(response, "Messages membres")
        self.assertContains(response, reverse("compte:login"))
        self.assertNotContains(response, "{% url 'compte:login' %}")

    def test_short_login_route_redirects_to_login_page(self):
        response = self.client.get("/login/")

        self.assertRedirects(
            response,
            reverse("compte:login"),
            fetch_redirect_response=False,
        )

    def test_landing_script_uses_rendered_button_href_for_login(self):
        script = (settings.BASE_DIR / "static" / "js" / "script_accueil.js").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("{% url 'compte:login' %}", script)
        self.assertNotIn("loginBtn.addEventListener", script)
        self.assertNotIn("mobileLoginBtn.addEventListener", script)

    def test_landing_uses_versioned_script_to_avoid_stale_browser_cache(self):
        response = self.client.get("/")

        self.assertContains(response, "script_accueil.js?v=landing-v1-member-messaging")

    def test_health_route_returns_plain_ok(self):
        response = self.client.get("/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertEqual(response.content.decode("utf-8"), "ok")

    def test_root_route_uses_public_landing_template(self):
        response = self.client.get("/")

        self.assertTemplateUsed(response, "compte/accueil.html")

    def test_health_details_route_requires_staff_authentication(self):
        response = self.client.get("/health/details/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_health_details_route_returns_minimal_json_for_staff(self):
        staff_user = User.objects.create_superuser(
            username="health-admin",
            email="health-admin@example.com",
            password="HealthAdmin123!",
        )
        self.client.force_login(staff_user)
        response = self.client.get("/health/details/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertIn("database", payload)
        self.assertNotIn("tenancy", payload)
        self.assertNotIn("debug", payload)

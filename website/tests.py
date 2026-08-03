from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from compte.models import User


class PublicRouteTests(TestCase):
    def test_root_route_displays_landing_page(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Royal Gym")
        self.assertContains(response, "Musculation")
        self.assertContains(response, "Envoyer mon message")
        self.assertContains(response, reverse("compte:login"))
        self.assertNotContains(response, "fa-facebook")
        self.assertNotContains(response, "fa-instagram")
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

        self.assertContains(response, "script_accueil.js?v=landing-v8-royal-gym")

    def test_landing_mobile_header_uses_direct_login_link(self):
        response = self.client.get("/")

        self.assertContains(response, 'id="mobile-login-link"')
        self.assertContains(response, reverse("compte:login"))
        self.assertNotContains(response, 'id="menu-btn"')
        self.assertNotContains(response, 'id="mobile-menu"')

    def test_contact_request_sends_email_to_contact_address(self):
        response = self.client.post(
            "/",
            {
                "full_name": "Rosette Mukendi",
                "email": "rosette@example.com",
                "phone": "+243821000000",
                "message": "Je souhaite connaître vos tarifs et horaires.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.to, ["contact@royalgym.example"])
        self.assertEqual(sent_email.reply_to, ["rosette@example.com"])
        self.assertIn("Rosette Mukendi", sent_email.subject)
        self.assertIn("Rosette Mukendi", sent_email.body)
        self.assertIn("tarifs et horaires", sent_email.body)

    def test_contact_request_can_be_signaled_on_whatsapp_after_email(self):
        response = self.client.post(
            "/",
            {
                "full_name": "Mila Kanku",
                "email": "mila@example.com",
                "phone": "+243979000000",
                "message": "Je veux visiter la salle.",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Contacter aussi sur WhatsApp")
        self.assertContains(response, "https://wa.me/243000000000?text=")
        self.assertContains(response, "Mila%20Kanku")

    def test_contact_request_invalid_submission_shows_errors(self):
        response = self.client.post(
            "/",
            {
                "full_name": "",
                "email": "email-invalide",
                "phone": "",
                "message": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce champ est obligatoire.")
        self.assertContains(response, "Saisissez une adresse de courriel valide.")
        self.assertEqual(len(mail.outbox), 0)

    def test_health_route_returns_plain_ok(self):
        response = self.client.get("/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertEqual(response.content.decode("utf-8"), "ok")

    @override_settings(
        ALLOWED_HOSTS=["smartclubpro.org", "www.smartclubpro.org", ".onrender.com"],
        CANONICAL_HOST="smartclubpro.org",
        CANONICAL_HOST_EXEMPT_PATHS=(),
        SECURE_SSL_REDIRECT=True,
    )
    def test_onrender_host_redirects_to_smartclubpro(self):
        response = self.client.get(
            "/compte/login/?next=/admin/",
            HTTP_HOST="gesgym-web.onrender.com",
        )

        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response["Location"],
            "https://smartclubpro.org/compte/login/?next=/admin/",
        )

    @override_settings(
        ALLOWED_HOSTS=["smartclubpro.org", "www.smartclubpro.org", ".onrender.com"],
        CANONICAL_HOST="smartclubpro.org",
        CANONICAL_HOST_EXEMPT_PATHS=(),
        SECURE_SSL_REDIRECT=False,
    )
    def test_www_host_redirects_to_root_smartclubpro_domain(self):
        response = self.client.get("/?pack=club", HTTP_HOST="www.smartclubpro.org")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://smartclubpro.org/?pack=club")

    @override_settings(
        ALLOWED_HOSTS=["smartclubpro.org", "www.smartclubpro.org", ".onrender.com"],
        CANONICAL_HOST="smartclubpro.org",
        CANONICAL_HOST_EXEMPT_PATHS=(),
        SECURE_SSL_REDIRECT=False,
    )
    def test_health_route_on_render_host_redirects_to_smartclubpro(self):
        response = self.client.get("/health/", HTTP_HOST="gesgym-web.onrender.com")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://smartclubpro.org/health/")

    def test_root_route_uses_public_landing_template(self):
        response = self.client.get("/")

        self.assertTemplateUsed(response, "compte/accueil.html")

    def test_landing_includes_primary_seo_tags(self):
        response = self.client.get("/")

        self.assertContains(response, '<meta name="description"')
        self.assertContains(response, '<meta property="og:title"')
        self.assertContains(response, '<link rel="canonical" href="http://testserver/"')
        self.assertContains(response, '<script type="application/ld+json">', html=False)

    def test_robots_txt_exposes_sitemap_and_sensitive_disallow_rules(self):
        response = self.client.get("/robots.txt")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertIn("Disallow: /admin/", response.content.decode("utf-8"))
        self.assertIn("Sitemap: http://testserver/sitemap.xml", response.content.decode("utf-8"))

    def test_sitemap_xml_lists_landing_page(self):
        response = self.client.get("/sitemap.xml")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml; charset=utf-8")
        self.assertIn("<loc>http://testserver/</loc>", response.content.decode("utf-8"))

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

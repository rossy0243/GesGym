from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from compte.models import User, UserGymRole
from organizations.models import Gym, Organization


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


class LandingFooterTests(TestCase):
    """Le proprietaire renseigne le pied de page depuis Parametres."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Royal Gym",
            slug="royal-gym-vitrine",
            address="12 avenue de la Justice, Gombe, Kinshasa",
            phone="+243 81 000 00 00",
            email="contact@royalgym.cd",
            whatsapp_number="243810000000",
            footer_services="Musculation\nCross-training\nSauna",
            facebook_url="https://facebook.com/royalgym",
            instagram_url="https://instagram.com/royalgym",
        )

    def _pied_de_page(self, response):
        """Contenu du <footer> seul : le reste de la page a ses propres textes."""
        html = response.content.decode("utf-8", "replace")
        debut = html.index("<footer")
        return html[debut : html.index("</footer>", debut)]

    # --- Ce que lit le visiteur ---------------------------------------------

    def test_the_footer_shows_the_organization_contact_details(self):
        response = self.client.get("/")

        self.assertContains(response, "12 avenue de la Justice, Gombe, Kinshasa")
        self.assertContains(response, "+243 81 000 00 00")
        self.assertContains(response, "contact@royalgym.cd")

    def test_the_placeholder_values_are_gone(self):
        response = self.client.get("/")

        # "Adresse a confirmer" figurait a deux endroits : le pied de page et
        # le bloc "Horaires & localisation". Les deux doivent disparaitre.
        self.assertNotContains(response, "Adresse à confirmer")
        self.assertNotContains(response, "contact@royalgym.example")
        self.assertNotContains(response, "+243 00 000 0000")

    def test_the_footer_lists_the_declared_services(self):
        response = self.client.get("/")
        pied = self._pied_de_page(response)

        self.assertIn("Cross-training", pied)
        self.assertIn("Sauna", pied)
        # "Cardio-training" reste ailleurs sur la page : c'est le pied de page
        # qui doit suivre la liste declaree, pas le corps du site.
        self.assertNotIn("Cardio-training", pied)

    def test_only_the_declared_social_networks_appear(self):
        response = self.client.get("/")

        self.assertContains(response, "https://facebook.com/royalgym")
        self.assertContains(response, "https://instagram.com/royalgym")
        self.assertNotContains(response, "tiktok.com")

    def test_the_whatsapp_link_uses_the_declared_number(self):
        response = self.client.get("/")

        self.assertContains(response, "https://wa.me/243810000000")
        self.assertNotContains(response, "wa.me/243000000000")

    # --- Referencement --------------------------------------------------------

    def test_the_search_engine_block_carries_the_real_address(self):
        response = self.client.get("/")
        schema = response.context["seo_schema_json"]

        self.assertIn("12 avenue de la Justice", schema)
        self.assertIn("contact@royalgym.cd", schema)
        self.assertNotIn("Adresse a confirmer", schema)

    # --- Formulaire de contact -------------------------------------------------

    def test_a_contact_request_reaches_the_organization_address(self):
        self.client.post(
            "/",
            {
                "full_name": "Rosette Mukendi",
                "email": "rosette@example.com",
                "phone": "+243821000000",
                "message": "Vos tarifs ?",
            },
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["contact@royalgym.cd"])
        self.assertIn("Royal Gym", mail.outbox[0].subject)

    # --- Sans organisation renseignee ------------------------------------------

    def test_the_page_still_stands_without_any_organization(self):
        Organization.objects.all().delete()

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Musculation")

    def test_an_empty_field_hides_its_line_rather_than_showing_a_placeholder(self):
        self.organization.address = ""
        self.organization.phone = ""
        self.organization.save(update_fields=["address", "phone"])

        response = self.client.get("/")

        self.assertNotContains(response, "fa-map-marker-alt")
        self.assertNotContains(response, "fa-phone-alt")
        self.assertContains(response, "contact@royalgym.cd")


class OrganizationFooterSettingsTests(TestCase):
    """Seul le proprietaire regle la vitrine, et le numero est verifie."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Vitrine", slug="org-vitrine"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Vitrine",
            slug="gym-vitrine",
            subdomain="gym-vitrine",
        )
        self.owner = User.objects.create_user(
            username="proprio-vitrine",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _enregistrer(self, **overrides):
        payload = {
            "action": "organization",
            "name": "Org Vitrine",
            "address": "Avenue du Commerce",
            "phone": "+243810000001",
            "email": "vitrine@example.cd",
            "whatsapp_number": "243 81 000 00 02",
            "footer_services": "Musculation\nYoga",
            "facebook_url": "",
            "instagram_url": "",
            "tiktok_url": "",
        }
        payload.update(overrides)
        return self.client.post(reverse("core:settings"), payload, follow=True)

    def test_the_owner_saves_the_footer_details(self):
        self._enregistrer()

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.address, "Avenue du Commerce")
        self.assertEqual(self.organization.footer_services, "Musculation\nYoga")

    def test_the_whatsapp_number_is_stripped_of_spaces_and_signs(self):
        self._enregistrer()

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.whatsapp_number, "243810000002")
        self.assertEqual(
            self.organization.whatsapp_url, "https://wa.me/243810000002"
        )

    def test_a_truncated_whatsapp_number_is_refused(self):
        self._enregistrer(whatsapp_number="8100")

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.whatsapp_number, "")

    def test_a_manager_cannot_reach_the_organization_form(self):
        manager = User.objects.create_user(
            username="gerant-vitrine", password="pass12345"
        )
        UserGymRole.objects.create(
            user=manager, gym=self.gym, role="manager", is_active=True
        )
        self.client.force_login(manager)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

        self._enregistrer(address="Tentative")

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.address, None)

    def test_the_services_list_ignores_blank_lines(self):
        self._enregistrer(footer_services="Musculation\n\n  \nYoga\n")

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.services_list, ["Musculation", "Yoga"])

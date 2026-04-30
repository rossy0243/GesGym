from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from compte.models import User, UserGymRole
from organizations.models import Gym, GymModule, Module, Organization


class OwnerLoginAndGymSwitchTests(TestCase):
    def create_owner(self, username, organization):
        return User.objects.create_user(
            username=username,
            password="pass12345",
            owned_organization=organization,
        )

    def create_gym(self, organization, name, slug):
        return Gym.objects.create(
            organization=organization,
            name=name,
            slug=slug,
            subdomain=slug,
        )

    def test_owner_without_gym_role_can_login_and_single_gym_redirects_to_dashboard(self):
        organization = Organization.objects.create(name="Fit One", slug="fit-one")
        gym = self.create_gym(organization, "Fit One Downtown", "fit-one-downtown")
        self.create_owner("owner-one", organization)

        response = self.client.post(
            reverse("compte:login"),
            {"username": "owner-one", "password": "pass12345"},
        )

        self.assertRedirects(
            response,
            reverse("compte:welcome"),
            fetch_redirect_response=False,
        )

        response = self.client.get(reverse("core:dashboard_redirect"))
        self.assertRedirects(
            response,
            reverse("core:gym_dashboard", kwargs={"gym_id": gym.id}),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.client.session["current_gym_id"], gym.id)

    def test_owner_with_multiple_gyms_must_choose_then_session_keeps_selected_gym(self):
        organization = Organization.objects.create(name="Fit Group", slug="fit-group")
        gym_a = self.create_gym(organization, "Gombe", "gombe")
        gym_b = self.create_gym(organization, "Limete", "limete")
        self.create_owner("owner-group", organization)

        self.client.post(
            reverse("compte:login"),
            {"username": "owner-group", "password": "pass12345"},
        )

        welcome_response = self.client.get(reverse("compte:welcome"))
        self.assertEqual(welcome_response.status_code, 200)
        self.assertContains(welcome_response, "Fit Group")

        response = self.client.get(reverse("core:dashboard_redirect"))
        self.assertRedirects(
            response,
            reverse("core:select_gym"),
            fetch_redirect_response=False,
        )

        response = self.client.get(reverse("core:select_gym"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Choisir la salle de travail", content)
        self.assertIn(gym_a.name, content)
        self.assertIn(gym_b.name, content)

        response = self.client.post(reverse("core:switch_gym", args=[gym_b.id]))
        self.assertRedirects(
            response,
            reverse("core:gym_dashboard", kwargs={"gym_id": gym_b.id}),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.client.session["current_gym_id"], gym_b.id)

        response = self.client.get(reverse("core:dashboard_redirect"))
        self.assertRedirects(
            response,
            reverse("core:gym_dashboard", kwargs={"gym_id": gym_b.id}),
            fetch_redirect_response=False,
        )

    def test_owner_cannot_switch_to_gym_from_another_organization(self):
        organization = Organization.objects.create(name="Tenant A", slug="tenant-a")
        other_organization = Organization.objects.create(name="Tenant B", slug="tenant-b")
        gym = self.create_gym(organization, "Tenant A Gym", "tenant-a-gym")
        other_gym = self.create_gym(other_organization, "Tenant B Gym", "tenant-b-gym")
        owner = self.create_owner("owner-tenant-a", organization)

        self.client.force_login(owner)
        session = self.client.session
        session["current_gym_id"] = gym.id
        session.save()

        response = self.client.post(reverse("core:switch_gym", args=[other_gym.id]))

        self.assertRedirects(
            response,
            reverse("core:select_gym"),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.client.session["current_gym_id"], gym.id)

    def test_switch_gym_requires_post_to_change_session(self):
        organization = Organization.objects.create(name="Post Only", slug="post-only")
        gym = self.create_gym(organization, "Post Gym", "post-gym")
        owner = self.create_owner("owner-post", organization)
        self.client.force_login(owner)

        response = self.client.get(reverse("core:switch_gym", args=[gym.id]))

        self.assertEqual(response.status_code, 405)
        self.assertNotIn("current_gym_id", self.client.session)

    def test_select_gym_renders_cleanly_when_owner_has_no_active_gym(self):
        organization = Organization.objects.create(name="Empty Org", slug="empty-org")
        owner = self.create_owner("owner-empty", organization)
        self.client.force_login(owner)

        response = self.client.get(reverse("core:select_gym"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("Aucune salle active", response.content.decode("utf-8"))


class LoginConfigurationTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Remember Org", slug="remember-org")
        self.user = User.objects.create_user(
            username="remember-owner",
            password="RememberPass123",
            email="remember@example.com",
            owned_organization=self.organization,
        )

    def test_login_without_remember_me_expires_at_browser_close(self):
        response = self.client.post(
            reverse("compte:login"),
            {
                "username": "remember-owner",
                "password": "RememberPass123",
            },
        )

        self.assertRedirects(
            response,
            reverse("compte:welcome"),
            fetch_redirect_response=False,
        )
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_login_with_remember_me_uses_persistent_session(self):
        response = self.client.post(
            reverse("compte:login"),
            {
                "username": "remember-owner",
                "password": "RememberPass123",
                "remember_me": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("compte:welcome"),
            fetch_redirect_response=False,
        )
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_welcome_screen_uses_org_and_gym_context_for_staff(self):
        organization = Organization.objects.create(name="Splash Org", slug="splash-org")
        gym = Gym.objects.create(
            organization=organization,
            name="Splash Gym",
            slug="splash-gym",
            subdomain="splash-gym",
        )
        user = User.objects.create_user(username="staff-splash", password="pass12345")
        UserGymRole.objects.create(user=user, gym=gym, role="manager", is_active=True)

        self.client.force_login(user)
        session = self.client.session
        session["post_login_target"] = reverse("core:dashboard_redirect")
        session["current_gym_id"] = gym.id
        session.save()

        response = self.client.get(reverse("compte:welcome"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Splash Org")
        self.assertContains(response, "Splash Gym")

    @override_settings(
        SOCIAL_LINKS=[
            {"label": "GitHub", "icon": "fab fa-github", "url": "https://github.com/rossy0243"},
            {"label": "Facebook", "icon": "fab fa-facebook-f", "url": ""},
        ]
    )
    def test_login_page_displays_configured_social_links(self):
        response = self.client.get(reverse("compte:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("compte:password_reset"))
        self.assertContains(response, "https://github.com/rossy0243")
        self.assertNotContains(response, 'aria-label="Facebook"')


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
)
class PasswordResetFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="reset-user",
            password="AncienPass123",
            email="reset@example.com",
        )

    def test_password_reset_request_sends_email(self):
        response = self.client.post(
            reverse("compte:password_reset"),
            {"email": "reset@example.com"},
        )

        self.assertRedirects(
            response,
            reverse("compte:password_reset_done"),
            fetch_redirect_response=False,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["reset@example.com"])
        self.assertIn("/compte/reset/", mail.outbox[0].body)

    def test_password_reset_confirm_updates_password(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        confirm_url = reverse(
            "compte:password_reset_confirm",
            kwargs={"uidb64": uidb64, "token": token},
        )

        response = self.client.get(confirm_url, follow=True)
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            response.request["PATH_INFO"],
            {
                "new_password1": "NouveauPass123",
                "new_password2": "NouveauPass123",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mot de passe mis à jour")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NouveauPass123"))


class UserProfileTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Profile Org", slug="profile-org")
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Profile Gym",
            slug="profile-gym",
            subdomain="profile-gym",
        )
        self.user = User.objects.create_user(
            username="profile-owner",
            password="oldpass123",
            first_name="Old",
            last_name="Name",
            email="old@example.com",
            owned_organization=self.organization,
        )
        self.client.force_login(self.user)

    def test_profile_page_renders_context_and_breadcrumbs(self):
        response = self.client.get(reverse("compte:profile"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Mon profil", content)
        self.assertIn("Accueil", content)
        self.assertIn("Profile Org", content)
        self.assertIn("Profile Gym", content)

    def test_profile_update_persists_and_shows_success_toast(self):
        response = self.client.post(
            reverse("compte:profile"),
            {
                "action": "profile",
                "first_name": "New",
                "last_name": "Owner",
                "email": "new@example.com",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "New")
        self.assertEqual(self.user.last_name, "Owner")
        self.assertEqual(self.user.email, "new@example.com")
        self.assertContains(response, "Profil mis a jour avec succes.")
        self.assertContains(response, "bg-success")

    def test_password_change_updates_password_and_keeps_user_logged_in(self):
        response = self.client.post(
            reverse("compte:profile"),
            {
                "action": "password",
                "old_password": "oldpass123",
                "new_password1": "NewStrongPass123",
                "new_password2": "NewStrongPass123",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewStrongPass123"))
        self.assertContains(response, "Mot de passe modifie avec succes.")

        response = self.client.get(reverse("compte:profile"))
        self.assertEqual(response.status_code, 200)


class SuperAdminOwnerCreationTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="superadmin",
            password="superpass123",
            email="superadmin@example.com",
        )
        self.module_members, _ = Module.objects.get_or_create(code="MEMBERS", defaults={"name": "Membres"})
        self.module_pos, _ = Module.objects.get_or_create(code="POS", defaults={"name": "Point de vente"})

    def test_superadmin_can_open_owner_creation_view(self):
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("admin:create_owner_view"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Creer un Owner + organisation + gyms")
        self.assertContains(response, "MEMBERS - Membres")
        self.assertContains(response, "POS - Point de vente")

    def test_superadmin_can_create_owner_organization_gyms_and_modules(self):
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse("admin:create_owner_view"),
            {
                "first_name": "Client",
                "last_name": "Owner",
                "email": "owner.client@example.com",
                "organization_name": "Client Demo Admin",
                "organization_slug": "client-demo-admin",
                "organization_phone": "+243900111222",
                "organization_email": "contact@client-demo.test",
                "organization_address": "Kinshasa",
                "gyms": "Gombe Premium\nLimete Express",
                "modules": [self.module_members.id, self.module_pos.id],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("admin:compte_user_changelist"))
        organization = Organization.objects.get(slug="client-demo-admin")
        owner = User.objects.get(email="owner.client@example.com")
        self.assertEqual(owner.owned_organization, organization)
        self.assertFalse(owner.is_staff)
        self.assertTrue(owner.check_password("12345"))

        gyms = Gym.objects.filter(organization=organization).order_by("name")
        self.assertEqual(gyms.count(), 2)
        self.assertEqual(UserGymRole.objects.filter(user=owner, role="owner", gym__in=gyms).count(), 2)
        self.assertEqual(
            GymModule.objects.filter(
                gym__in=gyms,
                module__code__in=["MEMBERS", "POS"],
                is_active=True,
            ).count(),
            4,
        )

    def test_non_superuser_cannot_access_owner_creation_view(self):
        staff = User.objects.create_user(username="staff", password="pass", is_staff=True)
        self.client.force_login(staff)

        response = self.client.get(reverse("admin:create_owner_view"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("admin:compte_user_changelist"))

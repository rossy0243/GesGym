from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from compte.forms import CreateUserForm
from compte.models import User, UserGymRole
from members.models import Member
from organizations.models import Gym, GymModule, Module, Organization
from organizations.module_packs import get_pack_module_codes


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


class OwnerScopedUserManagementTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Scoped Org", slug="scoped-org")
        self.gym_a = Gym.objects.create(
            organization=self.organization,
            name="Gym A",
            slug="scoped-gym-a",
            subdomain="scoped-gym-a",
        )
        self.gym_b = Gym.objects.create(
            organization=self.organization,
            name="Gym B",
            slug="scoped-gym-b",
            subdomain="scoped-gym-b",
        )
        self.owner = User.objects.create_user(
            username="scoped-owner",
            password="ScopedOwner123!",
            owned_organization=self.organization,
        )
        UserGymRole.objects.create(user=self.owner, gym=self.gym_a, role="owner")
        self.shared_user = User.objects.create_user(
            username="shared-user",
            password="SharedUser123!",
            email="shared-user@example.com",
        )
        self.role_a = UserGymRole.objects.create(user=self.shared_user, gym=self.gym_a, role="cashier")
        self.role_b = UserGymRole.objects.create(user=self.shared_user, gym=self.gym_b, role="cashier")

        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()

    def test_owner_cannot_reset_password_for_shared_user_identity(self):
        response = self.client.post(reverse("compte:reset_password", args=[self.shared_user.id]))

        self.assertRedirects(response, reverse("compte:user_list"), fetch_redirect_response=False)
        self.shared_user.refresh_from_db()
        self.assertFalse(self.shared_user.force_password_change)
        self.assertTrue(self.shared_user.check_password("SharedUser123!"))

    def test_user_management_actions_require_post(self):
        reset_response = self.client.get(reverse("compte:reset_password", args=[self.shared_user.id]))
        deactivate_response = self.client.get(reverse("compte:deactivate_user", args=[self.shared_user.id]))
        activate_response = self.client.get(reverse("compte:activate_user", args=[self.shared_user.id]))

        self.assertEqual(reset_response.status_code, 405)
        self.assertEqual(deactivate_response.status_code, 405)
        self.assertEqual(activate_response.status_code, 405)
        self.shared_user.refresh_from_db()
        self.role_a.refresh_from_db()
        self.assertTrue(self.shared_user.check_password("SharedUser123!"))
        self.assertTrue(self.role_a.is_active)

    def test_owner_deactivation_only_disables_current_gym_role(self):
        response = self.client.post(reverse("compte:deactivate_user", args=[self.shared_user.id]))

        self.assertRedirects(response, reverse("compte:user_list"), fetch_redirect_response=False)
        self.role_a.refresh_from_db()
        self.role_b.refresh_from_db()
        self.shared_user.refresh_from_db()
        self.assertFalse(self.role_a.is_active)
        self.assertTrue(self.role_b.is_active)
        self.assertTrue(self.shared_user.is_active)


class SharedStaffMultiGymContextTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Shared Staff Org", slug="shared-staff-org")
        self.gym_a = Gym.objects.create(
            organization=self.organization,
            name="Gym A",
            slug="shared-staff-gym-a",
            subdomain="shared-staff-gym-a",
        )
        self.gym_b = Gym.objects.create(
            organization=self.organization,
            name="Gym B",
            slug="shared-staff-gym-b",
            subdomain="shared-staff-gym-b",
        )
        self.user = User.objects.create_user(
            username="shared-staff",
            password="SharedStaff123!",
            email="shared-staff@example.com",
        )
        UserGymRole.objects.create(user=self.user, gym=self.gym_a, role="cashier", is_active=True)
        UserGymRole.objects.create(user=self.user, gym=self.gym_b, role="manager", is_active=True)
        module_pos, _ = Module.objects.get_or_create(code="POS", defaults={"name": "Point de vente"})
        GymModule.objects.get_or_create(gym=self.gym_a, module=module_pos, defaults={"is_active": True})
        self.client.force_login(self.user)

    def test_session_current_gym_id_drives_staff_context_and_role(self):
        session = self.client.session
        session["current_gym_id"] = self.gym_b.id
        session.save()

        response = self.client.get(reverse("core:dashboard_redirect"))

        self.assertRedirects(
            response,
            reverse("core:gym_dashboard", kwargs={"gym_id": self.gym_b.id}),
            fetch_redirect_response=False,
        )

    def test_staff_can_switch_context_between_roles_using_session_gym(self):
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()

        cashier_response = self.client.get(reverse("core:dashboard_redirect"))
        self.assertRedirects(
            cashier_response,
            reverse("pos:cashier_dashboard"),
            fetch_redirect_response=False,
        )

        session = self.client.session
        session["current_gym_id"] = self.gym_b.id
        session.save()

        dashboard_response = self.client.get(reverse("core:gym_dashboard", args=[self.gym_b.id]))
        self.assertEqual(dashboard_response.status_code, 200)


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

    def test_login_page_displays_password_toggle_and_help_text(self):
        response = self.client.get(reverse("compte:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="toggle-password"')
        self.assertContains(response, "Afficher")
        self.assertContains(response, "Mot de passe oublié ?")
        self.assertContains(response, "si vous ne retrouvez plus vos accès")

    def test_owner_create_user_form_requires_email_for_password_reset_autonomy(self):
        form = CreateUserForm(
            data={
                "first_name": "Amina",
                "last_name": "Kasongo",
                "email": "",
                "role": "manager",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_member_login_prioritizes_member_portal_even_with_staff_role(self):
        organization = Organization.objects.create(name="Member Org", slug="member-org")
        gym = Gym.objects.create(
            organization=organization,
            name="Member Gym",
            slug="member-gym",
            subdomain="member-gym",
        )
        user = User.objects.create_user(
            username="member-priority",
            password="pass12345",
        )
        Member.objects.create(
            gym=gym,
            user=user,
            first_name="Mila",
            last_name="Portal",
            phone="+243810009999",
            email="mila.portal@example.com",
        )
        UserGymRole.objects.create(user=user, gym=gym, role="cashier", is_active=True)

        response = self.client.post(
            reverse("compte:login"),
            {"username": "member-priority", "password": "pass12345"},
        )

        self.assertRedirects(
            response,
            reverse("compte:welcome"),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.client.session["post_login_target"], reverse("members:member_portal"))

    def test_coach_login_sets_welcome_target_to_coach_portal(self):
        organization = Organization.objects.create(name="Coach Org", slug="coach-org")
        gym = Gym.objects.create(
            organization=organization,
            name="Coach Gym",
            slug="coach-gym",
            subdomain="coach-gym",
        )
        module, _ = Module.objects.get_or_create(code="COACHING", defaults={"name": "Coaching"})
        GymModule.objects.get_or_create(gym=gym, module=module, defaults={"is_active": True})
        user = User.objects.create_user(
            username="coach-route",
            password="pass12345",
            first_name="Coach",
            last_name="Route",
        )
        UserGymRole.objects.create(user=user, gym=gym, role="coach", is_active=True)

        response = self.client.post(
            reverse("compte:login"),
            {"username": "coach-route", "password": "pass12345"},
        )

        self.assertRedirects(
            response,
            reverse("compte:welcome"),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.client.session["post_login_target"], reverse("coaching:coach_portal"))

    def test_login_redirects_to_profile_when_password_change_is_forced(self):
        forced_user = User.objects.create_user(
            username="force-owner",
            password="TempPass123!",
            email="force@example.com",
            owned_organization=self.organization,
            force_password_change=True,
        )

        response = self.client.post(
            reverse("compte:login"),
            {"username": "force-owner", "password": "TempPass123!"},
        )

        self.assertRedirects(
            response,
            reverse("compte:profile"),
            fetch_redirect_response=False,
        )


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
        self.assertEqual(mail.outbox[0].from_email, "noreply@example.com")
        self.assertEqual(mail.outbox[0].subject, "SmartClub Pro - Reinitialisez votre mot de passe")
        self.assertIn("/compte/reset/", mail.outbox[0].body)
        self.assertTrue(mail.outbox[0].alternatives)
        self.assertIn("Definir un nouveau mot de passe", mail.outbox[0].alternatives[0][0])

    def test_password_reset_request_uses_organization_brand_for_staff_user(self):
        organization = Organization.objects.create(name="Royal Gym", slug="royal-gym")
        gym = Gym.objects.create(
            organization=organization,
            name="Royal Gym Gombe",
            slug="royal-gym-gombe",
            subdomain="royal-gym-gombe",
        )
        branded_user = User.objects.create_user(
            username="royal-manager",
            password="AncienPass123",
            email="manager@royalgym.example",
        )
        UserGymRole.objects.create(user=branded_user, gym=gym, role="manager")

        response = self.client.post(
            reverse("compte:password_reset"),
            {"email": "manager@royalgym.example"},
        )

        self.assertRedirects(
            response,
            reverse("compte:password_reset_done"),
            fetch_redirect_response=False,
        )
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["manager@royalgym.example"])
        self.assertEqual(message.from_email, "Royal Gym <noreply@example.com>")
        self.assertEqual(message.subject, "Royal Gym - Reinitialisez votre mot de passe")
        self.assertIn("compte Royal Gym", message.body)
        self.assertIn("L'equipe Royal Gym", message.body)
        self.assertIn("Royal Gym", message.alternatives[0][0])

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

    def test_forced_password_change_uses_dedicated_form_and_clears_flag(self):
        self.user.force_password_change = True
        self.user.set_password("TempPass123!")
        self.user.save(update_fields=["force_password_change", "password"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("compte:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mot de passe temporaire")
        self.assertNotContains(response, "Mot de passe actuel")

        response = self.client.post(
            reverse("compte:profile"),
            {
                "action": "password",
                "new_password1": "BrandNewPass123!",
                "new_password2": "BrandNewPass123!",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.force_password_change)
        self.assertTrue(self.user.check_password("BrandNewPass123!"))


class SuperAdminOwnerCreationTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="superadmin",
            password="superpass123",
            email="superadmin@example.com",
        )

    def test_superadmin_can_open_owner_creation_view(self):
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("admin:create_owner_view"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Creer un Owner + organisation + gyms")
        self.assertContains(response, "Pack client")
        self.assertContains(response, "Pack Club")
        self.assertContains(response, "Pack Premium")

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
                "subscription_pack": Organization.PACK_CLUB,
                "gyms": "Gombe Premium\nLimete Express",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Verifier le recapitulatif avant creation")
        self.assertContains(response, "Client Demo Admin")
        self.assertContains(response, "Gombe Premium")

        response = self.client.post(
            reverse("admin:create_owner_view"),
            {"_confirm_create": "1"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request["PATH_INFO"], reverse("admin:create_owner_success_view"))
        organization = Organization.objects.get(slug="client-demo-admin")
        owner = User.objects.get(email="owner.client@example.com")
        self.assertEqual(owner.owned_organization, organization)
        self.assertEqual(organization.subscription_pack, Organization.PACK_CLUB)
        self.assertFalse(owner.is_staff)
        self.assertTrue(owner.force_password_change)

        gyms = Gym.objects.filter(organization=organization).order_by("name")
        self.assertEqual(gyms.count(), 2)
        self.assertEqual(UserGymRole.objects.filter(user=owner, role="owner", gym__in=gyms).count(), 2)
        expected_codes = get_pack_module_codes(Organization.PACK_CLUB)
        self.assertEqual(
            GymModule.objects.filter(
                gym__in=gyms,
                module__code__in=expected_codes,
                is_active=True,
            ).count(),
            len(expected_codes) * 2,
        )
        self.assertFalse(
            GymModule.objects.filter(
                gym__in=gyms,
                module__code="COACHING",
                is_active=True,
            ).exists()
        )
        self.assertContains(response, "Login pret : Oui")
        self.assertContains(response, "Pack Club")
        self.assertContains(response, owner.username)

    def test_owner_creation_blocks_duplicate_gym_names_in_same_submission(self):
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse("admin:create_owner_view"),
            {
                "first_name": "Client",
                "last_name": "Owner",
                "email": "owner.duplicate@example.com",
                "organization_name": "Client Duplicate",
                "organization_slug": "client-duplicate",
                "subscription_pack": Organization.PACK_PREMIUM,
                "gyms": "Gombe\ngombe",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "est saisi plusieurs fois")

    def test_non_superuser_cannot_access_owner_creation_view(self):
        staff = User.objects.create_user(username="staff", password="pass", is_staff=True)
        self.client.force_login(staff)

        response = self.client.get(reverse("admin:create_owner_view"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("admin:compte_user_changelist"))

from django.test import TestCase
from django.urls import reverse

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
            reverse("core:dashboard_redirect"),
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

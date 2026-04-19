from django.test import TestCase
from django.urls import reverse

from compte.models import User
from organizations.models import Gym, Organization


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

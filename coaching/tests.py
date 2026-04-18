from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from compte.models import User, UserGymRole
from members.models import Member
from organizations.models import Gym, GymModule, Module, Organization

from .models import Coach


class CoachingTenantTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Org A", slug="coaching-org-a")
        self.org_b = Organization.objects.create(name="Org B", slug="coaching-org-b")
        self.gym_a = Gym.objects.create(
            organization=self.org_a,
            name="Gym A",
            slug="coaching-gym-a",
            subdomain="coaching-gym-a",
        )
        self.gym_b = Gym.objects.create(
            organization=self.org_b,
            name="Gym B",
            slug="coaching-gym-b",
            subdomain="coaching-gym-b",
        )
        module, _ = Module.objects.get_or_create(code="COACHING", defaults={"name": "Coaching"})
        GymModule.objects.create(gym=self.gym_a, module=module, is_active=True)
        GymModule.objects.create(gym=self.gym_b, module=module, is_active=True)

        self.user = User.objects.create_user(username="coach-manager", password="test-pass")
        UserGymRole.objects.create(user=self.user, gym=self.gym_a, role="manager")

        self.coach_a = Coach.objects.create(
            gym=self.gym_a,
            name="Coach A",
            phone="1000",
            specialty="Musculation",
        )
        self.coach_b = Coach.objects.create(
            gym=self.gym_b,
            name="Coach B",
            phone="2000",
            specialty="Yoga",
        )
        self.member_a = Member.objects.create(
            gym=self.gym_a,
            first_name="Alice",
            last_name="Member",
            phone="111",
            email="alice.coaching@example.com",
            status="active",
            is_active=True,
        )
        self.member_b = Member.objects.create(
            gym=self.gym_b,
            first_name="Bob",
            last_name="Member",
            phone="222",
            email="bob.coaching@example.com",
            status="active",
            is_active=True,
        )
        self.coach_b.members.add(self.member_b)
        self.client.login(username="coach-manager", password="test-pass")

    def test_coach_list_is_scoped_to_current_gym(self):
        response = self.client.get(reverse("coaching:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Coach A")
        self.assertNotContains(response, "Coach B")
        self.assertContains(response, "Total coaches")

    def test_other_gym_coach_detail_is_not_accessible(self):
        response = self.client.get(reverse("coaching:detail", args=[self.coach_b.id]))

        self.assertEqual(response.status_code, 404)

    def test_assign_member_uses_current_gym_only(self):
        response = self.client.post(
            reverse("coaching:assign_member", args=[self.coach_a.id]),
            {"member": self.member_a.id},
        )

        self.assertRedirects(response, reverse("coaching:detail", args=[self.coach_a.id]))
        self.assertTrue(self.coach_a.members.filter(id=self.member_a.id).exists())

    def test_assign_member_rejects_other_gym_member(self):
        response = self.client.post(
            reverse("coaching:assign_member", args=[self.coach_a.id]),
            {"member": self.member_b.id},
        )

        self.assertRedirects(response, reverse("coaching:detail", args=[self.coach_a.id]))
        self.assertFalse(self.coach_a.members.filter(id=self.member_b.id).exists())

    def test_model_rejects_cross_gym_member_assignment(self):
        with self.assertRaises(ValidationError):
            self.coach_a.members.add(self.member_b)

    def test_remove_member_uses_current_gym_only(self):
        self.coach_a.members.add(self.member_a)

        response = self.client.post(
            reverse("coaching:remove_member", args=[self.coach_a.id, self.member_a.id]),
        )

        self.assertRedirects(response, reverse("coaching:detail", args=[self.coach_a.id]))
        self.assertFalse(self.coach_a.members.filter(id=self.member_a.id).exists())

    def test_form_pages_render_without_gym_id_urls(self):
        urls = [
            reverse("coaching:create"),
            reverse("coaching:update", args=[self.coach_a.id]),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_general_dashboard_includes_scoped_coaching_kpis(self):
        self.coach_a.members.add(self.member_a)
        response = self.client.get(reverse("core:gym_dashboard", args=[self.gym_a.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "KPI coaching")
        self.assertContains(response, "Graphique coaching")
        self.assertContains(response, "coachingWorkloadChart")
        self.assertContains(response, "Coach A")
        self.assertNotContains(response, "Coach B")

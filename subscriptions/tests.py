from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from members.models import Member
from organizations.models import Gym, Organization
from subscriptions.forms import MemberSubscriptionForm, SubscriptionPlanForm
from subscriptions.models import MemberSubscription, SubscriptionPlan
from subscriptions.views import create_member_subscription


class SubscriptionTenantSafetyTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Org A", slug="org-a")
        self.org_b = Organization.objects.create(name="Org B", slug="org-b")
        self.gym_a = Gym.objects.create(
            organization=self.org_a,
            name="Gym A",
            slug="gym-a",
            subdomain="gym-a",
        )
        self.gym_b = Gym.objects.create(
            organization=self.org_b,
            name="Gym B",
            slug="gym-b",
            subdomain="gym-b",
        )
        self.member_a = Member.objects.create(
            gym=self.gym_a,
            first_name="Alice",
            last_name="Tenant",
            phone="10001",
            email="alice@example.com",
        )
        self.member_b = Member.objects.create(
            gym=self.gym_b,
            first_name="Bob",
            last_name="Tenant",
            phone="20001",
            email="bob@example.com",
        )
        self.plan_a = SubscriptionPlan.objects.create(
            gym=self.gym_a,
            name="Mensuel",
            duration_days=30,
            price=100,
        )
        self.plan_b = SubscriptionPlan.objects.create(
            gym=self.gym_b,
            name="Premium",
            duration_days=30,
            price=200,
        )

    def test_subscription_form_querysets_are_scoped_to_current_gym(self):
        form = MemberSubscriptionForm(gym=self.gym_a)

        self.assertIn(self.member_a, form.fields["member"].queryset)
        self.assertNotIn(self.member_b, form.fields["member"].queryset)
        self.assertIn(self.plan_a, form.fields["plan"].queryset)
        self.assertNotIn(self.plan_b, form.fields["plan"].queryset)

    def test_subscription_form_rejects_cross_gym_post_data(self):
        form = MemberSubscriptionForm(
            data={
                "member": self.member_a.pk,
                "plan": self.plan_b.pk,
                "start_date": timezone.now().date().isoformat(),
            },
            gym=self.gym_a,
        )

        self.assertFalse(form.is_valid())

    def test_model_rejects_cross_gym_member_and_plan(self):
        today = timezone.now().date()
        subscription = MemberSubscription(
            gym=self.gym_a,
            member=self.member_a,
            plan=self.plan_b,
            start_date=today,
            end_date=today + timedelta(days=30),
        )

        with self.assertRaises(ValidationError):
            subscription.full_clean()

    def test_plan_name_uniqueness_is_scoped_to_gym(self):
        same_gym_form = SubscriptionPlanForm(
            data={
                "name": "mensuel",
                "duration_days": 45,
                "price": 150,
                "is_active": "on",
            },
            gym=self.gym_a,
        )
        other_gym_form = SubscriptionPlanForm(
            data={
                "name": "Mensuel",
                "duration_days": 45,
                "price": 150,
                "is_active": "on",
            },
            gym=self.gym_b,
        )

        self.assertFalse(same_gym_form.is_valid())
        self.assertTrue(other_gym_form.is_valid())

    def test_create_member_subscription_sets_gym_and_replaces_active_subscription(self):
        first_subscription = create_member_subscription(self.member_a, self.plan_a)
        second_subscription = create_member_subscription(self.member_a, self.plan_a)

        first_subscription.refresh_from_db()
        self.assertEqual(second_subscription.gym, self.gym_a)
        self.assertFalse(first_subscription.is_active)
        self.assertTrue(second_subscription.is_active)

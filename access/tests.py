from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from compte.models import User, UserGymRole
from members.models import Member
from organizations.models import Gym, Organization
from subscriptions.models import MemberSubscription, SubscriptionPlan
from .models import AccessLog
from .views import DOUBLE_SCAN_REASON


class AccessControlTests(TestCase):
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
        self.user = User.objects.create_user(
            username="reception-a",
            password="test-pass",
        )
        UserGymRole.objects.create(
            user=self.user,
            gym=self.gym_a,
            role="reception",
        )
        self.member_a = Member.objects.create(
            gym=self.gym_a,
            first_name="Alice",
            last_name="Access",
            phone="10001",
            email="alice-access@example.com",
        )
        self.member_b = Member.objects.create(
            gym=self.gym_b,
            first_name="Bob",
            last_name="Access",
            phone="20001",
            email="bob-access@example.com",
        )
        self.plan_a = SubscriptionPlan.objects.create(
            gym=self.gym_a,
            name="Mensuel",
            duration_days=30,
            price=30,
        )
        today = timezone.now().date()
        MemberSubscription.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            plan=self.plan_a,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )
        self.client.login(username="reception-a", password="test-pass")

    def test_access_log_rejects_cross_gym_member(self):
        with self.assertRaises(ValidationError):
            AccessLog.objects.create(
                gym=self.gym_a,
                member=self.member_b,
                access_granted=True,
                device_used="Manuel",
            )

    def test_manual_access_creates_scoped_log_for_current_gym(self):
        response = self.client.post(
            reverse("access:manual_access_entry", args=[self.member_a.id])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["access"])
        self.assertEqual(payload["log"]["method"], "Manuel")
        self.assertEqual(payload["log"]["status"], "success")
        self.assertEqual(payload["log"]["member"], "Alice Access")

        log = AccessLog.objects.get(member=self.member_a)
        self.assertEqual(log.gym, self.gym_a)
        self.assertEqual(log.scanned_by, self.user)
        self.assertEqual(log.device_used, "Manuel")

    def test_manual_access_denies_second_entry_same_day(self):
        first_response = self.client.post(
            reverse("access:manual_access_entry", args=[self.member_a.id])
        )
        second_response = self.client.post(
            reverse("access:manual_access_entry", args=[self.member_a.id])
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(first_response.json()["access"])

        payload = second_response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], DOUBLE_SCAN_REASON)
        self.assertEqual(payload["log"]["status"], "denied")
        self.assertEqual(payload["log"]["reason"], DOUBLE_SCAN_REASON)
        self.assertEqual(payload["stats"]["entries"], 1)
        self.assertEqual(payload["stats"]["denied"], 1)

        logs = AccessLog.objects.filter(member=self.member_a).order_by("id")
        self.assertEqual(logs.count(), 2)
        self.assertTrue(logs[0].access_granted)
        self.assertFalse(logs[1].access_granted)
        self.assertEqual(logs[1].denial_reason, DOUBLE_SCAN_REASON)

    def test_qr_access_denies_second_scan_same_day(self):
        first_response = self.client.post(
            reverse("access:member_access", args=[self.member_a.qr_code])
        )
        second_response = self.client.post(
            reverse("access:member_access", args=[self.member_a.qr_code])
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(first_response.json()["access"])

        payload = second_response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], DOUBLE_SCAN_REASON)
        self.assertEqual(payload["log"]["method"], "QR Scanner")
        self.assertEqual(payload["stats"]["entries"], 1)
        self.assertEqual(payload["stats"]["denied"], 1)

    def test_previous_day_entry_does_not_block_today(self):
        log = AccessLog.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            access_granted=True,
            device_used="Manuel",
            scanned_by=self.user,
        )
        AccessLog.objects.filter(pk=log.pk).update(
            check_in_time=timezone.now() - timedelta(days=1)
        )

        response = self.client.post(
            reverse("access:manual_access_entry", args=[self.member_a.id])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["access"])
        self.assertEqual(payload["stats"]["entries"], 1)
        self.assertEqual(
            AccessLog.objects.filter(member=self.member_a, access_granted=True).count(),
            2,
        )

    def test_denied_attempt_does_not_block_later_valid_entry(self):
        member = Member.objects.create(
            gym=self.gym_a,
            first_name="Retry",
            last_name="Member",
            phone="10003",
            email="retry-access@example.com",
        )

        first_response = self.client.post(
            reverse("access:manual_access_entry", args=[member.id])
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertFalse(first_response.json()["access"])

        today = timezone.now().date()
        MemberSubscription.objects.create(
            gym=self.gym_a,
            member=member,
            plan=self.plan_a,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )

        second_response = self.client.post(
            reverse("access:manual_access_entry", args=[member.id])
        )

        self.assertEqual(second_response.status_code, 200)
        payload = second_response.json()
        self.assertTrue(payload["access"])
        self.assertEqual(payload["stats"]["entries"], 1)
        self.assertEqual(payload["stats"]["denied"], 1)

    def test_qr_access_cannot_read_member_from_other_gym(self):
        response = self.client.post(
            reverse("access:member_access", args=[self.member_b.qr_code])
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(AccessLog.objects.filter(member=self.member_b).exists())

    def test_member_without_valid_subscription_is_denied(self):
        member = Member.objects.create(
            gym=self.gym_a,
            first_name="Expired",
            last_name="Member",
            phone="10002",
            email="expired-access@example.com",
        )

        response = self.client.post(
            reverse("access:manual_access_entry", args=[member.id])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], "Aucun abonnement actif")
        self.assertEqual(payload["log"]["reason"], "Aucun abonnement actif")
        self.assertEqual(payload["log"]["status"], "denied")

        log = AccessLog.objects.get(member=member)
        self.assertFalse(log.access_granted)
        self.assertEqual(log.denial_reason, "Aucun abonnement actif")

    def test_realtime_access_is_scoped_to_current_gym(self):
        AccessLog.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            access_granted=True,
            device_used="Manuel",
            scanned_by=self.user,
        )
        AccessLog.objects.create(
            gym=self.gym_b,
            member=self.member_b,
            access_granted=True,
            device_used="Manuel",
        )

        response = self.client.get("/access/access/realtime/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["member"], "Alice Access")

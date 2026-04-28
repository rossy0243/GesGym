from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from compte.models import User, UserGymRole
from members.models import Member
from notifications.models import Notification
from organizations.models import Gym, GymModule, Module, Organization
from subscriptions.models import MemberSubscription, SubscriptionPlan


class InAppNotificationDashboardTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Notify Org", slug="notify-org")
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Notify Gym",
            slug="notify-gym",
            subdomain="notify-gym",
        )
        self.module, _ = Module.objects.get_or_create(
            code="NOTIFICATIONS",
            defaults={"name": "Notifications"},
        )
        GymModule.objects.create(gym=self.gym, module=self.module, is_active=True)
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Maya",
            last_name="Message",
            phone="+243810000404",
        )
        self.active_member = Member.objects.create(
            gym=self.gym,
            first_name="Alice",
            last_name="Active",
            phone="+243810000405",
        )
        self.suspended_member = Member.objects.create(
            gym=self.gym,
            first_name="Sam",
            last_name="Suspendu",
            phone="+243810000406",
            status="suspended",
        )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym,
            name="Mensuel",
            duration_days=30,
            price=35,
        )
        today = timezone.localdate()
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.active_member,
            plan=self.plan,
            start_date=today,
            end_date=today + timedelta(days=20),
            is_active=True,
        )
        self.owner = User.objects.create_user(
            username="owner-notify",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.reception = User.objects.create_user(
            username="reception-notify",
            password="pass12345",
        )
        UserGymRole.objects.create(user=self.reception, gym=self.gym, role="reception")

    def test_dashboard_sends_in_app_message(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("notifications:dashboard"),
            {
                "target": "individual",
                "member": self.member.id,
                "title": "Rappel",
                "message": "Votre abonnement expire bientot.",
            },
        )

        self.assertEqual(response.status_code, 302)
        notification = Notification.objects.get(member=self.member)
        self.assertEqual(notification.gym, self.gym)
        self.assertEqual(notification.title, "Rappel")
        self.assertEqual(notification.message, "Votre abonnement expire bientot.")
        self.assertEqual(notification.channel, Notification.CHANNEL_IN_APP)
        self.assertEqual(notification.status, Notification.STATUS_SENT)
        self.assertEqual(notification.sent_by, self.owner)
        self.assertIsNotNone(notification.sent_at)

    def test_dashboard_can_send_to_active_members_only(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("notifications:dashboard"),
            {
                "target": "active",
                "title": "Bravo",
                "message": "Votre abonnement est actif.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Notification.objects.count(), 1)
        notification = Notification.objects.get()
        self.assertEqual(notification.member, self.active_member)
        self.assertEqual(notification.title, "Bravo")

    def test_dashboard_can_send_to_expired_members(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("notifications:dashboard"),
            {
                "target": "expired",
                "title": "Renouvellement",
                "message": "Votre abonnement est expire.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(
                Notification.objects.order_by("member__first_name").values_list(
                    "member__first_name",
                    flat=True,
                )
            ),
            ["Maya"],
        )

    def test_reception_can_open_dashboard_when_module_is_active(self):
        self.client.force_login(self.reception)

        response = self.client.get(reverse("notifications:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Messages membres")
        self.assertContains(response, "Maya Message")

from django.test import TestCase
from django.urls import reverse

from compte.models import User, UserGymRole
from members.models import Member
from notifications.models import Notification
from organizations.models import Gym, GymModule, Module, Organization


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

    def test_reception_can_open_dashboard_when_module_is_active(self):
        self.client.force_login(self.reception)

        response = self.client.get(reverse("notifications:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Messages membres")
        self.assertContains(response, "Maya Message")

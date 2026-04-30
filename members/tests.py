from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from coaching.models import Coach
from compte.models import User, UserGymRole
from members.models import Member, MemberPreRegistration, MemberPreRegistrationLink
from notifications.models import Notification
from organizations.models import Gym, Organization
from subscriptions.models import MemberSubscription, SubscriptionPlan, SubscriptionRequest


class MemberPreRegistrationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org Members", slug="org-members")
        self.other_org = Organization.objects.create(name="Other Org", slug="other-org")
        self.gym = Gym.objects.create(
            organization=self.org,
            name="Main Gym",
            slug="main-gym",
            subdomain="main-gym",
        )
        self.other_gym = Gym.objects.create(
            organization=self.other_org,
            name="Other Gym",
            slug="other-gym",
            subdomain="other-gym",
        )
        self.owner = User.objects.create_user(
            username="owner-members",
            password="pass12345",
            owned_organization=self.org,
        )

    def test_member_list_exposes_public_pre_registration_link_for_current_gym(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("members:member_list"))

        self.assertEqual(response.status_code, 200)
        link = MemberPreRegistrationLink.objects.get(gym=self.gym)
        self.assertContains(response, str(link.token))
        self.assertContains(response, "Lien de preinscription")

    def test_public_pre_registration_creates_pending_request_for_link_gym(self):
        link = MemberPreRegistrationLink.objects.get(gym=self.gym)

        response = self.client.post(
            reverse("members:public_pre_registration", args=[link.token]),
            {
                "first_name": "Alice",
                "last_name": "Visitor",
                "phone": "+243810000001",
                "email": "alice.visitor@example.com",
                "address": "Kinshasa",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Demande envoyee")
        pre_registration = MemberPreRegistration.objects.get(phone="+243810000001")
        self.assertEqual(pre_registration.gym, self.gym)
        self.assertEqual(pre_registration.status, MemberPreRegistration.STATUS_PENDING)
        self.assertGreater(pre_registration.expires_at, timezone.now() + timedelta(days=6, hours=23))
        self.assertFalse(Member.objects.filter(phone="+243810000001").exists())

    def test_confirm_pre_registration_creates_member_and_default_user(self):
        pre_registration = MemberPreRegistration.objects.create(
            gym=self.gym,
            first_name="Bob",
            last_name="Ready",
            phone="+243810000002",
            email="bob.ready@example.com",
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("members:confirm_pre_registration", args=[pre_registration.id])
        )

        self.assertRedirects(response, reverse("members:pre_registration_list"))
        pre_registration.refresh_from_db()
        self.assertEqual(pre_registration.status, MemberPreRegistration.STATUS_CONFIRMED)
        self.assertIsNotNone(pre_registration.member)
        member = pre_registration.member
        self.assertEqual(member.gym, self.gym)
        self.assertIsNotNone(member.user)
        self.assertTrue(member.user.check_password("12345"))
        self.assertTrue(
            UserGymRole.objects.filter(
                user=member.user,
                gym=self.gym,
                role="accountant",
                is_active=True,
            ).exists()
        )

    def test_pre_registration_list_is_scoped_to_current_gym(self):
        MemberPreRegistration.objects.create(
            gym=self.gym,
            first_name="Visible",
            last_name="Tenant",
            phone="+243810000003",
        )
        MemberPreRegistration.objects.create(
            gym=self.other_gym,
            first_name="Hidden",
            last_name="Tenant",
            phone="+243810000004",
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("members:pre_registration_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visible")
        self.assertNotContains(response, "Hidden")

    def test_expired_pending_pre_registrations_are_deleted_by_command(self):
        expired = MemberPreRegistration.objects.create(
            gym=self.gym,
            first_name="Expired",
            last_name="Lead",
            phone="+243810000005",
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        confirmed = MemberPreRegistration.objects.create(
            gym=self.gym,
            first_name="Confirmed",
            last_name="Lead",
            phone="+243810000006",
            status=MemberPreRegistration.STATUS_CONFIRMED,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        output = StringIO()
        call_command("cleanup_expired_preregistrations", stdout=output)

        self.assertFalse(MemberPreRegistration.objects.filter(id=expired.id).exists())
        self.assertTrue(MemberPreRegistration.objects.filter(id=confirmed.id).exists())
        self.assertIn("1 preinscription", output.getvalue())


class MemberPortalTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Portal Org", slug="portal-org")
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Portal Gym",
            slug="portal-gym",
            subdomain="portal-gym",
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Maya",
            last_name="Mobile",
            phone="+243810000101",
            email="maya.mobile@example.com",
        )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym,
            name="Mensuel",
            duration_days=30,
            price=35,
        )
        self.year_plan = SubscriptionPlan.objects.create(
            gym=self.gym,
            name="Annuel",
            duration_days=365,
            price=320,
        )
        today = timezone.now().date()
        self.subscription = MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )
        self.coach = Coach.objects.create(
            gym=self.gym,
            name="Coach Junior",
            phone="+243990000101",
            specialty="Musculation",
        )
        self.coach.members.add(self.member)

    def test_member_login_redirects_to_mobile_portal(self):
        response = self.client.post(
            reverse("compte:login"),
            {
                "username": self.member.user.username,
                "password": "12345",
            },
        )

        self.assertRedirects(
            response,
            reverse("members:member_portal"),
            fetch_redirect_response=False,
        )

    def test_member_portal_shows_identity_card_and_subscription(self):
        self.client.force_login(self.member.user)

        response = self.client.get(reverse("members:member_portal"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Carte membre")
        self.assertContains(response, "Mon accompagnement")
        self.assertContains(response, "Derniers acces")
        self.assertContains(response, f"MEM-{self.member.id:05d}")
        self.assertContains(response, self.member.user.username)
        self.assertContains(response, reverse("members:member_portal_qr"))
        self.assertNotContains(response, "Imprimer carte")
        self.assertNotContains(response, "window.print")

        subscription_response = self.client.get(reverse("members:member_portal"), {"tab": "subscription"})
        self.assertContains(subscription_response, "Mensuel")
        self.assertContains(subscription_response, "Dernieres operations")

        plans_response = self.client.get(reverse("members:member_portal"), {"tab": "plans"})
        self.assertContains(plans_response, "Choisir un abonnement")
        self.assertContains(plans_response, "Annuel")

    def test_member_can_read_in_app_notification(self):
        notification = Notification.objects.create(
            gym=self.gym,
            member=self.member,
            title="Bienvenue",
            message="Votre carte membre est active.",
            channel=Notification.CHANNEL_IN_APP,
            status=Notification.STATUS_SENT,
            sent_at=timezone.now(),
        )
        self.client.force_login(self.member.user)

        response = self.client.get(reverse("members:member_portal"), {"tab": "messages"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bienvenue")
        self.assertContains(response, "Non lu")

        response = self.client.post(
            reverse("members:member_notification_read", args=[notification.id])
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('members:member_portal')}?tab=messages")
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

    def test_member_can_create_pending_subscription_request_without_activating_plan(self):
        self.client.force_login(self.member.user)

        response = self.client.post(
            reverse("members:member_subscription_request"),
            {"plan_id": self.year_plan.id},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('members:member_portal')}?tab=plans")

        request_obj = SubscriptionRequest.objects.get(member=self.member, plan=self.year_plan)
        self.assertEqual(request_obj.gym, self.gym)
        self.assertEqual(request_obj.status, SubscriptionRequest.STATUS_PENDING)
        self.assertEqual(request_obj.price_usd, self.year_plan.price)
        self.assertEqual(request_obj.requested_by, self.member.user)
        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.is_active)

        response = self.client.get(reverse("members:member_portal"), {"tab": "plans"})
        self.assertContains(response, "Demande en attente")
        self.assertContains(response, "En attente")

    def test_member_portal_messages_tab_shows_unread_badge_and_compact_sections(self):
        Notification.objects.create(
            gym=self.gym,
            member=self.member,
            title="Info 1",
            message="Premier message important",
            channel=Notification.CHANNEL_IN_APP,
            status=Notification.STATUS_SENT,
            sent_at=timezone.now(),
        )
        Notification.objects.create(
            gym=self.gym,
            member=self.member,
            title="Info 2",
            message="Second message deja lu",
            channel=Notification.CHANNEL_IN_APP,
            status=Notification.STATUS_SENT,
            sent_at=timezone.now(),
            read_at=timezone.now(),
        )
        self.client.force_login(self.member.user)

        response = self.client.get(reverse("members:member_portal"), {"tab": "messages"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Boite de reception")
        self.assertContains(response, "Prioritaires")
        self.assertContains(response, "Recents")
        self.assertContains(response, "1 non lu")

    def test_member_portal_qr_is_limited_to_authenticated_member(self):
        anonymous_response = self.client.get(reverse("members:member_portal_qr"))
        self.assertEqual(anonymous_response.status_code, 302)

        self.client.force_login(self.member.user)
        response = self.client.get(reverse("members:member_portal_qr"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    def test_pwa_manifest_and_service_worker_are_available(self):
        manifest_response = self.client.get(reverse("members:member_app_manifest"))
        worker_response = self.client.get(reverse("members:member_app_service_worker"))

        self.assertEqual(manifest_response.status_code, 200)
        self.assertEqual(manifest_response.json()["start_url"], reverse("members:member_portal"))
        self.assertEqual(manifest_response.json()["display"], "standalone")
        self.assertEqual(worker_response.status_code, 200)
        self.assertEqual(worker_response["Service-Worker-Allowed"], "/members/")
        self.assertIn("service-worker", reverse("members:member_app_service_worker"))
        self.assertNotIn("/members/me/", worker_response.content.decode("utf-8"))

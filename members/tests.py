from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from compte.models import User, UserGymRole
from members.models import Member, MemberPreRegistration, MemberPreRegistrationLink
from organizations.models import Gym, Organization


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

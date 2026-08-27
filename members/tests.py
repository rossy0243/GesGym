import json
from datetime import timedelta
from io import BytesIO, StringIO
from unittest.mock import PropertyMock, patch

from django.core.exceptions import ValidationError
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from access import door
from access.models import AccessLog
from coaching.models import Coach, CoachAssignment, CoachingFeedback, GroupCoachingProgram
from compte.models import User, UserGymRole
from members import invitations
from members.forms import MemberCreationForm, MemberPreRegistrationForm
from members.models import (
    GuestPass,
    Member,
    MemberGoal,
    MemberPreRegistration,
    MemberPreRegistrationLink,
    MemberWeightMeasurement,
)
from notifications.models import Notification
from organizations.models import Gym, GymModule, Module, Organization, SensitiveActivityLog
from subscriptions.models import MemberSubscription, SubscriptionOffer, SubscriptionPlan, SubscriptionRequest


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
        self.manager = User.objects.create_user(
            username="manager-members",
            password="pass12345",
        )
        self.reception = User.objects.create_user(
            username="reception-members",
            password="pass12345",
        )
        self.cashier = User.objects.create_user(
            username="cashier-members",
            password="pass12345",
        )
        UserGymRole.objects.create(user=self.manager, gym=self.gym, role="manager", is_active=True)
        UserGymRole.objects.create(user=self.reception, gym=self.gym, role="reception", is_active=True)
        UserGymRole.objects.create(user=self.cashier, gym=self.gym, role="cashier", is_active=True)

    def test_member_list_exposes_public_pre_registration_link_for_current_gym(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("members:member_list"))

        self.assertEqual(response.status_code, 200)
        link = MemberPreRegistrationLink.objects.get(gym=self.gym)
        self.assertContains(response, str(link.token))
        self.assertContains(response, "Lien de preinscription")

    def test_member_list_active_filter_excludes_future_subscriptions(self):
        today = timezone.now().date()
        future_member = Member.objects.create(
            gym=self.gym,
            first_name="Future",
            last_name="Starter",
            phone="+243810000007",
            email="future.starter@example.com",
        )
        plan = SubscriptionPlan.objects.create(
            gym=self.gym,
            name="Mensuel",
            duration_days=30,
            price=25,
        )
        MemberSubscription.objects.create(
            gym=self.gym,
            member=future_member,
            plan=plan,
            start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=33),
            is_active=True,
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("members:member_list"), {"status": "active"})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Future")

    def test_cashier_cannot_access_member_list(self):
        self.client.force_login(self.cashier)

        response = self.client.get(reverse("members:member_list"))

        self.assertEqual(response.status_code, 403)

    def test_reception_can_create_and_edit_member(self):
        self.client.force_login(self.reception)

        create_response = self.client.post(
            reverse("members:create_member"),
            {
                "first_name": "Reception",
                "last_name": "Created",
                "phone": "+243810000099",
                "email": "reception.created@example.com",
                "address": "Kinshasa",
            },
        )

        self.assertRedirects(create_response, reverse("members:member_list"), fetch_redirect_response=False)
        member = Member.objects.get(phone="+243810000099")
        self.assertEqual(member.gym, self.gym)

        edit_response = self.client.post(
            reverse("members:edit_member", args=[member.id]),
            {
                "first_name": "Reception",
                "last_name": "Updated",
                "phone": member.phone,
                "email": member.email,
                "address": "Gombe",
            },
        )

        self.assertEqual(edit_response.status_code, 200)
        member.refresh_from_db()
        self.assertEqual(member.last_name, "Updated")
        self.assertEqual(member.address, "Gombe")

    @override_settings(DEFAULT_FROM_EMAIL="noreply@smartclubpro.org")
    @patch("members.signals.generate_temporary_password", return_value="ManualTemp123!")
    def test_create_member_sends_credentials_email(self, _mock_password):
        self.client.force_login(self.reception)

        response = self.client.post(
            reverse("members:create_member"),
            {
                "first_name": "Mail",
                "last_name": "Target",
                "phone": "+243810000198",
                "email": "mail.target@example.com",
                "address": "Kinshasa",
            },
        )

        self.assertRedirects(response, reverse("members:member_list"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        member = Member.objects.get(phone="+243810000198")
        self.assertEqual(message.from_email, "Org Members <noreply@smartclubpro.org>")
        self.assertEqual(message.to, ["mail.target@example.com"])
        self.assertIn("Org Members - Vos coordonnees membre", message.subject)
        self.assertIn(member.user.username, message.body)
        self.assertIn("ManualTemp123!", message.body)
        self.assertIn("Kinshasa", message.body)

    @patch("members.views.generate_temporary_password", return_value="MemberTemp123!")
    def test_reception_can_reset_member_password_and_view_temporary_credentials(self, _mock_password):
        member = Member.objects.create(
            gym=self.gym,
            first_name="Reset",
            last_name="Target",
            phone="+243810000108",
            email="reset.target@example.com",
        )
        self.client.force_login(self.reception)

        response = self.client.post(
            reverse("members:reset_member_password", args=[member.id]),
            follow=True,
        )

        self.assertEqual(response.redirect_chain, [(reverse("members:member_list"), 302)])
        member.user.refresh_from_db()
        self.assertTrue(member.user.force_password_change)
        self.assertTrue(member.user.check_password("MemberTemp123!"))
        self.assertContains(response, "Nouveau mot de passe temporaire")
        self.assertContains(response, member.user.username)
        self.assertContains(response, "MemberTemp123!")

    def test_sensitive_member_actions_require_post(self):
        member = Member.objects.create(
            gym=self.gym,
            first_name="Post",
            last_name="Only",
            phone="+243810000111",
            email="post.only@example.com",
        )

        self.client.force_login(self.reception)
        reset_response = self.client.get(reverse("members:reset_member_password", args=[member.id]))
        self.assertEqual(reset_response.status_code, 405)

        self.client.force_login(self.manager)
        suspend_response = self.client.get(reverse("members:suspend_member", args=[member.id]))
        reactivate_response = self.client.get(reverse("members:reactivate_member", args=[member.id]))
        self.assertEqual(suspend_response.status_code, 405)
        self.assertEqual(reactivate_response.status_code, 405)

        self.client.force_login(self.owner)
        delete_response = self.client.get(reverse("members:delete_member", args=[member.id]))
        self.assertEqual(delete_response.status_code, 405)
        self.assertTrue(Member.objects.filter(id=member.id).exists())

    def test_only_owner_can_delete_member_and_action_is_logged(self):
        member = Member.objects.create(
            gym=self.gym,
            first_name="Delete",
            last_name="Target",
            phone="+243810000112",
            email="delete.target@example.com",
        )

        self.client.force_login(self.manager)
        denied_response = self.client.post(reverse("members:delete_member", args=[member.id]))
        self.assertEqual(denied_response.status_code, 403)
        self.assertTrue(Member.objects.filter(id=member.id).exists())
        self.assertFalse(SensitiveActivityLog.objects.filter(action="member.deleted").exists())

        self.client.force_login(self.owner)
        delete_response = self.client.post(reverse("members:delete_member", args=[member.id]))
        self.assertRedirects(delete_response, reverse("members:member_list"), fetch_redirect_response=False)
        self.assertFalse(Member.objects.filter(id=member.id).exists())

        log = SensitiveActivityLog.objects.get(action="member.deleted")
        self.assertEqual(log.organization, self.org)
        self.assertEqual(log.gym, self.gym)
        self.assertEqual(log.actor, self.owner)
        self.assertEqual(log.target_type, "Member")
        self.assertEqual(log.target_label, "Delete Target")
        self.assertEqual(log.metadata["member_id"], member.id)
        self.assertEqual(log.metadata["phone"], "+243810000112")
        self.assertEqual(log.metadata["email"], "delete.target@example.com")

    def test_managers_and_owners_can_regenerate_member_qr_and_action_is_logged(self):
        member = Member.objects.create(
            gym=self.gym,
            first_name="Qr",
            last_name="Target",
            phone="+243810000113",
            email="qr.target@example.com",
        )
        old_qr_code = str(member.qr_code)

        # La reception n'y a pas droit : regenerer invalide la carte imprimee.
        self.client.force_login(self.reception)
        denied_response = self.client.post(reverse("members:regenerate_member_qr", args=[member.id]))
        self.assertEqual(denied_response.status_code, 403)
        member.refresh_from_db()
        self.assertEqual(str(member.qr_code), old_qr_code)

        self.client.force_login(self.owner)
        response = self.client.post(reverse("members:regenerate_member_qr", args=[member.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        member.refresh_from_db()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["qr_code"], str(member.qr_code))
        self.assertNotEqual(str(member.qr_code), old_qr_code)
        self.assertGreater(member.qr_code_expires_at, timezone.now())

        log = SensitiveActivityLog.objects.get(action="member.qr_regenerated")
        self.assertEqual(log.actor, self.owner)
        self.assertEqual(log.gym, self.gym)
        self.assertEqual(log.metadata["previous_qr_code"], old_qr_code)
        self.assertEqual(log.metadata["new_qr_code"], str(member.qr_code))

    def test_cashier_cannot_reset_member_password(self):
        member = Member.objects.create(
            gym=self.gym,
            first_name="Denied",
            last_name="Reset",
            phone="+243810000110",
            email="denied.reset@example.com",
        )
        member.user.set_password("InitialMember123!")
        member.user.force_password_change = False
        member.user.save(update_fields=["password", "force_password_change"])
        self.client.force_login(self.cashier)

        response = self.client.post(reverse("members:reset_member_password", args=[member.id]))

        self.assertEqual(response.status_code, 403)
        member.user.refresh_from_db()
        self.assertFalse(member.user.force_password_change)
        self.assertTrue(member.user.check_password("InitialMember123!"))

    def test_owner_and_manager_can_suspend_and_reactivate_member(self):
        member = Member.objects.create(
            gym=self.gym,
            first_name="Status",
            last_name="Target",
            phone="+243810000109",
            email="status.target@example.com",
        )
        plan = SubscriptionPlan.objects.create(
            gym=self.gym,
            name="Mensuel permission",
            duration_days=30,
            price=20,
        )
        MemberSubscription.objects.create(
            gym=self.gym,
            member=member,
            plan=plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )

        for user in [self.reception, self.cashier]:
            self.client.force_login(user)
            response = self.client.post(reverse("members:suspend_member", args=[member.id]))
            self.assertEqual(response.status_code, 403)

        self.client.force_login(self.owner)
        owner_suspend_response = self.client.post(reverse("members:suspend_member", args=[member.id]))
        self.assertRedirects(owner_suspend_response, reverse("members:member_list"), fetch_redirect_response=False)
        member.refresh_from_db()
        self.assertEqual(member.status, "suspended")

        owner_reactivate_response = self.client.post(reverse("members:reactivate_member", args=[member.id]))
        self.assertRedirects(owner_reactivate_response, reverse("members:member_list"), fetch_redirect_response=False)
        member.refresh_from_db()
        self.assertEqual(member.status, "active")

        self.client.force_login(self.manager)
        suspend_response = self.client.post(reverse("members:suspend_member", args=[member.id]))
        self.assertRedirects(suspend_response, reverse("members:member_list"), fetch_redirect_response=False)
        member.refresh_from_db()
        self.assertEqual(member.status, "suspended")

        self.client.force_login(self.reception)
        denied_reactivate = self.client.post(reverse("members:reactivate_member", args=[member.id]))
        self.assertEqual(denied_reactivate.status_code, 403)

        self.client.force_login(self.manager)
        reactivate_response = self.client.post(reverse("members:reactivate_member", args=[member.id]))
        self.assertRedirects(reactivate_response, reverse("members:member_list"), fetch_redirect_response=False)
        member.refresh_from_db()
        self.assertEqual(member.status, "active")

    def test_member_list_masks_write_and_status_actions_by_role(self):
        sample_member = Member.objects.create(
            gym=self.gym,
            first_name="Ui",
            last_name="Sample",
            phone="+243810000119",
            email="ui.sample@example.com",
        )

        self.client.force_login(self.reception)
        reception_response = self.client.get(reverse("members:member_list"))
        self.assertContains(reception_response, "Nouveau Membre")
        self.assertContains(reception_response, "openEditMemberModal(")
        self.assertNotContains(reception_response, 'id="statusToggleBtn"', html=False)
        self.assertNotContains(reception_response, f'id="delete-form-{sample_member.id}"', html=False)

        self.client.force_login(self.manager)
        manager_response = self.client.get(reverse("members:member_list"))
        self.assertContains(manager_response, 'id="statusToggleBtn"', html=False)
        self.assertNotContains(manager_response, f'id="delete-form-{sample_member.id}"', html=False)

        self.client.force_login(self.owner)
        owner_response = self.client.get(reverse("members:member_list"))
        self.assertContains(owner_response, 'id="statusToggleBtn"', html=False)
        self.assertContains(owner_response, f'id="delete-form-{sample_member.id}"', html=False)
        self.assertContains(owner_response, '<img id="memberCardPreview"', html=False)
        self.assertNotContains(owner_response, '<canvas id="memberCardPreview"', html=False)
        self.assertContains(owner_response, "function setMemberDetailStatus", html=False)
        self.assertContains(owner_response, "badge-actif", html=False)
        self.assertContains(owner_response, "badge-suspendu", html=False)
        self.assertContains(owner_response, "badge-expire", html=False)

    def test_member_photo_upload_rejects_non_image_file(self):
        uploaded = SimpleUploadedFile(
            "payload.txt",
            b"<script>alert(1)</script>",
            content_type="text/plain",
        )
        form = MemberCreationForm(
            data={
                "first_name": "Bad",
                "last_name": "Upload",
                "phone": "+243810000120",
                "email": "bad.upload@example.com",
                "address": "Kinshasa",
            },
            files={"photo": uploaded},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("photo", form.errors)

    @override_settings(DEFAULT_FROM_EMAIL="noreply@smartclubpro.org")
    def test_public_pre_registration_creates_pending_request_and_sends_received_email(self):
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
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.from_email, "Org Members <noreply@smartclubpro.org>")
        self.assertEqual(message.to, ["alice.visitor@example.com"])
        self.assertIn("Org Members - Preinscription recue", message.subject)
        self.assertIn("Votre preinscription chez Org Members a bien ete recue", message.body)
        self.assertIn("Salle de sport : Org Members - Main Gym", message.body)
        self.assertIn("Passez a la salle", message.body)

    def test_public_pre_registration_requires_phone_and_email(self):
        link = MemberPreRegistrationLink.objects.get(gym=self.gym)

        response = self.client.post(
            reverse("members:public_pre_registration", args=[link.token]),
            {
                "first_name": "No",
                "last_name": "Contact",
                "phone": "",
                "email": "",
                "address": "Kinshasa",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(MemberPreRegistration.objects.filter(first_name="No").exists())
        self.assertFormError(response.context["form"], "phone", "Ce champ est obligatoire.")
        self.assertFormError(response.context["form"], "email", "Ce champ est obligatoire.")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(DEFAULT_FROM_EMAIL="noreply@smartclubpro.org")
    @patch("members.signals.generate_temporary_password", return_value="TempPass123!")
    def test_confirm_pre_registration_creates_member_and_default_user(self, _mock_password):
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
        self.assertTrue(member.user.check_password("TempPass123!"))
        self.assertTrue(member.user.force_password_change)
        self.assertFalse(UserGymRole.objects.filter(user=member.user, gym=self.gym, is_active=True).exists())
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.from_email, "Org Members <noreply@smartclubpro.org>")
        self.assertEqual(message.to, ["bob.ready@example.com"])
        self.assertIn("Org Members - Vos coordonnees membre", message.subject)
        self.assertIn(member.user.username, message.body)
        self.assertIn("TempPass123!", message.body)
        self.assertIn("Vous devrez changer ce mot de passe", message.body)
        self.assertIn("Votre carte membre est jointe", message.body)
        self.assertTrue(message.alternatives)
        self.assertIn("Votre carte membre est jointe", message.alternatives[0][0])
        self.assertEqual(message.extra_headers["Auto-Submitted"], "auto-generated")
        self.assertEqual(message.extra_headers["X-Auto-Response-Suppress"], "All")
        self.assertEqual(len(message.attachments), 1)
        attachment_name, attachment_content, attachment_type = message.attachments[0]
        self.assertTrue(attachment_name.startswith("carte_membre_bob-ready"))
        self.assertEqual(attachment_type, "image/png")
        self.assertTrue(attachment_content.startswith(b"\x89PNG"))
        from members.card_images import render_member_card_png

        self.assertEqual(attachment_content, render_member_card_png(member))

        card_response = self.client.get(reverse("members:member_card_image", args=[member.id]))
        self.assertEqual(card_response.status_code, 200)
        self.assertEqual(card_response.content, attachment_content)

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

    def test_expired_pending_pre_registrations_are_marked_by_command(self):
        """Elles sont conservees pour le suivi commercial, plus supprimees."""
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

        expired.refresh_from_db()
        confirmed.refresh_from_db()
        self.assertEqual(expired.status, MemberPreRegistration.STATUS_EXPIRED)
        self.assertEqual(confirmed.status, MemberPreRegistration.STATUS_CONFIRMED)
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
        self.member.user.set_password("MemberPortal123!")
        self.member.user.force_password_change = False
        self.member.user.save(update_fields=["password", "force_password_change"])
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym,
            name="Mensuel",
            duration_days=30,
            price=35,
            coaching_mode=SubscriptionPlan.COACHING_MODE_BOTH,
            coaching_level=SubscriptionPlan.COACHING_LEVEL_PREMIUM,
        )
        self.year_plan = SubscriptionPlan.objects.create(
            gym=self.gym,
            name="Annuel",
            duration_days=365,
            price=320,
            coaching_mode=SubscriptionPlan.COACHING_MODE_GROUP,
            coaching_level=SubscriptionPlan.COACHING_LEVEL_STANDARD,
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
        self.second_coach = Coach.objects.create(
            gym=self.gym,
            name="Coach Balance",
            phone="+243990000102",
            specialty="Cardio",
        )
        self.group_program = GroupCoachingProgram.objects.create(
            gym=self.gym,
            coach=self.coach,
            name="Transformation 8 semaines",
            objective="Perte de poids",
            description="Accompagnement collectif progressif",
            capacity=10,
        )

    def test_member_login_redirects_to_mobile_portal(self):
        response = self.client.post(
            reverse("compte:login"),
            {
                "username": self.member.user.username,
                "password": "MemberPortal123!",
            },
        )

        self.assertRedirects(
            response,
            reverse("compte:welcome"),
            fetch_redirect_response=False,
        )

    def test_member_portal_shows_identity_card_and_subscription(self):
        offer = SubscriptionOffer.objects.create(
            gym=self.gym,
            name="Acces coach premium",
            category=SubscriptionOffer.CATEGORY_COACHING,
            grants_individual_coaching=True,
        )
        self.plan.offers.add(offer)
        self.client.force_login(self.member.user)

        response = self.client.get(reverse("members:member_portal"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Carte membre")
        self.assertContains(response, "Mon accompagnement")
        self.assertContains(response, "Coaching individuel et groupe")
        self.assertContains(response, "Premium")
        self.assertContains(response, "Derniers acces")
        self.assertContains(response, "Mot de passe")
        self.assertContains(response, f"MEM-{self.member.id:05d}")
        self.assertContains(response, self.member.user.username)
        self.assertContains(response, reverse("members:member_portal_qr"))
        self.assertContains(response, f"{reverse('members:member_portal')}?tab=password")
        self.assertNotContains(response, "Changer mon mot de passe")
        self.assertNotContains(response, "Mon objectif poids")
        self.assertNotContains(response, "Actions rapides")
        self.assertNotContains(response, "Imprimer carte")
        self.assertNotContains(response, "window.print")

        goal_response = self.client.get(reverse("members:member_portal"), {"tab": "goal"})
        self.assertContains(goal_response, "Mon objectif poids")

        password_response = self.client.get(reverse("members:member_portal"), {"tab": "password"})
        self.assertContains(password_response, "Changer mon mot de passe")

        subscription_response = self.client.get(reverse("members:member_portal"), {"tab": "subscription"})
        self.assertContains(subscription_response, "Carte membre")
        self.assertContains(subscription_response, "Premium")
        self.assertNotContains(subscription_response, "Dernieres operations")
        self.assertNotContains(subscription_response, "?tab=subscription")

        plans_response = self.client.get(reverse("members:member_portal"), {"tab": "plans"})
        self.assertContains(plans_response, "Choisir un abonnement")
        self.assertContains(plans_response, "Annuel")
        self.assertContains(plans_response, "Acces coach premium")

    def test_member_portal_hides_future_subscription_from_home_overview(self):
        self.subscription.is_active = False
        self.subscription.save(update_fields=["is_active"])
        today = timezone.now().date()
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=33),
            is_active=True,
        )
        self.client.force_login(self.member.user)

        response = self.client.get(reverse("members:member_portal"))

        self.assertContains(response, "Abonnement")
        self.assertNotContains(response, "<dd>Mensuel</dd>", html=False)
        self.assertNotContains(response, "Dernieres operations")

    def test_member_computed_status_is_expired_when_only_paused_subscription_exists(self):
        self.subscription.is_paused = True
        self.subscription.paused_at = timezone.now()
        self.subscription.save(update_fields=["is_paused", "paused_at"])

        self.member.refresh_from_db()
        self.assertEqual(self.member.computed_status, "expired")
        self.assertIsNone(self.member.active_subscription)

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
        self.assertContains(response, "Voir")
        self.assertNotContains(response, "Marquer comme lu")

        response = self.client.post(
            reverse("members:member_notification_read", args=[notification.id])
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{reverse('members:member_portal')}?tab=messages&message={notification.id}",
        )
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

    def test_member_can_create_weight_goal_with_member_starter(self):
        self.client.force_login(self.member.user)

        response = self.client.post(
            reverse("members:member_goal_create"),
            {
                "goal_type": MemberGoal.GOAL_GAIN_WEIGHT,
                "target_weight": "78.5",
                "target_date": (timezone.localdate() + timedelta(days=90)).isoformat(),
                "measurement_starter": MemberGoal.STARTER_MEMBER,
                "note": "Prise de masse progressive",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('members:member_portal')}?tab=goal")
        goal = MemberGoal.objects.get(member=self.member, status=MemberGoal.STATUS_ACTIVE)
        self.assertEqual(goal.gym, self.gym)
        self.assertEqual(goal.goal_type, MemberGoal.GOAL_GAIN_WEIGHT)
        self.assertEqual(goal.measurement_starter, MemberGoal.STARTER_MEMBER)
        self.assertEqual(goal.created_by, self.member.user)

    def test_member_can_record_first_weight_when_member_starts_goal(self):
        goal = MemberGoal.objects.create(
            gym=self.gym,
            member=self.member,
            goal_type=MemberGoal.GOAL_LOSE_WEIGHT,
            target_weight="68.0",
            measurement_starter=MemberGoal.STARTER_MEMBER,
            created_by=self.member.user,
        )
        self.client.force_login(self.member.user)

        response = self.client.post(
            reverse("members:member_goal_measurement_create"),
            {
                "weight": "74.2",
                "measured_at": timezone.localdate().isoformat(),
                "note": "Premiere pesee",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('members:member_portal')}?tab=goal")
        measurement = MemberWeightMeasurement.objects.get(goal=goal)
        self.assertEqual(measurement.member, self.member)
        self.assertEqual(measurement.source, MemberWeightMeasurement.SOURCE_MEMBER)
        self.assertEqual(measurement.recorded_by, self.member.user)

    def test_member_cannot_record_first_weight_when_coach_must_start_goal(self):
        goal = MemberGoal.objects.create(
            gym=self.gym,
            member=self.member,
            goal_type=MemberGoal.GOAL_LOSE_WEIGHT,
            target_weight="67.0",
            measurement_starter=MemberGoal.STARTER_COACH,
            created_by=self.member.user,
        )
        self.client.force_login(self.member.user)

        response = self.client.post(
            reverse("members:member_goal_measurement_create"),
            {
                "weight": "73.8",
                "measured_at": timezone.localdate().isoformat(),
                "note": "Tentative membre",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La premiere pesee doit etre enregistree par le coach.")
        self.assertFalse(MemberWeightMeasurement.objects.filter(goal=goal).exists())

    def test_member_portal_shows_waiting_message_when_coach_must_start_goal(self):
        MemberGoal.objects.create(
            gym=self.gym,
            member=self.member,
            goal_type=MemberGoal.GOAL_LOSE_WEIGHT,
            target_weight="67.0",
            measurement_starter=MemberGoal.STARTER_COACH,
            created_by=self.member.user,
        )
        self.client.force_login(self.member.user)

        response = self.client.get(reverse("members:member_portal"), {"tab": "goal"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Le coach doit lancer la premiere pesee")

    def test_member_detail_json_exposes_subscription_offers(self):
        offer = SubscriptionOffer.objects.create(
            gym=self.gym,
            name="Acces groupe coaching",
            category=SubscriptionOffer.CATEGORY_COACHING,
            grants_group_coaching=True,
        )
        self.plan.offers.add(offer)
        reception_user = User.objects.create_user(username="reception-portal", password="pass12345")
        UserGymRole.objects.create(user=reception_user, gym=self.gym, role="reception", is_active=True)
        self.client.force_login(reception_user)

        response = self.client.get(reverse("members:member_detail", args=[self.member.id]))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("subscription_offers", data)
        self.assertEqual(data["subscription_offers"], ["Acces groupe coaching"])
        self.assertEqual(data["card_image_url"], reverse("members:member_card_image", args=[self.member.id]))

    def test_member_detail_json_converts_unexpected_model_values(self):
        reception_user = User.objects.create_user(username="reception-safe-json", password="pass12345")
        UserGymRole.objects.create(user=reception_user, gym=self.gym, role="reception", is_active=True)
        self.client.force_login(reception_user)

        with patch.object(Member, "subscription_type", new_callable=PropertyMock) as mocked_subscription_type:
            mocked_subscription_type.return_value = self.gym
            response = self.client.get(reverse("members:member_detail", args=[self.member.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["subscription_type"], str(self.gym))

    @override_settings(
        STORAGES={
            "default": {
                "BACKEND": "django.core.files.storage.InMemoryStorage",
            },
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
            },
        }
    )
    def test_member_detail_uses_same_origin_organization_logo_for_card(self):
        logo_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02"
            b"\xfeA\x0f\xb4\x16\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        self.organization.logo.save(
            "card-logo.png",
            SimpleUploadedFile("card-logo.png", logo_bytes, content_type="image/png"),
            save=True,
        )
        reception_user = User.objects.create_user(username="reception-card", password="pass12345")
        UserGymRole.objects.create(user=reception_user, gym=self.gym, role="reception", is_active=True)
        self.client.force_login(reception_user)

        response = self.client.get(reverse("members:member_detail", args=[self.member.id]))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["organization_logo_url"], reverse("members:organization_logo"))
        self.assertEqual(data["card_image_url"], reverse("members:member_card_image", args=[self.member.id]))

        logo_response = self.client.get(reverse("members:organization_logo"))

        self.assertEqual(logo_response.status_code, 200)
        self.assertEqual(logo_response["Content-Type"], "image/png")
        self.assertTrue(b"".join(logo_response.streaming_content).startswith(b"\x89PNG"))

        card_response = self.client.get(data["card_image_url"])
        self.assertEqual(card_response.status_code, 200)
        self.assertEqual(card_response["Content-Type"], "image/png")
        self.assertEqual(card_response["Cache-Control"], "private, no-store")
        self.assertTrue(card_response.content.startswith(b"\x89PNG"))

        from members.card_images import render_member_card_png

        member = Member.objects.select_related("gym__organization", "user").get(id=self.member.id)
        self.assertEqual(card_response.content, render_member_card_png(member))

    def test_member_offer_only_plan_unlocks_coach_and_group_choices(self):
        offer_plan = SubscriptionPlan.objects.create(
            gym=self.gym,
            name="Pack offres complet",
            duration_days=45,
            price=90,
            coaching_mode=SubscriptionPlan.COACHING_MODE_NONE,
            coaching_level=SubscriptionPlan.COACHING_LEVEL_STANDARD,
        )
        offer_plan.offers.add(
            SubscriptionOffer.objects.create(
                gym=self.gym,
                name="Acces coach individuel",
                category=SubscriptionOffer.CATEGORY_COACHING,
                grants_individual_coaching=True,
            ),
            SubscriptionOffer.objects.create(
                gym=self.gym,
                name="Acces coaching groupe",
                category=SubscriptionOffer.CATEGORY_COACHING,
                grants_group_coaching=True,
            ),
        )
        self.subscription.is_active = False
        self.subscription.save(update_fields=["is_active"])
        today = timezone.localdate()
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=offer_plan,
            start_date=today,
            end_date=today + timedelta(days=45),
            is_active=True,
        )
        self.client.force_login(self.member.user)

        response = self.client.get(reverse("members:member_portal"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choisir mon coach")
        self.assertContains(response, "Rejoindre un programme groupe")

    def test_member_portal_hides_unsent_notifications(self):
        Notification.objects.create(
            gym=self.gym,
            member=self.member,
            title="Visible",
            message="Message envoye.",
            channel=Notification.CHANNEL_IN_APP,
            status=Notification.STATUS_SENT,
            sent_at=timezone.now(),
        )
        Notification.objects.create(
            gym=self.gym,
            member=self.member,
            title="Cache",
            message="Message non envoye.",
            channel=Notification.CHANNEL_IN_APP,
            status=Notification.STATUS_PENDING,
        )
        self.client.force_login(self.member.user)

        response = self.client.get(reverse("members:member_portal"), {"tab": "messages"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visible")
        self.assertNotContains(response, "Cache")
        self.assertEqual(response.context["unread_notification_count"], 1)

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

    def test_member_plans_tab_shows_best_selling_plan_first(self):
        second_member = Member.objects.create(
            gym=self.gym,
            first_name="Lina",
            last_name="Choice",
            phone="+243810000102",
            email="lina.choice@example.com",
        )
        today = timezone.now().date()
        MemberSubscription.objects.create(
            gym=self.gym,
            member=second_member,
            plan=self.year_plan,
            start_date=today,
            end_date=today + timedelta(days=365),
            is_active=True,
        )
        MemberSubscription.objects.create(
            gym=self.gym,
            member=second_member,
            plan=self.year_plan,
            start_date=today - timedelta(days=400),
            end_date=today - timedelta(days=35),
            is_active=False,
        )

        self.client.force_login(self.member.user)

        response = self.client.get(reverse("members:member_portal"), {"tab": "plans"})

        self.assertEqual(response.status_code, 200)
        plans = list(response.context["available_plans"])
        self.assertEqual(plans[0].id, self.year_plan.id)
        self.assertEqual(response.context["top_plan_sales_count"], 2)
        self.assertContains(response, "La plus choisie")

    def test_member_portal_messages_tab_shows_unread_badge_and_compact_sections(self):
        unread_body = "Premier message important " + ("details " * 20) + "FIN_CACHEE_NON_LUE"
        read_body = "Second message deja lu " + ("contenu " * 20) + "FIN_CACHEE_LUE"
        Notification.objects.create(
            gym=self.gym,
            member=self.member,
            title="Info 1",
            message=unread_body,
            channel=Notification.CHANNEL_IN_APP,
            status=Notification.STATUS_SENT,
            sent_at=timezone.now(),
        )
        read_notification = Notification.objects.create(
            gym=self.gym,
            member=self.member,
            title="Info 2",
            message=read_body,
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
        self.assertContains(response, "Voir")
        self.assertNotContains(response, "Marquer comme lu")
        self.assertNotContains(response, "FIN_CACHEE_NON_LUE")
        self.assertNotContains(response, "FIN_CACHEE_LUE")

        response = self.client.get(
            reverse("members:member_portal"),
            {"tab": "messages", "message": read_notification.id},
        )

        self.assertContains(response, "FIN_CACHEE_LUE")

    def test_member_can_change_password_from_portal(self):
        self.client.force_login(self.member.user)

        response = self.client.post(
            reverse("members:member_change_password"),
            {
                "old_password": "MemberPortal123!",
                "new_password1": "NouveauPass123!",
                "new_password2": "NouveauPass123!",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('members:member_portal')}?tab=password")
        self.member.user.refresh_from_db()
        self.assertTrue(self.member.user.check_password("NouveauPass123!"))

        self.client.logout()
        login_response = self.client.post(
            reverse("compte:login"),
            {
                "username": self.member.user.username,
                "password": "NouveauPass123!",
            },
        )
        self.assertRedirects(
            login_response,
            reverse("compte:welcome"),
            fetch_redirect_response=False,
        )

    def test_member_can_choose_a_new_coach_from_portal(self):
        self.client.force_login(self.member.user)

        response = self.client.post(
            reverse("members:member_choose_coach"),
            {"coach_id": self.second_coach.id},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('members:member_portal')}?tab=home")
        self.assertTrue(self.second_coach.members.filter(id=self.member.id).exists())
        self.assertFalse(self.coach.members.filter(id=self.member.id).exists())
        self.assertTrue(
            CoachAssignment.objects.filter(
                coach=self.second_coach,
                member=self.member,
                ended_at__isnull=True,
            ).exists()
        )

    def test_member_can_join_group_program_from_portal(self):
        self.client.force_login(self.member.user)

        response = self.client.post(
            reverse("members:member_choose_group_program"),
            {"program_id": self.group_program.id},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('members:member_portal')}?tab=home")
        self.assertTrue(self.group_program.participants.filter(id=self.member.id).exists())

        home_response = self.client.get(reverse("members:member_portal"))
        self.assertContains(home_response, "Transformation 8 semaines")
        self.assertContains(home_response, "Rejoindre un programme groupe")

    def test_member_can_submit_feedback_for_current_coach(self):
        self.client.force_login(self.member.user)

        response = self.client.post(
            reverse("members:member_submit_coaching_feedback"),
            {
                "feedback_kind": "coach",
                "coach_id": self.coach.id,
                "coach-feedback-overall_rating": "5",
                "coach-feedback-listening_rating": "5",
                "coach-feedback-clarity_rating": "4",
                "coach-feedback-motivation_rating": "5",
                "coach-feedback-availability_rating": "4",
                "coach-feedback-comment": "Coach tres implique et rassurant.",
                "coach-feedback-wants_contact": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('members:member_portal')}?tab=home")
        feedback = CoachingFeedback.objects.get(member=self.member, coach=self.coach, group_program__isnull=True)
        self.assertEqual(feedback.overall_rating, 5)
        self.assertTrue(feedback.wants_contact)

    def test_member_can_submit_feedback_for_current_group_program(self):
        self.group_program.participants.add(self.member)
        self.client.force_login(self.member.user)

        response = self.client.post(
            reverse("members:member_submit_coaching_feedback"),
            {
                "feedback_kind": "group_program",
                "coach_id": self.coach.id,
                "program_id": self.group_program.id,
                "group-feedback-overall_rating": "4",
                "group-feedback-listening_rating": "4",
                "group-feedback-clarity_rating": "4",
                "group-feedback-motivation_rating": "5",
                "group-feedback-availability_rating": "4",
                "group-feedback-comment": "Le format groupe motive beaucoup.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('members:member_portal')}?tab=home")
        feedback = CoachingFeedback.objects.get(member=self.member, group_program=self.group_program)
        self.assertEqual(feedback.coach, self.coach)

    def test_member_cannot_submit_individual_feedback_without_current_individual_rights(self):
        self.subscription.plan = self.year_plan
        self.subscription.save(update_fields=["plan"])
        self.client.force_login(self.member.user)

        response = self.client.post(
            reverse("members:member_submit_coaching_feedback"),
            {
                "feedback_kind": "coach",
                "coach_id": self.coach.id,
                "coach-feedback-overall_rating": "5",
                "coach-feedback-listening_rating": "5",
                "coach-feedback-clarity_rating": "4",
                "coach-feedback-motivation_rating": "5",
                "coach-feedback-availability_rating": "4",
                "coach-feedback-comment": "Tentative sans droit individuel.",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ne permet pas de laisser un avis coaching individuel")
        self.assertFalse(
            CoachingFeedback.objects.filter(
                member=self.member,
                coach=self.coach,
                comment__icontains="Tentative sans droit individuel",
            ).exists()
        )

    def test_member_portal_qr_is_limited_to_authenticated_member(self):
        anonymous_response = self.client.get(reverse("members:member_portal_qr"))
        self.assertEqual(anonymous_response.status_code, 302)

        self.client.force_login(self.member.user)
        response = self.client.get(reverse("members:member_portal_qr"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    def test_member_portal_qr_never_rotates_the_printed_code(self):
        """Le QR est imprime sur la carte : le consulter ne doit pas le changer."""
        old_qr_code = str(self.member.qr_code)
        self.member.qr_code_expires_at = timezone.now() - timedelta(minutes=1)
        self.member.save(update_fields=["qr_code_expires_at"])
        self.client.force_login(self.member.user)

        response = self.client.get(reverse("members:member_portal_qr"))

        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertEqual(str(self.member.qr_code), old_qr_code)

    def test_member_api_payload_never_rotates_the_printed_code(self):
        old_qr_code = str(self.member.qr_code)
        self.member.qr_code_expires_at = timezone.now() - timedelta(minutes=1)
        self.member.save(update_fields=["qr_code_expires_at"])

        response = self.client.post(
            reverse("members:member_api_login"),
            data=json.dumps(
                {
                    "username": self.member.user.username,
                    "password": "MemberPortal123!",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        payload = response.json()
        self.assertEqual(str(self.member.qr_code), old_qr_code)
        self.assertEqual(payload["data"]["member"]["qr_data"], old_qr_code)

    def test_rotate_member_qrcodes_command_rotates_expired_members(self):
        old_qr_code = str(self.member.qr_code)
        self.member.qr_code_expires_at = timezone.now() - timedelta(minutes=1)
        self.member.save(update_fields=["qr_code_expires_at"])

        output = StringIO()
        call_command("rotate_member_qrcodes", stdout=output)

        self.member.refresh_from_db()
        self.assertNotEqual(str(self.member.qr_code), old_qr_code)
        self.assertGreater(self.member.qr_code_expires_at, timezone.now())
        self.assertIn("1 QR code", output.getvalue())

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

    @override_settings(
        STORAGES={
            "default": {
                "BACKEND": "django.core.files.storage.InMemoryStorage",
            },
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
            },
        }
    )
    def test_pwa_manifest_uses_authenticated_member_organization_logo(self):
        logo_file = BytesIO()
        Image.new("RGBA", (32, 32), (220, 38, 38, 255)).save(logo_file, format="PNG")
        self.organization.logo.save(
            "portal-org.png",
            SimpleUploadedFile("portal-org.png", logo_file.getvalue(), content_type="image/png"),
            save=True,
        )
        self.client.force_login(self.member.user)

        expected_icon_192 = reverse("members:member_app_organization_icon", args=[self.organization.id, 192])
        expected_icon_512 = reverse("members:member_app_organization_icon", args=[self.organization.id, 512])
        manifest_response = self.client.get(reverse("members:member_app_manifest"))
        portal_response = self.client.get(reverse("members:member_portal"))
        icon_response = self.client.get(expected_icon_512)

        self.assertEqual(manifest_response.status_code, 200)
        manifest = manifest_response.json()
        self.assertEqual(manifest["name"], "Portal Org Membre")
        self.assertEqual(manifest["short_name"], "Portal Org")
        self.assertEqual(manifest_response["Cache-Control"], "private, no-store")
        self.assertEqual(manifest["icons"][0]["src"], expected_icon_192)
        self.assertEqual(manifest["icons"][1]["src"], expected_icon_512)
        self.assertEqual(manifest["icons"][2]["src"], expected_icon_512)
        self.assertEqual(manifest["icons"][0]["purpose"], "any")
        self.assertEqual(icon_response.status_code, 200)
        self.assertEqual(icon_response["Content-Type"], "image/png")
        self.assertTrue(icon_response.content.startswith(b"\x89PNG"))
        self.assertEqual(icon_response["Cache-Control"], "public, max-age=3600")
        self.assertContains(portal_response, f'rel="apple-touch-icon" href="{expected_icon_512}"')

    def test_pwa_manifest_keeps_the_gym_brand_without_session_cookie(self):
        # Le navigateur telecharge le manifeste hors session : sans repli sur
        # l'organisation passee en parametre, l'application installee
        # s'appellerait "SmartClub" au lieu du nom de la salle.
        self.client.force_login(self.member.user)
        portal_response = self.client.get(reverse("members:member_portal"))
        self.assertContains(
            portal_response,
            f'href="{reverse("members:member_app_manifest")}?org={self.organization.id}"',
        )
        self.assertContains(portal_response, 'crossorigin="use-credentials"')

        self.client.logout()
        anonyme = self.client.get(
            reverse("members:member_app_manifest"), {"org": self.organization.id}
        )

        self.assertEqual(anonyme.status_code, 200)
        self.assertEqual(anonyme.json()["name"], "Portal Org Membre")

    def test_pwa_manifest_falls_back_when_the_organization_is_unknown(self):
        anonyme = self.client.get(
            reverse("members:member_app_manifest"), {"org": "n-importe-quoi"}
        )

        self.assertEqual(anonyme.status_code, 200)
        self.assertEqual(anonyme.json()["name"], "SmartClub Membre")

    def test_member_api_login_and_me_payload(self):
        AccessLog.objects.create(gym=self.gym, member=self.member, access_granted=True)

        response = self.client.post(
            reverse("members:member_api_login"),
            data=json.dumps(
                {
                    "username": self.member.user.username,
                    "password": "MemberPortal123!",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["force_password_change"])
        self.assertEqual(payload["data"]["member"]["qr_data"], str(self.member.qr_code))
        self.assertEqual(payload["data"]["member"]["code"], f"MEM-{self.member.id:05d}")
        self.assertEqual(payload["data"]["subscription"]["plan"]["name"], "Mensuel")
        self.assertEqual(payload["data"]["access"]["granted_count"], 1)
        self.assertIn("plans", payload["data"])

        me_response = self.client.get(reverse("members:member_api_me"))

        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["data"]["member"]["username"], self.member.user.username)

    def test_member_api_rejects_non_member_account(self):
        staff_user = User.objects.create_user(username="staff-api", password="pass12345")

        response = self.client.post(
            reverse("members:member_api_login"),
            data=json.dumps({"username": staff_user.username, "password": "pass12345"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["ok"])

    def test_member_api_me_scopes_to_current_member_gym(self):
        other_org = Organization.objects.create(name="Other Portal Org", slug="other-portal-org")
        other_gym = Gym.objects.create(
            organization=other_org,
            name="Other Portal Gym",
            slug="other-portal-gym",
            subdomain="other-portal-gym",
        )
        other_plan = SubscriptionPlan.objects.create(
            gym=other_gym,
            name="Plan autre gym",
            duration_days=90,
            price=100,
        )
        other_member = Member.objects.create(
            gym=other_gym,
            first_name="Other",
            last_name="Member",
            phone="+243810099999",
            email="other.member@example.com",
        )
        Notification.objects.create(
            gym=other_gym,
            member=other_member,
            title="Message autre gym",
            message="Invisible depuis le membre courant",
            channel=Notification.CHANNEL_IN_APP,
            status=Notification.STATUS_SENT,
            sent_at=timezone.now(),
        )
        self.client.force_login(self.member.user)

        response = self.client.get(reverse("members:member_api_me"))

        self.assertEqual(response.status_code, 200)
        encoded_payload = json.dumps(response.json()["data"])
        self.assertNotIn(other_plan.name, encoded_payload)
        self.assertNotIn("Message autre gym", encoded_payload)

    def test_member_api_actions_update_existing_portal_models(self):
        notification = Notification.objects.create(
            gym=self.gym,
            member=self.member,
            title="Action API",
            message="Lecture depuis mobile",
            channel=Notification.CHANNEL_IN_APP,
            status=Notification.STATUS_SENT,
            sent_at=timezone.now(),
        )
        self.client.force_login(self.member.user)

        subscription_response = self.client.post(
            reverse("members:member_api_subscription_request"),
            data=json.dumps({"plan_id": self.year_plan.id}),
            content_type="application/json",
        )
        read_response = self.client.post(
            reverse("members:member_api_notification_read", args=[notification.id]),
            data=json.dumps({}),
            content_type="application/json",
        )
        coach_response = self.client.post(
            reverse("members:member_api_choose_coach"),
            data=json.dumps({"coach_id": self.second_coach.id}),
            content_type="application/json",
        )

        self.assertIn(subscription_response.status_code, [200, 201])
        self.assertEqual(read_response.status_code, 200)
        self.assertEqual(coach_response.status_code, 200)
        self.assertTrue(SubscriptionRequest.objects.filter(member=self.member, plan=self.year_plan).exists())
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)
        self.assertTrue(self.second_coach.members.filter(id=self.member.id).exists())


class PreRegistrationLinkHardeningTests(TestCase):
    """Lien public : domaine partageable, revocation, protection anti-robot."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Org Lien", slug="org-lien")
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Lien",
            slug="gym-lien",
            subdomain="gym-lien",
        )
        self.owner = User.objects.create_user(
            username="owner-lien",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.reception = User.objects.create_user(
            username="reception-lien",
            password="pass12345",
        )
        UserGymRole.objects.create(
            user=self.reception, gym=self.gym, role="reception", is_active=True
        )

    def _link(self):
        return MemberPreRegistrationLink.objects.get(gym=self.gym)

    def _public_path(self, token):
        return reverse("members:public_pre_registration", args=[token])

    def _form_data(self, index=1, **overrides):
        data = {
            "first_name": f"Prospect{index}",
            "last_name": "Lien",
            "phone": f"+2438100001{index:02d}",
            "email": f"prospect{index}.lien@example.com",
            "address": "Kinshasa",
        }
        data.update(overrides)
        return data

    # --- 1. Domaine des liens partages ------------------------------------

    @override_settings(PUBLIC_BASE_URL="https://royalgym-fitness.com")
    def test_link_uses_public_domain_not_browsing_address(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("members:pre_registration_list"))

        url = response.context["pre_registration_url"]
        self.assertTrue(url.startswith("https://royalgym-fitness.com/"))
        self.assertFalse(response.context["pre_registration_url_is_local"])

    @override_settings(PUBLIC_BASE_URL="", CANONICAL_HOST="")
    def test_local_link_is_flagged_to_the_user(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("members:pre_registration_list"))

        self.assertTrue(response.context["pre_registration_url_is_local"])

    # --- 2. Revocation du lien --------------------------------------------

    def test_regenerating_the_link_breaks_the_previous_one(self):
        self.client.force_login(self.owner)
        self.client.get(reverse("members:pre_registration_list"))
        previous_token = self._link().token

        self.assertEqual(
            self.client.get(self._public_path(previous_token)).status_code, 200
        )

        response = self.client.post(
            reverse("members:regenerate_pre_registration_link")
        )

        self.assertEqual(response.status_code, 302)
        new_token = self._link().token
        self.assertNotEqual(new_token, previous_token)
        self.assertEqual(
            self.client.get(self._public_path(previous_token)).status_code, 404
        )
        self.assertEqual(self.client.get(self._public_path(new_token)).status_code, 200)

    def test_regeneration_keeps_existing_requests(self):
        self.client.force_login(self.owner)
        self.client.get(reverse("members:pre_registration_list"))
        link = self._link()
        MemberPreRegistration.objects.create(
            gym=self.gym,
            link=link,
            first_name="Deja",
            last_name="Inscrit",
            phone="+243810000900",
            email="deja.inscrit@example.com",
        )

        self.client.post(reverse("members:regenerate_pre_registration_link"))

        self.assertEqual(MemberPreRegistration.objects.filter(gym=self.gym).count(), 1)

    def test_reception_cannot_regenerate_the_link(self):
        self.client.force_login(self.owner)
        self.client.get(reverse("members:pre_registration_list"))
        previous_token = self._link().token

        self.client.force_login(self.reception)
        response = self.client.post(
            reverse("members:regenerate_pre_registration_link")
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._link().token, previous_token)

    # --- 3. Protection du formulaire public --------------------------------

    def test_honeypot_field_rejects_bot_submission(self):
        self.client.force_login(self.owner)
        self.client.get(reverse("members:pre_registration_list"))
        path = self._public_path(self._link().token)

        self.client.logout()
        response = self.client.post(
            path, self._form_data(website="http://spam.example")
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(MemberPreRegistration.objects.count(), 0)

    def test_submissions_are_capped_per_ip(self):
        self.client.force_login(self.owner)
        self.client.get(reverse("members:pre_registration_list"))
        path = self._public_path(self._link().token)
        self.client.logout()

        allowed = MemberPreRegistrationForm.MAX_PER_IP_PER_HOUR
        for index in range(allowed):
            self.client.post(
                path, self._form_data(index), REMOTE_ADDR="203.0.113.7"
            )
        self.assertEqual(MemberPreRegistration.objects.count(), allowed)

        response = self.client.post(
            path, self._form_data(allowed + 1), REMOTE_ADDR="203.0.113.7"
        )

        self.assertEqual(MemberPreRegistration.objects.count(), allowed)
        self.assertContains(response, "Trop de demandes")

    def test_another_ip_is_not_blocked_by_a_saturated_one(self):
        self.client.force_login(self.owner)
        self.client.get(reverse("members:pre_registration_list"))
        path = self._public_path(self._link().token)
        self.client.logout()

        allowed = MemberPreRegistrationForm.MAX_PER_IP_PER_HOUR
        for index in range(allowed):
            self.client.post(
                path, self._form_data(index), REMOTE_ADDR="203.0.113.7"
            )

        self.client.post(
            path, self._form_data(90), REMOTE_ADDR="203.0.113.8"
        )

        self.assertEqual(MemberPreRegistration.objects.count(), allowed + 1)

    def test_visitor_ip_is_recorded(self):
        self.client.force_login(self.owner)
        self.client.get(reverse("members:pre_registration_list"))
        path = self._public_path(self._link().token)
        self.client.logout()

        self.client.post(path, self._form_data(), REMOTE_ADDR="203.0.113.7")

        self.assertEqual(
            MemberPreRegistration.objects.get().ip_address, "203.0.113.7"
        )

    def test_ip_behind_proxy_is_taken_from_forwarded_header(self):
        self.client.force_login(self.owner)
        self.client.get(reverse("members:pre_registration_list"))
        path = self._public_path(self._link().token)
        self.client.logout()

        self.client.post(
            path,
            self._form_data(),
            REMOTE_ADDR="10.0.0.5",
            HTTP_X_FORWARDED_FOR="198.51.100.4, 10.0.0.5",
        )

        self.assertEqual(
            MemberPreRegistration.objects.get().ip_address, "198.51.100.4"
        )


class PreRegistrationConfirmationHardeningTests(TestCase):
    """Remise des identifiants, atomicite de la confirmation, sort des expirees."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Confirm", slug="org-confirm"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Confirm",
            slug="gym-confirm",
            subdomain="gym-confirm",
        )
        self.owner = User.objects.create_user(
            username="owner-confirm",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.client.force_login(self.owner)

    def _pending(self, tag="01", **overrides):
        data = {
            "gym": self.gym,
            "first_name": f"Cand{tag}",
            "last_name": "Confirm",
            "phone": f"+2438200000{tag}",
            "email": f"cand{tag}.confirm@example.com",
        }
        data.update(overrides)
        return MemberPreRegistration.objects.create(**data)

    def _messages(self, response):
        return list(response.context["messages"])

    # --- 1. Les identifiants ne peuvent plus etre perdus -------------------

    def test_credentials_message_does_not_auto_dismiss(self):
        pre_registration = self._pending()

        response = self.client.post(
            reverse("members:confirm_pre_registration", args=[pre_registration.id]),
            follow=True,
        )

        message = self._messages(response)[0]
        self.assertIn("persistent", message.tags)
        self.assertIn("Mot de passe temporaire", str(message))

    def test_resetting_password_issues_new_credentials_and_emails_them(self):
        """Filet de securite quand les identifiants d'origine ont ete perdus."""
        pre_registration = self._pending()
        self.client.post(
            reverse("members:confirm_pre_registration", args=[pre_registration.id])
        )
        pre_registration.refresh_from_db()
        member = pre_registration.member
        previous_hash = member.user.password
        mail.outbox.clear()

        self.client.post(
            reverse("members:reset_member_password", args=[member.id]), follow=True
        )

        member.user.refresh_from_db()
        self.assertNotEqual(member.user.password, previous_hash)
        self.assertTrue(member.user.force_password_change)
        self.assertEqual(len(mail.outbox), 1)

    def test_reset_credentials_are_shown_on_the_member_list(self):
        pre_registration = self._pending()
        self.client.post(
            reverse("members:confirm_pre_registration", args=[pre_registration.id])
        )
        pre_registration.refresh_from_db()

        self.client.post(
            reverse("members:reset_member_password", args=[pre_registration.member.id])
        )

        credentials = self.client.session.get("member_password_credentials")
        self.assertIsNotNone(credentials)
        self.assertEqual(credentials["username"], pre_registration.member.user.username)

    # --- 2. Garde-fous portes par le modele -------------------------------

    def test_model_refuses_to_confirm_a_duplicate_member(self):
        first = self._pending("01")
        self.client.post(
            reverse("members:confirm_pre_registration", args=[first.id])
        )
        first.refresh_from_db()

        duplicate = self._pending("02", phone=first.member.phone)

        with self.assertRaises(ValueError):
            duplicate.confirm(self.owner)

        self.assertEqual(
            Member.objects.filter(gym=self.gym, phone=first.member.phone).count(), 1
        )

    def test_confirmation_leaves_nothing_behind_when_it_fails(self):
        pre_registration = self._pending()
        member_count = Member.objects.count()

        with patch(
            "members.models.MemberPreRegistration.save",
            side_effect=RuntimeError("panne"),
        ):
            with self.assertRaises(RuntimeError):
                pre_registration.confirm(self.owner)

        self.assertEqual(Member.objects.count(), member_count)

    # --- 3. Les demandes expirees sont conservees --------------------------

    def test_expired_requests_are_marked_not_deleted(self):
        pre_registration = self._pending()
        MemberPreRegistration.objects.filter(pk=pre_registration.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )

        marked = MemberPreRegistration.mark_expired_pending()

        pre_registration.refresh_from_db()
        self.assertEqual(marked, 1)
        self.assertEqual(pre_registration.status, MemberPreRegistration.STATUS_EXPIRED)

    def test_confirming_an_expired_request_keeps_it_for_follow_up(self):
        pre_registration = self._pending()
        MemberPreRegistration.objects.filter(pk=pre_registration.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )

        response = self.client.post(
            reverse("members:confirm_pre_registration", args=[pre_registration.id]),
            follow=True,
        )

        pre_registration.refresh_from_db()
        self.assertEqual(pre_registration.status, MemberPreRegistration.STATUS_EXPIRED)
        self.assertIsNone(pre_registration.member)
        self.assertIn("expire", str(self._messages(response)[0]).lower())

    def test_expired_requests_are_listed_under_their_own_filter(self):
        pre_registration = self._pending()
        MemberPreRegistration.objects.filter(pk=pre_registration.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )

        response = self.client.get(
            reverse("members:pre_registration_list"), {"status": "expired"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["expired_count"], 1)
        self.assertIn(pre_registration, response.context["page_obj"].object_list)

    def test_cleanup_command_marks_instead_of_deleting(self):
        pre_registration = self._pending()
        MemberPreRegistration.objects.filter(pk=pre_registration.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )

        output = StringIO()
        call_command("cleanup_expired_preregistrations", stdout=output)

        pre_registration.refresh_from_db()
        self.assertEqual(pre_registration.status, MemberPreRegistration.STATUS_EXPIRED)
        self.assertIn("expiree", output.getvalue())


class MemberCreationHardeningTests(TestCase):
    """Creation et modification d'un membre : doublons, erreurs, identifiants."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Saisie", slug="org-saisie"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Saisie",
            slug="gym-saisie",
            subdomain="gym-saisie",
        )
        self.other_gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Voisin",
            slug="gym-voisin",
            subdomain="gym-voisin",
        )
        self.owner = User.objects.create_user(
            username="owner-saisie",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _create(self, **overrides):
        payload = {
            "first_name": "Alpha",
            "last_name": "Saisie",
            "phone": "+243830000001",
            "email": "alpha.saisie@example.com",
            "address": "Kinshasa",
        }
        payload.update(overrides)
        return self.client.post(
            reverse("members:create_member"), payload, follow=True
        )

    def _messages(self, response):
        return [str(item) for item in response.context["messages"]]

    # --- Doublons : plus de plantage -------------------------------------

    def test_duplicate_phone_is_reported_instead_of_crashing(self):
        self._create()

        response = self._create(email="autre.saisie@example.com")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Member.objects.filter(gym=self.gym).count(), 1)
        self.assertIn(
            "Telephone : Un membre de cette salle utilise deja ce numero de telephone.",
            self._messages(response),
        )

    def test_duplicate_email_is_reported_instead_of_crashing(self):
        self._create()

        response = self._create(phone="+243830000002")

        self.assertEqual(Member.objects.filter(gym=self.gym).count(), 1)
        self.assertIn(
            "E-mail : Un membre de cette salle utilise deja cette adresse e-mail.",
            self._messages(response),
        )

    def test_same_phone_is_allowed_in_another_gym(self):
        self._create()
        Member.objects.create(
            gym=self.other_gym,
            first_name="Homonyme",
            last_name="Saisie",
            phone="+243830000001",
            email="homonyme.saisie@example.com",
        )

        self.assertEqual(Member.objects.filter(phone="+243830000001").count(), 2)

    def test_two_members_without_email_can_coexist(self):
        # La saisie manuelle exige desormais un e-mail, mais les fiches creees
        # hors formulaire (import, reprise de donnees) peuvent en manquer : la
        # contrainte (gym, email) ne doit pas les faire entrer en collision.
        Member.objects.create(
            gym=self.gym,
            first_name="Sans",
            last_name="Mail Un",
            phone="+243830000011",
            email=None,
        )
        Member.objects.create(
            gym=self.gym,
            first_name="Sans",
            last_name="Mail Deux",
            phone="+243830000012",
            email=None,
        )

        self.assertEqual(Member.objects.filter(gym=self.gym).count(), 2)
        self.assertTrue(
            all(member.email is None for member in Member.objects.filter(gym=self.gym))
        )

    def test_email_is_required_in_the_form(self):
        # Quatre coordonnees sont obligatoires a la saisie : prenom, nom,
        # telephone et e-mail.
        response = self._create(email="")

        self.assertEqual(Member.objects.filter(gym=self.gym).count(), 0)
        self.assertIn("E-mail : Ce champ est obligatoire.", self._messages(response))

    # --- Erreurs de saisie visibles ---------------------------------------

    def test_invalid_form_reports_the_reason(self):
        response = self._create(first_name="")

        self.assertEqual(Member.objects.filter(gym=self.gym).count(), 0)
        self.assertIn("Prenom : Ce champ est obligatoire.", self._messages(response))

    # --- Identifiants et securite du message ------------------------------

    def test_credentials_message_does_not_auto_dismiss(self):
        response = self._create()

        message = response.context["messages"]._loaded_messages[0]
        self.assertIn("persistent", message.tags)
        self.assertIn("Mot de passe temporaire", str(message))

    def test_member_name_is_escaped_in_the_html_message(self):
        response = self._create(first_name="<img src=x onerror=alert(1)>")

        self.assertIn("&lt;img", self._messages(response)[0])

    # --- Modification ------------------------------------------------------

    def test_editing_a_member_keeps_its_own_phone(self):
        self._create()
        member = Member.objects.get(gym=self.gym)

        response = self.client.post(
            reverse("members:edit_member", args=[member.id]),
            {
                "first_name": "Beta",
                "last_name": "Saisie",
                "phone": member.phone,
                "email": member.email,
                "address": "Gombe",
            },
        )

        member.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(member.first_name, "Beta")

    def test_editing_cannot_steal_another_member_phone(self):
        self._create()
        other = Member.objects.create(
            gym=self.gym,
            first_name="Gamma",
            last_name="Saisie",
            phone="+243830000009",
            email="gamma.saisie@example.com",
        )

        response = self.client.post(
            reverse("members:edit_member", args=[other.id]),
            {
                "first_name": "Gamma",
                "last_name": "Saisie",
                "phone": "+243830000001",
                "email": other.email,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("phone", response.json()["errors"])


class MemberQrCodeStabilityTests(TestCase):
    """Le QR est imprime sur les cartes : il ne change que sur decision humaine."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Org QR", slug="org-qr")
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym QR",
            slug="gym-qr",
            subdomain="gym-qr",
        )
        self.owner = User.objects.create_user(
            username="owner-qr",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.manager = User.objects.create_user(username="manager-qr", password="pass12345")
        self.reception = User.objects.create_user(username="reception-qr", password="pass12345")
        UserGymRole.objects.create(
            user=self.manager, gym=self.gym, role="manager", is_active=True
        )
        UserGymRole.objects.create(
            user=self.reception, gym=self.gym, role="reception", is_active=True
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Carte",
            last_name="Imprimee",
            phone="+243840000001",
            email="carte.imprimee@example.com",
        )

    def _expire_qr(self):
        Member.objects.filter(pk=self.member.pk).update(
            qr_code_expires_at=timezone.now() - timedelta(days=1)
        )

    def _current_qr(self):
        return Member.objects.get(pk=self.member.pk).qr_code

    # --- Aucune rotation implicite ----------------------------------------

    def test_viewing_details_never_changes_the_qr_code(self):
        self._expire_qr()
        before = self._current_qr()
        self.client.force_login(self.owner)

        self.client.get(reverse("members:member_detail", args=[self.member.id]))

        self.assertEqual(self._current_qr(), before)

    def test_reading_the_qr_image_never_changes_it(self):
        self._expire_qr()
        before = self._current_qr()
        self.client.force_login(self.owner)

        self.client.get(reverse("members:member_qr", args=[before]))

        self.assertEqual(self._current_qr(), before)

    def test_new_members_get_a_long_lived_qr(self):
        """Une carte imprimee doit rester valable bien au-dela de quelques jours."""
        self.assertGreater(
            self.member.qr_code_expires_at, timezone.now() + timedelta(days=365)
        )

    # --- Rotation explicite seulement --------------------------------------

    def test_manager_can_regenerate_the_qr(self):
        before = self._current_qr()
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("members:regenerate_member_qr", args=[self.member.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(self._current_qr(), before)

    def test_owner_can_regenerate_the_qr(self):
        before = self._current_qr()
        self.client.force_login(self.owner)

        self.client.post(
            reverse("members:regenerate_member_qr", args=[self.member.id])
        )

        self.assertNotEqual(self._current_qr(), before)

    def test_reception_cannot_regenerate_the_qr(self):
        before = self._current_qr()
        self.client.force_login(self.reception)

        response = self.client.post(
            reverse("members:regenerate_member_qr", args=[self.member.id])
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._current_qr(), before)

    def test_regeneration_flag_is_a_boolean_in_the_payload(self):
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse("members:member_detail", args=[self.member.id])
        )

        self.assertIs(response.json()["can_regenerate_qr"], True)

    @override_settings(PUBLIC_BASE_URL="https://royalgym-fitness.com")
    def test_member_portal_url_uses_the_public_domain(self):
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse("members:member_detail", args=[self.member.id])
        )

        self.assertTrue(
            response.json()["member_portal_url"].startswith(
                "https://royalgym-fitness.com/"
            )
        )


class MemberPasswordResetEmailTests(TestCase):
    """L'e-mail de reinitialisation est distinct de celui de creation."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Reinit", slug="org-reinit"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Reinit",
            slug="gym-reinit",
            subdomain="gym-reinit",
        )
        self.owner = User.objects.create_user(
            username="owner-reinit",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Ancien",
            last_name="Membre",
            phone="+243850000001",
            email="ancien.membre@example.com",
        )
        self.client.force_login(self.owner)
        mail.outbox.clear()

    def _reset(self):
        return self.client.post(
            reverse("members:reset_member_password", args=[self.member.id]),
            follow=True,
        )

    def test_reset_email_does_not_welcome_an_existing_member(self):
        self._reset()

        body = mail.outbox[0].body
        self.assertIn("reinitialise par l'equipe", body)
        self.assertNotIn("Votre fiche membre a ete creee", body)

    def test_reset_email_has_its_own_subject_and_type(self):
        self._reset()

        message = mail.outbox[0]
        self.assertIn("Reinitialisation de votre mot de passe", message.subject)
        self.assertEqual(
            message.extra_headers["X-SmartClub-Email-Type"], "password-reset"
        )

    def test_reset_email_carries_the_new_credentials(self):
        self._reset()

        credentials = self.client.session.get("member_password_credentials")
        body = mail.outbox[0].body
        self.assertIn(self.member.user.username, body)
        self.assertIn("Mot de passe temporaire", body)
        self.assertIsNone(credentials)  # consommees par l'affichage de la liste

    def test_reset_email_does_not_attach_the_membership_card(self):
        """Le QR code n'a pas change : rejoindre la carte n'aurait pas de sens."""
        self._reset()

        self.assertEqual(len(mail.outbox[0].attachments), 0)

    def test_reset_email_warns_about_an_unexpected_request(self):
        self._reset()

        self.assertIn("contactez la salle", mail.outbox[0].body)

    def test_creation_still_sends_the_welcome_email(self):
        self.client.post(
            reverse("members:create_member"),
            {
                "first_name": "Tout",
                "last_name": "Neuf",
                "phone": "+243850000002",
                "email": "tout.neuf@example.com",
            },
        )

        message = mail.outbox[-1]
        self.assertIn("Votre fiche membre a ete creee", message.body)
        self.assertEqual(
            message.extra_headers["X-SmartClub-Email-Type"], "account-creation"
        )


class SuspendedMemberTests(TestCase):
    """Suspension : messages fideles, portail bride, actions refusees."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Org Susp", slug="org-susp")
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Susp",
            slug="gym-susp",
            subdomain="gym-susp",
        )
        self.owner = User.objects.create_user(
            username="owner-susp",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", duration_days=30, price=30
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Suspendu",
            last_name="Test",
            phone="+243860000001",
            email="suspendu.test@example.com",
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
        self.member.user.set_password("MembrePortail123!")
        self.member.user.force_password_change = False
        self.member.user.save()

    def _staff(self):
        client = Client()
        client.force_login(self.owner)
        return client

    def _portal(self):
        client = Client()
        client.login(username=self.member.user.username, password="MembrePortail123!")
        return client

    def _suspend(self):
        return self._staff().post(
            reverse("members:suspend_member", args=[self.member.id]), follow=True
        )

    def _first_message(self, response):
        return str(list(response.context["messages"])[0])

    # --- Messages fideles a la situation -----------------------------------

    def test_message_mentions_the_paused_subscription(self):
        response = self._suspend()

        self.assertIn("Son abonnement est en pause", self._first_message(response))

    def test_message_admits_when_there_is_no_subscription(self):
        orphan = Member.objects.create(
            gym=self.gym,
            first_name="Sans",
            last_name="Abonnement",
            phone="+243860000002",
            email="sans.abonnement@example.com",
        )

        response = self._staff().post(
            reverse("members:suspend_member", args=[orphan.id]), follow=True
        )

        self.assertIn("aucun abonnement actif", self._first_message(response))

    def test_reactivation_message_states_the_recovered_days(self):
        self._suspend()
        MemberSubscription.objects.filter(pk=self.subscription.pk).update(
            paused_at=timezone.now() - timedelta(days=6)
        )

        response = self._staff().post(
            reverse("members:reactivate_member", args=[self.member.id]), follow=True
        )

        self.assertIn("prolonge de 6 jours", self._first_message(response))

    def test_reactivation_message_when_the_pause_was_shorter_than_a_day(self):
        self._suspend()

        response = self._staff().post(
            reverse("members:reactivate_member", args=[self.member.id]), follow=True
        )

        self.assertIn("moins d'une journee", self._first_message(response))

    # --- Portail bride ------------------------------------------------------

    def test_portal_shows_the_suspension_banner(self):
        self._suspend()

        response = self._portal().get(reverse("members:member_portal"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["member_is_suspended"])
        self.assertContains(response, "Compte suspendu")

    def test_portal_hides_the_subscribe_button(self):
        self._suspend()

        response = self._portal().get(reverse("members:member_portal"))

        self.assertNotContains(response, ">Souscrire<")

    def test_banner_disappears_after_reactivation(self):
        self._suspend()
        self._staff().post(reverse("members:reactivate_member", args=[self.member.id]))

        response = self._portal().get(reverse("members:member_portal"))

        self.assertFalse(response.context["member_is_suspended"])

    # --- Actions refusees cote serveur --------------------------------------

    def test_subscription_request_is_refused_from_the_web(self):
        self._suspend()

        response = self._portal().post(
            reverse("members:member_subscription_request"),
            {"plan_id": self.plan.id},
            follow=True,
        )

        self.assertIn("suspendu", self._first_message(response))
        self.assertFalse(SubscriptionRequest.objects.filter(member=self.member).exists())

    def test_subscription_request_is_refused_from_the_mobile_app(self):
        self._suspend()

        response = self._portal().post(
            reverse("members:member_api_subscription_request"),
            data=json.dumps({"plan_id": self.plan.id}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(SubscriptionRequest.objects.filter(member=self.member).exists())

    def test_choosing_a_coach_is_refused_from_the_mobile_app(self):
        self._suspend()

        response = self._portal().post(
            reverse("members:member_api_choose_coach"),
            data=json.dumps({"coach_id": 1}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_an_active_member_is_not_blocked(self):
        response = self._portal().post(
            reverse("members:member_subscription_request"),
            {"plan_id": self.plan.id},
            follow=True,
        )

        self.assertNotIn("suspendu", self._first_message(response))
        self.assertTrue(SubscriptionRequest.objects.filter(member=self.member).exists())


class MemberDownloadTests(TestCase):
    """Telechargement du QR code et de la carte membre."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Org Tele", slug="org-tele")
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Tele",
            slug="gym-tele",
            subdomain="gym-tele",
        )
        self.owner = User.objects.create_user(
            username="owner-tele",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Jean",
            last_name="Telechargement",
            phone="+243870000001",
            email="jean.telechargement@example.com",
        )
        self.client.force_login(self.owner)

    def _image(self, response):
        from PIL import Image

        return Image.open(BytesIO(response.content))

    def _qr_url(self):
        return reverse("members:member_qr", args=[self.member.qr_code])

    # --- Resolution adaptee a l'impression ---------------------------------

    def test_downloaded_qr_is_high_resolution(self):
        response = self.client.get(self._qr_url())

        self.assertEqual(self._image(response).size, (1024, 1024))

    def test_qr_size_can_be_requested(self):
        response = self.client.get(self._qr_url(), {"size": 512})

        self.assertEqual(self._image(response).size, (512, 512))

    def test_absurd_qr_size_is_capped(self):
        response = self.client.get(self._qr_url(), {"size": 99999})

        self.assertEqual(self._image(response).size, (2048, 2048))

    def test_invalid_qr_size_falls_back_to_the_default(self):
        response = self.client.get(self._qr_url(), {"size": "abc"})

        self.assertEqual(self._image(response).size, (1024, 1024))

    def test_qr_modules_are_sharp(self):
        """Deux nuances seulement : aucun reechantillonnage n'a floute le code."""
        response = self.client.get(self._qr_url())

        greyscale = self._image(response).convert("L")
        shades = {value for _, value in greyscale.getcolors(maxcolors=100000)}
        self.assertEqual(len(shades), 2)

    # --- En-tete de telechargement ------------------------------------------

    def test_qr_is_shown_inline_by_default(self):
        response = self.client.get(self._qr_url())

        self.assertNotIn("Content-Disposition", response)

    def test_qr_download_carries_a_readable_filename(self):
        response = self.client.get(self._qr_url(), {"download": "1"})

        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="qr_jean-telechargement.png"',
        )

    def test_card_download_carries_a_readable_filename(self):
        response = self.client.get(
            reverse("members:member_card_image", args=[self.member.id]),
            {"download": "1"},
        )

        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="carte_membre_jean-telechargement.png"',
        )

    def test_card_is_shown_inline_by_default(self):
        response = self.client.get(
            reverse("members:member_card_image", args=[self.member.id])
        )

        self.assertNotIn("Content-Disposition", response)
        self.assertEqual(response["Cache-Control"], "private, no-store")

    # --- URL fournies a l'interface ------------------------------------------

    def test_detail_payload_exposes_download_urls(self):
        response = self.client.get(
            reverse("members:member_detail", args=[self.member.id])
        )

        payload = response.json()
        self.assertTrue(payload["qr_download_url"].endswith("?download=1"))
        self.assertTrue(payload["card_download_url"].endswith("?download=1"))

    # --- Cloisonnement --------------------------------------------------------

    def test_another_gym_member_cannot_be_downloaded(self):
        # Autre organisation, sinon le proprietaire posseerait deux salles et
        # le middleware ne saurait plus laquelle est active.
        other_organization = Organization.objects.create(
            name="Org Voisine Tele", slug="org-voisine-tele"
        )
        other_gym = Gym.objects.create(
            organization=other_organization,
            name="Gym Voisin Tele",
            slug="gym-voisin-tele",
            subdomain="gym-voisin-tele",
        )
        outsider = Member.objects.create(
            gym=other_gym,
            first_name="Etranger",
            last_name="Tele",
            phone="+243870000002",
            email="etranger.tele@example.com",
        )

        self.assertEqual(
            self.client.get(
                reverse("members:member_card_image", args=[outsider.id])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("members:member_qr", args=[outsider.qr_code])
            ).status_code,
            404,
        )


class RegistrationAuthorshipTests(TestCase):
    """Toute fiche membre porte le nom de qui l'a inscrite."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Auteur", slug="org-auteur"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Auteur",
            slug="gym-auteur",
            subdomain="gym-auteur",
        )
        self.receptionniste = User.objects.create_user(
            username="reception-auteur",
            password="pass12345",
            first_name="Claire",
            last_name="Mbala",
        )
        UserGymRole.objects.create(
            user=self.receptionniste, gym=self.gym, role="reception", is_active=True
        )
        self.client.force_login(self.receptionniste)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _saisir(self, **overrides):
        payload = {
            "first_name": "Bruno",
            "last_name": "Kalala",
            "phone": "+243840000001",
            "email": "bruno.kalala@example.com",
            "address": "Kinshasa",
        }
        payload.update(overrides)
        return self.client.post(
            reverse("members:create_member"), payload, follow=True
        )

    def _demande(self, **overrides):
        champs = {
            "gym": self.gym,
            "first_name": "Sarah",
            "last_name": "Nkosi",
            "phone": "+243840000002",
            "email": "sarah.nkosi@example.com",
        }
        champs.update(overrides)
        return MemberPreRegistration.objects.create(**champs)

    # --- Saisie directe ------------------------------------------------------

    def test_a_manually_created_member_carries_its_author(self):
        self._saisir()

        membre = Member.objects.get(gym=self.gym, phone="+243840000001")
        self.assertEqual(membre.created_by, self.receptionniste)
        self.assertEqual(membre.registration_source, Member.SOURCE_MANUAL)

    def test_the_author_label_prefers_the_full_name(self):
        self._saisir()

        membre = Member.objects.get(gym=self.gym, phone="+243840000001")
        self.assertEqual(membre.registered_by_label, "Claire Mbala")

    def test_the_author_label_falls_back_to_the_username(self):
        self.receptionniste.first_name = ""
        self.receptionniste.last_name = ""
        self.receptionniste.save(update_fields=["first_name", "last_name"])

        self._saisir()

        membre = Member.objects.get(gym=self.gym, phone="+243840000001")
        self.assertEqual(membre.registered_by_label, "reception-auteur")

    def test_a_member_without_author_is_not_attributed_to_anyone(self):
        # Fiche reprise d'un ancien fichier : personne ne l'a saisie ici.
        membre = Member.objects.create(
            gym=self.gym,
            first_name="Ancien",
            last_name="Dossier",
            phone="+243840000099",
        )

        self.assertIsNone(membre.created_by)
        self.assertEqual(membre.registration_source, Member.SOURCE_OTHER)
        self.assertEqual(membre.registered_by_label, "Inconnu")

    def test_the_member_sheet_shows_who_registered_it(self):
        self._saisir()
        membre = Member.objects.get(gym=self.gym, phone="+243840000001")

        response = self.client.get(reverse("members:member_detail", args=[membre.id]))

        charge = response.json()
        self.assertEqual(charge["registered_by"], "Claire Mbala")
        self.assertEqual(charge["registration_source"], "Saisie directe")

    # --- Confirmation d'une preinscription -----------------------------------

    def test_a_confirmed_pre_registration_names_its_confirmer(self):
        demande = self._demande()

        self.client.post(
            reverse("members:confirm_pre_registration", args=[demande.id]), follow=True
        )

        demande.refresh_from_db()
        self.assertEqual(demande.confirmed_by, self.receptionniste)
        self.assertIsNotNone(demande.confirmed_at)

    def test_the_member_born_from_a_confirmation_carries_the_confirmer(self):
        demande = self._demande()

        self.client.post(
            reverse("members:confirm_pre_registration", args=[demande.id]), follow=True
        )

        demande.refresh_from_db()
        self.assertEqual(demande.member.created_by, self.receptionniste)
        self.assertEqual(
            demande.member.registration_source, Member.SOURCE_PRE_REGISTRATION
        )

    def test_the_confirmation_is_traced_in_the_sensitive_log(self):
        demande = self._demande()

        self.client.post(
            reverse("members:confirm_pre_registration", args=[demande.id]), follow=True
        )

        trace = SensitiveActivityLog.objects.get(
            action="member.pre_registration_confirmed"
        )
        self.assertEqual(trace.actor, self.receptionniste)
        self.assertEqual(trace.target_label, "Sarah Nkosi")

    def test_the_list_shows_who_confirmed(self):
        demande = self._demande()
        self.client.post(
            reverse("members:confirm_pre_registration", args=[demande.id]), follow=True
        )

        response = self.client.get(
            reverse("members:pre_registration_list"), {"status": "confirmed"}
        )

        self.assertContains(response, "Traitee par")
        self.assertContains(response, "Claire Mbala")

    def test_the_list_shows_who_cancelled(self):
        demande = self._demande()
        self.client.post(
            reverse("members:cancel_pre_registration", args=[demande.id]), follow=True
        )

        response = self.client.get(
            reverse("members:pre_registration_list"), {"status": "cancelled"}
        )

        self.assertContains(response, "Claire Mbala")

    def test_the_member_list_names_the_author_on_each_row(self):
        self._saisir()

        response = self.client.get(reverse("members:member_list"))

        self.assertContains(response, "Inscrit par Claire Mbala")

    def test_the_member_list_says_plainly_when_the_author_is_unknown(self):
        Member.objects.create(
            gym=self.gym,
            first_name="Ancien",
            last_name="Dossier",
            phone="+243840000098",
        )

        response = self.client.get(reverse("members:member_list"))

        self.assertContains(response, "Auteur inconnu")

    # --- Annulation d'une preinscription -------------------------------------

    def test_a_cancelled_pre_registration_names_its_author(self):
        demande = self._demande()

        self.client.post(
            reverse("members:cancel_pre_registration", args=[demande.id]), follow=True
        )

        demande.refresh_from_db()
        self.assertEqual(demande.status, MemberPreRegistration.STATUS_CANCELLED)
        self.assertEqual(demande.cancelled_by, self.receptionniste)
        self.assertIsNotNone(demande.cancelled_at)

    def test_the_cancellation_is_traced_in_the_sensitive_log(self):
        demande = self._demande()

        self.client.post(
            reverse("members:cancel_pre_registration", args=[demande.id]), follow=True
        )

        trace = SensitiveActivityLog.objects.get(
            action="member.pre_registration_cancelled"
        )
        self.assertEqual(trace.actor, self.receptionniste)

    def test_an_already_handled_request_cannot_be_cancelled_again(self):
        demande = self._demande()
        demande.cancel(self.receptionniste)

        with self.assertRaises(ValueError):
            demande.cancel(self.receptionniste)


class MemberPortalGymIdentityTests(TestCase):
    """Le membre doit savoir dans quelle salle il est inscrit."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Royal Gym",
            slug="royal-gym-identite",
            address="Siege social, Gombe",
            phone="+243800000000",
            email="contact@royalgym.cd",
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Royal Gym Limete",
            slug="royal-limete",
            subdomain="royal-limete",
            address="45 avenue Kabinda, Limete",
            phone="+243811111111",
            opening_hours="Lundi au vendredi : 06h - 21h\nSamedi : 08h - 18h",
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Yann",
            last_name="Ilunga",
            phone="+243812222222",
            email="yann.ilunga@example.com",
        )
        # Un membre nouvellement cree doit changer son mot de passe avant
        # d'atteindre le portail : on simule cette premiere connexion faite.
        self.member.user.set_password("MemberPortal123!")
        self.member.user.force_password_change = False
        self.member.user.save(update_fields=["password", "force_password_change"])
        self.client.force_login(self.member.user)

    def _portail(self):
        return self.client.get(reverse("members:member_portal"))

    # --- Identification de la salle ------------------------------------------

    def test_the_portal_names_the_gym_not_only_the_organization(self):
        response = self._portail()

        self.assertContains(response, "Royal Gym Limete")
        self.assertContains(response, "Ma salle : Royal Gym Limete")

    def test_the_installed_app_is_named_after_the_gym(self):
        response = self._portail()

        self.assertContains(
            response, '<meta name="apple-mobile-web-app-title" content="Royal Gym Limete">'
        )

    def test_the_portal_never_shows_the_software_publisher(self):
        response = self._portail()

        self.assertNotContains(response, "logo_smartclub")
        self.assertNotContains(response, "SmartClub")

    def test_the_member_card_block_names_the_gym(self):
        response = self._portail()

        self.assertContains(response, "Carte membre - Royal Gym Limete")

    # --- Coordonnees propres a la salle ---------------------------------------

    def test_the_gym_own_address_wins_over_the_organization_one(self):
        self.assertEqual(self.gym.contact_address, "45 avenue Kabinda, Limete")
        self.assertEqual(self.gym.contact_phone, "+243811111111")

    def test_an_empty_field_falls_back_to_the_organization(self):
        # L'e-mail n'est pas renseigne sur la salle : celui du siege vaut
        # mieux que rien.
        self.assertEqual(self.gym.contact_email, "contact@royalgym.cd")

    def test_the_hours_are_never_borrowed_from_the_organization(self):
        sans_horaires = Gym.objects.create(
            organization=self.organization,
            name="Royal Gym Bandal",
            slug="royal-bandal",
            subdomain="royal-bandal",
        )

        self.assertEqual(sans_horaires.contact_hours, "")
        self.assertEqual(sans_horaires.contact_address, "Siege social, Gombe")

    def test_the_portal_shows_the_gym_contact_details(self):
        response = self._portail()

        self.assertContains(response, "45 avenue Kabinda, Limete")
        self.assertContains(response, "+243811111111")
        self.assertContains(response, "Lundi au vendredi : 06h - 21h")

    def test_a_gym_without_any_contact_says_so_plainly(self):
        gym_vide = Gym.objects.create(
            organization=Organization.objects.create(
                name="Club Nu", slug="club-nu"
            ),
            name="Club Nu Centre",
            slug="club-nu-centre",
            subdomain="club-nu-centre",
        )
        membre = Member.objects.create(
            gym=gym_vide,
            first_name="Sans",
            last_name="Contact",
            phone="+243813333333",
        )
        membre.user.set_password("MemberPortal123!")
        membre.user.force_password_change = False
        membre.user.save(update_fields=["password", "force_password_change"])
        self.client.force_login(membre.user)

        response = self._portail()

        self.assertFalse(gym_vide.has_public_contact)
        self.assertContains(response, "Adressez-vous a l'accueil de Club Nu Centre")

    # --- Bandeau de suspension ------------------------------------------------

    def test_the_suspension_banner_names_the_gym_and_its_phone(self):
        self.member.status = "suspended"
        self.member.save(update_fields=["status"])

        response = self._portail()

        self.assertContains(response, "Salle concernee")
        self.assertContains(response, "Royal Gym Limete")
        self.assertContains(response, "+243811111111")


class GymContactSettingsTests(TestCase):
    """Les coordonnees de la salle se saisissent dans Parametres."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Coordonnees", slug="org-coordonnees"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Coordonnees",
            slug="gym-coordonnees",
            subdomain="gym-coordonnees",
        )
        self.manager = User.objects.create_user(
            username="gerant-coordonnees", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.manager, gym=self.gym, role="manager", is_active=True
        )
        self.client.force_login(self.manager)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def test_the_settings_page_saves_the_gym_contact_details(self):
        response = self.client.post(
            reverse("core:settings"),
            {
                "action": "gym_contact",
                "address": "12 avenue de la Justice",
                "phone": "+243820000000",
                "email": "limete@example.cd",
                "opening_hours": "Tous les jours : 06h - 22h",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.gym.refresh_from_db()
        self.assertEqual(self.gym.address, "12 avenue de la Justice")
        self.assertEqual(self.gym.phone, "+243820000000")
        self.assertEqual(self.gym.opening_hours, "Tous les jours : 06h - 22h")

    def test_the_change_is_traced_in_the_sensitive_log(self):
        self.client.post(
            reverse("core:settings"),
            {
                "action": "gym_contact",
                "address": "12 avenue de la Justice",
                "phone": "",
                "email": "",
                "opening_hours": "",
            },
            follow=True,
        )

        trace = SensitiveActivityLog.objects.get(action="gym.contact_updated")
        self.assertEqual(trace.actor, self.manager)
        self.assertIn("address", trace.metadata["champs_modifies"])

    def test_a_malformed_email_is_refused(self):
        self.client.post(
            reverse("core:settings"),
            {
                "action": "gym_contact",
                "address": "",
                "phone": "",
                "email": "pas-une-adresse",
                "opening_hours": "",
            },
        )

        self.gym.refresh_from_db()
        self.assertEqual(self.gym.email, "")

    def test_the_settings_page_offers_the_gym_tab(self):
        response = self.client.get(reverse("core:settings"), {"tab": "salle"})

        self.assertContains(response, "Ma salle")
        self.assertContains(response, "Coordonnees de Gym Coordonnees")


class GuestPassQuotaTests(TestCase):
    """
    Le droit d'inviter : d'ou il vient, quand il s'epuise, quand il repart.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Invite", slug="org-invite"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Invite",
            slug="gym-invite", subdomain="gym-invite",
        )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Premium", price=50, duration_days=30,
            guest_invites_per_month=1, guest_sessions_per_invite=3,
        )
        self.simple = SubscriptionPlan.objects.create(
            gym=self.gym, name="Standard", price=30, duration_days=30,
        )
        self.member = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243900001111",
        )

    def _abonner(self, plan=None, debut=None):
        debut = debut or timezone.localdate()
        return MemberSubscription.objects.create(
            gym=self.gym, member=self.member, plan=plan or self.plan,
            start_date=debut, end_date=debut + timedelta(days=90),
            is_active=True,
        )

    # --- D'ou vient le droit ---------------------------------------------------

    def test_a_plan_without_invitations_grants_none(self):
        self._abonner(plan=self.simple)

        self.assertEqual(invitations.quota(self.member)["accorde"], 0)

    def test_a_member_without_subscription_grants_none(self):
        # Sans abonnement il n'y a pas de formule, donc pas de droit.
        self.assertEqual(invitations.quota(self.member)["accorde"], 0)

    def test_the_plan_decides_how_many_sessions(self):
        self._abonner()

        self.assertEqual(invitations.quota(self.member)["seances"], 3)

    # --- Le quota s'epuise et repart -------------------------------------------

    def test_issuing_consumes_the_quota(self):
        self._abonner()

        invitations.emettre(self.member, "Paul Kabeya", "0820000001")

        self.assertEqual(invitations.quota(self.member)["restant"], 0)

    def test_a_second_invitation_is_refused_in_the_same_month(self):
        self._abonner()
        invitations.emettre(self.member, "Paul Kabeya", "0820000001")

        with self.assertRaises(ValidationError) as capture:
            invitations.emettre(self.member, "Jean Musa", "0820000002")

        self.assertIn("toutes vos invitations", str(capture.exception))

    def test_the_quota_returns_the_next_subscription_month(self):
        # Un abonnement de trois mois donne trois invitations, une par tranche.
        self._abonner(debut=timezone.localdate() - timedelta(days=35))
        carnet = invitations.emettre(self.member, "Paul Kabeya", "0820000001")
        GuestPass.objects.filter(pk=carnet.pk).update(
            created_at=timezone.now() - timedelta(days=34)
        )

        self.assertEqual(invitations.quota(self.member)["restant"], 1)

    def test_an_expired_pass_does_not_give_the_quota_back(self):
        # Le mois a passe avec lui : le recours est la reattribution, pas la
        # restitution.
        self._abonner()
        carnet = invitations.emettre(self.member, "Paul Kabeya", "0820000001")
        GuestPass.objects.filter(pk=carnet.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )

        self.assertEqual(invitations.quota(self.member)["restant"], 0)

    # --- Le plafond par personne ------------------------------------------------

    def test_the_same_person_cannot_be_invited_for_ever(self):
        # Deux invitations par mois a la meme personne vaudraient un demi
        # abonnement gratuit a vie.
        self._abonner()
        for numero in range(invitations.PLAFOND_PAR_PERSONNE):
            carnet = invitations.emettre(self.member, "Paul Kabeya", "0820000001")
            GuestPass.objects.filter(pk=carnet.pk).update(
                created_at=timezone.now() - timedelta(days=31 * (numero + 1))
            )

        with self.assertRaises(ValidationError) as capture:
            invitations.emettre(self.member, "Paul Kabeya", "0820000001")

        self.assertIn("abonnement", str(capture.exception))

    def test_the_cap_ignores_how_the_number_is_written(self):
        # « 0820000001 » et « 082 000 00 01 » sont la meme personne.
        self._abonner()
        carnet = invitations.emettre(self.member, "Paul Kabeya", "0820000001")
        GuestPass.objects.filter(pk=carnet.pk).update(
            created_at=timezone.now() - timedelta(days=31)
        )

        self.assertEqual(
            invitations.passages_de(self.gym, "082 000 00 01"), 1
        )

    # --- Ce qui est refuse a l'emission -------------------------------------------

    def test_a_nameless_guest_is_refused(self):
        self._abonner()

        with self.assertRaises(ValidationError):
            invitations.emettre(self.member, "", "0820000001")

    def test_a_guest_without_a_number_is_refused(self):
        self._abonner()

        with self.assertRaises(ValidationError):
            invitations.emettre(self.member, "Paul Kabeya", "")


class GuestPassLifeTests(TestCase):
    """Les trois etats d'un carnet, et la reattribution."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Vie", slug="org-vie"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Vie",
            slug="gym-vie", subdomain="gym-vie",
        )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Premium", price=50, duration_days=30,
            guest_invites_per_month=1, guest_sessions_per_invite=2,
        )
        self.member = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243900002222",
        )
        MemberSubscription.objects.create(
            gym=self.gym, member=self.member, plan=self.plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )
        self.carnet = invitations.emettre(self.member, "Paul Kabeya", "0820000001")

    # --- Les etats ---------------------------------------------------------------

    def test_a_fresh_pass_is_active(self):
        self.assertEqual(self.carnet.state, "actif")

    def test_a_pass_lasts_thirty_full_days(self):
        # Adosse au mois, un carnet emis le 29 n'aurait dure que deux jours.
        ecart = self.carnet.expires_at - self.carnet.created_at
        self.assertEqual(ecart.days, 30)

    def test_a_used_up_pass_is_exhausted(self):
        invitations.consommer(self.carnet)
        invitations.consommer(self.carnet)
        self.carnet.refresh_from_db()

        self.assertEqual(self.carnet.state, "epuise")

    def test_an_untouched_pass_past_its_date_is_lapsed(self):
        GuestPass.objects.filter(pk=self.carnet.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )
        self.carnet.refresh_from_db()

        self.assertEqual(self.carnet.state, "caduc")

    def test_being_used_up_wins_over_being_late(self):
        # Ce qui compte pour le membre, c'est que son invite est venu.
        invitations.consommer(self.carnet)
        invitations.consommer(self.carnet)
        GuestPass.objects.filter(pk=self.carnet.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )
        self.carnet.refresh_from_db()

        self.assertEqual(self.carnet.state, "epuise")

    # --- La reattribution ----------------------------------------------------------

    def test_an_untouched_pass_can_change_hands(self):
        invitations.reattribuer(self.carnet, "Jean Musa", "0820000002")
        self.carnet.refresh_from_db()

        self.assertEqual(self.carnet.guest_name, "Jean Musa")
        self.assertEqual(self.carnet.reassigned_count, 1)

    def test_reassigning_does_not_push_the_deadline(self):
        # Sinon un membre la reculerait indefiniment en changeant de nom la
        # veille de chaque echeance.
        avant = self.carnet.expires_at

        invitations.reattribuer(self.carnet, "Jean Musa", "0820000002")
        self.carnet.refresh_from_db()

        self.assertEqual(self.carnet.expires_at, avant)

    def test_reassigning_does_not_consume_a_new_invitation(self):
        invitations.reattribuer(self.carnet, "Jean Musa", "0820000002")

        self.assertEqual(invitations.quota(self.member)["utilise"], 1)

    def test_a_used_pass_cannot_change_hands(self):
        # Une seance consommee a profite a quelqu'un.
        invitations.consommer(self.carnet)
        self.carnet.refresh_from_db()

        with self.assertRaises(ValidationError) as capture:
            invitations.reattribuer(self.carnet, "Jean Musa", "0820000002")

        self.assertIn("deja servi", str(capture.exception))

    def test_a_lapsed_pass_cannot_change_hands(self):
        GuestPass.objects.filter(pk=self.carnet.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )
        self.carnet.refresh_from_db()

        with self.assertRaises(ValidationError):
            invitations.reattribuer(self.carnet, "Jean Musa", "0820000002")

    def test_the_cap_is_rechecked_on_the_new_number(self):
        # Sans cela, la reattribution serait la porte de sortie du plafond.
        for numero in range(invitations.PLAFOND_PAR_PERSONNE):
            autre = GuestPass.objects.create(
                gym=self.gym, host=self.member, guest_name="Jean Musa",
                guest_phone="0820000002", sessions_allowed=1,
                expires_at=timezone.now() + timedelta(days=30),
            )
            GuestPass.objects.filter(pk=autre.pk).update(
                created_at=timezone.now() - timedelta(days=31 * (numero + 1))
            )

        with self.assertRaises(ValidationError) as capture:
            invitations.reattribuer(self.carnet, "Jean Musa", "0820000002")

        self.assertIn("deja ete invitee", str(capture.exception))


class GuestEntryTests(TestCase):
    """L'invite se presente : ce qui le laisse entrer, ce qui l'arrete."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Entree", slug="org-entree"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Entree",
            slug="gym-entree", subdomain="gym-entree",
        )
        module, _ = Module.objects.get_or_create(
            code="ACCESS", defaults={"name": "Access"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Premium", price=50, duration_days=30,
            guest_invites_per_month=1, guest_sessions_per_invite=2,
        )
        self.member = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243900003333",
        )
        self.abonnement = MemberSubscription.objects.create(
            gym=self.gym, member=self.member, plan=self.plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )
        self.carnet = invitations.emettre(self.member, "Paul Kabeya", "0820000001")

        self.agent = User.objects.create_user(username="accueil-invite", password="pass12345")
        UserGymRole.objects.create(
            user=self.agent, gym=self.gym, role="reception", is_active=True
        )
        self.client.force_login(self.agent)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _presenter(self, code=None):
        with patch.object(door, "open_doors", return_value=[]):
            return self.client.post(
                reverse("access:member_access", args=[code or self.carnet.code])
            )

    # --- Ce qui laisse entrer ------------------------------------------------------

    def test_a_valid_pass_opens_the_door(self):
        reponse = self._presenter()

        self.assertTrue(reponse.json()["access"])

    def test_the_entry_consumes_one_session(self):
        self._presenter()
        self.carnet.refresh_from_db()

        self.assertEqual(self.carnet.sessions_used, 1)

    def test_the_journal_names_the_guest_and_the_host(self):
        self._presenter()

        log = AccessLog.objects.get(gym=self.gym)
        self.assertIsNone(log.member)
        self.assertEqual(log.guest_pass_id, self.carnet.id)
        self.assertIn("Paul Kabeya", log.device_used)
        self.assertIn("Ada", log.device_used)

    def test_a_guest_does_not_inflate_member_attendance(self):
        # Personne ne s'est abonne : la frequentation ne doit pas bouger.
        self._presenter()

        stats = self.client.get(reverse("access:acces_dashboard")).context
        self.assertEqual(stats["today_entries"], 0)

    def test_the_second_session_still_works(self):
        self._presenter()

        reponse = self._presenter()

        self.assertTrue(reponse.json()["access"])

    # --- Ce qui l'arrete -------------------------------------------------------------

    def test_an_exhausted_pass_is_refused(self):
        self._presenter()
        self._presenter()

        reponse = self._presenter()

        self.assertFalse(reponse.json()["access"])
        self.assertIn("epuise", reponse.json()["reason"])

    def test_a_lapsed_pass_is_refused(self):
        GuestPass.objects.filter(pk=self.carnet.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )

        reponse = self._presenter()

        self.assertFalse(reponse.json()["access"])
        self.assertIn("caduc", reponse.json()["reason"])

    def test_the_host_losing_his_subscription_closes_the_pass(self):
        # Un membre partant ne doit pas laisser derriere lui des invitations
        # encore vivantes.
        MemberSubscription.objects.filter(pk=self.abonnement.pk).update(
            is_active=False, end_date=timezone.localdate() - timedelta(days=1)
        )

        reponse = self._presenter()

        self.assertFalse(reponse.json()["access"])
        self.assertIn("expire", reponse.json()["reason"])

    def test_a_refusal_is_journalised_too(self):
        # Un invite refoule doit laisser une trace : c'est le genre de passage
        # que le gerant veut pouvoir relire.
        GuestPass.objects.filter(pk=self.carnet.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )

        self._presenter()

        log = AccessLog.objects.get(gym=self.gym)
        self.assertFalse(log.access_granted)
        self.assertEqual(log.guest_pass_id, self.carnet.id)

    def test_an_unknown_code_is_still_a_404(self):
        import uuid as uuid_module

        reponse = self._presenter(code=uuid_module.uuid4())

        self.assertEqual(reponse.status_code, 404)

    def test_a_pass_of_another_gym_does_not_open_this_door(self):
        autre = Gym.objects.create(
            organization=self.organization, name="Ailleurs",
            slug="ailleurs-invite", subdomain="ailleurs-invite",
        )
        etranger = GuestPass.objects.create(
            gym=autre, host=self.member, guest_name="Intrus",
            guest_phone="0829999999", sessions_allowed=1,
            expires_at=timezone.now() + timedelta(days=30),
        )

        reponse = self._presenter(code=etranger.code)

        self.assertEqual(reponse.status_code, 404)

    # --- La liste de l'accueil ----------------------------------------------------

    def test_reception_sees_the_running_invitations(self):
        reponse = self.client.get(reverse("access:guest_passes"))

        ligne = reponse.json()["invitations"][0]
        self.assertEqual(ligne["invite"], "Paul Kabeya")
        self.assertEqual(ligne["telephone"], "0820000001")
        self.assertEqual(ligne["hote"], "Ada Mbala")
        self.assertFalse(ligne["deja_passe"])

    def test_the_list_says_who_has_already_come(self):
        self._presenter()

        ligne = self.client.get(reverse("access:guest_passes")).json()["invitations"][0]
        self.assertTrue(ligne["deja_passe"])
        self.assertEqual(ligne["seances_restantes"], 1)

    def test_an_exhausted_pass_leaves_the_list(self):
        self._presenter()
        self._presenter()

        reponse = self.client.get(reverse("access:guest_passes"))

        self.assertEqual(reponse.json()["invitations"], [])

import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from access.models import AccessLog
from coaching.models import Coach, CoachAssignment, CoachingFeedback, GroupCoachingProgram
from compte.models import User, UserGymRole
from members.forms import MemberCreationForm
from members.models import (
    Member,
    MemberGoal,
    MemberPreRegistration,
    MemberPreRegistrationLink,
    MemberWeightMeasurement,
)
from notifications.models import Notification
from organizations.models import Gym, Organization
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

        self.client.force_login(self.manager)
        manager_response = self.client.get(reverse("members:member_list"))
        self.assertContains(manager_response, 'id="statusToggleBtn"', html=False)

        self.client.force_login(self.owner)
        owner_response = self.client.get(reverse("members:member_list"))
        self.assertContains(owner_response, 'id="statusToggleBtn"', html=False)

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
        self.assertEqual(response.json()["organization_logo_url"], reverse("members:organization_logo"))

        logo_response = self.client.get(reverse("members:organization_logo"))

        self.assertEqual(logo_response.status_code, 200)
        self.assertEqual(logo_response["Content-Type"], "image/png")
        self.assertTrue(b"".join(logo_response.streaming_content).startswith(b"\x89PNG"))

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

    def test_pwa_manifest_uses_authenticated_member_organization_logo(self):
        self.organization.logo = "organizations/logos/portal-org.png"
        self.organization.save(update_fields=["logo"])
        self.client.force_login(self.member.user)

        manifest_response = self.client.get(reverse("members:member_app_manifest"))
        portal_response = self.client.get(reverse("members:member_portal"))

        self.assertEqual(manifest_response.status_code, 200)
        manifest = manifest_response.json()
        self.assertEqual(manifest["name"], "Portal Org Membre")
        self.assertEqual(manifest["short_name"], "Portal Org")
        self.assertEqual(manifest_response["Cache-Control"], "private, no-store")
        self.assertTrue(manifest["icons"][0]["src"].endswith("/media/organizations/logos/portal-org.png"))
        self.assertEqual(manifest["icons"][0]["purpose"], "any")
        self.assertContains(portal_response, 'rel="apple-touch-icon" href="/media/organizations/logos/portal-org.png"')

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

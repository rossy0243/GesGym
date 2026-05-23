from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from coaching.models import Coach, CoachAssignment, CoachingFeedback, GroupCoachingProgram
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

    def test_only_manager_can_suspend_and_reactivate_member(self):
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

        for user in [self.owner, self.reception, self.cashier]:
            self.client.force_login(user)
            response = self.client.post(reverse("members:suspend_member", args=[member.id]))
            self.assertEqual(response.status_code, 403)

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
        self.assertNotContains(owner_response, 'id="statusToggleBtn"', html=False)

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
        self.assertFalse(UserGymRole.objects.filter(user=member.user, gym=self.gym, is_active=True).exists())

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
                "password": "12345",
            },
        )

        self.assertRedirects(
            response,
            reverse("compte:welcome"),
            fetch_redirect_response=False,
        )

    def test_member_portal_shows_identity_card_and_subscription(self):
        self.client.force_login(self.member.user)

        response = self.client.get(reverse("members:member_portal"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Carte membre")
        self.assertContains(response, "Mon accompagnement")
        self.assertContains(response, "Coaching individuel et groupe")
        self.assertContains(response, "Premium")
        self.assertContains(response, "Derniers acces")
        self.assertContains(response, "Changer mon mot de passe")
        self.assertContains(response, "Mot de passe")
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

    def test_member_portal_hides_future_subscription_from_active_subscription_tab(self):
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

        response = self.client.get(reverse("members:member_portal"), {"tab": "subscription"})

        self.assertContains(response, "Aucun abonnement actif n'est rattache a ce compte.")
        self.assertNotContains(response, "<dd>Mensuel</dd>", html=False)

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

        response = self.client.post(
            reverse("members:member_notification_read", args=[notification.id])
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('members:member_portal')}?tab=messages")
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

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

    def test_member_can_change_password_from_portal(self):
        self.client.force_login(self.member.user)

        response = self.client.post(
            reverse("members:member_change_password"),
            {
                "old_password": "12345",
                "new_password1": "NouveauPass123!",
                "new_password2": "NouveauPass123!",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('members:member_portal')}?tab=home")
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

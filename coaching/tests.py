from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from compte.models import User, UserGymRole
from members.models import Member, MemberGoal, MemberWeightMeasurement
from organizations.models import Gym, GymModule, Module, Organization
from subscriptions.models import MemberSubscription, SubscriptionOffer, SubscriptionPlan

from .models import Coach, CoachAssignment, CoachingFeedback, CoachingFollowUp, GroupCoachingProgram


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
        self.coach_user = User.objects.create_user(
            username="coach-mobile",
            password="test-pass",
            first_name="Coach",
            last_name="A",
        )
        UserGymRole.objects.create(user=self.coach_user, gym=self.gym_a, role="coach")

        self.coach_a = Coach.objects.create(
            gym=self.gym_a,
            user=self.coach_user,
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
        self.plan_individual_a = SubscriptionPlan.objects.create(
            gym=self.gym_a,
            name="Coaching individuel",
            duration_days=30,
            price=50,
            coaching_mode=SubscriptionPlan.COACHING_MODE_INDIVIDUAL,
        )
        self.plan_group_a = SubscriptionPlan.objects.create(
            gym=self.gym_a,
            name="Coaching groupe",
            duration_days=30,
            price=40,
            coaching_mode=SubscriptionPlan.COACHING_MODE_GROUP,
        )
        self.plan_b = SubscriptionPlan.objects.create(
            gym=self.gym_b,
            name="Coaching externe",
            duration_days=30,
            price=55,
            coaching_mode=SubscriptionPlan.COACHING_MODE_BOTH,
        )
        self.offer_individual_a = SubscriptionOffer.objects.create(
            gym=self.gym_a,
            name="Acces coach individuel",
            category=SubscriptionOffer.CATEGORY_COACHING,
            grants_individual_coaching=True,
        )
        self.offer_group_a = SubscriptionOffer.objects.create(
            gym=self.gym_a,
            name="Acces coaching groupe",
            category=SubscriptionOffer.CATEGORY_COACHING,
            grants_group_coaching=True,
        )
        today = timezone.now().date()
        self.subscription_a = MemberSubscription.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            plan=self.plan_individual_a,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )
        MemberSubscription.objects.create(
            gym=self.gym_b,
            member=self.member_b,
            plan=self.plan_b,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )
        self.coach_b.members.add(self.member_b)
        self.client.login(username="coach-manager", password="test-pass")

    def test_coach_list_is_scoped_to_current_gym(self):
        response = self.client.get(reverse("coaching:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Coach A")
        self.assertNotContains(response, "Coach B")
        self.assertContains(response, "Coachs actifs")
        self.assertContains(response, "Membres sans coach")
        self.assertContains(response, "Nouveau workflow de pilotage")

    def test_coach_list_search_filters_results(self):
        response = self.client.get(reverse("coaching:list"), {"search": "Musculation"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Coach A")
        self.assertNotContains(response, "Coach B")

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
        self.assertTrue(
            CoachAssignment.objects.filter(
                coach=self.coach_a,
                member=self.member_a,
                ended_at__isnull=True,
            ).exists()
        )

    def test_assign_member_rejects_other_gym_member(self):
        response = self.client.post(
            reverse("coaching:assign_member", args=[self.coach_a.id]),
            {"member": self.member_b.id},
        )

        self.assertRedirects(response, reverse("coaching:detail", args=[self.coach_a.id]))
        self.assertFalse(self.coach_a.members.filter(id=self.member_b.id).exists())

    def test_assign_member_rejects_member_without_individual_coaching_rights(self):
        no_rights_member = Member.objects.create(
            gym=self.gym_a,
            first_name="Nina",
            last_name="NoRights",
            phone="333",
            email="nina.norights@example.com",
            status="active",
            is_active=True,
        )
        today = timezone.now().date()
        MemberSubscription.objects.create(
            gym=self.gym_a,
            member=no_rights_member,
            plan=self.plan_group_a,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )

        response = self.client.post(
            reverse("coaching:assign_member", args=[self.coach_a.id]),
            {"member": no_rights_member.id},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.coach_a.members.filter(id=no_rights_member.id).exists())
        self.assertContains(response, "Membre invalide pour ce coach")

    def test_assign_member_accepts_member_with_individual_coaching_offer_only(self):
        offer_plan = SubscriptionPlan.objects.create(
            gym=self.gym_a,
            name="Pack offre individuelle",
            duration_days=30,
            price=42,
            coaching_mode=SubscriptionPlan.COACHING_MODE_NONE,
        )
        offer_plan.offers.add(self.offer_individual_a)
        member = Member.objects.create(
            gym=self.gym_a,
            first_name="Offer",
            last_name="Individual",
            phone="334",
            email="offer.individual@example.com",
            status="active",
            is_active=True,
        )
        today = timezone.now().date()
        MemberSubscription.objects.create(
            gym=self.gym_a,
            member=member,
            plan=offer_plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )

        response = self.client.post(
            reverse("coaching:assign_member", args=[self.coach_a.id]),
            {"member": member.id},
        )

        self.assertRedirects(response, reverse("coaching:detail", args=[self.coach_a.id]))
        self.assertTrue(self.coach_a.members.filter(id=member.id).exists())

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
        self.assertFalse(
            CoachAssignment.objects.filter(
                coach=self.coach_a,
                member=self.member_a,
                ended_at__isnull=True,
            ).exists()
        )

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

    def test_coach_mobile_portal_is_available_for_coach_role(self):
        self.client.logout()
        self.client.login(username="coach-mobile", password="test-pass")
        self.coach_a.members.add(self.member_a)

        response = self.client.get(reverse("coaching:coach_portal"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Espace coach")
        self.assertContains(response, "Coach A")
        self.assertContains(response, "Alice Member")

    def test_coach_portal_hides_member_without_current_coaching_access(self):
        self.client.logout()
        self.client.login(username="coach-mobile", password="test-pass")
        self.coach_a.members.add(self.member_a)
        self.subscription_a.is_active = False
        self.subscription_a.save(update_fields=["is_active"])

        response = self.client.get(reverse("coaching:coach_portal"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Alice Member")

    def test_group_program_pages_are_scoped_to_current_gym(self):
        program = GroupCoachingProgram.objects.create(
            gym=self.gym_a,
            coach=self.coach_a,
            name="Transformation 8 semaines",
            objective="Perte de poids",
            capacity=10,
        )
        other_program = GroupCoachingProgram.objects.create(
            gym=self.gym_b,
            coach=self.coach_b,
            name="Yoga collectif",
            objective="Souplesse",
            capacity=8,
        )
        program.participants.add(self.member_a)
        other_program.participants.add(self.member_b)

        response = self.client.get(reverse("coaching:group_program_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Transformation 8 semaines")
        self.assertNotContains(response, "Yoga collectif")

        detail_response = self.client.get(reverse("coaching:group_program_detail", args=[program.id]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Alice Member")

        other_detail_response = self.client.get(reverse("coaching:group_program_detail", args=[other_program.id]))
        self.assertEqual(other_detail_response.status_code, 404)

    def test_group_program_rejects_member_without_group_coaching_rights(self):
        program = GroupCoachingProgram.objects.create(
            gym=self.gym_a,
            coach=self.coach_a,
            name="Team cardio",
            objective="Cardio",
            capacity=10,
        )

        with self.assertRaises(ValidationError):
            program.join_member(self.member_a)

    def test_group_program_accepts_member_with_group_coaching_offer_only(self):
        program = GroupCoachingProgram.objects.create(
            gym=self.gym_a,
            coach=self.coach_a,
            name="Team mobility",
            objective="Mobilite",
            capacity=10,
        )
        offer_plan = SubscriptionPlan.objects.create(
            gym=self.gym_a,
            name="Pack offre groupe",
            duration_days=30,
            price=38,
            coaching_mode=SubscriptionPlan.COACHING_MODE_NONE,
        )
        offer_plan.offers.add(self.offer_group_a)
        member = Member.objects.create(
            gym=self.gym_a,
            first_name="Offer",
            last_name="Group",
            phone="335",
            email="offer.group@example.com",
            status="active",
            is_active=True,
        )
        today = timezone.now().date()
        MemberSubscription.objects.create(
            gym=self.gym_a,
            member=member,
            plan=offer_plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )

        program.join_member(member)

        self.assertTrue(program.participants.filter(id=member.id).exists())

    def test_coach_can_open_member_follow_up_detail(self):
        self.client.logout()
        self.client.login(username="coach-mobile", password="test-pass")
        self.coach_a.members.add(self.member_a)

        response = self.client.get(reverse("coaching:coach_member_detail", args=[self.member_a.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Suivi membre")
        self.assertContains(response, "Alice Member")

    def test_coach_can_record_first_weight_when_coach_starts_goal(self):
        self.client.logout()
        self.client.login(username="coach-mobile", password="test-pass")
        self.coach_a.members.add(self.member_a)
        goal = MemberGoal.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            goal_type=MemberGoal.GOAL_LOSE_WEIGHT,
            target_weight="68.0",
            measurement_starter=MemberGoal.STARTER_COACH,
            created_by=self.coach_user,
        )

        response = self.client.post(
            reverse("coaching:coach_member_weight_measurement_create", args=[self.member_a.id]),
            {
                "weight": "75.0",
                "measured_at": timezone.localdate().isoformat(),
                "note": "Bilan initial",
            },
        )

        self.assertRedirects(response, reverse("coaching:coach_member_detail", args=[self.member_a.id]))
        measurement = MemberWeightMeasurement.objects.get(goal=goal)
        self.assertEqual(measurement.source, MemberWeightMeasurement.SOURCE_COACH)
        self.assertEqual(measurement.recorded_by, self.coach_user)

    def test_coach_cannot_record_first_weight_when_member_must_start_goal(self):
        self.client.logout()
        self.client.login(username="coach-mobile", password="test-pass")
        self.coach_a.members.add(self.member_a)
        goal = MemberGoal.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            goal_type=MemberGoal.GOAL_GAIN_WEIGHT,
            target_weight="82.0",
            measurement_starter=MemberGoal.STARTER_MEMBER,
            created_by=self.coach_user,
        )

        response = self.client.post(
            reverse("coaching:coach_member_weight_measurement_create", args=[self.member_a.id]),
            {
                "weight": "72.5",
                "measured_at": timezone.localdate().isoformat(),
                "note": "Tentative coach",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La premiere pesee doit etre enregistree par le membre.")
        self.assertFalse(MemberWeightMeasurement.objects.filter(goal=goal).exists())

    def test_coach_member_detail_shows_weight_goal_section(self):
        self.client.logout()
        self.client.login(username="coach-mobile", password="test-pass")
        self.coach_a.members.add(self.member_a)
        MemberGoal.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            goal_type=MemberGoal.GOAL_LOSE_WEIGHT,
            target_weight="69.0",
            measurement_starter=MemberGoal.STARTER_COACH,
            created_by=self.coach_user,
        )

        response = self.client.get(reverse("coaching:coach_member_detail", args=[self.member_a.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Objectif poids")
        self.assertContains(response, "Perte de poids")
        self.assertContains(response, "Commencer les releves")

    def test_coach_cannot_open_member_outside_portfolio(self):
        self.client.logout()
        self.client.login(username="coach-mobile", password="test-pass")

        response = self.client.get(reverse("coaching:coach_member_detail", args=[self.member_a.id]))

        self.assertEqual(response.status_code, 404)

    def test_coach_can_add_follow_up_for_assigned_member(self):
        self.client.logout()
        self.client.login(username="coach-mobile", password="test-pass")
        self.coach_a.members.add(self.member_a)

        response = self.client.post(
            reverse("coaching:coach_member_detail", args=[self.member_a.id]),
            {
                "interaction_type": CoachingFollowUp.INTERACTION_CALL,
                "summary": "Appel de bienvenue et cadrage des objectifs.",
                "next_action": "Prevoir un bilan complet",
                "next_follow_up_at": "2026-05-20",
            },
        )

        self.assertRedirects(response, reverse("coaching:coach_member_detail", args=[self.member_a.id]))
        follow_up = CoachingFollowUp.objects.get(member=self.member_a, coach=self.coach_a)
        self.assertEqual(follow_up.gym, self.gym_a)
        self.assertEqual(follow_up.interaction_type, CoachingFollowUp.INTERACTION_CALL)
        self.assertEqual(follow_up.next_action, "Prevoir un bilan complet")

    def test_coach_portal_shows_follow_up_shortcuts(self):
        self.client.logout()
        self.client.login(username="coach-mobile", password="test-pass")
        self.coach_a.members.add(self.member_a)
        CoachingFollowUp.objects.create(
            gym=self.gym_a,
            coach=self.coach_a,
            member=self.member_a,
            interaction_type=CoachingFollowUp.INTERACTION_FOLLOW_UP,
            summary="Relance simple",
            next_action="Verifier la reprise",
        )

        response = self.client.get(reverse("coaching:coach_portal"), {"tab": "members"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Voir le suivi membre")
        self.assertContains(response, "Dernier suivi")

    def test_coach_portal_surfaces_first_contact_alerts(self):
        self.client.logout()
        self.client.login(username="coach-mobile", password="test-pass")
        self.coach_a.members.add(self.member_a)
        CoachAssignment.objects.filter(coach=self.coach_a, member=self.member_a, ended_at__isnull=True).update(
            started_at=timezone.now() - timedelta(days=5)
        )

        response = self.client.get(reverse("coaching:coach_portal"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Priorites du jour")
        self.assertContains(response, "Premier contact en retard")
        self.assertContains(response, "Premier contact")

    def test_coach_portal_surfaces_sensitive_feedback_alerts(self):
        self.client.logout()
        self.client.login(username="coach-mobile", password="test-pass")
        self.coach_a.members.add(self.member_a)
        CoachingFeedback.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            coach=self.coach_a,
            overall_rating=2,
            listening_rating=2,
            clarity_rating=2,
            motivation_rating=3,
            availability_rating=2,
            comment="Je me sens peu suivi",
            wants_contact=True,
        )

        response = self.client.get(reverse("coaching:coach_portal"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Feedbacks sensibles")
        self.assertContains(response, "A rappeler")
        self.assertContains(response, "Je me sens peu suivi")

    def test_coach_portal_builds_unified_priority_queue(self):
        self.client.logout()
        self.client.login(username="coach-mobile", password="test-pass")
        self.coach_a.members.add(self.member_a)
        CoachingFeedback.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            coach=self.coach_a,
            overall_rating=2,
            listening_rating=2,
            clarity_rating=2,
            motivation_rating=2,
            availability_rating=2,
            comment="Besoin aide rapide",
            wants_contact=True,
        )

        response = self.client.get(reverse("coaching:coach_portal"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A traiter maintenant")
        self.assertContains(response, "Besoin aide rapide")

    def test_manager_dashboard_shows_follow_up_alerts(self):
        self.coach_a.members.add(self.member_a)
        CoachAssignment.objects.filter(coach=self.coach_a, member=self.member_a, ended_at__isnull=True).update(
            started_at=timezone.now() - timedelta(days=5)
        )
        CoachingFollowUp.objects.create(
            gym=self.gym_a,
            coach=self.coach_a,
            member=self.member_a,
            interaction_type=CoachingFollowUp.INTERACTION_FOLLOW_UP,
            summary="Relance a faire",
            next_action="Rappeler le membre",
            next_follow_up_at="2026-05-01",
        )

        response = self.client.get(reverse("coaching:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Relances en retard")
        self.assertContains(response, "Membres sans suivi trace")
        self.assertContains(response, "Dernier suivi")

    def test_manager_dashboard_shows_first_contact_and_stale_follow_up_alerts(self):
        self.coach_a.members.add(self.member_a)
        CoachAssignment.objects.filter(coach=self.coach_a, member=self.member_a, ended_at__isnull=True).update(
            started_at=timezone.now() - timedelta(days=20)
        )
        old_follow_up = CoachingFollowUp.objects.create(
            gym=self.gym_a,
            coach=self.coach_a,
            member=self.member_a,
            interaction_type=CoachingFollowUp.INTERACTION_FOLLOW_UP,
            summary="Ancien suivi",
            next_action="Reprendre contact",
        )
        CoachingFollowUp.objects.filter(id=old_follow_up.id).update(created_at=timezone.now() - timedelta(days=15))

        response = self.client.get(reverse("coaching:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Premiers contacts en retard")
        self.assertContains(response, "Suivis anciens")

    def test_manager_dashboard_shows_recent_feedbacks(self):
        self.coach_a.members.add(self.member_a)
        CoachingFeedback.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            coach=self.coach_a,
            overall_rating=4,
            listening_rating=4,
            clarity_rating=4,
            motivation_rating=5,
            availability_rating=4,
            comment="Tres bon suivi",
            wants_contact=True,
        )

        response = self.client.get(reverse("coaching:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Feedbacks recents")
        self.assertContains(response, "Tres bon suivi")
        self.assertContains(response, "A rappeler")

    def test_manager_dashboard_shows_sensitive_feedback_alerts(self):
        self.coach_a.members.add(self.member_a)
        CoachingFeedback.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            coach=self.coach_a,
            overall_rating=2,
            listening_rating=2,
            clarity_rating=2,
            motivation_rating=2,
            availability_rating=2,
            comment="Accompagnement trop faible",
            wants_contact=True,
        )

        response = self.client.get(reverse("coaching:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Feedbacks sensibles")
        self.assertContains(response, "Accompagnement trop faible")
        self.assertContains(response, "avis ont une note globale de 2/5 ou moins")

    def test_manager_dashboard_builds_priority_queue(self):
        self.coach_a.members.add(self.member_a)
        CoachingFeedback.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            coach=self.coach_a,
            overall_rating=2,
            listening_rating=2,
            clarity_rating=2,
            motivation_rating=2,
            availability_rating=2,
            comment="Sujet a escalader",
            wants_contact=True,
        )

        response = self.client.get(reverse("coaching:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "File manager a traiter")
        self.assertContains(response, "Sujet a escalader")

    def test_reassigning_member_closes_old_assignment_and_opens_new_one(self):
        self.coach_a.members.add(self.member_a)
        old_assignment = CoachAssignment.objects.get(coach=self.coach_a, member=self.member_a, ended_at__isnull=True)
        self.coach_a.members.remove(self.member_a)
        self.coach_b = Coach.objects.create(
            gym=self.gym_a,
            name="Coach C",
            phone="3000",
            specialty="Cardio",
        )
        self.coach_b.members.add(self.member_a)

        old_assignment.refresh_from_db()
        self.assertIsNotNone(old_assignment.ended_at)
        self.assertTrue(
            CoachAssignment.objects.filter(
                coach=self.coach_b,
                member=self.member_a,
                ended_at__isnull=True,
            ).exists()
        )

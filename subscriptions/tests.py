from datetime import timedelta

from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from compte.models import User
from members.models import Member
from organizations.models import Gym, GymModule, Module, Organization
from pos.models import CashRegister, Payment
from subscriptions.forms import MemberSubscriptionForm, SubscriptionPlanForm
from subscriptions.models import MemberSubscription, SubscriptionOffer, SubscriptionPlan
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
            coaching_mode=SubscriptionPlan.COACHING_MODE_INDIVIDUAL,
            coaching_level=SubscriptionPlan.COACHING_LEVEL_STANDARD,
        )
        self.plan_b = SubscriptionPlan.objects.create(
            gym=self.gym_b,
            name="Premium",
            duration_days=30,
            price=200,
            coaching_mode=SubscriptionPlan.COACHING_MODE_BOTH,
            coaching_level=SubscriptionPlan.COACHING_LEVEL_PREMIUM,
        )
        self.offer_a = SubscriptionOffer.objects.create(
            gym=self.gym_a,
            name="Acces coach",
            category=SubscriptionOffer.CATEGORY_COACHING,
            grants_individual_coaching=True,
        )
        self.offer_b = SubscriptionOffer.objects.create(
            gym=self.gym_b,
            name="Acces Zumba",
            category=SubscriptionOffer.CATEGORY_CLASS,
        )
        self.owner = User.objects.create_user(
            username="owner-subscriptions",
            password="pass12345",
            owned_organization=self.org_a,
        )
        module, _ = Module.objects.get_or_create(code="SUBSCRIPTIONS", defaults={"name": "Subscriptions"})
        GymModule.objects.get_or_create(gym=self.gym_a, module=module, defaults={"is_active": True})

    def test_subscription_form_querysets_are_scoped_to_current_gym(self):
        form = MemberSubscriptionForm(gym=self.gym_a)

        self.assertIn(self.member_a, form.fields["member"].queryset)
        self.assertNotIn(self.member_b, form.fields["member"].queryset)
        self.assertIn(self.plan_a, form.fields["plan"].queryset)
        self.assertNotIn(self.plan_b, form.fields["plan"].queryset)

    def test_plan_form_scopes_available_offers_to_current_gym(self):
        form = SubscriptionPlanForm(gym=self.gym_a)

        self.assertIn(self.offer_a, form.fields["offers"].queryset)
        self.assertNotIn(self.offer_b, form.fields["offers"].queryset)

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
                "coaching_mode": SubscriptionPlan.COACHING_MODE_NONE,
                "coaching_level": SubscriptionPlan.COACHING_LEVEL_STANDARD,
                "is_active": "on",
            },
            gym=self.gym_a,
        )
        other_gym_form = SubscriptionPlanForm(
            data={
                "name": "Mensuel",
                "duration_days": 45,
                "price": 150,
                "coaching_mode": SubscriptionPlan.COACHING_MODE_BOTH,
                "coaching_level": SubscriptionPlan.COACHING_LEVEL_PREMIUM,
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

    def test_plan_exposes_coaching_rights_payload(self):
        rights = self.plan_b.coaching_rights_payload()

        self.assertTrue(rights["has_any_access"])
        self.assertTrue(rights["allows_individual"])
        self.assertTrue(rights["allows_group"])
        self.assertEqual(rights["level"], SubscriptionPlan.COACHING_LEVEL_PREMIUM)

    def test_plan_can_grant_coaching_access_via_parametrable_offer(self):
        plan = SubscriptionPlan.objects.create(
            gym=self.gym_a,
            name="Pack offres",
            duration_days=30,
            price=120,
            coaching_mode=SubscriptionPlan.COACHING_MODE_NONE,
            coaching_level=SubscriptionPlan.COACHING_LEVEL_STANDARD,
        )
        plan.offers.add(self.offer_a)

        rights = plan.coaching_rights_payload()

        self.assertTrue(plan.allows_individual_coaching)
        self.assertFalse(plan.allows_group_coaching)
        self.assertTrue(rights["has_any_access"])
        self.assertEqual(rights["offers"][0]["name"], "Acces coach")

    def test_plan_form_derives_legacy_coaching_mode_from_selected_offers(self):
        form = SubscriptionPlanForm(
            data={
                "name": "Pack auto",
                "duration_days": 30,
                "price": 80,
                "offers": [str(self.offer_a.id)],
                "is_active": "on",
            },
            gym=self.gym_a,
        )

        self.assertTrue(form.is_valid(), form.errors)
        plan = form.save(commit=False)
        self.assertEqual(form.cleaned_data["coaching_mode"], SubscriptionPlan.COACHING_MODE_INDIVIDUAL)
        self.assertEqual(plan.coaching_mode, SubscriptionPlan.COACHING_MODE_INDIVIDUAL)

    def test_plan_list_requires_active_module(self):
        self.client.force_login(self.owner)
        GymModule.objects.filter(gym=self.gym_a, module__code="SUBSCRIPTIONS").update(is_active=False)
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()

        response = self.client.get(reverse("subscriptions:subscription_plan_list"))

        self.assertEqual(response.status_code, 403)

    def test_create_plan_can_assign_offers(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()

        response = self.client.post(
            reverse("subscriptions:create_subscription_plan"),
            {
                "name": "Pack hybride",
                "duration_days": 45,
                "price": 180,
                "description": "Formule avec options",
                "offers": [str(self.offer_a.id)],
                "coaching_mode": SubscriptionPlan.COACHING_MODE_NONE,
                "coaching_level": SubscriptionPlan.COACHING_LEVEL_STANDARD,
                "is_active": "on",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        plan = SubscriptionPlan.objects.get(gym=self.gym_a, name="Pack hybride")
        self.assertEqual(list(plan.offers.values_list("id", flat=True)), [self.offer_a.id])

    def test_delete_plan_requires_post(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()

        response = self.client.get(reverse("subscriptions:delete_subscription_plan", args=[self.plan_a.id]))

        self.assertEqual(response.status_code, 405)
        self.assertTrue(SubscriptionPlan.objects.filter(id=self.plan_a.id).exists())

    def test_create_offer_creates_offer_for_current_gym(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()

        response = self.client.post(
            reverse("subscriptions:create_subscription_offer"),
            {
                "offer-name": "Pack nutrition",
                "offer-category": SubscriptionOffer.CATEGORY_OTHER,
                "offer-description": "Conseils alimentaires inclus",
                "offer-grants_individual_coaching": "on",
                "offer-is_active": "on",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        offer = SubscriptionOffer.objects.get(gym=self.gym_a, name="Pack nutrition")
        self.assertEqual(offer.category, SubscriptionOffer.CATEGORY_OTHER)
        self.assertTrue(offer.grants_individual_coaching)
        self.assertFalse(offer.grants_group_coaching)

    def test_edit_offer_returns_json_payload_for_modal(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()

        response = self.client.get(
            reverse("subscriptions:edit_subscription_offer", args=[self.offer_a.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], self.offer_a.name)
        self.assertTrue(response.json()["grants_individual_coaching"])

    def test_edit_offer_updates_existing_offer(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()

        response = self.client.post(
            reverse("subscriptions:edit_subscription_offer", args=[self.offer_a.id]),
            {
                "offer-name": "Acces coach elite",
                "offer-category": SubscriptionOffer.CATEGORY_COACHING,
                "offer-description": "Version renforcee",
                "offer-grants_group_coaching": "on",
                "offer-is_active": "on",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.offer_a.refresh_from_db()
        self.assertEqual(self.offer_a.name, "Acces coach elite")
        self.assertFalse(self.offer_a.grants_individual_coaching)
        self.assertTrue(self.offer_a.grants_group_coaching)

    def test_edit_plan_updates_assigned_offers_and_mode(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()
        group_offer = SubscriptionOffer.objects.create(
            gym=self.gym_a,
            name="Acces groupe",
            category=SubscriptionOffer.CATEGORY_CLASS,
            grants_group_coaching=True,
        )
        self.plan_a.offers.add(self.offer_a)

        response = self.client.post(
            reverse("subscriptions:edit_subscription_plan", args=[self.plan_a.id]),
            {
                "name": "Mensuel optimise",
                "duration_days": 60,
                "price": 150,
                "description": "Formule mise a jour",
                "offers": [str(group_offer.id)],
                "coaching_mode": SubscriptionPlan.COACHING_MODE_NONE,
                "coaching_level": SubscriptionPlan.COACHING_LEVEL_STANDARD,
                "is_active": "on",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.plan_a.refresh_from_db()
        self.assertEqual(self.plan_a.name, "Mensuel optimise")
        self.assertEqual(self.plan_a.duration_days, 60)
        self.assertEqual(list(self.plan_a.offers.values_list("id", flat=True)), [group_offer.id])
        self.assertEqual(self.plan_a.coaching_mode, SubscriptionPlan.COACHING_MODE_GROUP)

    def test_create_subscription_shows_consistent_success_message(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()
        CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=0,
            exchange_rate=2800,
        )

        response = self.client.post(
            reverse("subscriptions:create_subscription"),
            {
                "member": self.member_a.id,
                "plan": self.plan_a.id,
                "start_date": timezone.now().date().isoformat(),
                "auto_renew": "on",
                "currency": "USD",
                "payment_method": "cash",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("Abonnement enregistre avec succes et paiement POS cree" in message for message in messages))
        subscription = MemberSubscription.objects.get(member=self.member_a, plan=self.plan_a)
        payment = Payment.objects.get(subscription=subscription)
        self.assertTrue(subscription.auto_renew)
        self.assertEqual(payment.category, "subscription")
        self.assertEqual(payment.amount_cdf, 280000)

    def test_create_subscription_requires_open_register_for_paid_activation(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()

        response = self.client.post(
            reverse("subscriptions:create_subscription"),
            {
                "member": self.member_a.id,
                "plan": self.plan_a.id,
                "start_date": timezone.now().date().isoformat(),
                "currency": "USD",
                "payment_method": "cash",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aucune caisse ouverte")
        self.assertFalse(MemberSubscription.objects.filter(member=self.member_a, plan=self.plan_a).exists())

    def test_plan_list_marks_best_selling_plan(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()

        second_member = Member.objects.create(
            gym=self.gym_a,
            first_name="Emma",
            last_name="Top",
            phone="10002",
            email="emma@example.com",
        )
        other_plan = SubscriptionPlan.objects.create(
            gym=self.gym_a,
            name="Annuel",
            duration_days=365,
            price=500,
            coaching_mode=SubscriptionPlan.COACHING_MODE_NONE,
            coaching_level=SubscriptionPlan.COACHING_LEVEL_STANDARD,
        )

        create_member_subscription(self.member_a, self.plan_a)
        create_member_subscription(self.member_a, self.plan_a)
        create_member_subscription(second_member, other_plan)

        response = self.client.get(reverse("subscriptions:subscription_plan_list"))

        self.assertEqual(response.status_code, 200)
        plans = list(response.context["plans"])
        mensuel = next(plan for plan in plans if plan.id == self.plan_a.id)
        annuel = next(plan for plan in plans if plan.id == other_plan.id)

        self.assertEqual(response.context["top_sales_count"], 2)
        self.assertEqual(mensuel.total_sales_count, 2)
        self.assertEqual(annuel.total_sales_count, 1)
        self.assertContains(response, "Plus vendue", count=1)

    def test_plan_list_excludes_future_subscriptions_from_active_counts(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym_a.id
        session.save()
        today = timezone.now().date()
        future_member = Member.objects.create(
            gym=self.gym_a,
            first_name="Future",
            last_name="Member",
            phone="10003",
            email="future.member@example.com",
        )

        MemberSubscription.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            plan=self.plan_a,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )
        MemberSubscription.objects.create(
            gym=self.gym_a,
            member=future_member,
            plan=self.plan_a,
            start_date=today + timedelta(days=5),
            end_date=today + timedelta(days=35),
            is_active=True,
        )

        response = self.client.get(reverse("subscriptions:subscription_plan_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_subscriptions_count"], 1)
        plan = next(plan for plan in response.context["plans"] if plan.id == self.plan_a.id)
        self.assertEqual(plan.active_members_count, 1)

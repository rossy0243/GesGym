from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from decimal import Decimal

from django.conf import settings
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from compte.models import User, UserGymRole
from members.models import Member
from organizations.models import Gym, GymModule, Module, Organization
from pos.models import CashRegister, Payment
from products.models import Product, StockMovement
from subscriptions import avantages, corrections
from subscriptions.forms import MemberSubscriptionForm, SubscriptionPlanForm
from subscriptions.models import (
    BenefitMovement,
    MemberSubscription,
    OfferItem,
    SubscriptionCorrection,
    SubscriptionOffer,
    SubscriptionPlan,
    SubscriptionRequest,
)
from pos.services import record_subscription_payment


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

    def test_a_new_sale_sets_the_gym_and_replaces_the_active_subscription(self):
        # Un abonnement ne nait plus que d'un paiement : la fonction qui le
        # creait sans paiement - et donc sans kit - a disparu.
        CashRegister.objects.create(
            gym=self.gym_a,
            opening_amount=Decimal("0.00"),
            exchange_rate=Decimal("2800.00"),
        )
        first_subscription, _ = record_subscription_payment(
            gym=self.gym_a, member=self.member_a, plan=self.plan_a,
            currency="USD", method="cash",
        )
        second_subscription, _ = record_subscription_payment(
            gym=self.gym_a, member=self.member_a, plan=self.plan_a,
            currency="USD", method="cash",
        )

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
            # Sans opened_by, aucune caisse n'est trouvee pour l'utilisateur
            # connecte et l'abonnement est refuse.
            opened_by=self.owner,
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

        if not CashRegister.objects.filter(gym=self.gym_a, is_closed=False).exists():
            CashRegister.objects.create(
                gym=self.gym_a,
                opening_amount=Decimal("0.00"),
                exchange_rate=Decimal("2800.00"),
            )
        for membre, formule in (
            (self.member_a, self.plan_a),
            (self.member_a, self.plan_a),
            (second_member, other_plan),
        ):
            record_subscription_payment(
                gym=self.gym_a, member=membre, plan=formule,
                currency="USD", method="cash",
            )

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


class SubscriptionRenewalTests(TestCase):
    """Renouvellement anticipe et encaissement d'un membre suspendu."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Renouv", slug="org-renouv"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Renouv",
            slug="gym-renouv",
            subdomain="gym-renouv",
        )
        module, _ = Module.objects.get_or_create(
            code="SUBSCRIPTIONS", defaults={"name": "Subscriptions"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.owner = User.objects.create_user(
            username="owner-renouv",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", duration_days=30, price=Decimal("100.00")
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Fidele",
            last_name="Renouv",
            phone="+243890000001",
            email="fidele.renouv@example.com",
        )
        CashRegister.objects.create(
            gym=self.gym,
            opened_by=self.owner,
            opening_amount=Decimal("0.00"),
            exchange_rate=Decimal("2800.00"),
        )
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()
        self.today = timezone.localdate()

    def _buy(self, member=None):
        return self.client.post(
            reverse("subscriptions:create_subscription"),
            {
                "member": (member or self.member).id,
                "plan": self.plan.id,
                "start_date": self.today.isoformat(),
                "currency": "USD",
                "payment_method": "cash",
            },
            follow=True,
        )

    def _messages(self, response):
        return [str(item) for item in response.context["messages"]]

    def _active(self, member=None):
        return MemberSubscription.objects.get(
            member=member or self.member, is_active=True
        )

    # --- Report des jours restants ------------------------------------------

    def test_early_renewal_carries_the_remaining_days_over(self):
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=self.today - timedelta(days=10),
            end_date=self.today + timedelta(days=20),
            is_active=True,
        )

        self._buy()

        subscription = self._active()
        self.assertEqual(
            (subscription.end_date - subscription.start_date).days,
            self.plan.duration_days + 20,
        )

    def test_the_carried_over_days_are_announced(self):
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=self.today - timedelta(days=10),
            end_date=self.today + timedelta(days=20),
            is_active=True,
        )

        response = self._buy()

        self.assertTrue(
            any("20 jour(s) restant(s)" in message for message in self._messages(response))
        )

    def test_a_first_subscription_gets_exactly_the_plan_duration(self):
        response = self._buy()

        subscription = self._active()
        self.assertEqual(
            (subscription.end_date - subscription.start_date).days,
            self.plan.duration_days,
        )
        self.assertFalse(
            any("reportes" in message for message in self._messages(response))
        )

    def test_an_expired_subscription_carries_nothing_over(self):
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=self.today - timedelta(days=60),
            end_date=self.today - timedelta(days=30),
            is_active=True,
        )

        self._buy()

        subscription = self._active()
        self.assertEqual(
            (subscription.end_date - subscription.start_date).days,
            self.plan.duration_days,
        )

    def test_only_one_subscription_stays_active(self):
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=self.today - timedelta(days=10),
            end_date=self.today + timedelta(days=20),
            is_active=True,
        )

        self._buy()

        self.assertEqual(
            MemberSubscription.objects.filter(
                member=self.member, is_active=True
            ).count(),
            1,
        )

    # --- Membre suspendu ------------------------------------------------------

    def test_paying_for_a_suspended_member_warns_the_desk(self):
        suspended = Member.objects.create(
            gym=self.gym,
            first_name="Bloque",
            last_name="Renouv",
            phone="+243890000002",
            email="bloque.renouv@example.com",
            status="suspended",
        )

        response = self._buy(suspended)

        self.assertTrue(
            any(
                "toujours suspendu" in message for message in self._messages(response)
            )
        )
        self.assertTrue(
            MemberSubscription.objects.filter(member=suspended).exists()
        )

    def test_suspended_members_are_flagged_in_the_dropdown(self):
        Member.objects.create(
            gym=self.gym,
            first_name="Bloque",
            last_name="Renouv",
            phone="+243890000003",
            email="bloque2.renouv@example.com",
            status="suspended",
        )

        form = MemberSubscriptionForm(gym=self.gym)

        labels = [str(label) for value, label in form.fields["member"].choices if value]
        self.assertIn("Bloque Renouv - SUSPENDU", labels)
        self.assertIn("Fidele Renouv", labels)

    def test_an_active_member_is_not_flagged(self):
        form = MemberSubscriptionForm(gym=self.gym)

        labels = [str(label) for value, label in form.fields["member"].choices if value]
        self.assertNotIn("Fidele Renouv - SUSPENDU", labels)


class PlanNameCollisionTests(TestCase):
    """
    Le refus doit dire ou chercher.

    Supprimer une formule qui a servi la desactive au lieu de l'effacer : son
    nom reste pris, mais elle ne saute plus aux yeux. Un message qui se
    contente de « ce nom existe deja » envoie chercher une formule qu'on croit
    absente.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Noms", slug="org-noms"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Noms",
            slug="gym-noms", subdomain="gym-noms",
        )

    def _formulaire(self, nom="Etudiant", instance=None):
        return SubscriptionPlanForm(
            data={
                "name": nom,
                "duration_days": 30,
                "price": "60",
                "description": "Destinee aux etudiants",
                "is_active": "on",
            },
            instance=instance,
            gym=self.gym,
        )

    def _formule(self, nom="Etudiant", active=True):
        return SubscriptionPlan.objects.create(
            gym=self.gym, name=nom, duration_days=30, price=50,
            is_active=active,
        )

    # --- Ce que dit le refus -------------------------------------------------

    def test_an_active_twin_says_it_is_active(self):
        self._formule(active=True)

        form = self._formulaire()

        self.assertFalse(form.is_valid())
        self.assertIn("active", form.errors["name"][0])

    def test_an_archived_twin_says_where_to_look(self):
        # Le cas qui piege : la formule est invisible dans la liste des
        # formules utilisables, mais son nom bloque toujours.
        self._formule(active=False)

        form = self._formulaire()

        self.assertFalse(form.is_valid())
        message = form.errors["name"][0]
        self.assertIn("desactivee", message)
        self.assertIn("Activer la formule", message)

    def test_the_message_names_the_blocking_plan(self):
        # Sans son nom ni son numero, on cherche a l'aveugle une formule qu'on
        # ne voit pas dans la liste.
        jumelle = self._formule(nom="Etudiant", active=False)

        message = self._formulaire().errors["name"][0]

        self.assertIn("Etudiant", message)
        self.assertIn(str(jumelle.id), message)

    def test_the_database_refusal_reads_differently(self):
        # Les deux chemins - validation du formulaire et contrainte de la base -
        # disaient exactement la meme phrase : rien ne permettait de savoir
        # lequel avait refuse, ni donc ou chercher.
        chemin = Path(settings.BASE_DIR) / "subscriptions" / "views.py"
        vues = chemin.read_text(encoding="utf-8")

        self.assertIn("La base a refuse ce nom", vues)
        self.assertNotIn(
            "Une formule avec ce nom existe deja dans ce gym", vues
        )

    def test_the_two_messages_differ(self):
        self._formule(active=True)
        actif = self._formulaire().errors["name"][0]

        SubscriptionPlan.objects.update(is_active=False)
        archive = self._formulaire().errors["name"][0]

        self.assertNotEqual(actif, archive)

    # --- La porte de sortie ---------------------------------------------------

    def test_an_archived_plan_can_be_revived_and_repriced(self):
        # C'est la sortie que le message indique : elle doit exister.
        archivee = self._formule(active=False)

        form = self._formulaire(instance=archivee)

        self.assertTrue(form.is_valid(), form.errors)
        plan = form.save()
        self.assertTrue(plan.is_active)
        self.assertEqual(plan.price, Decimal("60"))

    # --- Ce qui doit continuer de passer -----------------------------------------

    def test_a_free_name_is_accepted(self):
        self._formule(nom="Mensuel")

        self.assertTrue(self._formulaire(nom="Etudiant").is_valid())

    def test_the_same_name_in_another_gym_is_free(self):
        voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-noms-voisine", subdomain="gym-noms-voisine",
        )
        SubscriptionPlan.objects.create(
            gym=voisine, name="Etudiant", duration_days=30, price=50
        )

        self.assertTrue(self._formulaire().is_valid())

    def test_editing_a_plan_without_renaming_it_is_allowed(self):
        # Se heurter a son propre nom serait absurde.
        plan = self._formule()

        self.assertTrue(self._formulaire(instance=plan).is_valid())


class PlanCreationFailureTests(TestCase):
    """
    Ce que la base refuse, et ce qu'on en apprend.

    ``IntegrityError`` couvre toutes les atteintes a l'integrite : un nom en
    double, mais aussi un champ obligatoire absent. Le rattrapage annoncait un
    nom en double sans l'avoir verifie, ce qui a envoye chercher une formule
    qui n'existait pas.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Echec", slug="org-echec"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Echec",
            slug="gym-echec", subdomain="gym-echec",
        )
        module, _ = Module.objects.get_or_create(
            code="SUBSCRIPTIONS", defaults={"name": "Subscriptions"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.gerant = User.objects.create_user(
            username="gerant-echec", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _creer(self, nom="Etudiant", **extra):
        # Les champs d'invitation sont envoyes vides, comme le fait le vrai
        # formulaire. Les omettre laisserait Django appliquer le defaut du
        # modele et masquerait toute erreur de nettoyage : un champ vide n'est
        # pas un champ absent.
        charge = {
            "name": nom,
            "duration_days": 30,
            "price": "60",
            "description": "Destinee aux etudiants",
            "is_active": "on",
            "guest_invites_per_month": "",
            "guest_sessions_per_invite": "",
        }
        charge.update(extra)
        return self.client.post(
            reverse("subscriptions:create_subscription_plan"),
            charge,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_a_free_name_is_created(self):
        reponse = self._creer()

        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(
            SubscriptionPlan.objects.filter(gym=self.gym, name="Etudiant").exists()
        )

    def test_empty_invitation_fields_fall_back_to_the_defaults(self):
        # Le defaut du modele ne s'applique qu'aux champs absents. Envoyes
        # vides, ils arrivaient a None et la base refusait tout la formule -
        # en annoncant un nom deja pris, ce qui n'avait rien a voir.
        self._creer()

        plan = SubscriptionPlan.objects.get(gym=self.gym, name="Etudiant")
        self.assertEqual(plan.guest_invites_per_month, 0)
        self.assertEqual(plan.guest_sessions_per_invite, 1)

    def test_invitation_quotas_are_kept_when_given(self):
        self._creer(guest_invites_per_month="2", guest_sessions_per_invite="3")

        plan = SubscriptionPlan.objects.get(gym=self.gym, name="Etudiant")
        self.assertEqual(plan.guest_invites_per_month, 2)
        self.assertEqual(plan.guest_sessions_per_invite, 3)

    def test_the_form_catches_the_duplicate_before_the_database(self):
        # La validation doit prendre la main la premiere : c'est elle qui sait
        # nommer la formule fautive.
        self._creer()

        reponse = self._creer()

        self.assertEqual(reponse.status_code, 400)
        message = reponse.json()["errors"]["name"][0]
        self.assertIn("porte deja ce nom", message)
        self.assertNotIn("La base a refuse", message)

    def test_a_database_refusal_is_written_to_the_log(self):
        # Sans cette trace, une atteinte a l'integrite qui n'a rien a voir avec
        # le nom continuerait de se faire passer pour un doublon.
        from django.db import IntegrityError

        with patch.object(
            SubscriptionPlan, "save", side_effect=IntegrityError("null value in column gym_id")
        ):
            with self.assertLogs("subscriptions", level="WARNING") as journal:
                reponse = self._creer(nom="Inedit")

        self.assertEqual(reponse.status_code, 400)
        trace = chr(10).join(journal.output)
        self.assertIn("refusee par la base", trace)
        self.assertIn("gym_id", trace)


class SubscriptionCorrectionTests(TestCase):
    """
    Reparer une periode mal saisie.

    Une receptionniste a vendu une periode deja terminee : le membre paie et
    n'a aucun acces. Corriger les dates repare l'acces sans toucher a l'argent.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Correction", slug="org-correction"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Correction",
            slug="gym-correction", subdomain="gym-correction",
        )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        self.member = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243870001111",
        )
        self.gerant = User.objects.create_user(
            username="gerant-correction", password="pass12345"
        )
        self.proprietaire = User.objects.create_user(
            username="proprio-correction", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )

        # L'erreur reelle : une periode close le mois dernier.
        self.faux_debut = timezone.localdate() - timedelta(days=60)
        self.abonnement = MemberSubscription.objects.create(
            gym=self.gym, member=self.member, plan=self.plan,
            start_date=self.faux_debut,
            end_date=self.faux_debut + timedelta(days=30),
            is_active=True,
        )

    def _corriger(self, debut=None, motif="Erreur de saisie a l'accueil", par=None):
        return corrections.corriger(
            self.abonnement,
            debut or timezone.localdate(),
            motif,
            par or self.gerant,
        )

    # --- Ce que la correction repare ---------------------------------------------

    def test_the_member_had_no_access_before(self):
        self.assertIsNone(self.member.active_subscription)

    def test_correcting_gives_the_access_back(self):
        self._corriger()

        self.assertIsNotNone(self.member.active_subscription)

    def test_the_end_date_follows_the_plan_duration(self):
        # Une correction ne doit pas pouvoir allonger discretement un
        # abonnement : la fin se recalcule, elle ne se saisit pas.
        debut = timezone.localdate()

        self._corriger(debut=debut)

        self.abonnement.refresh_from_db()
        self.assertEqual(self.abonnement.end_date, debut + timedelta(days=30))

    def test_the_payment_is_never_touched(self):
        # C'est la frontiere du dispositif : corriger une periode n'annule pas
        # une vente. L'argent a bien ete encaisse.
        avant = Payment.objects.filter(gym=self.gym).count()

        self._corriger()

        self.assertEqual(Payment.objects.filter(gym=self.gym).count(), avant)

    def test_the_previous_period_is_kept(self):
        self._corriger()

        trace = SubscriptionCorrection.objects.get(subscription=self.abonnement)
        self.assertEqual(trace.previous_start, self.faux_debut)
        self.assertEqual(trace.new_start, timezone.localdate())

    def test_the_correction_takes_effect_at_once(self):
        # Elle n'attend aucune validation : le membre retrouve son acces
        # sur-le-champ, meme un dimanche.
        trace = self._corriger()

        self.abonnement.refresh_from_db()
        self.assertTrue(self.abonnement.is_active)
        self.assertFalse(trace.is_acknowledged)

    # --- Ce qui est refuse ----------------------------------------------------------

    def test_a_correction_without_a_reason_is_refused(self):
        with self.assertRaises(ValidationError) as capture:
            self._corriger(motif="   ")

        self.assertIn("motif", str(capture.exception).lower())

    def test_the_same_date_is_refused(self):
        with self.assertRaises(ValidationError) as capture:
            self._corriger(debut=self.faux_debut)

        self.assertIn("rien a corriger", str(capture.exception))

    def test_a_subscription_can_be_corrected_as_often_as_needed(self):
        # Le plafond de deux protegeait contre un gerant qui deplacerait une
        # periode a repetition. La correction est reservee au proprietaire : le
        # plafond n'a plus d'objet.
        for decalage in range(4):
            self._corriger(debut=timezone.localdate() - timedelta(days=decalage))

        self.assertEqual(
            SubscriptionCorrection.objects.filter(subscription=self.abonnement).count(),
            4,
        )

    def test_an_overlapping_period_is_refused(self):
        # Le membre a rachete depuis : deplacer l'ancienne periode ne doit pas
        # lui offrir deux abonnements simultanes.
        MemberSubscription.objects.create(
            gym=self.gym, member=self.member, plan=self.plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )

        with self.assertRaises(ValidationError) as capture:
            self._corriger(debut=timezone.localdate() + timedelta(days=5))

        self.assertIn("chevauche", str(capture.exception))

    # --- L'accuse de reception --------------------------------------------------------

    def test_a_managers_correction_waits_to_be_seen(self):
        self._corriger(par=self.gerant)

        self.assertEqual(corrections.en_attente(self.gym).count(), 1)

    def test_an_owners_own_correction_needs_no_acknowledgement(self):
        # Il n'a pas a s'accuser reception a lui-meme.
        corrections.corriger(
            self.abonnement, timezone.localdate(), "Je corrige moi-meme",
            self.proprietaire, acquitte=True,
        )

        self.assertEqual(corrections.en_attente(self.gym).count(), 0)

    def test_acknowledging_clears_the_banner(self):
        trace = self._corriger()

        corrections.accuser_reception(trace, self.proprietaire)

        self.assertEqual(corrections.en_attente(self.gym).count(), 0)
        trace.refresh_from_db()
        self.assertEqual(trace.acknowledged_by, self.proprietaire)

    def test_acknowledging_twice_keeps_the_first_reader(self):
        trace = self._corriger()
        corrections.accuser_reception(trace, self.proprietaire)
        premier = trace.acknowledged_at

        corrections.accuser_reception(trace, self.gerant)

        trace.refresh_from_db()
        self.assertEqual(trace.acknowledged_at, premier)
        self.assertEqual(trace.acknowledged_by, self.proprietaire)

    def test_another_gym_correction_stays_out(self):
        autre = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-correction-voisine", subdomain="gym-correction-voisine",
        )
        self._corriger()

        self.assertEqual(corrections.en_attente(autre).count(), 0)

    # --- L'avertissement a la saisie ---------------------------------------------------

    def test_a_closed_period_is_detected(self):
        ancien = timezone.localdate() - timedelta(days=60)

        self.assertTrue(corrections.periode_close(ancien, self.plan))

    def test_a_recent_start_is_not_a_closed_period(self):
        # Saisir la vente d'hier reste legitime : seule une periode deja
        # terminee doit alerter.
        recent = timezone.localdate() - timedelta(days=5)

        self.assertFalse(corrections.periode_close(recent, self.plan))

    def test_today_is_never_a_closed_period(self):
        self.assertFalse(corrections.periode_close(timezone.localdate(), self.plan))


class SubscriptionCorrectionViewTests(TestCase):
    """
    La correction depuis la fiche du membre.

    Le piege du dispositif : l'abonnement fautif est deja termine, donc
    invisible partout. Sans l'historique, personne ne pourrait l'atteindre.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Correction Vue", slug="org-correction-vue"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Correction Vue",
            slug="gym-correction-vue", subdomain="gym-correction-vue",
        )
        for code in ("MEMBERS", "SUBSCRIPTIONS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )

        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        self.member = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243870002222",
        )
        self.faux_debut = timezone.localdate() - timedelta(days=60)
        self.abonnement = MemberSubscription.objects.create(
            gym=self.gym, member=self.member, plan=self.plan,
            start_date=self.faux_debut,
            end_date=self.faux_debut + timedelta(days=30),
            is_active=True,
        )

        self.gerant = self._utilisateur("gerant-correction-vue", "manager")
        # La correction est reservee au proprietaire : c'est lui qu'on connecte.
        self.proprietaire = self._utilisateur("proprio-principal-vue", "owner")
        self._connecter(self.proprietaire)

    def _utilisateur(self, nom, role):
        utilisateur = User.objects.create_user(username=nom, password="pass12345")
        UserGymRole.objects.create(
            user=utilisateur, gym=self.gym, role=role, is_active=True
        )
        return utilisateur

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _fiche(self):
        return self.client.get(
            reverse("members:member_detail", args=[self.member.id])
        ).json()

    def _corriger(self, debut=None, motif="Date saisie a l envers"):
        return self.client.post(
            reverse("subscriptions:correct_subscription", args=[self.abonnement.id]),
            {
                "start_date": (debut or timezone.localdate()).isoformat(),
                "reason": motif,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    # --- La fiche expose l'abonnement fautif -------------------------------------

    def test_the_expired_subscription_is_invisible_in_the_active_slot(self):
        # C'est tout le probleme : la fiche ne montre que l'abonnement en
        # cours, et il n'y en a pas.
        self.assertIsNone(self._fiche()["start_date"])

    def test_the_history_still_shows_it(self):
        historique = self._fiche()["subscriptions"]

        self.assertEqual(len(historique), 1)
        self.assertEqual(historique[0]["id"], self.abonnement.id)
        self.assertEqual(historique[0]["state"], "Termine")

    def test_the_owner_is_offered_the_correction(self):
        self.assertTrue(self._fiche()["subscriptions"][0]["can_correct"])

    def test_a_manager_is_no_longer_offered_the_correction(self):
        self._connecter(self.gerant)

        self.assertFalse(self._fiche()["subscriptions"][0]["can_correct"])

    def test_a_receptionist_is_not_offered_the_correction(self):
        self._connecter(self._utilisateur("accueil-correction-vue", "reception"))

        self.assertFalse(self._fiche()["subscriptions"][0]["can_correct"])

    def test_a_corrected_subscription_is_still_offered(self):
        # Plus de plafond : une periode corrigee deux fois reste corrigeable.
        corrections.corriger(
            self.abonnement, timezone.localdate(), "un", self.proprietaire, acquitte=True
        )
        corrections.corriger(
            self.abonnement, timezone.localdate() - timedelta(days=1),
            "deux", self.proprietaire, acquitte=True,
        )

        self.assertTrue(self._fiche()["subscriptions"][0]["can_correct"])

    def test_the_history_carries_the_past_corrections(self):
        corrections.corriger(
            self.abonnement, timezone.localdate(), "Erreur d accueil", self.gerant
        )

        trace = self._fiche()["subscriptions"][0]["corrections"][0]
        self.assertEqual(trace["reason"], "Erreur d accueil")
        self.assertIn(self.faux_debut.strftime("%d/%m/%Y"), trace["previous"])

    def test_a_neighbouring_members_subscription_stays_out(self):
        voisin = Member.objects.create(
            gym=self.gym, first_name="Bob", last_name="Kasa",
            phone="+243870003333",
        )
        MemberSubscription.objects.create(
            gym=self.gym, member=voisin, plan=self.plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )

        historique = self._fiche()["subscriptions"]
        self.assertEqual([ligne["id"] for ligne in historique], [self.abonnement.id])

    # --- La correction elle-meme -------------------------------------------------

    def test_a_manager_can_no_longer_correct(self):
        self._connecter(self.gerant)

        reponse = self._corriger()

        self.assertEqual(reponse.status_code, 403)
        self.abonnement.refresh_from_db()
        self.assertEqual(self.abonnement.start_date, self.faux_debut)

    def test_the_owner_can_correct_and_the_member_gets_access_back(self):
        reponse = self._corriger()

        self.assertTrue(reponse.json()["success"])
        self.assertIsNotNone(self.member.active_subscription)

    def test_a_cashier_cannot_correct(self):
        self._connecter(self._utilisateur("caisse-correction-vue", "cashier"))

        self.assertEqual(self._corriger().status_code, 403)

    def test_a_correction_without_a_reason_is_refused(self):
        reponse = self._corriger(motif="  ")

        self.assertEqual(reponse.status_code, 400)
        self.assertIn("motif", reponse.json()["error"].lower())
        self.abonnement.refresh_from_db()
        self.assertEqual(self.abonnement.start_date, self.faux_debut)

    def test_the_owners_correction_is_acknowledged_at_once(self):
        # Il n'a pas a s'accuser reception a lui-meme : rien n'arrive au bandeau.
        self._corriger()

        self.assertEqual(corrections.en_attente(self.gym).count(), 0)

    def test_an_owners_correction_needs_no_acknowledgement(self):
        self._connecter(self._utilisateur("proprio-correction-vue", "owner"))

        self._corriger()

        self.assertEqual(corrections.en_attente(self.gym).count(), 0)

    def test_a_neighbouring_gym_subscription_cannot_be_corrected(self):
        voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-correction-vue-voisine",
            subdomain="gym-correction-vue-voisine",
        )
        ailleurs = MemberSubscription.objects.create(
            gym=voisine,
            member=Member.objects.create(
                gym=voisine, first_name="Zoe", last_name="Nsimba",
                phone="+243870004444",
            ),
            plan=SubscriptionPlan.objects.create(
                gym=voisine, name="Mensuel", price=30, duration_days=30
            ),
            start_date=self.faux_debut - timedelta(days=200),
            end_date=self.faux_debut - timedelta(days=170),
            is_active=True,
        )

        reponse = self.client.post(
            reverse("subscriptions:correct_subscription", args=[ailleurs.id]),
            {"start_date": timezone.localdate().isoformat(), "reason": "x"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(reponse.status_code, 404)

    # --- L'accuse de reception ---------------------------------------------------

    def test_the_owner_can_acknowledge(self):
        # Une correction faite par un gerant avant que ce geste lui soit retire
        # reste a acquitter : le bandeau sert encore pour elle.
        trace = corrections.corriger(
            self.abonnement, timezone.localdate(), "Ancienne correction", self.gerant
        )
        self._connecter(self._utilisateur("proprio-accuse", "owner"))

        reponse = self.client.post(
            reverse("subscriptions:acknowledge_correction", args=[trace.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertTrue(reponse.json()["success"])
        self.assertEqual(corrections.en_attente(self.gym).count(), 0)

    def test_a_manager_cannot_acknowledge(self):
        # L'accuse de reception reste reserve au proprietaire, y compris pour
        # les corrections faites par un gerant avant la revision.
        trace = corrections.corriger(
            self.abonnement, timezone.localdate(), "Ancienne correction", self.gerant
        )
        self._connecter(self.gerant)

        reponse = self.client.post(
            reverse("subscriptions:acknowledge_correction", args=[trace.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(corrections.en_attente(self.gym).count(), 1)


class SubscriptionCorrectionBannerTests(TestCase):
    """
    Le bandeau du proprietaire.

    C'est la contrepartie du dispositif : un gerant peut deplacer une periode
    vendue, et cela prend effet aussitot. Le proprietaire doit l'apprendre
    autrement que par une ligne de journal qu'il pourrait ne jamais lire.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Bandeau", slug="org-bandeau"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Bandeau",
            slug="gym-bandeau", subdomain="gym-bandeau",
        )
        module, _ = Module.objects.get_or_create(
            code="MEMBERS", defaults={"name": "MEMBERS"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )

        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        self.member = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243870006666",
        )
        faux_debut = timezone.localdate() - timedelta(days=60)
        self.abonnement = MemberSubscription.objects.create(
            gym=self.gym, member=self.member, plan=self.plan,
            start_date=faux_debut, end_date=faux_debut + timedelta(days=30),
            is_active=True,
        )
        self.gerant = self._utilisateur("gerant-bandeau", "manager")
        self.proprietaire = self._utilisateur("proprio-bandeau", "owner")

    def _utilisateur(self, nom, role):
        utilisateur = User.objects.create_user(username=nom, password="pass12345")
        UserGymRole.objects.create(
            user=utilisateur, gym=self.gym, role=role, is_active=True
        )
        return utilisateur

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _page(self):
        return self.client.get(reverse("members:member_list"))

    def test_the_owner_is_shown_the_correction(self):
        corrections.corriger(
            self.abonnement, timezone.localdate(), "Erreur d accueil", self.gerant
        )
        self._connecter(self.proprietaire)

        reponse = self._page()

        self.assertContains(reponse, "Erreur d accueil")
        self.assertEqual(
            reponse.context["subscription_corrections_banner"]["total"], 1
        )

    def test_the_manager_who_corrected_sees_no_banner(self):
        corrections.corriger(
            self.abonnement, timezone.localdate(), "Erreur d accueil", self.gerant
        )
        self._connecter(self.gerant)

        self.assertIsNone(
            self._page().context["subscription_corrections_banner"]
        )

    def test_the_banner_goes_once_acknowledged(self):
        trace = corrections.corriger(
            self.abonnement, timezone.localdate(), "Erreur d accueil", self.gerant
        )
        corrections.accuser_reception(trace, self.proprietaire)
        self._connecter(self.proprietaire)

        self.assertIsNone(
            self._page().context["subscription_corrections_banner"]
        )

    def test_nothing_shows_when_nothing_was_corrected(self):
        self._connecter(self.proprietaire)

        self.assertIsNone(
            self._page().context["subscription_corrections_banner"]
        )

    def test_a_neighbouring_gym_correction_stays_out(self):
        voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-bandeau-voisine", subdomain="gym-bandeau-voisine",
        )
        GymModule.objects.get_or_create(
            gym=voisine, module=Module.objects.get(code="MEMBERS"),
            defaults={"is_active": True},
        )
        UserGymRole.objects.create(
            user=self.proprietaire, gym=voisine, role="owner", is_active=True
        )
        corrections.corriger(
            self.abonnement, timezone.localdate(), "Erreur d accueil", self.gerant
        )

        self.client.force_login(self.proprietaire)
        session = self.client.session
        session["current_gym_id"] = voisine.id
        session.save()

        self.assertIsNone(
            self._page().context["subscription_corrections_banner"]
        )


class GuestInvitationVisibilityTests(TestCase):
    """
    Le droit d'inviter, annonce comme une offre.

    Il se parametre sur la formule et non dans la table des offres : il
    n'apparaissait donc nulle part ou l'on lit ce qu'une formule comprend.
    Vendu sans etre annonce, il passait inapercu.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Invitation Vue", slug="org-invitation-vue"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Invitation Vue",
            slug="gym-invitation-vue", subdomain="gym-invitation-vue",
        )
        for code in ("MEMBERS", "SUBSCRIPTIONS"):
            module, _ = Module.objects.get_or_create(
                code=code, defaults={"name": code}
            )
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )

        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Premium", price=50, duration_days=30,
            guest_invites_per_month=1, guest_sessions_per_invite=1,
        )
        self.sans_invitation = SubscriptionPlan.objects.create(
            gym=self.gym, name="Basique", price=20, duration_days=30,
        )
        self.gerant = User.objects.create_user(
            username="gerant-invitation-vue", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.gerant, gym=self.gym, role="manager", is_active=True
        )
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    # --- Le libelle ------------------------------------------------------------

    def test_a_plan_without_invitations_says_nothing(self):
        # A zero, la formule n'offre rien : elle ne doit rien annoncer.
        self.assertEqual(self.sans_invitation.guest_invitation_label, "")

    def test_one_guest_and_one_session_is_said_in_the_singular(self):
        self.assertEqual(
            self.plan.guest_invitation_label,
            "Invitation : 1 invite / 30 jours (1 seance)",
        )

    def test_several_guests_and_sessions_are_said_in_the_plural(self):
        self.plan.guest_invites_per_month = 3
        self.plan.guest_sessions_per_invite = 2

        self.assertEqual(
            self.plan.guest_invitation_label,
            "Invitation : 3 invites / 30 jours (2 seances)",
        )

    def test_the_window_is_thirty_days_not_a_calendar_month(self):
        # Un abonnement pris le 29 ne doit pas donner deux jours de droit.
        self.assertIn("30 jours", self.plan.guest_invitation_label)

    # --- La liste des avantages ------------------------------------------------

    def test_the_invitation_joins_the_offers(self):
        self.plan.offers.add(
            SubscriptionOffer.objects.create(
                gym=self.gym, name="Sauna", is_active=True
            )
        )

        self.assertEqual(
            self.plan.advantage_labels,
            ["Sauna", "Invitation : 1 invite / 30 jours (1 seance)"],
        )

    def test_a_plan_without_offers_still_announces_its_invitation(self):
        self.assertEqual(
            self.plan.advantage_labels,
            ["Invitation : 1 invite / 30 jours (1 seance)"],
        )

    def test_an_inactive_offer_stays_out(self):
        self.plan.offers.add(
            SubscriptionOffer.objects.create(
                gym=self.gym, name="Sauna", is_active=False
            )
        )

        self.assertNotIn("Sauna", self.plan.advantage_labels)

    def test_a_plan_with_neither_announces_nothing(self):
        self.assertEqual(self.sans_invitation.advantage_labels, [])

    # --- Les ecrans ------------------------------------------------------------

    def test_the_plan_list_shows_it(self):
        reponse = self.client.get(reverse("subscriptions:subscription_plan_list"))

        self.assertContains(reponse, "Invitation : 1 invite / 30 jours (1 seance)")

    def test_the_cashier_screen_flags_the_plan(self):
        module, _ = Module.objects.get_or_create(code="POS", defaults={"name": "POS"})
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )

        reponse = self.client.get(reverse("pos:cashier_dashboard"))

        self.assertContains(reponse, "invitation incluse")

    def test_the_member_sheet_lists_it_among_the_offers(self):
        member = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243870007777",
        )
        MemberSubscription.objects.create(
            gym=self.gym, member=member, plan=self.plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )

        fiche = self.client.get(
            reverse("members:member_detail", args=[member.id])
        ).json()

        self.assertIn(
            "Invitation : 1 invite / 30 jours (1 seance)",
            fiche["subscription_offers"],
        )

    def test_the_public_pricing_announces_it(self):
        from website.branding import landing_plans

        formules = {f["name"]: f for f in landing_plans(self.organization)}

        self.assertIn(
            "Invitation : 1 invite / 30 jours (1 seance)",
            formules["Premium"]["offers"],
        )
        self.assertEqual(formules["Basique"]["offers"], [])


class SubscriptionKitTests(TestCase):
    """
    Le kit d'une formule.

    Un membre qui paie sa formule Premium recoit une serviette et quelques
    bouteilles d'eau. Le solde se reporte d'un paiement au suivant, ce qui est
    pris ne se recredite pas, et aucun article offert ne passe par la caisse.
    """

    def setUp(self):
        self.organization = Organization.objects.create(name="Org Kit", slug="org-kit")
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Kit",
            slug="gym-kit", subdomain="gym-kit",
        )
        for code in ("MEMBERS", "SUBSCRIPTIONS", "POS", "ACCESS"):
            module, _ = Module.objects.get_or_create(code=code, defaults={"name": code})
            GymModule.objects.get_or_create(
                gym=self.gym, module=module, defaults={"is_active": True}
            )

        self.caissiere = self._utilisateur("caisse-kit", "cashier")
        self.registre = CashRegister.objects.create(
            gym=self.gym, opened_by=self.caissiere,
            opening_amount=Decimal("0.00"), exchange_rate=Decimal("2800.00"),
        )
        self.premium = SubscriptionPlan.objects.create(
            gym=self.gym, name="Premium", price=50, duration_days=30
        )
        self.standard = SubscriptionPlan.objects.create(
            gym=self.gym, name="Standard", price=30, duration_days=30
        )
        self.serviette = Product.objects.create(
            gym=self.gym, name="Serviette", price=Decimal("5000"),
            currency=Product.CURRENCY_CDF, quantity=20,
        )
        self.bouteille = Product.objects.create(
            gym=self.gym, name="Bouteille d'eau", price=Decimal("1000"),
            currency=Product.CURRENCY_CDF, quantity=50,
        )
        self.kit = SubscriptionOffer.objects.create(
            gym=self.gym, name="Kit Premium", is_active=True
        )
        avantages.definir_articles(
            self.kit, [(self.serviette.id, 1), (self.bouteille.id, 4)]
        )
        self.premium.offers.add(self.kit)
        self.membre = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala", phone="+243870123456",
        )

    # --- Fabriques ---------------------------------------------------------------

    def _utilisateur(self, nom, role, gym=None):
        utilisateur = User.objects.create_user(username=nom, password="pass12345")
        UserGymRole.objects.create(
            user=utilisateur, gym=gym or self.gym, role=role, is_active=True
        )
        return utilisateur

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _vendre(self, plan=None):
        return record_subscription_payment(
            gym=self.gym, member=self.membre, plan=plan or self.premium,
            currency="USD", method="cash", created_by=self.caissiere,
        )

    def _solde(self, produit):
        return avantages.solde(self.membre, produit)

    # --- Le credit ------------------------------------------------------------------

    def test_a_sale_credits_the_kit(self):
        self._vendre()

        self.assertEqual(self._solde(self.serviette), 1)
        self.assertEqual(self._solde(self.bouteille), 4)

    def test_a_renewal_credits_it_again_and_carries_over(self):
        # Ce qui n'a pas ete pris s'ajoute au kit suivant.
        self._vendre()
        self._vendre()

        self.assertEqual(self._solde(self.serviette), 2)
        self.assertEqual(self._solde(self.bouteille), 8)

    def test_a_plan_without_the_offer_credits_nothing(self):
        self._vendre(plan=self.standard)

        self.assertFalse(BenefitMovement.objects.filter(member=self.membre).exists())

    def test_an_inactive_offer_credits_nothing(self):
        SubscriptionOffer.objects.filter(pk=self.kit.pk).update(is_active=False)

        self._vendre()

        self.assertEqual(self._solde(self.bouteille), 0)

    def test_the_same_article_in_two_offers_adds_up(self):
        bonus = SubscriptionOffer.objects.create(gym=self.gym, name="Bonus", is_active=True)
        avantages.definir_articles(bonus, [(self.bouteille.id, 2)])
        self.premium.offers.add(bonus)

        self._vendre()

        self.assertEqual(self._solde(self.bouteille), 6)
        self.assertEqual(
            BenefitMovement.objects.filter(
                member=self.membre, product=self.bouteille, kind=BenefitMovement.KIND_CREDIT
            ).count(),
            1,
        )

    def test_crediting_creates_no_payment(self):
        # Le seul paiement est celui de l'abonnement : le kit ne passe pas par
        # la caisse.
        self._vendre()

        self.assertEqual(Payment.objects.filter(gym=self.gym).count(), 1)

    def test_changing_the_kit_only_affects_future_sales(self):
        self._vendre()

        avantages.definir_articles(self.kit, [(self.bouteille.id, 10)])

        self.assertEqual(self._solde(self.serviette), 1)
        self.assertEqual(self._solde(self.bouteille), 4)
        self._vendre()
        self.assertEqual(self._solde(self.bouteille), 14)

    # --- La remise -----------------------------------------------------------------

    def test_giving_an_article_lowers_the_stock_and_the_balance(self):
        self._vendre()

        avantages.remettre(self.membre, self.bouteille.id, 3, par=self.caissiere)

        self.bouteille.refresh_from_db()
        self.assertEqual(self.bouteille.quantity, 47)
        self.assertEqual(self._solde(self.bouteille), 1)

    def test_giving_creates_no_payment(self):
        # Une vente a zero ferait apparaitre une fausse vente dans les
        # encaissements.
        self._vendre()
        avant = Payment.objects.filter(gym=self.gym).count()

        avantages.remettre(self.membre, self.serviette.id, 1, par=self.caissiere)

        self.assertEqual(Payment.objects.filter(gym=self.gym).count(), avant)

    def test_the_stock_movement_says_why(self):
        self._vendre()

        avantages.remettre(self.membre, self.serviette.id, 1, par=self.caissiere)

        mouvement = StockMovement.objects.filter(
            product=self.serviette, movement_type="out"
        ).latest("created_at")
        self.assertTrue(mouvement.reason.startswith("Avantage abonne"))

    def test_cannot_give_more_than_the_balance(self):
        self._vendre()

        with self.assertRaises(ValidationError):
            avantages.remettre(self.membre, self.bouteille.id, 5, par=self.caissiere)

    def test_what_was_taken_is_not_credited_back_before_the_next_payment(self):
        self._vendre()
        avantages.remettre(self.membre, self.serviette.id, 1, par=self.caissiere)

        with self.assertRaises(ValidationError):
            avantages.remettre(self.membre, self.serviette.id, 1, par=self.caissiere)

    def test_out_of_stock_keeps_the_balance(self):
        # Le membre ne perd rien parce qu'on ne peut pas le servir aujourd'hui.
        self._vendre()
        Product.objects.filter(pk=self.serviette.pk).update(quantity=0)

        with self.assertRaises(ValidationError):
            avantages.remettre(self.membre, self.serviette.id, 1, par=self.caissiere)

        self.assertEqual(self._solde(self.serviette), 1)

    def test_without_an_active_subscription_the_balance_is_kept(self):
        self._vendre()
        MemberSubscription.objects.filter(member=self.membre).update(is_active=False)

        with self.assertRaises(ValidationError):
            avantages.remettre(self.membre, self.bouteille.id, 1, par=self.caissiere)

        self.assertEqual(self._solde(self.bouteille), 4)

    # --- L'annulation --------------------------------------------------------------

    def test_a_same_day_cancellation_restores_stock_and_balance(self):
        self._vendre()
        remise = avantages.remettre(self.membre, self.bouteille.id, 2, par=self.caissiere)

        avantages.annuler(remise, "Mauvais membre", par=self.caissiere)

        self.bouteille.refresh_from_db()
        self.assertEqual(self.bouteille.quantity, 50)
        self.assertEqual(self._solde(self.bouteille), 4)

    def test_both_lines_stay_in_the_journal(self):
        self._vendre()
        remise = avantages.remettre(self.membre, self.bouteille.id, 2, par=self.caissiere)

        annulation = avantages.annuler(remise, "Mauvais membre", par=self.caissiere)

        self.assertTrue(BenefitMovement.objects.filter(pk=remise.pk).exists())
        self.assertEqual(annulation.cancels_id, remise.pk)

    def test_cancelling_requires_a_reason(self):
        self._vendre()
        remise = avantages.remettre(self.membre, self.bouteille.id, 1, par=self.caissiere)

        with self.assertRaises(ValidationError):
            avantages.annuler(remise, "  ", par=self.caissiere)

    def test_yesterdays_giving_cannot_be_cancelled(self):
        self._vendre()
        remise = avantages.remettre(self.membre, self.bouteille.id, 1, par=self.caissiere)
        BenefitMovement.objects.filter(pk=remise.pk).update(
            created_at=timezone.now() - timedelta(days=1)
        )

        with self.assertRaises(ValidationError):
            avantages.annuler(remise, "Trop tard", par=self.caissiere)

    def test_a_giving_cannot_be_cancelled_twice(self):
        self._vendre()
        remise = avantages.remettre(self.membre, self.bouteille.id, 1, par=self.caissiere)
        avantages.annuler(remise, "Erreur", par=self.caissiere)

        with self.assertRaises(ValidationError):
            avantages.annuler(remise, "Encore", par=self.caissiere)

    # --- Au comptoir ------------------------------------------------------------------

    def test_reception_gives_from_the_counter(self):
        self._vendre()
        self._connecter(self._utilisateur("accueil-kit", "reception"))

        reponse = self.client.post(
            reverse("subscriptions:remettre_avantage", args=[self.membre.id]),
            {"product_id": self.serviette.id, "quantite": 1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertTrue(reponse.json()["success"])
        self.assertEqual(self._solde(self.serviette), 0)

    def test_a_coach_cannot_give(self):
        self._vendre()
        self._connecter(self._utilisateur("coach-kit", "coach"))

        reponse = self.client.post(
            reverse("subscriptions:remettre_avantage", args=[self.membre.id]),
            {"product_id": self.serviette.id, "quantite": 1},
        )

        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(self._solde(self.serviette), 1)

    def test_a_neighbouring_gym_member_is_out_of_reach(self):
        voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-kit-voisine", subdomain="gym-kit-voisine",
        )
        ailleurs = Member.objects.create(
            gym=voisine, first_name="Zoe", last_name="Ailleurs", phone="+243870999111",
        )
        self._connecter(self._utilisateur("accueil-kit2", "reception"))

        reponse = self.client.post(
            reverse("subscriptions:remettre_avantage", args=[ailleurs.id]),
            {"product_id": self.serviette.id, "quantite": 1},
        )

        self.assertEqual(reponse.status_code, 404)

    def test_cancelling_from_the_counter(self):
        self._vendre()
        remise = avantages.remettre(self.membre, self.bouteille.id, 2, par=self.caissiere)
        self._connecter(self._utilisateur("accueil-kit3", "reception"))

        reponse = self.client.post(
            reverse("subscriptions:annuler_avantage", args=[remise.id]),
            {"motif": "Mauvais membre"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertTrue(reponse.json()["success"])
        self.assertEqual(self._solde(self.bouteille), 4)

    def test_the_member_sheet_shows_the_balance(self):
        self._vendre()
        self._connecter(self._utilisateur("gerant-kit", "manager"))

        fiche = self.client.get(reverse("members:member_detail", args=[self.membre.id])).json()

        soldes = {ligne["nom"]: ligne["solde"] for ligne in fiche["avantages"]["soldes"]}
        self.assertEqual(soldes["Serviette"], 1)
        self.assertEqual(soldes["Bouteille d'eau"], 4)

    def test_the_scan_shows_the_balance(self):
        # Le kit se remet la ou le membre arrive : juste apres le scan.
        self._vendre()
        self._connecter(self._utilisateur("accueil-kit4", "reception"))

        # La route n'accepte que POST, comme l'ecran de scan l'appelle.
        reponse = self.client.post(
            reverse("access:member_access", args=[self.membre.qr_code])
        ).json()

        self.assertEqual(reponse["member_id"], self.membre.id)
        self.assertTrue(reponse["avantages"]["soldes"])

    # --- Le parametrage de l'offre ------------------------------------------------------

    def test_the_offer_form_saves_its_kit(self):
        self._connecter(self._utilisateur("gerant-kit2", "manager"))

        reponse = self.client.post(
            reverse("subscriptions:create_subscription_offer"),
            {
                "offer-name": "Kit Standard",
                "offer-category": "access",
                "offer-is_active": "on",
                "kit_present": "1",
                "kit_product": [self.serviette.id, self.bouteille.id],
                "kit_quantity": ["1", "2"],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertTrue(reponse.json()["success"])
        offre = SubscriptionOffer.objects.get(gym=self.gym, name="Kit Standard")
        self.assertEqual(
            {(article.product_id, article.quantity) for article in offre.items.all()},
            {(self.serviette.id, 1), (self.bouteille.id, 2)},
        )

    def test_an_article_from_another_gym_cancels_the_whole_offer(self):
        # L'offre et son kit naissent ensemble : pas d'offre sans les articles
        # prevus.
        voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-kit-voisine2", subdomain="gym-kit-voisine2",
        )
        etranger = Product.objects.create(
            gym=voisine, name="Casquette", price=Decimal("3000"),
            currency=Product.CURRENCY_CDF, quantity=5,
        )
        self._connecter(self._utilisateur("gerant-kit3", "manager"))

        reponse = self.client.post(
            reverse("subscriptions:create_subscription_offer"),
            {
                "offer-name": "Kit Fautif",
                "offer-category": "access",
                "offer-is_active": "on",
                "kit_present": "1",
                "kit_product": [etranger.id],
                "kit_quantity": ["1"],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(reponse.status_code, 400)
        self.assertFalse(SubscriptionOffer.objects.filter(name="Kit Fautif").exists())

    def test_the_offer_edit_returns_its_kit(self):
        self._connecter(self._utilisateur("gerant-kit4", "manager"))

        donnees = self.client.get(
            reverse("subscriptions:edit_subscription_offer", args=[self.kit.id])
        ).json()

        self.assertEqual(
            {(article["product_id"], article["quantity"]) for article in donnees["items"]},
            {(self.serviette.id, 1), (self.bouteille.id, 4)},
        )

    def test_an_offer_saved_without_kit_fields_keeps_its_kit(self):
        # Un envoi qui ne porte pas le formulaire du kit ne doit pas l'effacer.
        self._connecter(self._utilisateur("gerant-kit5", "manager"))

        self.client.post(
            reverse("subscriptions:edit_subscription_offer", args=[self.kit.id]),
            {"offer-name": "Kit Premium", "offer-category": "access", "offer-is_active": "on"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(OfferItem.objects.filter(offer=self.kit).count(), 2)

    # --- La grille du revenu --------------------------------------------------------------

    def test_the_revenue_grid_counts_what_was_given(self):
        self._vendre()
        avantages.remettre(self.membre, self.bouteille.id, 3, par=self.caissiere)
        avantages.remettre(self.membre, self.serviette.id, 1, par=self.caissiere)
        self._connecter(self._utilisateur("gerant-kit6", "manager"))

        bilan = self.client.get(
            reverse("core:gym_dashboard", args=[self.gym.id]),
            {"view": "analytics", "period": "month"},
        ).context["bilan_periode"]

        offerts = {ligne["nom"]: ligne["quantite"] for ligne in bilan["articles_offerts"]["articles"]}
        self.assertEqual(offerts, {"Bouteille d'eau": 3, "Serviette": 1})
        self.assertEqual(bilan["articles_offerts"]["valeur_cdf"], Decimal("8000.00"))

    def test_a_cancelled_giving_is_not_counted(self):
        self._vendre()
        remise = avantages.remettre(self.membre, self.bouteille.id, 3, par=self.caissiere)
        avantages.annuler(remise, "Erreur", par=self.caissiere)

        offerts = avantages.offerts_sur_periode(
            self.gym, timezone.localdate(), timezone.localdate()
        )

        self.assertEqual(offerts["articles"], [])


class SubscriptionPaymentPathTests(TestCase):
    """
    Les deux constats corriges en construisant le kit.

    Une demande faite depuis le portail restait « en attente » apres la vente au
    comptoir. Et un abonnement pouvait naitre sans paiement, donc sans kit.
    """

    def setUp(self):
        self.organization = Organization.objects.create(name="Org Chemin", slug="org-chemin")
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Chemin",
            slug="gym-chemin", subdomain="gym-chemin",
        )
        CashRegister.objects.create(
            gym=self.gym, opening_amount=Decimal("0.00"), exchange_rate=Decimal("2800.00"),
        )
        self.premium = SubscriptionPlan.objects.create(
            gym=self.gym, name="Premium", price=50, duration_days=30
        )
        self.standard = SubscriptionPlan.objects.create(
            gym=self.gym, name="Standard", price=30, duration_days=30
        )
        self.membre = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala", phone="+243870654321",
        )

    def _demande(self, plan, statut=SubscriptionRequest.STATUS_PENDING):
        return SubscriptionRequest.objects.create(
            gym=self.gym, member=self.membre, plan=plan, status=statut, price_usd=plan.price,
        )

    def _vendre(self, plan):
        return record_subscription_payment(
            gym=self.gym, member=self.membre, plan=plan, currency="USD", method="cash",
        )

    def test_a_counter_sale_settles_the_portal_request(self):
        demande = self._demande(self.premium)

        self._vendre(self.premium)

        demande.refresh_from_db()
        self.assertEqual(demande.status, SubscriptionRequest.STATUS_PAID)

    def test_a_request_awaiting_payment_is_settled_too(self):
        demande = self._demande(self.premium, SubscriptionRequest.STATUS_AWAITING_PAYMENT)

        self._vendre(self.premium)

        demande.refresh_from_db()
        self.assertEqual(demande.status, SubscriptionRequest.STATUS_PAID)

    def test_a_request_for_another_plan_stays_pending(self):
        demande = self._demande(self.standard)

        self._vendre(self.premium)

        demande.refresh_from_db()
        self.assertEqual(demande.status, SubscriptionRequest.STATUS_PENDING)

    def test_a_cancelled_request_is_left_alone(self):
        demande = self._demande(self.premium, SubscriptionRequest.STATUS_CANCELLED)

        self._vendre(self.premium)

        demande.refresh_from_db()
        self.assertEqual(demande.status, SubscriptionRequest.STATUS_CANCELLED)

    def test_no_code_path_creates_a_subscription_without_payment(self):
        # La fonction qui creait un abonnement sans paiement - et donc sans kit
        # - a disparu : l'abonnement ne nait plus que d'une vente.
        from subscriptions import views as vues

        self.assertFalse(hasattr(vues, "create_member_subscription"))

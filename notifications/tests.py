from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from compte.models import User, UserGymRole
from members.models import Member
from notifications.models import Notification
from organizations.models import Gym, GymModule, Module, Organization, SensitiveActivityLog
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
        self.expired_member = Member.objects.create(
            gym=self.gym,
            first_name="Eli",
            last_name="Expire",
            phone="+243810000407",
        )
        self.future_member = Member.objects.create(
            gym=self.gym,
            first_name="Fiona",
            last_name="Future",
            phone="+243810000408",
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
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.expired_member,
            plan=self.plan,
            start_date=today - timedelta(days=40),
            end_date=today - timedelta(days=5),
            is_active=True,
        )
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.future_member,
            plan=self.plan,
            start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=32),
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
        self.manager = User.objects.create_user(
            username="manager-notify",
            password="pass12345",
        )
        UserGymRole.objects.create(user=self.reception, gym=self.gym, role="reception")
        UserGymRole.objects.create(user=self.manager, gym=self.gym, role="manager")

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
        self.assertTrue(
            SensitiveActivityLog.objects.filter(
                organization=self.organization,
                action="notification.batch_sent",
            ).exists()
        )

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
            ["Eli"],
        )

    def test_dashboard_excludes_future_subscriptions_from_active_and_expiring_audiences(self):
        self.client.force_login(self.owner)

        active_response = self.client.post(
            reverse("notifications:dashboard"),
            {
                "target": "active",
                "title": "Actif",
                "message": "Votre abonnement est actif.",
            },
        )
        self.assertEqual(active_response.status_code, 302)
        self.assertEqual(
            list(Notification.objects.values_list("member__first_name", flat=True)),
            ["Alice"],
        )

        Notification.objects.all().delete()

        expiring_response = self.client.post(
            reverse("notifications:dashboard"),
            {
                "target": "expiring_soon",
                "title": "Rappel",
                "message": "Votre abonnement expire bientot.",
            },
        )
        self.assertEqual(expiring_response.status_code, 302)
        self.assertEqual(Notification.objects.count(), 0)

    def test_dashboard_history_and_counts_ignore_unsent_notifications(self):
        self.client.force_login(self.owner)

        Notification.objects.create(
            gym=self.gym,
            member=self.member,
            title="Visible",
            message="Notification envoyee.",
            channel=Notification.CHANNEL_IN_APP,
            status=Notification.STATUS_SENT,
            sent_at=timezone.now(),
            sent_by=self.owner,
        )
        Notification.objects.create(
            gym=self.gym,
            member=self.active_member,
            title="Cachee",
            message="Notification en attente.",
            channel=Notification.CHANNEL_IN_APP,
            status=Notification.STATUS_PENDING,
            sent_by=self.owner,
        )

        response = self.client.get(reverse("notifications:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visible")
        self.assertNotContains(response, "Cachee")
        self.assertEqual(response.context["sent_count"], 1)
        self.assertEqual(response.context["unread_count"], 1)

    def test_manager_can_open_dashboard_when_module_is_active(self):
        self.client.force_login(self.manager)

        sent_at = timezone.now()
        for member in [self.member, self.active_member, self.suspended_member]:
            Notification.objects.create(
                gym=self.gym,
                member=member,
                title="Infos salle",
                message="Planning special cette semaine.",
                channel=Notification.CHANNEL_IN_APP,
                status=Notification.STATUS_SENT,
                sent_at=sent_at,
                sent_by=self.owner,
            )

        response = self.client.get(reverse("notifications:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Messages membres")
        self.assertContains(response, "Infos salle")
        self.assertContains(response, "3 membres")
        self.assertContains(response, "Apercu des destinataires")
        self.assertContains(response, "Maya Message")
        self.assertContains(response, "Alice Active")

    def test_reception_cannot_open_dashboard(self):
        self.client.force_login(self.reception)

        response = self.client.get(reverse("notifications:dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_dashboard_groups_large_campaigns_in_collapsible_history(self):
        self.client.force_login(self.owner)

        extra_members = [
            Member.objects.create(
                gym=self.gym,
                first_name=f"Member{i}",
                last_name="Bulk",
                phone=f"+24381000050{i}",
            )
            for i in range(5)
        ]
        sent_at = timezone.now()
        for member in [self.member, self.active_member, *extra_members]:
            Notification.objects.create(
                gym=self.gym,
                member=member,
                title="Campagne avril",
                message="Le club ouvre plus tot demain.",
                channel=Notification.CHANNEL_IN_APP,
                status=Notification.STATUS_SENT,
                sent_at=sent_at,
                sent_by=self.owner,
            )

        response = self.client.get(reverse("notifications:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "7 membres")
        self.assertContains(response, "Voir 3 autres")

    def test_dashboard_shows_read_and_unread_members_per_campaign(self):
        self.client.force_login(self.owner)

        sent_at = timezone.now()
        first = Notification.objects.create(
            gym=self.gym,
            member=self.member,
            title="Lecture",
            message="Merci de confirmer reception.",
            channel=Notification.CHANNEL_IN_APP,
            status=Notification.STATUS_SENT,
            sent_at=sent_at,
            sent_by=self.owner,
            read_at=timezone.now(),
        )
        Notification.objects.create(
            gym=self.gym,
            member=self.active_member,
            title=first.title,
            message=first.message,
            channel=Notification.CHANNEL_IN_APP,
            status=Notification.STATUS_SENT,
            sent_at=sent_at,
            sent_by=self.owner,
        )

        response = self.client.get(reverse("notifications:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ont lu (1)")
        self.assertContains(response, "N'ont pas lu (1)")
        self.assertContains(response, "Maya Message")
        self.assertContains(response, "Alice Active")


class MemberMessageRenderingTests(TestCase):
    """Le corps d'un message doit s'afficher entier, et sans jamais s'executer."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Org Msg", slug="org-msg")
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Msg",
            slug="gym-msg",
            subdomain="gym-msg",
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Lecteur",
            last_name="Message",
            phone="+243880000001",
            email="lecteur.message@example.com",
        )
        self.member.user.set_password("MembrePortail123!")
        self.member.user.force_password_change = False
        self.member.user.save()
        self.client.login(
            username=self.member.user.username, password="MembrePortail123!"
        )

    def _send(self, message):
        return Notification.objects.create(
            gym=self.gym,
            member=self.member,
            title="Information",
            message=message,
            channel=Notification.CHANNEL_IN_APP,
            status=Notification.STATUS_SENT,
            sent_at=timezone.now(),
        )

    def _inbox(self, notification=None):
        params = {"tab": "messages"}
        if notification:
            params["message"] = notification.id
        return self.client.get(reverse("members:member_portal"), params)

    def test_tag_like_text_is_not_swallowed(self):
        """striptags supprimait « <promo> » sans prevenir personne."""
        notification = self._send("Nouveau tarif <promo> disponible")

        response = self._inbox(notification)

        self.assertContains(response, "&lt;promo&gt;")
        self.assertContains(response, "Nouveau tarif")

    def test_html_in_a_message_is_never_executed(self):
        notification = self._send("<img src=x onerror=alert(1)>")

        response = self._inbox(notification)

        body = response.content.decode()
        self.assertNotIn("<img src=x onerror", body)
        self.assertIn("&lt;img src=x onerror", body)

    def test_line_breaks_are_preserved(self):
        notification = self._send("Ligne 1\nLigne 2")

        response = self._inbox(notification)

        self.assertContains(response, "Ligne 1<br>Ligne 2")

    def test_plain_message_reaches_the_member_intact(self):
        notification = self._send("Horaires : 6h -> 22h, tarif < 50 $")

        response = self._inbox(notification)

        self.assertContains(response, "Horaires : 6h -&gt; 22h, tarif &lt; 50 $")


class MessageBatchCancellationTests(TestCase):
    """Annulation et suppression d'un envoi groupe."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Org Lot", slug="org-lot")
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Lot",
            slug="gym-lot",
            subdomain="gym-lot",
        )
        module, _ = Module.objects.get_or_create(
            code="NOTIFICATIONS", defaults={"name": "Notifications"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.owner = User.objects.create_user(
            username="owner-lot",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.reception = User.objects.create_user(
            username="reception-lot", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.reception, gym=self.gym, role="reception", is_active=True
        )
        for index in range(1, 4):
            Member.objects.create(
                gym=self.gym,
                first_name=f"Membre{index}",
                last_name="Lot",
                phone=f"+24389000000{index}",
                email=f"membre{index}.lot@example.com",
            )
        self.client.force_login(self.owner)

    def _send(self):
        self.client.post(
            reverse("notifications:dashboard"),
            {"target": "all", "title": "Tarif", "message": "Nouveau tarif."},
            follow=True,
        )
        return Notification.objects.filter(gym=self.gym).first().batch_id

    def _visible_to_members(self):
        return Notification.objects.filter(
            gym=self.gym, status=Notification.STATUS_SENT
        ).count()

    def _first_message(self, response):
        return str(list(response.context["messages"])[0])

    # --- Envoi identifie ----------------------------------------------------

    def test_a_send_gets_one_shared_batch_id(self):
        batch_id = self._send()

        identifiers = set(
            Notification.objects.filter(gym=self.gym).values_list("batch_id", flat=True)
        )
        self.assertEqual(identifiers, {batch_id})
        self.assertEqual(Notification.objects.filter(gym=self.gym).count(), 3)

    # --- Annulation ---------------------------------------------------------

    def test_cancelling_removes_the_message_from_every_inbox(self):
        batch_id = self._send()

        response = self.client.post(
            reverse("notifications:cancel_message_batch", args=[batch_id]), follow=True
        )

        self.assertEqual(self._visible_to_members(), 0)
        self.assertEqual(
            Notification.objects.filter(
                gym=self.gym, status=Notification.STATUS_CANCELLED
            ).count(),
            3,
        )
        self.assertIn("Envoi annule", self._first_message(response))

    def test_cancelling_keeps_the_history_for_the_gym(self):
        batch_id = self._send()

        self.client.post(reverse("notifications:cancel_message_batch", args=[batch_id]))

        response = self.client.get(reverse("notifications:dashboard"))
        batch = response.context["message_batches"][0]
        self.assertTrue(batch["is_cancelled"])
        self.assertEqual(batch["total_count"], 3)

    def test_cancelling_records_who_and_when(self):
        batch_id = self._send()

        self.client.post(reverse("notifications:cancel_message_batch", args=[batch_id]))

        notification = Notification.objects.filter(gym=self.gym).first()
        self.assertEqual(notification.cancelled_by, self.owner)
        self.assertIsNotNone(notification.cancelled_at)

    def test_cancelling_reports_how_many_had_already_read(self):
        batch_id = self._send()
        first = Notification.objects.filter(gym=self.gym).first()
        Notification.objects.filter(pk=first.pk).update(read_at=timezone.now())

        response = self.client.post(
            reverse("notifications:cancel_message_batch", args=[batch_id]), follow=True
        )

        self.assertIn("1 membre(s)", self._first_message(response))
        self.assertIn("deja lu", self._first_message(response))

    def test_cancelling_twice_is_reported_not_repeated(self):
        batch_id = self._send()
        self.client.post(
            reverse("notifications:cancel_message_batch", args=[batch_id]), follow=True
        )

        response = self.client.post(
            reverse("notifications:cancel_message_batch", args=[batch_id]), follow=True
        )

        self.assertIn("deja annule", self._first_message(response))
        self.assertEqual(
            Notification.objects.filter(
                gym=self.gym, status=Notification.STATUS_CANCELLED
            ).count(),
            3,
        )

    # --- Suppression ---------------------------------------------------------

    def test_deleting_removes_every_trace(self):
        batch_id = self._send()

        response = self.client.post(
            reverse("notifications:delete_message_batch", args=[batch_id]), follow=True
        )

        self.assertEqual(Notification.objects.filter(gym=self.gym).count(), 0)
        self.assertIn("Envoi supprime", self._first_message(response))

    def test_a_cancelled_send_can_still_be_deleted(self):
        batch_id = self._send()
        self.client.post(reverse("notifications:cancel_message_batch", args=[batch_id]))

        self.client.post(reverse("notifications:delete_message_batch", args=[batch_id]))

        self.assertEqual(Notification.objects.filter(gym=self.gym).count(), 0)

    def test_deleting_an_unknown_send_is_reported(self):
        response = self.client.post(
            reverse(
                "notifications:delete_message_batch",
                args=["11111111-2222-3333-4444-555555555555"],
            ),
            follow=True,
        )

        self.assertIn("existe plus", self._first_message(response))

    # --- Cloisonnement et droits ---------------------------------------------

    def test_another_gym_send_cannot_be_touched(self):
        batch_id = self._send()
        other_organization = Organization.objects.create(
            name="Org Voisine Lot", slug="org-voisine-lot"
        )
        other_gym = Gym.objects.create(
            organization=other_organization,
            name="Gym Voisin Lot",
            slug="gym-voisin-lot",
            subdomain="gym-voisin-lot",
        )
        GymModule.objects.get_or_create(
            gym=other_gym,
            module=Module.objects.get(code="NOTIFICATIONS"),
            defaults={"is_active": True},
        )
        intruder = User.objects.create_user(
            username="owner-voisin-lot",
            password="pass12345",
            owned_organization=other_organization,
        )

        other_client = Client()
        other_client.force_login(intruder)
        other_client.post(
            reverse("notifications:cancel_message_batch", args=[batch_id]), follow=True
        )

        self.assertEqual(self._visible_to_members(), 3)

    def test_reception_cannot_cancel_a_send(self):
        batch_id = self._send()

        self.client.force_login(self.reception)
        response = self.client.post(
            reverse("notifications:cancel_message_batch", args=[batch_id])
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._visible_to_members(), 3)

    def test_get_requests_change_nothing(self):
        batch_id = self._send()

        response = self.client.get(
            reverse("notifications:delete_message_batch", args=[batch_id])
        )

        self.assertEqual(response.status_code, 405)
        self.assertEqual(Notification.objects.filter(gym=self.gym).count(), 3)

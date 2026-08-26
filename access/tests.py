import json
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from io import BytesIO
from pathlib import Path

from PIL import Image

from compte.models import User, UserGymRole
from members.models import Member
from organizations.models import (
    Gym,
    GymModule,
    Module,
    Organization,
    SensitiveActivityLog,
)
from subscriptions.models import MemberSubscription, SubscriptionPlan
from . import door, enrollment, hikvision
from .device_views import (
    UNKNOWN_CREDENTIAL_REASON,
    _refresh_device_state,
    _serialize_device,
)
from .hikvision import parse_event_payload
from .health import resume_hors_ligne
from .models import AccessDevice, AccessLog, validate_device_host
from .views import (
    EXPIRED_QR_REASON,
    NO_SUBSCRIPTION_REASON,
    RETURN_LABEL,
    SHARED_CREDENTIAL_REASON,
)


class AccessControlTests(TestCase):
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
        self.user = User.objects.create_user(
            username="reception-a",
            password="test-pass",
        )
        access_module, _ = Module.objects.get_or_create(code="ACCESS", defaults={"name": "Access"})
        GymModule.objects.get_or_create(gym=self.gym_a, module=access_module, defaults={"is_active": True})
        UserGymRole.objects.create(
            user=self.user,
            gym=self.gym_a,
            role="reception",
        )
        self.member_a = Member.objects.create(
            gym=self.gym_a,
            first_name="Alice",
            last_name="Access",
            phone="10001",
            email="alice-access@example.com",
        )
        self.member_b = Member.objects.create(
            gym=self.gym_b,
            first_name="Bob",
            last_name="Access",
            phone="20001",
            email="bob-access@example.com",
        )
        self.member_c = Member.objects.create(
            gym=self.gym_a,
            first_name="Carla",
            last_name="Access",
            phone="10005",
            email="carla-access@example.com",
        )
        self.plan_a = SubscriptionPlan.objects.create(
            gym=self.gym_a,
            name="Mensuel",
            duration_days=30,
            price=30,
        )
        today = timezone.now().date()
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
            member=self.member_c,
            plan=self.plan_a,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )
        self.client.login(username="reception-a", password="test-pass")

    def test_access_log_rejects_cross_gym_member(self):
        with self.assertRaises(ValidationError):
            AccessLog.objects.create(
                gym=self.gym_a,
                member=self.member_b,
                access_granted=True,
                device_used="Manuel",
            )

    def test_manual_access_creates_scoped_log_for_current_gym(self):
        response = self.client.post(
            reverse("access:manual_access_entry", args=[self.member_a.id])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["access"])
        self.assertEqual(payload["log"]["method"], "Manuel")
        self.assertEqual(payload["log"]["status"], "success")
        self.assertEqual(payload["log"]["member"], "Alice Access")

        log = AccessLog.objects.get(member=self.member_a)
        self.assertEqual(log.gym, self.gym_a)
        self.assertEqual(log.scanned_by, self.user)
        self.assertEqual(log.device_used, "Manuel")

    def test_manual_access_refuses_a_second_entry_the_same_day(self):
        """
        Le nom donne a l'accueil ne prouve rien : n'importe qui peut le donner.

        Un second passage le meme jour reste donc refuse. Seule la
        reconnaissance faciale autorise un retour, parce que personne ne peut
        presenter le visage d'un autre.
        """
        first_response = self.client.post(
            reverse("access:manual_access_entry", args=[self.member_a.id])
        )
        second_response = self.client.post(
            reverse("access:manual_access_entry", args=[self.member_a.id])
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(first_response.json()["access"])

        payload = second_response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], SHARED_CREDENTIAL_REASON)
        self.assertEqual(payload["log"]["status"], "denied")
        self.assertFalse(payload["log"]["is_return"])
        self.assertEqual(payload["stats"]["entries"], 1)
        self.assertEqual(payload["stats"]["denied"], 1)

        logs = AccessLog.objects.filter(member=self.member_a).order_by("id")
        self.assertEqual(logs.count(), 2)
        self.assertTrue(logs[0].access_granted)
        self.assertFalse(logs[1].access_granted)
        self.assertFalse(logs[1].is_return)

    def test_qr_access_refuses_a_second_scan_the_same_day(self):
        first_response = self.client.post(
            reverse("access:member_access", args=[self.member_a.qr_code])
        )
        second_response = self.client.post(
            reverse("access:member_access", args=[self.member_a.qr_code])
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(first_response.json()["access"])

        payload = second_response.json()
        # Un QR code se prete : le second passage peut etre un ami.
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], SHARED_CREDENTIAL_REASON)
        self.assertEqual(payload["log"]["method"], "QR Scanner")
        self.assertEqual(payload["stats"]["entries"], 1)
        self.assertEqual(payload["stats"]["denied"], 1)

    def test_qr_access_denies_expired_qr_code(self):
        self.member_a.qr_code_expires_at = timezone.now() - timedelta(minutes=1)
        self.member_a.save(update_fields=["qr_code_expires_at"])

        response = self.client.post(
            reverse("access:member_access", args=[self.member_a.qr_code])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], EXPIRED_QR_REASON)
        self.assertEqual(payload["log"]["status"], "denied")

    def test_manual_access_still_allows_member_when_qr_is_expired(self):
        self.member_a.qr_code_expires_at = timezone.now() - timedelta(minutes=1)
        self.member_a.save(update_fields=["qr_code_expires_at"])

        response = self.client.post(
            reverse("access:manual_access_entry", args=[self.member_a.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["access"])

    def test_qr_access_allows_multiple_different_members_in_sequence(self):
        first_response = self.client.post(
            reverse("access:member_access", args=[self.member_a.qr_code])
        )
        second_response = self.client.post(
            reverse("access:member_access", args=[self.member_c.qr_code])
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(first_response.json()["access"])

        payload = second_response.json()
        self.assertTrue(payload["access"])
        self.assertEqual(payload["member"], "Carla Access")
        self.assertEqual(payload["stats"]["entries"], 2)
        self.assertEqual(payload["stats"]["denied"], 0)

        logs = AccessLog.objects.filter(gym=self.gym_a, access_granted=True)
        self.assertEqual(logs.count(), 2)

    def test_scanner_template_keeps_camera_active_after_successful_scan(self):
        template = (
            settings.BASE_DIR / "access" / "templates" / "access" / "acces.html"
        ).read_text(encoding="utf-8")
        on_success = template.split("function onScanSuccess", 1)[1].split(
            "function renderHistorique",
            1,
        )[0]

        self.assertNotIn("html5QrCode.stop()", on_success)
        self.assertIn("cameraScanInProgress", on_success)
        self.assertIn("Prêt pour le membre suivant.", template)

    def test_previous_day_entry_does_not_block_today(self):
        log = AccessLog.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            access_granted=True,
            device_used="Manuel",
            scanned_by=self.user,
        )
        AccessLog.objects.filter(pk=log.pk).update(
            check_in_time=timezone.now() - timedelta(days=1)
        )

        response = self.client.post(
            reverse("access:manual_access_entry", args=[self.member_a.id])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["access"])
        self.assertEqual(payload["stats"]["entries"], 1)
        self.assertEqual(
            AccessLog.objects.filter(member=self.member_a, access_granted=True).count(),
            2,
        )

    def test_denied_attempt_does_not_block_later_valid_entry(self):
        member = Member.objects.create(
            gym=self.gym_a,
            first_name="Retry",
            last_name="Member",
            phone="10003",
            email="retry-access@example.com",
        )

        first_response = self.client.post(
            reverse("access:manual_access_entry", args=[member.id])
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertFalse(first_response.json()["access"])

        today = timezone.now().date()
        MemberSubscription.objects.create(
            gym=self.gym_a,
            member=member,
            plan=self.plan_a,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )

        second_response = self.client.post(
            reverse("access:manual_access_entry", args=[member.id])
        )

        self.assertEqual(second_response.status_code, 200)
        payload = second_response.json()
        self.assertTrue(payload["access"])
        self.assertEqual(payload["stats"]["entries"], 1)
        self.assertEqual(payload["stats"]["denied"], 1)

    def test_qr_access_cannot_read_member_from_other_gym(self):
        response = self.client.post(
            reverse("access:member_access", args=[self.member_b.qr_code])
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(AccessLog.objects.filter(member=self.member_b).exists())

    def test_member_without_valid_subscription_is_denied(self):
        member = Member.objects.create(
            gym=self.gym_a,
            first_name="Expired",
            last_name="Member",
            phone="10002",
            email="expired-access@example.com",
        )

        response = self.client.post(
            reverse("access:manual_access_entry", args=[member.id])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], NO_SUBSCRIPTION_REASON)
        self.assertEqual(payload["log"]["reason"], NO_SUBSCRIPTION_REASON)
        self.assertEqual(payload["log"]["status"], "denied")

        log = AccessLog.objects.get(member=member)
        self.assertFalse(log.access_granted)
        self.assertEqual(log.denial_reason, NO_SUBSCRIPTION_REASON)

    def test_member_with_future_subscription_is_denied_until_start_date(self):
        member = Member.objects.create(
            gym=self.gym_a,
            first_name="Future",
            last_name="Member",
            phone="10004",
            email="future-access@example.com",
        )
        today = timezone.now().date()
        MemberSubscription.objects.create(
            gym=self.gym_a,
            member=member,
            plan=self.plan_a,
            start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=32),
            is_active=True,
        )

        response = self.client.post(
            reverse("access:manual_access_entry", args=[member.id])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(
            payload["reason"],
            f"Abonnement valable a partir du {(today + timedelta(days=2)):%d/%m/%Y}",
        )

    def test_realtime_access_is_scoped_to_current_gym(self):
        AccessLog.objects.create(
            gym=self.gym_a,
            member=self.member_a,
            access_granted=True,
            device_used="Manuel",
            scanned_by=self.user,
        )
        AccessLog.objects.create(
            gym=self.gym_b,
            member=self.member_b,
            access_granted=True,
            device_used="Manuel",
        )

        response = self.client.get("/access/access/realtime/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["member"], "Alice Access")

    def test_access_dashboard_renders_readers_section(self):
        response = self.client.get(reverse("access:acces_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="lecteursSection"')
        self.assertContains(response, "Détecter un lecteur sur le réseau")

    def test_access_dashboard_requires_active_module(self):
        GymModule.objects.filter(gym=self.gym_a, module__code="ACCESS").update(is_active=False)

        response = self.client.get(reverse("access:acces_dashboard"))

        self.assertEqual(response.status_code, 403)


class HikvisionEventParsingTests(TestCase):
    """Extraction de l'identifiant scanne dans les notifications du lecteur."""

    def test_extracts_qr_content_from_json_event(self):
        payload = json.dumps({
            "eventType": "AccessControllerEvent",
            "dateTime": "2026-08-09T10:00:00+01:00",
            "AccessControllerEvent": {
                "majorEventType": 5,
                "subEventType": 75,
                "cardNo": "0",
                "QRCodeInfo": "0f1d4c62-6f52-4a2e-9f42-7d3f6a1b2c3d",
            },
        })

        parsed = parse_event_payload(payload.encode(), "application/json")

        self.assertEqual(parsed["credential"], "0f1d4c62-6f52-4a2e-9f42-7d3f6a1b2c3d")

    def test_extracts_card_number_when_no_qr(self):
        payload = json.dumps({
            "AccessControllerEvent": {"cardNo": "1234567890"},
        })

        parsed = parse_event_payload(payload.encode(), "application/json")

        self.assertEqual(parsed["credential"], "1234567890")

    def test_extracts_json_block_from_multipart_body(self):
        body = (
            "--MIME_boundary\r\n"
            'Content-Disposition: form-data; name="event_log"\r\n'
            "Content-Type: application/json\r\n\r\n"
            '{"AccessControllerEvent": {"QRCodeInfo": "abc-123"}}\r\n'
            "--MIME_boundary--\r\n"
        )

        parsed = parse_event_payload(
            body.encode(),
            "multipart/form-data; boundary=MIME_boundary",
        )

        self.assertEqual(parsed["credential"], "abc-123")

    def test_returns_empty_credential_on_unreadable_body(self):
        parsed = parse_event_payload(b"heartbeat", "text/plain")

        self.assertEqual(parsed["credential"], "")


class AccessDeviceWebhookTests(TestCase):
    """Passages pousses par un lecteur physique vers l'application."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Org D", slug="org-d")
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym D",
            slug="gym-d",
            subdomain="gym-d",
        )
        self.other_gym = Gym.objects.create(
            organization=self.organization,
            name="Gym E",
            slug="gym-e",
            subdomain="gym-e",
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym,
            name="Entree principale",
            host="192.168.1.64",
            username="admin",
            password="secret",
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Dina",
            last_name="Device",
            phone="30001",
            email="dina-device@example.com",
        )
        self.outsider = Member.objects.create(
            gym=self.other_gym,
            first_name="Elio",
            last_name="Device",
            phone="40001",
            email="elio-device@example.com",
        )
        plan = SubscriptionPlan.objects.create(
            gym=self.gym,
            name="Mensuel",
            duration_days=30,
            price=30,
        )
        today = timezone.now().date()
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )

        # Aucun test ne doit joindre un vrai lecteur : les cas qui accordent
        # l'acces declenchent l'ouverture, on neutralise donc le relais par
        # defaut. Les tests qui verifient l'ouverture reposent leur propre patch.
        patcher = patch("access.hikvision.HikvisionClient.open_door")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post_scan(self, credential, token=None):
        payload = json.dumps({
            "eventType": "AccessControllerEvent",
            "AccessControllerEvent": {"QRCodeInfo": str(credential)},
        })
        url = reverse(
            "access:device_webhook",
            args=[token or self.device.webhook_token],
        )
        return self.client.post(url, data=payload, content_type="application/json")

    def test_valid_scan_grants_access_and_logs_device(self):
        response = self._post_scan(self.member.qr_code)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["access"])
        self.assertEqual(payload["member"], "Dina Device")

        log = AccessLog.objects.get(member=self.member)
        self.assertEqual(log.gym, self.gym)
        self.assertEqual(log.device, self.device)
        self.assertEqual(log.device_used, "Entree principale")
        self.assertIsNone(log.scanned_by)

    def test_scan_marks_device_as_seen(self):
        self.assertIsNone(self.device.last_seen_at)

        self._post_scan(self.member.qr_code)

        self.device.refresh_from_db()
        self.assertIsNotNone(self.device.last_seen_at)

    def test_unknown_credential_is_refused_without_log(self):
        response = self._post_scan("11111111-2222-3333-4444-555555555555")

        payload = response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], UNKNOWN_CREDENTIAL_REASON)
        self.assertEqual(AccessLog.objects.count(), 0)

    def test_member_from_another_gym_is_not_resolved(self):
        response = self._post_scan(self.outsider.qr_code)

        payload = response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], UNKNOWN_CREDENTIAL_REASON)
        self.assertEqual(AccessLog.objects.count(), 0)

    def test_expired_qr_code_is_refused(self):
        Member.objects.filter(pk=self.member.pk).update(
            qr_code_expires_at=timezone.now() - timedelta(days=1)
        )

        response = self._post_scan(self.member.qr_code)

        payload = response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], EXPIRED_QR_REASON)

    def test_a_second_qr_scan_the_same_day_is_refused(self):
        # Meme presente au lecteur, un QR code reste pretable : seul le visage
        # ouvre droit a un retour.
        self._post_scan(self.member.qr_code)
        response = self._post_scan(self.member.qr_code)

        payload = response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], SHARED_CREDENTIAL_REASON)

    def test_unknown_token_returns_404(self):
        response = self._post_scan(
            self.member.qr_code,
            token="99999999-8888-7777-6666-555555555555",
        )

        self.assertEqual(response.status_code, 404)

    def test_inactive_device_is_rejected(self):
        AccessDevice.objects.filter(pk=self.device.pk).update(is_active=False)

        response = self._post_scan(self.member.qr_code)

        self.assertEqual(response.status_code, 404)

    def test_get_is_not_allowed(self):
        url = reverse("access:device_webhook", args=[self.device.webhook_token])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 405)

    def test_granted_scan_opens_the_door(self):
        with patch("access.hikvision.HikvisionClient.open_door") as open_door:
            response = self._post_scan(self.member.qr_code)

        open_door.assert_called_once_with(self.device.door_number)
        payload = response.json()
        self.assertTrue(payload["door"]["opened"])

    def test_denied_scan_never_opens_the_door(self):
        with patch("access.hikvision.HikvisionClient.open_door") as open_door:
            response = self._post_scan("11111111-2222-3333-4444-555555555555")

        open_door.assert_not_called()
        self.assertFalse(response.json().get("door", {}).get("attempted"))

    def test_device_failure_does_not_cancel_a_granted_access(self):
        """Une panne du relais ne doit pas invalider une decision deja prise."""
        with patch(
            "access.hikvision.HikvisionClient.open_door",
            side_effect=hikvision.HikvisionUnreachable("timed out"),
        ):
            response = self._post_scan(self.member.qr_code)

        payload = response.json()
        self.assertTrue(payload["access"])
        self.assertFalse(payload["door"]["opened"])
        self.assertIn("timed out", payload["door"]["message"])

        log = AccessLog.objects.get(member=self.member)
        self.assertTrue(log.access_granted)

        self.device.refresh_from_db()
        self.assertIn("timed out", self.device.last_error)

    def test_device_with_auto_open_disabled_stays_closed(self):
        AccessDevice.objects.filter(pk=self.device.pk).update(open_on_granted=False)

        with patch("access.hikvision.HikvisionClient.open_door") as open_door:
            response = self._post_scan(self.member.qr_code)

        open_door.assert_not_called()
        self.assertTrue(response.json()["access"])


class DashboardDoorOpeningTests(TestCase):
    """Scan QR et pointage manuel : la porte suit la decision metier."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Org F", slug="org-f")
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym F",
            slug="gym-f",
            subdomain="gym-f",
        )
        access_module, _ = Module.objects.get_or_create(
            code="ACCESS", defaults={"name": "Access"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=access_module, defaults={"is_active": True}
        )
        self.user = User.objects.create_user(username="reception-f", password="test-pass")
        UserGymRole.objects.create(user=self.user, gym=self.gym, role="reception")

        self.device = AccessDevice.objects.create(
            gym=self.gym,
            name="Tourniquet",
            host="192.0.0.64",
            username="admin",
            password="secret",
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Fara",
            last_name="Scan",
            phone="50001",
            email="fara-scan@example.com",
        )
        plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", duration_days=30, price=30
        )
        today = timezone.now().date()
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )
        self.client.login(username="reception-f", password="test-pass")

        patcher = patch("access.hikvision.HikvisionClient.open_door")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _scan(self, qr_code):
        return self.client.post(reverse("access:member_access", args=[qr_code]))

    def test_valid_qr_opens_the_door(self):
        with patch("access.hikvision.HikvisionClient.open_door") as open_door:
            response = self._scan(self.member.qr_code)

        open_door.assert_called_once_with(1)
        payload = response.json()
        self.assertTrue(payload["access"])
        self.assertTrue(payload["door"]["opened"])

    def test_expired_qr_leaves_the_door_closed(self):
        Member.objects.filter(pk=self.member.pk).update(
            qr_code_expires_at=timezone.now() - timedelta(days=1)
        )

        with patch("access.hikvision.HikvisionClient.open_door") as open_door:
            response = self._scan(self.member.qr_code)

        open_door.assert_not_called()
        self.assertFalse(response.json()["access"])

    def test_a_second_qr_scan_the_same_day_leaves_the_door_closed(self):
        """
        L'application commande le relais quand le passage vient d'un QR code :
        garder la porte fermee a donc un effet reel, contrairement au cas du
        visage ou le lecteur a deja ouvert de lui-meme.
        """
        with patch("access.hikvision.HikvisionClient.open_door"):
            self._scan(self.member.qr_code)

        with patch("access.hikvision.HikvisionClient.open_door") as open_door:
            response = self._scan(self.member.qr_code)

        open_door.assert_not_called()
        payload = response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], SHARED_CREDENTIAL_REASON)

    def test_gym_without_device_still_grants_access(self):
        AccessDevice.objects.filter(pk=self.device.pk).delete()

        response = self._scan(self.member.qr_code)

        payload = response.json()
        self.assertTrue(payload["access"])
        self.assertFalse(payload["door"]["attempted"])

    # --- Pointage manuel ---------------------------------------------------

    def _manual_entry(self, member):
        return self.client.post(
            reverse("access:manual_access_entry", args=[member.id])
        )

    def test_manual_entry_opens_the_door(self):
        with patch("access.hikvision.HikvisionClient.open_door") as open_door:
            response = self._manual_entry(self.member)

        open_door.assert_called_once_with(1)
        payload = response.json()
        self.assertTrue(payload["access"])
        self.assertTrue(payload["door"]["opened"])

    def test_manual_entry_without_subscription_leaves_the_door_closed(self):
        outsider = Member.objects.create(
            gym=self.gym,
            first_name="Gaby",
            last_name="Sansabo",
            phone="50002",
            email="gaby-sansabo@example.com",
        )

        with patch("access.hikvision.HikvisionClient.open_door") as open_door:
            response = self._manual_entry(outsider)

        open_door.assert_not_called()
        self.assertFalse(response.json()["access"])

    def test_manual_entry_second_time_same_day_leaves_the_door_closed(self):
        with patch("access.hikvision.HikvisionClient.open_door"):
            self._manual_entry(self.member)

        with patch("access.hikvision.HikvisionClient.open_door") as open_door:
            response = self._manual_entry(self.member)

        open_door.assert_not_called()
        payload = response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], SHARED_CREDENTIAL_REASON)

    def test_manual_entry_survives_a_door_failure(self):
        with patch(
            "access.hikvision.HikvisionClient.open_door",
            side_effect=hikvision.HikvisionUnreachable("timed out"),
        ):
            response = self._manual_entry(self.member)

        payload = response.json()
        self.assertTrue(payload["access"])
        self.assertFalse(payload["door"]["opened"])
        self.assertTrue(AccessLog.objects.get(member=self.member).access_granted)


class AccessRefusalReasonTests(TestCase):
    """Chaque refus doit dire quoi faire, pas seulement qu'il refuse."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Motif", slug="org-motif"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Motif",
            slug="gym-motif",
            subdomain="gym-motif",
        )
        module, _ = Module.objects.get_or_create(
            code="ACCESS", defaults={"name": "Access"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.user = User.objects.create_user(
            username="reception-motif", password="test-pass"
        )
        UserGymRole.objects.create(
            user=self.user, gym=self.gym, role="reception", is_active=True
        )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", duration_days=30, price=30
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Portique",
            last_name="Motif",
            phone="+243900000001",
            email="portique.motif@example.com",
        )
        self.today = timezone.now().date()
        self.client.login(username="reception-motif", password="test-pass")

    def _reason(self):
        response = self.client.post(
            reverse("access:manual_access_entry", args=[self.member.id])
        )
        return response.json()["reason"]

    def test_a_member_who_never_subscribed_is_named_as_such(self):
        self.assertEqual(self._reason(), NO_SUBSCRIPTION_REASON)

    def test_a_paused_subscription_says_so(self):
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=self.today,
            end_date=self.today + timedelta(days=30),
            is_active=True,
            is_paused=True,
        )

        self.assertEqual(self._reason(), "Abonnement en pause")

    def test_an_expired_subscription_gives_its_end_date(self):
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=self.today - timedelta(days=60),
            end_date=self.today - timedelta(days=12),
            is_active=True,
        )

        self.assertEqual(
            self._reason(),
            f"Abonnement echu le {(self.today - timedelta(days=12)):%d/%m/%Y}",
        )

    def test_a_future_subscription_gives_its_start_date(self):
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=self.today + timedelta(days=5),
            end_date=self.today + timedelta(days=35),
            is_active=True,
        )

        self.assertEqual(
            self._reason(),
            f"Abonnement valable a partir du {(self.today + timedelta(days=5)):%d/%m/%Y}",
        )

    def test_a_paused_subscription_wins_over_an_old_expired_one(self):
        """Le cas actionnable prime : c'est la pause qu'il faut lever."""
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=self.today - timedelta(days=200),
            end_date=self.today - timedelta(days=170),
            is_active=False,
        )
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=self.today,
            end_date=self.today + timedelta(days=30),
            is_active=True,
            is_paused=True,
        )

        self.assertEqual(self._reason(), "Abonnement en pause")

    def test_the_reason_is_stored_in_the_access_log(self):
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=self.today - timedelta(days=60),
            end_date=self.today - timedelta(days=12),
            is_active=True,
        )

        self._reason()

        log = AccessLog.objects.get(member=self.member)
        self.assertFalse(log.access_granted)
        self.assertIn("Abonnement echu", log.denial_reason)

    def test_a_suspended_member_keeps_its_own_reason(self):
        Member.objects.filter(pk=self.member.pk).update(status="suspended")
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=self.today,
            end_date=self.today + timedelta(days=30),
            is_active=True,
        )

        self.assertEqual(self._reason(), "Membre suspendu")

    def test_a_valid_member_is_still_granted(self):
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            start_date=self.today,
            end_date=self.today + timedelta(days=30),
            is_active=True,
        )

        response = self.client.post(
            reverse("access:manual_access_entry", args=[self.member.id])
        )

        self.assertTrue(response.json()["access"])
        self.assertEqual(response.json()["reason"], "")


class FaceEnrollmentServiceTests(TestCase):
    """Traduction d'un membre en fiche lecteur."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Visage", slug="org-visage"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Visage",
            slug="gym-visage",
            subdomain="gym-visage",
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym,
            name="Terminal facial",
            host="10.0.0.9",
            password="secret",
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Alice",
            last_name="Nzuzi",
            phone="+243850000001",
        )

    # --- Identifiants ---------------------------------------------------------

    def test_the_reader_id_is_shifted_out_of_the_manual_range(self):
        # Le materiel impose un employeeNo numerique, et les fiches saisies a
        # la main sur le terminal occupent les petits nombres. Sans decalage,
        # inscrire un membre ecraserait le badge d'un employe.
        self.assertEqual(
            enrollment.employee_no(self.member),
            str(enrollment.PLAGE_APPLICATION + self.member.id),
        )

    def test_a_manual_record_is_never_taken_for_a_member(self):
        self.assertIsNone(enrollment.member_id_depuis("2"))
        self.assertIsNone(enrollment.member_id_depuis("badge-personnel"))
        self.assertIsNone(enrollment.member_id_depuis(None))

    def test_an_application_record_maps_back_to_its_member(self):
        numero = enrollment.employee_no(self.member)

        self.assertEqual(enrollment.member_id_depuis(numero), self.member.id)

    # --- Photo ------------------------------------------------------------------

    def test_a_photo_is_converted_to_jpeg_and_bounded(self):
        tampon = BytesIO()
        Image.new("RGBA", (1600, 900), (12, 34, 56, 255)).save(tampon, format="PNG")

        prete = enrollment.preparer_photo(tampon.getvalue())
        relue = Image.open(BytesIO(prete))

        self.assertEqual(relue.format, "JPEG")
        self.assertEqual(relue.mode, "RGB")
        self.assertLessEqual(relue.width, enrollment.LARGEUR_MAX)

    def test_a_file_that_is_not_an_image_is_refused_clearly(self):
        with self.assertRaises(enrollment.EnrollmentError):
            enrollment.preparer_photo(b"ceci n'est pas une image")

    # --- Periode de validite -----------------------------------------------------

    def test_the_reader_receives_the_subscription_window(self):
        plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        today = timezone.localdate()
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_active=True,
        )

        with patch.object(hikvision.HikvisionClient, "upsert_user") as pose:
            enrollment.inscrire_membre(self.device, self.member)

        _, args, _ = pose.mock_calls[0]
        self.assertEqual(args[2], today.strftime("%Y-%m-%dT00:00:00"))
        self.assertEqual(
            args[3], (today + timedelta(days=30)).strftime("%Y-%m-%dT23:59:59")
        )

    def test_a_member_without_subscription_is_kept_but_closed(self):
        # Le visage reste sur le lecteur : au prochain encaissement, il suffit
        # de rouvrir les dates sans refaire passer le membre devant le terminal.
        with patch.object(hikvision.HikvisionClient, "upsert_user") as pose:
            resultat = enrollment.inscrire_membre(self.device, self.member)

        self.assertTrue(resultat["sans_abonnement"])
        _, args, _ = pose.mock_calls[0]
        fin = args[3]
        self.assertEqual(fin, timezone.localdate().strftime("%Y-%m-%dT00:00:00"))

    # --- Robustesse ---------------------------------------------------------------

    def test_an_unreachable_reader_never_blocks_the_business(self):
        # propager() est appelee lors d'un encaissement : un lecteur debranche
        # ne doit pas empecher de prendre l'argent.
        with patch.object(
            hikvision.HikvisionClient,
            "upsert_user",
            side_effect=hikvision.HikvisionUnreachable("cable arrache"),
        ):
            resultats = enrollment.propager(self.member)

        self.assertEqual(len(resultats), 1)
        self.assertFalse(resultats[0]["ok"])
        self.assertIn("injoignable", resultats[0]["error"])

    def test_a_gym_without_reader_propagates_nothing(self):
        self.device.delete()

        self.assertEqual(enrollment.propager(self.member), [])

    def test_a_rejected_face_says_the_record_still_exists(self):
        # Le lecteur refuse une image ou il ne distingue aucun visage. La fiche
        # est deja posee a ce moment-la : le message ne doit pas laisser croire
        # que rien n'a marche.
        tampon = BytesIO()
        Image.new("RGB", (352, 432), (40, 40, 40)).save(tampon, format="JPEG")

        with patch.object(hikvision.HikvisionClient, "upsert_user"), patch.object(
            hikvision.HikvisionClient,
            "set_face",
            side_effect=hikvision.HikvisionError("SubpicAnalysisModelingError"),
        ):
            with self.assertRaises(enrollment.EnrollmentError) as capture:
                enrollment.inscrire_membre(self.device, self.member, tampon.getvalue())

        self.assertIn("fiche est enregistree", str(capture.exception))

    def _refus_du_lecteur(self, corps):
        """Enrole un visage que le lecteur refuse, et rend le message affiche."""
        tampon = BytesIO()
        Image.new("RGB", (352, 432), (40, 40, 40)).save(tampon, format="JPEG")

        with patch.object(hikvision.HikvisionClient, "upsert_user"), patch.object(
            hikvision.HikvisionClient,
            "set_face",
            side_effect=hikvision.HikvisionError(corps),
        ):
            with self.assertRaises(enrollment.EnrollmentError) as capture:
                enrollment.inscrire_membre(self.device, self.member, tampon.getvalue())

        return str(capture.exception)

    def test_a_face_already_enrolled_elsewhere_is_named_as_such(self):
        # Le lecteur refuse d'attacher un meme visage a deux identites. Ce
        # refus etait annonce comme "aucun visage exploitable", ce qui envoyait
        # chercher un probleme de cadrage la ou l'image etait parfaite.
        message = self._refus_du_lecteur(
            'HTTP 400 : { "subStatusCode": "alreadyExistThisFace" }'
        )

        self.assertIn("deja enregistre sous une autre fiche", message)
        self.assertNotIn("aucun visage", message.lower())

    def test_that_refusal_says_where_to_look(self):
        # Le doublon peut venir d'une fiche creee a la main sur le terminal :
        # sans cette mention, on chercherait en vain du cote des membres.
        message = self._refus_du_lecteur(
            'HTTP 400 : { "subStatusCode": "alreadyExistThisFace" }'
        )

        self.assertIn("creee a la main", message)

    def test_a_face_too_blurred_asks_for_better_light(self):
        message = self._refus_du_lecteur(
            'HTTP 400 : { "subStatusCode": "lowScoreOfFaceQuality" }'
        )

        self.assertIn("qualite", message)
        self.assertIn("contre-jour", message)

    def test_an_image_without_a_face_still_says_so(self):
        message = self._refus_du_lecteur(
            'HTTP 400 : { "subStatusCode": "noFaceDetected" }'
        )

        self.assertIn("aucun visage", message)

    def test_an_unknown_refusal_keeps_the_reader_own_words(self):
        # Un code que nous ne connaissons pas ne doit pas etre travesti en
        # diagnostic invente : le texte brut reste la seule piste.
        message = self._refus_du_lecteur("quelqueChoseDeJamaisVu")

        self.assertIn("quelqueChoseDeJamaisVu", message)
        self.assertIn("sans motif reconnu", message)

    def test_every_refusal_says_the_record_was_saved(self):
        # La fiche est posee avant l'envoi du visage : laisser croire l'inverse
        # pousserait a tout recommencer.
        for corps in (
            'HTTP 400 : { "subStatusCode": "alreadyExistThisFace" }',
            'HTTP 400 : { "subStatusCode": "lowScoreOfFaceQuality" }',
            "quelqueChoseDeJamaisVu",
        ):
            with self.subTest(corps=corps):
                self.assertIn("fiche est enregistree", self._refus_du_lecteur(corps))

    def test_a_file_that_is_not_an_image_is_caught_before_the_reader(self):
        with patch.object(hikvision.HikvisionClient, "upsert_user"), patch.object(
            hikvision.HikvisionClient, "set_face"
        ) as envoi:
            with self.assertRaises(enrollment.EnrollmentError):
                enrollment.inscrire_membre(self.device, self.member, b"pas une image")

        envoi.assert_not_called()


class FaceEnrollmentScreenTests(TestCase):
    """Le parcours d'enrolement, vu de l'ecran."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Ecran", slug="org-ecran"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Ecran",
            slug="gym-ecran",
            subdomain="gym-ecran",
        )
        module, _ = Module.objects.get_or_create(
            code="ACCESS", defaults={"name": "Access"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="Terminal", host="10.0.0.9", password="secret"
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Alice",
            last_name="Nzuzi",
            phone="+243850000001",
        )
        self.manager = User.objects.create_user(
            username="gerant-visage", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.manager, gym=self.gym, role="manager", is_active=True
        )
        self._connecter(self.manager)

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _image(self):
        tampon = BytesIO()
        Image.new("RGB", (352, 432), (90, 90, 90)).save(tampon, format="JPEG")
        return tampon.getvalue()

    # --- L'ecran ------------------------------------------------------------------

    def test_the_screen_spells_out_the_three_steps(self):
        response = self.client.get(
            reverse("access:face_enrollment", args=[self.member.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Placez le membre devant le lecteur")
        self.assertContains(response, "Lancez la capture")
        self.assertContains(response, "Vérifiez puis validez")

    def test_the_screen_says_plainly_when_no_reader_exists(self):
        self.device.delete()

        response = self.client.get(
            reverse("access:face_enrollment", args=[self.member.id])
        )

        self.assertContains(response, "Aucun lecteur actif dans cette salle")

    def test_a_member_of_another_gym_is_out_of_reach(self):
        autre = Gym.objects.create(
            organization=self.organization,
            name="Autre",
            slug="autre-ecran",
            subdomain="autre-ecran",
        )
        etranger = Member.objects.create(
            gym=autre, first_name="Etranger", last_name="X", phone="+243850000009"
        )

        response = self.client.get(
            reverse("access:face_enrollment", args=[etranger.id])
        )

        self.assertEqual(response.status_code, 404)

    def test_a_receptionist_cannot_enrol_faces(self):
        reception = User.objects.create_user(
            username="reception-visage", password="pass12345"
        )
        UserGymRole.objects.create(
            user=reception, gym=self.gym, role="reception", is_active=True
        )
        self._connecter(reception)

        response = self.client.get(
            reverse("access:face_enrollment", args=[self.member.id])
        )

        self.assertIn(response.status_code, (302, 403))

    # --- Capture --------------------------------------------------------------------

    def test_the_capture_waits_for_validation_before_touching_the_file(self):
        with patch.object(
            hikvision.HikvisionClient, "capture_face", return_value=self._image()
        ):
            response = self.client.post(
                reverse("access:face_capture", args=[self.member.id]),
                {"device_id": self.device.id},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.member.refresh_from_db()
        # Rien n'est enregistre tant que l'operateur n'a pas vu l'image.
        self.assertFalse(self.member.photo)

    def test_a_failed_capture_explains_what_to_do(self):
        with patch.object(
            hikvision.HikvisionClient,
            "capture_face",
            side_effect=hikvision.HikvisionError("aucune image"),
        ):
            response = self.client.post(
                reverse("access:face_capture", args=[self.member.id]),
                {"device_id": self.device.id},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("se placer face au", response.json()["error"].lower())

    # --- Validation ------------------------------------------------------------------

    def test_validating_stores_the_photo_and_enrols_the_member(self):
        with patch.object(
            hikvision.HikvisionClient, "capture_face", return_value=self._image()
        ):
            self.client.post(
                reverse("access:face_capture", args=[self.member.id]),
                {"device_id": self.device.id},
            )

        with patch.object(hikvision.HikvisionClient, "upsert_user"), patch.object(
            hikvision.HikvisionClient, "set_face"
        ) as pose_visage:
            response = self.client.post(
                reverse("access:face_confirm", args=[self.member.id]), follow=True
            )

        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertTrue(self.member.photo)
        pose_visage.assert_called_once()
        self.assertEqual(
            pose_visage.mock_calls[0].args[0], enrollment.employee_no(self.member)
        )

    def test_validating_without_a_capture_is_refused(self):
        response = self.client.post(
            reverse("access:face_confirm", args=[self.member.id]), follow=True
        )

        self.assertContains(response, "Aucune capture en attente")
        self.member.refresh_from_db()
        self.assertFalse(self.member.photo)

    def test_the_enrolment_is_traced_in_the_sensitive_log(self):
        with patch.object(
            hikvision.HikvisionClient, "capture_face", return_value=self._image()
        ):
            self.client.post(
                reverse("access:face_capture", args=[self.member.id]),
                {"device_id": self.device.id},
            )
        with patch.object(hikvision.HikvisionClient, "upsert_user"), patch.object(
            hikvision.HikvisionClient, "set_face"
        ):
            self.client.post(
                reverse("access:face_confirm", args=[self.member.id]), follow=True
            )

        trace = SensitiveActivityLog.objects.get(action="access.face_enrolled")
        self.assertEqual(trace.actor, self.manager)
        self.assertEqual(trace.metadata["member_id"], self.member.id)

    # --- Retrait ----------------------------------------------------------------------

    def test_removing_takes_the_member_off_every_reader(self):
        with patch.object(hikvision.HikvisionClient, "delete_user") as retrait:
            self.client.post(
                reverse("access:face_remove", args=[self.member.id]), follow=True
            )

        retrait.assert_called_once_with(enrollment.employee_no(self.member))


class FaceEventWebhookTests(TestCase):
    """Un visage reconnu doit apparaitre au journal d'acces."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Remontee", slug="org-remontee"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Remontee",
            slug="gym-remontee",
            subdomain="gym-remontee",
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="Terminal", host="10.0.0.9", password="secret"
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Alice",
            last_name="Nzuzi",
            phone="+243860000001",
        )
        plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        today = timezone.localdate()
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=plan,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=29),
            is_active=True,
        )
        self.url = reverse("access:device_webhook", args=[self.device.webhook_token])

        # Un acces accorde declenche l'ouverture du relais : sans ce garde-fou,
        # chaque test attendrait l'expiration d'une connexion vers une adresse
        # fictive.
        patcher = patch("access.hikvision.HikvisionClient.open_door")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _pousser(self, employee_no):
        """Imite ce que le lecteur envoie apres une reconnaissance."""
        charge = {
            "AccessControllerEvent": {
                "majorEventType": 5,
                "subEventType": 75,
                "employeeNoString": str(employee_no),
                "currentVerifyMode": "face",
            }
        }
        return self.client.post(
            self.url, data=json.dumps(charge), content_type="application/json"
        )

    # --- Le cas normal --------------------------------------------------------

    def test_a_recognised_face_is_written_to_the_access_log(self):
        response = self._pousser(enrollment.employee_no(self.member))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["access"])
        log = AccessLog.objects.get(gym=self.gym, member=self.member)
        self.assertTrue(log.access_granted)

    def test_the_log_says_the_passage_came_from_a_face(self):
        # L'equipe doit distinguer un passage au visage d'un scan de QR code.
        self._pousser(enrollment.employee_no(self.member))

        log = AccessLog.objects.get(gym=self.gym, member=self.member)
        self.assertIn("visage", log.device_used)

    def test_a_face_is_not_refused_for_an_expired_qr_code(self):
        # Le QR code d'un membre peut etre perime sans que cela concerne son
        # visage : exiger sa fraicheur refuserait tous les passages faciaux.
        self.member.qr_code_expires_at = timezone.now() - timedelta(days=1)
        self.member.save(update_fields=["qr_code_expires_at"])

        response = self._pousser(enrollment.employee_no(self.member))

        self.assertTrue(response.json()["access"])

    # --- Ce qui ne doit pas passer ----------------------------------------------

    def test_a_manual_record_is_not_taken_for_a_member(self):
        # Le badge d'un employe, cree a la main sur le terminal, porte un
        # petit numero. Il ne doit jamais etre confondu avec un membre.
        response = self._pousser("2")

        self.assertFalse(response.json()["access"])
        self.assertFalse(AccessLog.objects.exists())

    def test_an_unknown_member_is_refused(self):
        response = self._pousser(enrollment.PLAGE_APPLICATION + 999999)

        self.assertFalse(response.json()["access"])
        self.assertFalse(AccessLog.objects.exists())

    def test_a_member_of_another_gym_is_refused(self):
        autre = Gym.objects.create(
            organization=self.organization,
            name="Autre salle",
            slug="autre-remontee",
            subdomain="autre-remontee",
        )
        etranger = Member.objects.create(
            gym=autre, first_name="Etranger", last_name="X", phone="+243860000009"
        )

        response = self._pousser(enrollment.employee_no(etranger))

        self.assertFalse(response.json()["access"])

    def test_a_suspended_member_is_refused_and_the_refusal_is_logged(self):
        self.member.status = "suspended"
        self.member.save(update_fields=["status"])

        response = self._pousser(enrollment.employee_no(self.member))

        self.assertFalse(response.json()["access"])
        log = AccessLog.objects.get(gym=self.gym, member=self.member)
        self.assertFalse(log.access_granted)
        self.assertTrue(log.denial_reason)

    # --- Le QR code continue de fonctionner --------------------------------------

    def test_a_qr_code_event_still_resolves_the_member(self):
        charge = {
            "AccessControllerEvent": {
                "QRCodeInfo": str(self.member.qr_code),
            }
        }
        response = self.client.post(
            self.url, data=json.dumps(charge), content_type="application/json"
        )

        self.assertTrue(response.json()["access"])
        log = AccessLog.objects.get(gym=self.gym, member=self.member)
        self.assertNotIn("visage", log.device_used)


class ReaderDeclarationTests(TestCase):
    """L'application doit s'annoncer au lecteur pour recevoir ses evenements."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Annonce", slug="org-annonce"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Annonce",
            slug="gym-annonce",
            subdomain="gym-annonce",
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="Terminal", host="10.0.0.9", password="secret"
        )

    def test_the_declared_url_carries_the_device_token(self):
        url = enrollment.url_de_notification(self.device, 8000, adresse="10.0.0.1")

        self.assertIn(str(self.device.webhook_token), url)
        self.assertTrue(url.startswith("http://10.0.0.1:8000/"))

    def test_the_declared_url_never_points_at_the_loopback(self):
        # Le lecteur joindrait alors sa propre boucle locale, pas le serveur.
        url = enrollment.url_de_notification(self.device, 8000, adresse="10.0.0.1")

        self.assertNotIn("127.0.0.1", url)
        self.assertNotIn("localhost", url)

    def test_the_reader_receives_address_port_and_subscription(self):
        with patch.object(hikvision.HikvisionClient, "request") as appel:
            enrollment.declarer_application(self.device, 8000, adresse="10.0.0.1")

        corps = appel.mock_calls[0].kwargs["body"]
        self.assertIn("<ipAddress>10.0.0.1</ipAddress>", corps)
        self.assertIn("<portNo>8000</portNo>", corps)
        # Sans abonnement aux evenements, le lecteur connait l'adresse mais
        # n'envoie rien.
        self.assertIn("<SubscribeEvent>", corps)
        # Le materiel refuse "json" en minuscules.
        self.assertIn("<parameterFormatType>JSON</parameterFormatType>", corps)

    def test_a_path_longer_than_the_hardware_limit_is_refused(self):
        client = hikvision.HikvisionClient("10.0.0.9", "admin", "x")

        with self.assertRaises(hikvision.HikvisionError):
            client.set_event_notification("http://10.0.0.1:8000/" + "a" * 200)

    def test_an_unreachable_reader_is_reported_plainly(self):
        with patch.object(
            hikvision.HikvisionClient,
            "set_event_notification",
            side_effect=hikvision.HikvisionUnreachable("cable arrache"),
        ):
            with self.assertRaises(enrollment.EnrollmentError) as capture:
                enrollment.declarer_application(self.device, 8000, adresse="10.0.0.1")

        self.assertIn("injoignable", str(capture.exception))

    # --- Viser le serveur public, sans tunnel --------------------------------
    #
    # Le lecteur sort vers internet tout seul : cette sortie n'est jamais
    # bloquee, la ou entrer dans le reseau de la salle exige un tunnel. Le
    # journal des passages n'a donc besoin d'aucun pont.

    def _corps_declare(self, url, emplacement=1):
        with patch.object(hikvision.HikvisionClient, "request") as appel:
            enrollment.declarer_url(self.device, url, emplacement=emplacement)
        return appel.mock_calls[0]

    def test_a_domain_name_is_declared_as_a_hostname(self):
        # Loge dans <ipAddress>, un nom de domaine est accepte sans erreur puis
        # ignore : le lecteur n'enverrait plus rien, sans rien signaler.
        corps = self._corps_declare(
            "https://www.royalgym-fitness.com/access/devices/webhook/abc/"
        ).kwargs["body"]

        self.assertIn("<hostName>www.royalgym-fitness.com</hostName>", corps)
        self.assertIn("<addressingFormatType>hostname</addressingFormatType>", corps)
        self.assertNotIn("<ipAddress>", corps)

    def test_an_ip_address_is_still_declared_as_an_ip(self):
        corps = self._corps_declare("http://10.0.0.1:8000/x/").kwargs["body"]

        self.assertIn("<ipAddress>10.0.0.1</ipAddress>", corps)
        self.assertIn("<addressingFormatType>ipaddress</addressingFormatType>", corps)
        self.assertNotIn("<hostName>", corps)

    def test_a_public_url_defaults_to_the_https_port(self):
        corps = self._corps_declare(
            "https://www.royalgym-fitness.com/access/devices/webhook/abc/"
        ).kwargs["body"]

        self.assertIn("<portNo>443</portNo>", corps)
        self.assertIn("<protocolType>HTTPS</protocolType>", corps)

    def test_the_public_target_uses_the_second_slot(self):
        # Ecrire dans le premier effacerait la destination locale, qui reste
        # necessaire tant que le tunnel n'existe pas.
        appel = self._corps_declare(
            "https://www.royalgym-fitness.com/access/devices/webhook/abc/",
            emplacement=enrollment.EMPLACEMENT_PUBLIC,
        )

        self.assertIn("/httpHosts/2", appel.args[0])
        self.assertIn("<id>2</id>", appel.kwargs["body"])

    def test_the_local_target_keeps_the_first_slot(self):
        appel = self._corps_declare("http://10.0.0.1:8000/x/")

        self.assertIn("/httpHosts/1", appel.args[0])

    def test_a_host_name_longer_than_the_hardware_limit_is_refused(self):
        # Le lecteur annonce hostName max=64 : au-dela il tronque en silence.
        client = hikvision.HikvisionClient("10.0.0.9", "admin", "x")

        with self.assertRaises(hikvision.HikvisionError) as capture:
            client.set_event_notification("https://" + "a" * 70 + ".com/x/")

        self.assertIn("trop long", str(capture.exception))

    def test_reading_back_a_hostname_target_shows_the_name(self):
        # Le lecteur laisse "0.0.0.0" dans <ipAddress> quand il vise un nom :
        # relire ce champ seul ferait croire a une declaration perdue.
        xml = (
            "<HttpHostNotification><id>2</id>"
            "<url>/access/devices/webhook/abc/</url>"
            "<protocolType>HTTPS</protocolType>"
            "<parameterFormatType>JSON</parameterFormatType>"
            "<addressingFormatType>hostname</addressingFormatType>"
            "<hostName>www.royalgym-fitness.com</hostName>"
            "<ipAddress>0.0.0.0</ipAddress>"
            "<portNo>443</portNo>"
            "</HttpHostNotification>"
        )
        client = hikvision.HikvisionClient("10.0.0.9", "admin", "x")

        with patch.object(hikvision.HikvisionClient, "request", return_value=xml):
            relu = client.get_event_notification(2)

        self.assertEqual(relu["hote"], "www.royalgym-fitness.com")
        self.assertNotEqual(relu["ip"], "0.0.0.0")


class DeviceScreenMessagesTests(TestCase):
    """Reglage des phrases affichees sur l'ecran du terminal."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Messages", slug="org-messages"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Messages",
            slug="gym-messages",
            subdomain="gym-messages",
        )
        module, _ = Module.objects.get_or_create(
            code="ACCESS", defaults={"name": "Access"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="Terminal", host="10.0.0.9", password="secret"
        )
        self.manager = User.objects.create_user(
            username="gerant-messages", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.manager, gym=self.gym, role="manager", is_active=True
        )
        self.client.force_login(self.manager)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()
        self.url = reverse("access:device_messages", args=[self.device.id])

        self.etat_lu = {
            "enabled": False,
            "messages": {
                "stranger": "",
                "authenticationSuccess": "",
                "authenticationFailed": "",
            },
        }

    def _lecture(self):
        return patch.object(
            hikvision.HikvisionClient, "get_custom_prompt", return_value=self.etat_lu
        )

    # --- L'ecran ---------------------------------------------------------------

    def test_the_screen_lists_the_three_messages(self):
        with self._lecture():
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Acces accorde")
        self.assertContains(response, "Acces refuse")
        self.assertContains(response, "Visage inconnu")

    def test_the_screen_warns_that_the_reader_shows_plain_text(self):
        # Sans cet avertissement, l'utilisateur croirait que le code couleur
        # de cet ecran apparait aussi sur le terminal.
        with self._lecture():
            response = self.client.get(self.url)

        self.assertContains(response, "ne sait pas les colorer")

    def test_the_screen_says_the_voice_is_not_configurable(self):
        with self._lecture():
            response = self.client.get(self.url)

        self.assertContains(response, "pas modifiable par cette voie")

    def test_an_unreachable_reader_does_not_block_the_screen(self):
        with patch.object(
            hikvision.HikvisionClient,
            "get_custom_prompt",
            side_effect=hikvision.HikvisionUnreachable("cable arrache"),
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Impossible de lire les messages actuels")

    # --- Ecriture ----------------------------------------------------------------

    def test_the_messages_reach_the_reader(self):
        with self._lecture(), patch.object(
            hikvision.HikvisionClient, "set_custom_prompt"
        ) as ecriture:
            self.client.post(
                self.url,
                {
                    "authenticationSuccess": "Bienvenue",
                    "authenticationFailed": "Voyez accueil",
                    "stranger": "Non reconnu",
                    "enabled": "on",
                },
                follow=True,
            )

        ecriture.assert_called_once()
        actif, envoyes = ecriture.mock_calls[0].args
        self.assertTrue(actif)
        self.assertEqual(envoyes["authenticationSuccess"], "Bienvenue")

    def test_a_message_longer_than_the_screen_is_refused_before_sending(self):
        with self._lecture(), patch.object(
            hikvision.HikvisionClient, "set_custom_prompt"
        ) as ecriture:
            response = self.client.post(
                self.url,
                {
                    "authenticationSuccess": "Bienvenue chez Royal Gym Kinshasa",
                    "authenticationFailed": "x",
                    "stranger": "y",
                    "enabled": "on",
                },
                follow=True,
            )

        ecriture.assert_not_called()
        self.assertContains(response, "depasse 16 caracteres")

    def test_unchecking_gives_the_reader_back_its_own_messages(self):
        with self._lecture(), patch.object(
            hikvision.HikvisionClient, "set_custom_prompt"
        ) as ecriture:
            self.client.post(
                self.url,
                {
                    "authenticationSuccess": "Bienvenue",
                    "authenticationFailed": "Voyez accueil",
                    "stranger": "Non reconnu",
                },
                follow=True,
            )

        actif, _ = ecriture.mock_calls[0].args
        self.assertFalse(actif)

    def test_the_change_is_traced_in_the_sensitive_log(self):
        with self._lecture(), patch.object(
            hikvision.HikvisionClient, "set_custom_prompt"
        ):
            self.client.post(
                self.url,
                {
                    "authenticationSuccess": "Bienvenue",
                    "authenticationFailed": "Voyez accueil",
                    "stranger": "Non reconnu",
                    "enabled": "on",
                },
                follow=True,
            )

        trace = SensitiveActivityLog.objects.get(
            action="access.device_messages_updated"
        )
        self.assertEqual(trace.actor, self.manager)
        self.assertTrue(trace.metadata["actif"])

    def test_a_reader_of_another_gym_is_out_of_reach(self):
        autre = Gym.objects.create(
            organization=self.organization,
            name="Autre",
            slug="autre-messages",
            subdomain="autre-messages",
        )
        etranger = AccessDevice.objects.create(
            gym=autre, name="Ailleurs", host="10.0.0.8", password="secret"
        )

        response = self.client.get(
            reverse("access:device_messages", args=[etranger.id])
        )

        self.assertEqual(response.status_code, 404)

    # --- Contrat avec le materiel --------------------------------------------------

    def test_an_empty_message_is_sent_as_a_dash(self):
        # Le materiel refuse une chaine vide : il exige au moins un caractere.
        client = hikvision.HikvisionClient("10.0.0.9", "admin", "x")

        with patch.object(client, "_json") as appel:
            client.set_custom_prompt(False, {"stranger": "", "authenticationSuccess": "",
                                             "authenticationFailed": ""})

        envoye = appel.mock_calls[0].kwargs["payload"]
        for entree in envoye["PromptList"]:
            self.assertEqual(entree["promptContent"], "-")

    def test_the_three_prompt_types_are_always_sent(self):
        client = hikvision.HikvisionClient("10.0.0.9", "admin", "x")

        with patch.object(client, "_json") as appel:
            client.set_custom_prompt(True, {"authenticationSuccess": "Bienvenue"})

        envoye = appel.mock_calls[0].kwargs["payload"]
        types = {e["promptType"] for e in envoye["PromptList"]}
        self.assertEqual(types, set(hikvision.HikvisionClient.PROMPT_TYPES))


class ReturnPassageTests(TestCase):
    """Un membre deja entre aujourd'hui repasse devant le lecteur."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Retour", slug="org-retour"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Retour",
            slug="gym-retour",
            subdomain="gym-retour",
        )
        module, _ = Module.objects.get_or_create(
            code="ACCESS", defaults={"name": "Access"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="Terminal", host="10.0.0.9", password="secret"
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Alice",
            last_name="Nzuzi",
            phone="+243870000001",
        )
        plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        today = timezone.localdate()
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=plan,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=29),
            is_active=True,
        )
        self.url = reverse("access:device_webhook", args=[self.device.webhook_token])

        patcher = patch("access.hikvision.HikvisionClient.open_door")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _passage(self):
        charge = {
            "AccessControllerEvent": {
                "employeeNoString": enrollment.employee_no(self.member),
                "currentVerifyMode": "face",
            }
        }
        return self.client.post(
            self.url, data=json.dumps(charge), content_type="application/json"
        )

    # --- Ce que voit le membre a la porte ------------------------------------

    def test_the_first_passage_is_a_plain_entry(self):
        reponse = self._passage()

        self.assertTrue(reponse.json()["access"])
        log = AccessLog.objects.get(member=self.member)
        self.assertFalse(log.is_return)

    def test_a_second_passage_is_granted_not_refused(self):
        # L'application doit dire la meme chose que le lecteur, qui decide
        # seul et ouvre : sinon le membre voit un feu vert sur le terminal
        # pendant que le journal enregistre un refus.
        self._passage()
        reponse = self._passage()

        self.assertTrue(reponse.json()["access"])

    def test_a_second_passage_is_marked_as_a_return(self):
        self._passage()
        self._passage()

        logs = AccessLog.objects.filter(member=self.member).order_by("id")
        self.assertEqual(logs.count(), 2)
        self.assertFalse(logs[0].is_return)
        self.assertTrue(logs[1].is_return)
        self.assertEqual(logs[1].denial_reason, RETURN_LABEL)

    def test_a_third_passage_is_also_a_return(self):
        self._passage()
        self._passage()
        self._passage()

        retours = AccessLog.objects.filter(member=self.member, is_return=True)
        self.assertEqual(retours.count(), 2)

    # --- Ce que comptent les statistiques ------------------------------------

    def test_returns_never_inflate_the_daily_attendance(self):
        self._passage()
        self._passage()
        self._passage()

        stats = self.client.post(
            self.url,
            data=json.dumps({"AccessControllerEvent": {"employeeNoString": "0"}}),
            content_type="application/json",
        )
        # Le comptage se lit sur un passage reel : on le relit directement.
        from access.views import _today_stats

        compte = _today_stats(self.gym)
        self.assertEqual(compte["entries"], 1)
        self.assertEqual(compte["returns"], 2)
        self.assertEqual(compte["denied"], 0)

    def test_two_different_members_count_two_visits(self):
        autre = Member.objects.create(
            gym=self.gym,
            first_name="Bruno",
            last_name="Kalala",
            phone="+243870000002",
        )
        plan = SubscriptionPlan.objects.get(gym=self.gym)
        today = timezone.localdate()
        MemberSubscription.objects.create(
            gym=self.gym,
            member=autre,
            plan=plan,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=29),
            is_active=True,
        )

        self._passage()
        self.client.post(
            self.url,
            data=json.dumps(
                {"AccessControllerEvent": {"employeeNoString": enrollment.employee_no(autre)}}
            ),
            content_type="application/json",
        )

        from access.views import _today_stats

        self.assertEqual(_today_stats(self.gym)["entries"], 2)

    # --- Un vrai refus reste un refus ------------------------------------------

    def test_a_suspended_member_is_still_refused_on_a_return(self):
        self._passage()
        self.member.status = "suspended"
        self.member.save(update_fields=["status"])

        reponse = self._passage()

        self.assertFalse(reponse.json()["access"])
        dernier = AccessLog.objects.filter(member=self.member).order_by("-id").first()
        self.assertFalse(dernier.access_granted)
        self.assertFalse(dernier.is_return)

    def test_a_member_without_subscription_is_refused_not_marked_a_return(self):
        MemberSubscription.objects.filter(member=self.member).update(is_active=False)

        reponse = self._passage()

        self.assertFalse(reponse.json()["access"])
        log = AccessLog.objects.get(member=self.member)
        self.assertFalse(log.is_return)

    # --- Ce que lit l'equipe ----------------------------------------------------

    def test_the_journal_distinguishes_a_return_from_an_entry(self):
        self._passage()
        self._passage()

        from access.views import _serialize_log

        logs = AccessLog.objects.filter(member=self.member).order_by("id")
        self.assertEqual(_serialize_log(logs[0])["status"], "success")
        self.assertEqual(_serialize_log(logs[1])["status"], "return")


class ReturnOnlyByFaceTests(TestCase):
    """
    Un QR code se prete, un badge se passe, un nom se donne a l'accueil.

    Seul le visage garantit que la personne devant le lecteur est bien le
    membre : c'est le seul mode qui autorise un second passage le meme jour.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Partage", slug="org-partage"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Partage",
            slug="gym-partage",
            subdomain="gym-partage",
        )
        module, _ = Module.objects.get_or_create(
            code="ACCESS", defaults={"name": "Access"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="Terminal", host="10.0.0.9", password="secret"
        )
        self.member = Member.objects.create(
            gym=self.gym,
            first_name="Alice",
            last_name="Nzuzi",
            phone="+243880000001",
        )
        plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        today = timezone.localdate()
        MemberSubscription.objects.create(
            gym=self.gym,
            member=self.member,
            plan=plan,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=29),
            is_active=True,
        )
        self.url = reverse("access:device_webhook", args=[self.device.webhook_token])

        patcher = patch("access.hikvision.HikvisionClient.open_door")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _passage(self, mode):
        """Passage remonte par le lecteur, dans le mode indique."""
        evenement = {"employeeNoString": enrollment.employee_no(self.member)}
        if mode is not None:
            evenement["currentVerifyMode"] = mode
        return self.client.post(
            self.url,
            data=json.dumps({"AccessControllerEvent": evenement}),
            content_type="application/json",
        )

    # --- Le visage ouvre droit au retour --------------------------------------

    def test_a_face_may_come_back_the_same_day(self):
        self._passage("face")
        reponse = self._passage("face")

        self.assertTrue(reponse.json()["access"])
        self.assertEqual(reponse.json()["reason"], RETURN_LABEL)

    # --- Les autres modes, non ------------------------------------------------

    def test_a_badge_may_not_come_back_the_same_day(self):
        # Un badge se prete : le second passage peut etre quelqu'un d'autre.
        self._passage("card")
        reponse = self._passage("card")

        self.assertFalse(reponse.json()["access"])
        self.assertEqual(reponse.json()["reason"], SHARED_CREDENTIAL_REASON)

    def test_a_fingerprint_is_treated_prudently(self):
        # Une empreinte n'est pas pretable, mais tant qu'on n'a pas verifie ce
        # que le materiel envoie exactement, on refuse plutot que de risquer
        # d'ouvrir sur un mode mal identifie.
        self._passage("fp")
        reponse = self._passage("fp")

        self.assertFalse(reponse.json()["access"])

    def test_a_combined_mode_does_not_prove_the_face_was_used(self):
        # "cardOrFace" : le badge seul a pu suffire.
        self._passage("cardOrFace")
        reponse = self._passage("cardOrFace")

        self.assertFalse(reponse.json()["access"])

    def test_a_missing_mode_never_grants_a_return(self):
        # Firmware qui n'annonce pas le mode : on ne devine pas.
        self._passage(None)
        reponse = self._passage(None)

        self.assertFalse(reponse.json()["access"])

    # --- Ce que lit l'equipe ---------------------------------------------------

    def test_the_journal_names_the_mode_used(self):
        self._passage("face")
        self._passage("card")

        methodes = list(
            AccessLog.objects.filter(member=self.member)
            .order_by("id")
            .values_list("device_used", flat=True)
        )
        self.assertEqual(methodes[0], "Terminal (visage)")
        self.assertEqual(methodes[1], "Terminal (badge)")

    def test_the_refusal_says_why_and_what_works(self):
        self._passage("card")
        reponse = self._passage("card")

        motif = reponse.json()["reason"]
        self.assertIn("reconnaissance faciale", motif)

    # --- La lecture du mode ------------------------------------------------------

    def test_a_real_event_from_the_hardware_is_recognised_as_a_face(self):
        """
        Evenement releve sur un DS-K1T342MFWX-E1 en V4.48.40.

        Il porte currentVerifyMode = "faceOrFpOrCardOrPw", qui decrit ce que la
        fiche **autorise** et non ce qui a **servi**. S'y fier faisait passer
        tous les visages pour des badges.
        """
        evenement = {
            "major": 5,
            "minor": 8,
            "employeeNoString": "1000107",
            "currentVerifyMode": "faceOrFpOrCardOrPw",
            "FaceRect": {"height": 0.413, "width": 0.233, "x": 0.31, "y": 0.538},
        }

        self.assertTrue(hikvision.est_un_visage(evenement))

    def test_the_face_rectangle_alone_proves_a_face(self):
        # Fait physique : la camera a localise un visage dans l'image.
        self.assertTrue(hikvision.est_un_visage({"FaceRect": {"x": 0.1}}))

    def test_the_documented_face_event_code_counts(self):
        self.assertTrue(hikvision.est_un_visage({"minor": 75}))

    def test_a_permissive_mode_alone_never_proves_a_face(self):
        # Ni visage detecte, ni code d'evenement : le badge a pu suffire.
        self.assertFalse(
            hikvision.est_un_visage({"currentVerifyMode": "faceOrFpOrCardOrPw"})
        )
        self.assertFalse(hikvision.est_un_visage({"currentVerifyMode": "cardOrFace"}))

    def test_an_explicit_face_mode_still_counts(self):
        self.assertTrue(hikvision.est_un_visage({"currentVerifyMode": "face"}))

    def test_an_empty_or_absurd_event_is_never_a_face(self):
        for valeur in ({}, {"minor": 1}, {"currentVerifyMode": "card"}, None, "face"):
            self.assertFalse(hikvision.est_un_visage(valeur), repr(valeur))


class DeviceAnnounceButtonTests(TestCase):
    """Declarer l'application au lecteur depuis l'ecran des lecteurs."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Annonce Bouton", slug="org-annonce-bouton"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Annonce Bouton",
            slug="gym-annonce-bouton",
            subdomain="gym-annonce-bouton",
        )
        module, _ = Module.objects.get_or_create(
            code="ACCESS", defaults={"name": "Access"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="Terminal", host="10.0.0.9", password="secret"
        )
        self.manager = User.objects.create_user(
            username="gerant-annonce", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.manager, gym=self.gym, role="manager", is_active=True
        )
        self.client.force_login(self.manager)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()
        self.url = reverse("access:device_announce", args=[self.device.id])

    def test_the_button_declares_the_application_to_the_reader(self):
        with patch.object(hikvision.HikvisionClient, "set_event_notification") as pose:
            reponse = self.client.post(self.url)

        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.json()["ok"])
        pose.assert_called_once()

    def test_the_declared_address_is_never_the_loopback(self):
        # Le lecteur joindrait sa propre boucle locale, pas le serveur.
        with patch.object(hikvision.HikvisionClient, "set_event_notification"):
            reponse = self.client.post(self.url)

        url = reponse.json()["url"]
        self.assertNotIn("127.0.0.1", url)
        self.assertNotIn("localhost", url)
        self.assertIn(str(self.device.webhook_token), url)

    def test_an_unreachable_reader_is_reported_without_crashing(self):
        with patch.object(
            hikvision.HikvisionClient,
            "set_event_notification",
            side_effect=hikvision.HikvisionUnreachable("cable arrache"),
        ):
            reponse = self.client.post(self.url)

        self.assertEqual(reponse.status_code, 400)
        self.assertIn("injoignable", reponse.json()["error"])

    def test_the_declaration_is_traced_in_the_sensitive_log(self):
        with patch.object(hikvision.HikvisionClient, "set_event_notification"):
            self.client.post(self.url)

        trace = SensitiveActivityLog.objects.get(action="access.device_announced")
        self.assertEqual(trace.actor, self.manager)

    def test_a_reader_of_another_gym_is_out_of_reach(self):
        autre = Gym.objects.create(
            organization=self.organization,
            name="Autre",
            slug="autre-annonce",
            subdomain="autre-annonce",
        )
        etranger = AccessDevice.objects.create(
            gym=autre, name="Ailleurs", host="10.0.0.8", password="secret"
        )

        reponse = self.client.post(
            reverse("access:device_announce", args=[etranger.id])
        )

        self.assertEqual(reponse.status_code, 404)

    def test_a_receptionist_cannot_declare_the_application(self):
        reception = User.objects.create_user(
            username="reception-annonce", password="pass12345"
        )
        UserGymRole.objects.create(
            user=reception, gym=self.gym, role="reception", is_active=True
        )
        self.client.force_login(reception)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

        reponse = self.client.post(self.url)

        self.assertIn(reponse.status_code, (302, 403))


class TunnelledDeviceTests(TestCase):
    """
    Un serveur heberge ne peut pas atteindre une adresse privee.

    Le lecteur est alors joint par un tunnel, qui lui donne un nom public et
    exige un jeton pour prouver que l'appel vient bien de notre serveur.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Tunnel", slug="org-tunnel"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Tunnel",
            slug="gym-tunnel",
            subdomain="gym-tunnel",
        )

    def _lecteur(self, **overrides):
        champs = {
            "gym": self.gym,
            "name": "Terminal",
            "host": "lecteur-kinshasa.exemple.com",
            "port": 443,
            "use_https": True,
            "password": "secret",
            "tunnel_client_id": "identifiant-du-jeton",
            "tunnel_client_secret": "secret-du-jeton",
        }
        champs.update(overrides)
        return AccessDevice.objects.create(**champs)

    # --- L'adresse ---------------------------------------------------------

    def test_a_hostname_is_accepted_as_an_address(self):
        # Le champ n'acceptait qu'une adresse IP : un nom de tunnel etait
        # refuse, ce qui rendait la solution impossible.
        lecteur = self._lecteur()
        lecteur.full_clean(exclude=["webhook_token"])

        self.assertEqual(lecteur.host, "lecteur-kinshasa.exemple.com")

    def test_a_local_address_still_works(self):
        lecteur = self._lecteur(host="192.168.1.87", port=80, use_https=False)
        lecteur.full_clean(exclude=["webhook_token"])

    def test_an_absurd_address_is_refused_with_an_example(self):
        lecteur = self._lecteur(host="ceci n'est pas une adresse")

        with self.assertRaises(ValidationError) as capture:
            lecteur.full_clean(exclude=["webhook_token"])

        self.assertIn("nom d'hote", str(capture.exception))

    def test_the_client_builds_an_https_url_from_the_hostname(self):
        client = hikvision.HikvisionClient.from_device(self._lecteur())

        self.assertEqual(client.base_url, "https://lecteur-kinshasa.exemple.com")

    # --- Le jeton ------------------------------------------------------------

    def test_every_request_carries_the_tunnel_token(self):
        lecteur = self._lecteur()
        client = hikvision.HikvisionClient.from_device(lecteur)

        self.assertEqual(
            client.tunnel_headers,
            {
                "CF-Access-Client-Id": "identifiant-du-jeton",
                "CF-Access-Client-Secret": "secret-du-jeton",
            },
        )

    def test_a_device_on_the_local_network_sends_no_token(self):
        # Sur le LAN il n'y a pas de tunnel : ajouter des en-tetes inutiles
        # risquerait de derouter le materiel.
        lecteur = self._lecteur(
            host="192.168.1.87", tunnel_client_id="", tunnel_client_secret=""
        )

        self.assertEqual(lecteur.tunnel_headers, {})

    def test_half_a_token_is_treated_as_no_token(self):
        lecteur = self._lecteur(tunnel_client_secret="")

        self.assertEqual(lecteur.tunnel_headers, {})

    def test_the_token_reaches_the_actual_request(self):
        client = hikvision.HikvisionClient.from_device(self._lecteur())

        with patch.object(client, "_opener") as ouvreur:
            ouvreur.return_value.open.return_value.read.return_value = b"<x/>"
            client.request("/ISAPI/System/deviceInfo")

        envoyee = ouvreur.return_value.open.call_args.args[0]
        self.assertEqual(
            envoyee.get_header("Cf-access-client-id"), "identifiant-du-jeton"
        )

    # --- Ce que l'interface expose ---------------------------------------------

    def test_the_secret_never_leaves_the_server(self):
        lecteur = self._lecteur()

        charge = _serialize_device(lecteur)

        texte = json.dumps(charge)
        self.assertNotIn("secret-du-jeton", texte)
        self.assertNotIn("identifiant-du-jeton", texte)
        self.assertNotIn("secret", texte.replace("tunnel_protege", ""))
        self.assertTrue(charge["tunnel_protege"])

    def test_a_local_device_is_reported_as_unprotected(self):
        lecteur = self._lecteur(
            host="192.168.1.87", tunnel_client_id="", tunnel_client_secret=""
        )

        self.assertFalse(_serialize_device(lecteur)["tunnel_protege"])


class OfflineDeviceBannerTests(TestCase):
    """
    Une panne franche se voit ; la panne silencieuse, non.

    Le lecteur continue d'ouvrir seul, mais les passages ne remontent plus et
    les abonnements encaisses ne lui parviennent pas.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Sante", slug="org-sante"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Sante",
            slug="gym-sante",
            subdomain="gym-sante",
        )
        module, _ = Module.objects.get_or_create(
            code="ACCESS", defaults={"name": "Access"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="Terminal", host="10.0.0.9", password="secret"
        )
        self.manager = User.objects.create_user(
            username="gerant-sante", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.manager, gym=self.gym, role="manager", is_active=True
        )
        self._connecter(self.manager)

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _vu_il_y_a(self, heures):
        AccessDevice.objects.filter(pk=self.device.pk).update(
            last_seen_at=timezone.now() - timedelta(hours=heures)
        )

    # --- Quand le bandeau parait --------------------------------------------

    def test_a_reader_silent_for_hours_raises_the_banner(self):
        self._vu_il_y_a(5)

        resume = resume_hors_ligne(self.gym)

        self.assertIsNotNone(resume)
        self.assertEqual(resume["total"], 1)

    def test_a_short_outage_does_not_alarm_the_team(self):
        # Une coupure d'une heure ne doit pas declencher l'alerte : elle serait
        # criee si souvent qu'on cesserait de la lire.
        self._vu_il_y_a(1)

        self.assertIsNone(resume_hors_ligne(self.gym))

    def test_a_reader_never_contacted_stays_quiet(self):
        # La fiche vient d'etre creee : rien d'anormal a signaler.
        self.assertIsNone(self.device.last_seen_at)
        self.assertIsNone(resume_hors_ligne(self.gym))

    def test_an_inactive_reader_is_ignored(self):
        self._vu_il_y_a(10)
        AccessDevice.objects.filter(pk=self.device.pk).update(is_active=False)

        self.assertIsNone(resume_hors_ligne(self.gym))

    # --- Ce que l'utilisateur lit ---------------------------------------------

    def test_the_banner_follows_the_manager_on_every_page(self):
        self._vu_il_y_a(5)

        response = self.client.get(reverse("access:acces_dashboard"))

        self.assertContains(response, "ne repond plus")
        self.assertContains(response, "La porte continue de fonctionner")

    def test_the_banner_says_what_stops_working(self):
        # Sans cela, l'equipe pourrait croire que la salle est bloquee et
        # renvoyer les membres chez eux.
        self._vu_il_y_a(5)

        response = self.client.get(reverse("access:acces_dashboard"))

        self.assertContains(response, "les passages ne sont plus")

    def test_a_receptionist_does_not_see_the_banner(self):
        self._vu_il_y_a(5)
        reception = User.objects.create_user(
            username="reception-sante", password="pass12345"
        )
        UserGymRole.objects.create(
            user=reception, gym=self.gym, role="reception", is_active=True
        )
        self._connecter(reception)

        response = self.client.get(reverse("access:acces_dashboard"))

        self.assertNotContains(response, "ne repond plus")

    def test_a_reader_of_another_gym_never_raises_our_banner(self):
        autre = Gym.objects.create(
            organization=self.organization, name="Ailleurs",
            slug="ailleurs-sante", subdomain="ailleurs-sante",
        )
        AccessDevice.objects.create(
            gym=autre, name="Autre", host="10.0.0.8", password="secret",
            last_seen_at=timezone.now() - timedelta(hours=20),
        )

        self.assertIsNone(resume_hors_ligne(self.gym))


class DeviceAddressTests(TestCase):
    """L'adresse du lecteur, apres le changement de type du champ."""

    def test_a_netmask_left_by_the_type_change_is_refused(self):
        # PostgreSQL stockait ce champ en type inet : le convertir en texte a
        # rendu "172.20.10.3" sous la forme "172.20.10.3/32", et la fiche ne
        # passait plus la validation. Une migration nettoie l'existant ; ce
        # test garantit qu'une telle valeur ne rentre pas de nouveau.
        with self.assertRaises(ValidationError):
            validate_device_host("172.20.10.3/32")

    def test_a_plain_address_passes(self):
        validate_device_host("172.20.10.3")


class ManualDeviceEntryTests(TestCase):
    """
    Creer la fiche d'un lecteur que le serveur ne peut pas joindre.

    La detection balaie le reseau du serveur. Hebergee en ligne, elle ne verra
    jamais le lecteur d'une salle : sans saisie manuelle, la fiche est
    impossible a creer, et son URL de notification reste inaccessible.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Manuelle", slug="org-manuelle"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Manuel",
            slug="gym-manuel",
            subdomain="gym-manuel",
        )
        module, _ = Module.objects.get_or_create(
            code="ACCESS", defaults={"name": "Access"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.owner = User.objects.create_user(username="owner-manuel", password="pass12345")
        UserGymRole.objects.create(
            user=self.owner, gym=self.gym, role="owner", is_active=True
        )
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _creer(self, **extra):
        charge = {
            "name": "Entree principale",
            "host": "192.168.1.188",
            "port": 80,
            "username": "admin",
            "password": "motdepasse",
            "door_number": 1,
        }
        charge.update(extra)
        return self.client.post(
            reverse("access:device_create"),
            data=json.dumps(charge),
            content_type="application/json",
        )

    # --- La fiche existe meme sans liaison ------------------------------------

    def test_an_unreachable_reader_is_still_registered(self):
        with patch.object(
            hikvision.HikvisionClient,
            "device_info",
            side_effect=hikvision.HikvisionUnreachable("hors de portee"),
        ):
            response = self._creer()

        self.assertEqual(response.status_code, 201)
        self.assertTrue(AccessDevice.objects.filter(gym=self.gym).exists())

    def test_the_answer_carries_the_notification_url(self):
        # C'est la seule facon d'obtenir le jeton du lecteur : il n'est
        # affiche nulle part ailleurs.
        with patch.object(
            hikvision.HikvisionClient,
            "device_info",
            side_effect=hikvision.HikvisionUnreachable("hors de portee"),
        ):
            response = self._creer()

        device = AccessDevice.objects.get(gym=self.gym)
        self.assertEqual(
            response.json()["device"]["webhook_path"],
            f"/access/devices/webhook/{device.webhook_token}/",
        )

    def test_the_failed_link_is_reported_without_hiding_the_success(self):
        with patch.object(
            hikvision.HikvisionClient,
            "device_info",
            side_effect=hikvision.HikvisionUnreachable("hors de portee"),
        ):
            response = self._creer()

        self.assertFalse(response.json()["test"]["ok"])

    # --- Le tunnel se renseigne des la creation --------------------------------

    def test_the_tunnel_token_is_kept(self):
        # Sans ces champs, activer le tunnel plus tard obligeait a supprimer la
        # fiche et a la recreer, ce qui change son jeton et fait taire le
        # lecteur jusqu'a une nouvelle declaration.
        with patch.object(
            hikvision.HikvisionClient,
            "device_info",
            side_effect=hikvision.HikvisionUnreachable("hors de portee"),
        ):
            self._creer(
                host="salle.exemple.com",
                port=443,
                use_https=True,
                tunnel_client_id="identifiant.access",
                tunnel_client_secret="secret-du-tunnel",
            )

        device = AccessDevice.objects.get(gym=self.gym)
        self.assertTrue(device.use_https)
        self.assertEqual(device.tunnel_headers["CF-Access-Client-Id"], "identifiant.access")

    def test_the_tunnel_secret_is_never_sent_back(self):
        with patch.object(
            hikvision.HikvisionClient,
            "device_info",
            side_effect=hikvision.HikvisionUnreachable("hors de portee"),
        ):
            response = self._creer(
                use_https=True,
                tunnel_client_id="identifiant.access",
                tunnel_client_secret="secret-du-tunnel",
            )

        self.assertNotIn("secret-du-tunnel", response.content.decode())

    def test_a_host_name_is_accepted_as_an_address(self):
        with patch.object(
            hikvision.HikvisionClient,
            "device_info",
            side_effect=hikvision.HikvisionUnreachable("hors de portee"),
        ):
            response = self._creer(host="salle-royal.exemple.com")

        self.assertEqual(response.status_code, 201)


class DeviceScreenTemplateTests(TestCase):
    """Ce que la page des lecteurs doit offrir."""

    def test_the_page_offers_a_manual_entry(self):
        # La detection ne suffit pas en production : le serveur en ligne ne
        # voit aucun reseau de salle.
        gabarit = (
            Path(settings.BASE_DIR) / "access" / "templates" / "access" / "acces.html"
        ).read_text(encoding="utf-8")

        # Verifier la seule existence de la fonction ne prouverait rien :
        # c est le bouton qui la rend atteignable.
        self.assertIn('onclick="openManualDeviceModal()"', gabarit)

    def test_the_address_field_is_not_locked(self):
        # Verrouille, il ne pouvait recevoir qu'une adresse issue de la
        # detection reseau.
        gabarit = (
            Path(settings.BASE_DIR) / "access" / "templates" / "access" / "acces.html"
        ).read_text(encoding="utf-8")

        champ = gabarit[gabarit.find('id="deviceHost"') - 200 :][:400]
        self.assertNotIn("readonly", champ)


class DeviceDirectionIndicatorTests(TestCase):
    """
    Deux sens de circulation, deux voyants.

    Le lecteur sort vers internet tout seul ; c'est l'appeler qui exige
    d'entrer dans le reseau de la salle. Un voyant unique melangeait les deux
    et faisait passer un lecteur qui remonte fidelement ses passages pour une
    panne, au seul motif que le serveur ne pouvait pas le joindre.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Sens", slug="org-sens"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Sens",
            slug="gym-sens",
            subdomain="gym-sens",
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="Terminal", host="10.0.0.9", password="secret"
        )

    def _vu_il_y_a(self, **ecart):
        AccessDevice.objects.filter(pk=self.device.pk).update(
            last_seen_at=timezone.now() - timedelta(**ecart)
        )
        self.device.refresh_from_db()

    # --- Le lecteur nous parle -------------------------------------------------

    def test_a_recent_heartbeat_means_the_reader_speaks_to_us(self):
        self._vu_il_y_a(seconds=30)

        self.assertTrue(self.device.nous_parle)

    def test_a_reader_silent_for_ten_minutes_no_longer_speaks(self):
        self._vu_il_y_a(minutes=10)

        self.assertFalse(self.device.nous_parle)

    def test_a_reader_never_heard_from_does_not_speak(self):
        self.assertIsNone(self.device.last_seen_at)
        self.assertFalse(self.device.nous_parle)

    def test_an_outbound_failure_does_not_silence_the_reader(self):
        # C'est exactement le cas du serveur en ligne : il ne peut pas appeler
        # le lecteur, mais recoit tous ses passages.
        self._vu_il_y_a(seconds=30)
        AccessDevice.objects.filter(pk=self.device.pk).update(
            last_error="Lecteur injoignable"
        )
        self.device.refresh_from_db()

        self.assertTrue(self.device.nous_parle)
        self.assertFalse(self.device.est_joignable)

    # --- L'application parle au lecteur ---------------------------------------

    def test_a_reader_without_error_is_pilotable(self):
        self.assertTrue(self.device.est_joignable)

    def test_a_failed_call_makes_it_unpilotable(self):
        AccessDevice.objects.filter(pk=self.device.pk).update(last_error="timeout")
        self.device.refresh_from_db()

        self.assertFalse(self.device.est_joignable)

    # --- Ce que l'ecran recoit -------------------------------------------------

    def test_both_directions_reach_the_screen(self):
        self._vu_il_y_a(seconds=30)
        AccessDevice.objects.filter(pk=self.device.pk).update(last_error="timeout")
        self.device.refresh_from_db()

        charge = _serialize_device(self.device)

        self.assertTrue(charge["nous_parle"])
        self.assertFalse(charge["joignable"])

    def test_a_heartbeat_does_not_clear_a_failed_outbound_call(self):
        # Le battement du lecteur effacait l'erreur du dernier appel sortant :
        # le voyant "Pilotable" repassait au vert trente secondes apres chaque
        # echec, et annoncait joignable un lecteur que rien ne pouvait appeler.
        AccessDevice.objects.filter(pk=self.device.pk).update(
            last_error="Lecteur injoignable : timed out"
        )

        self.client.post(
            reverse("access:device_webhook", args=[self.device.webhook_token]),
            data=json.dumps({"AccessControllerEvent": {}}),
            content_type="application/json",
        )

        self.device.refresh_from_db()
        self.assertFalse(self.device.est_joignable)

    def test_a_heartbeat_still_refreshes_the_contact_date(self):
        AccessDevice.objects.filter(pk=self.device.pk).update(
            last_error="Lecteur injoignable : timed out"
        )

        self.client.post(
            reverse("access:device_webhook", args=[self.device.webhook_token]),
            data=json.dumps({"AccessControllerEvent": {}}),
            content_type="application/json",
        )

        self.device.refresh_from_db()
        self.assertTrue(self.device.nous_parle)

    def test_a_successful_outbound_call_clears_the_error(self):
        # C'est le seul evenement qui prouve que le lecteur est joignable.
        AccessDevice.objects.filter(pk=self.device.pk).update(last_error="timed out")
        self.device.refresh_from_db()

        with patch.object(
            hikvision.HikvisionClient,
            "device_info",
            return_value={"model": "X", "serial": "1", "firmware": "V1", "mac": ""},
        ):
            _refresh_device_state(self.device)

        self.device.refresh_from_db()
        self.assertTrue(self.device.est_joignable)

    def test_a_stale_reader_is_no_longer_called_online(self):
        # L'ancien voyant restait au vert indefiniment : un lecteur mort depuis
        # un mois passait pour vivant tant qu'aucun appel n'avait echoue.
        self._vu_il_y_a(days=30)

        self.assertFalse(self.device.is_online)


class RepeatedDeviceEventTests(TestCase):
    """
    Le lecteur reemet la meme notification tant qu'il ne l'estime pas acquittee.

    Observe en production : un seul passage a produit dix-neuf lignes de
    journal, toutes portant le meme numero d'evenement du materiel.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Redite", slug="org-redite"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Redite",
            slug="gym-redite",
            subdomain="gym-redite",
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="L1", host="10.0.0.9", password="secret",
            open_on_granted=True,
        )
        self.member = Member.objects.create(
            gym=self.gym, first_name="Rossy", last_name="Mundyo",
            phone="+243870000001",
        )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Standard", price=80, duration_days=30
        )
        MemberSubscription.objects.create(
            gym=self.gym, member=self.member, plan=self.plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )
        self.url = reverse("access:device_webhook", args=[self.device.webhook_token])

    def _pousser(self, serial, minor=75):
        charge = {
            "AccessControllerEvent": {
                "employeeNoString": enrollment.employee_no(self.member),
                "serialNo": serial,
                "minor": minor,
                "currentVerifyMode": "faceOrFpOrCardOrPw",
            }
        }
        return self.client.post(
            self.url, data=json.dumps(charge), content_type="application/json"
        )

    # --- La redite ne doit rien ajouter ---------------------------------------

    def test_the_same_event_logs_only_once(self):
        for _ in range(5):
            self._pousser(1177)

        self.assertEqual(AccessLog.objects.filter(gym=self.gym).count(), 1)

    def test_the_repeat_still_answers_access_granted(self):
        # Repondre par un refus ferait clignoter un feu rouge sur le terminal
        # pour un passage deja autorise.
        premier = self._pousser(1177)
        redite = self._pousser(1177)

        self.assertTrue(premier.json()["access"])
        self.assertTrue(redite.json()["access"])

    def test_the_repeat_points_at_the_original_line(self):
        premier = self._pousser(1177)
        redite = self._pousser(1177)

        self.assertEqual(redite.json()["log_id"], premier.json()["log_id"])

    def test_a_new_event_number_is_a_new_passage(self):
        # Une redite se distingue d'un vrai retour par le numero du materiel.
        self._pousser(1177)
        self._pousser(1178)

        self.assertEqual(AccessLog.objects.filter(gym=self.gym).count(), 2)

    def test_the_event_number_is_kept_on_the_line(self):
        # C'est aussi la cle qui empeche le rattrapage de recreer ce passage.
        self._pousser(1177)

        log = AccessLog.objects.get(gym=self.gym)
        self.assertEqual(log.device_event_id, "1177")

    def test_an_event_without_a_number_is_still_logged(self):
        # Certains firmwares n'en envoient pas : mieux vaut un doublon possible
        # qu'un passage perdu.
        self._pousser("")

        self.assertEqual(AccessLog.objects.filter(gym=self.gym).count(), 1)


class DoorCommandScopeTests(TestCase):
    """
    Quand l'application doit commander le relais, et quand elle doit s'abstenir.

    Un appel impossible expirait au bout de cinq secondes et retardait la
    reponse au lecteur, qui cessait d'attendre et reemettait son evenement.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Relais", slug="org-relais"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Relais",
            slug="gym-relais",
            subdomain="gym-relais",
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="L1", host="10.0.0.9", password="secret",
            open_on_granted=True,
        )
        self.member = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243870000002",
        )
        self.plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Standard", price=80, duration_days=30
        )
        MemberSubscription.objects.create(
            gym=self.gym, member=self.member, plan=self.plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )
        self.url = reverse("access:device_webhook", args=[self.device.webhook_token])

    def _pousser(self, charge):
        return self.client.post(
            self.url, data=json.dumps(charge), content_type="application/json"
        )

    def test_a_recognised_face_does_not_trigger_the_relay(self):
        # Le lecteur a decide seul : la porte est deja ouverte.
        with patch.object(door, "open_doors") as commande:
            self._pousser({
                "AccessControllerEvent": {
                    "employeeNoString": enrollment.employee_no(self.member),
                    "serialNo": 2001,
                    "minor": 75,
                }
            })

        commande.assert_not_called()

    def test_a_qr_code_still_triggers_the_relay(self):
        # Le lecteur n'est alors qu'un scanner : sans cet ordre, rien n'ouvre.
        with patch.object(door, "open_doors", return_value=[]) as commande:
            self._pousser({
                "AccessControllerEvent": {
                    "QRCodeInfo": str(self.member.qr_code),
                    "serialNo": 2002,
                }
            })

        commande.assert_called_once()

    def test_a_refused_qr_code_never_opens(self):
        self.member.status = "suspended"
        self.member.save(update_fields=["status"])

        with patch.object(door, "open_doors") as commande:
            self._pousser({
                "AccessControllerEvent": {
                    "QRCodeInfo": str(self.member.qr_code),
                    "serialNo": 2003,
                }
            })

        commande.assert_not_called()

    def test_the_face_passage_is_still_logged_as_granted(self):
        # Ne plus commander le relais ne doit rien changer a la decision.
        with patch.object(door, "open_doors") as commande:
            reponse = self._pousser({
                "AccessControllerEvent": {
                    "employeeNoString": enrollment.employee_no(self.member),
                    "serialNo": 2004,
                    "minor": 75,
                }
            })

        commande.assert_not_called()
        self.assertTrue(reponse.json()["access"])
        self.assertTrue(AccessLog.objects.get(gym=self.gym).access_granted)


class DeviceUpdateTests(TestCase):
    """
    Modifier la fiche d'un lecteur sans perdre son jeton.

    Sans cette operation, changer d'adresse imposait de supprimer la fiche et
    de la recreer. Le jeton du webhook changeait alors, le lecteur continuait
    d'ecrire a l'ancien, et les passages disparaissaient du journal sans que
    rien ne le signale.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Edition", slug="org-edition"
        )
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Edition",
            slug="gym-edition",
            subdomain="gym-edition",
        )
        module, _ = Module.objects.get_or_create(
            code="ACCESS", defaults={"name": "Access"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="Entree", host="192.168.1.188", port=80,
            username="operateur", password="motdepasse-origine",
        )
        self.jeton = self.device.webhook_token
        self.owner = User.objects.create_user(
            username="owner-edition", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.owner, gym=self.gym, role="owner", is_active=True
        )
        self.client.force_login(self.owner)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _modifier(self, **extra):
        charge = {
            "name": "Entree",
            "host": "exemple.trycloudflare.com",
            "port": 443,
            "use_https": True,
            "username": "operateur",
            "door_number": 1,
        }
        charge.update(extra)
        with patch.object(
            hikvision.HikvisionClient,
            "device_info",
            side_effect=hikvision.HikvisionUnreachable("hors de portee"),
        ):
            return self.client.post(
                reverse("access:device_update", args=[self.device.id]),
                data=json.dumps(charge),
                content_type="application/json",
            )

    # --- Ce qui doit survivre -------------------------------------------------

    def test_the_webhook_token_never_changes(self):
        self._modifier()

        self.device.refresh_from_db()
        self.assertEqual(self.device.webhook_token, self.jeton)

    def test_an_empty_password_keeps_the_previous_one(self):
        # Reafficher un mot de passe pour le faire retaper le ferait circuler
        # sans raison ; le champ vide doit donc signifier "ne change pas".
        self._modifier(password="")

        self.device.refresh_from_db()
        self.assertEqual(self.device.password, "motdepasse-origine")

    def test_a_new_password_replaces_it(self):
        self._modifier(password="nouveau-motdepasse")

        self.device.refresh_from_db()
        self.assertEqual(self.device.password, "nouveau-motdepasse")

    # --- Ce qui doit changer ---------------------------------------------------

    def test_the_address_moves_to_the_tunnel(self):
        self._modifier()

        self.device.refresh_from_db()
        self.assertEqual(self.device.host, "exemple.trycloudflare.com")
        self.assertEqual(self.device.port, 443)
        self.assertTrue(self.device.use_https)

    def test_the_tunnel_token_can_be_added_later(self):
        self._modifier(
            tunnel_client_id="identifiant.access",
            tunnel_client_secret="secret-du-tunnel",
        )

        self.device.refresh_from_db()
        self.assertEqual(
            self.device.tunnel_headers["CF-Access-Client-Id"], "identifiant.access"
        )

    def test_the_tunnel_secret_is_never_sent_back(self):
        reponse = self._modifier(
            tunnel_client_id="identifiant.access",
            tunnel_client_secret="secret-du-tunnel",
        )

        self.assertNotIn("secret-du-tunnel", reponse.content.decode())

    def test_editing_something_else_keeps_the_tunnel_identifier(self):
        # Le formulaire ne reproposait pas l'identifiant : changer l'adresse
        # l'effacait en laissant le secret, et l'application cessait de
        # s'authentifier sans rien signaler.
        self.device.tunnel_client_id = "identifiant.access"
        self.device.tunnel_client_secret = "secret-du-tunnel"
        self.device.save(update_fields=["tunnel_client_id", "tunnel_client_secret"])

        charge = _serialize_device(self.device)
        self.assertEqual(charge["tunnel_client_id"], "identifiant.access")

        # Le formulaire renvoie ce qu'il a recu : la paire survit.
        self._modifier(
            host="autre.trycloudflare.com",
            tunnel_client_id=charge["tunnel_client_id"],
        )

        self.device.refresh_from_db()
        self.assertEqual(self.device.tunnel_client_id, "identifiant.access")
        self.assertEqual(self.device.tunnel_client_secret, "secret-du-tunnel")

    def test_an_empty_tunnel_token_is_valid_before_access_is_set_up(self):
        # Tant qu'aucune application Access ne protege le nom, il n'y a pas de
        # jeton a saisir : les deux champs restent vides.
        self._modifier(tunnel_client_id="", tunnel_client_secret="")

        self.device.refresh_from_db()
        self.assertEqual(self.device.tunnel_headers, {})

    def test_the_user_name_is_offered_back_to_the_form(self):
        # Sans lui, le formulaire le remettrait a "admin" a chaque modification.
        self.assertEqual(_serialize_device(self.device)["username"], "operateur")

    # --- Ce qui doit etre refuse -----------------------------------------------

    def test_an_empty_address_is_refused(self):
        reponse = self._modifier(host="")

        self.assertEqual(reponse.status_code, 400)
        self.device.refresh_from_db()
        self.assertEqual(self.device.host, "192.168.1.188")

    def test_a_reader_of_another_gym_is_out_of_reach(self):
        autre = Gym.objects.create(
            organization=self.organization, name="Ailleurs",
            slug="ailleurs-edition", subdomain="ailleurs-edition",
        )
        etranger = AccessDevice.objects.create(
            gym=autre, name="Autre", host="10.0.0.8", password="secret"
        )

        reponse = self.client.post(
            reverse("access:device_update", args=[etranger.id]),
            data=json.dumps({"host": "pirate.example.com"}),
            content_type="application/json",
        )

        self.assertEqual(reponse.status_code, 404)

    def test_a_receptionist_cannot_move_a_reader(self):
        reception = User.objects.create_user(
            username="reception-edition", password="pass12345"
        )
        UserGymRole.objects.create(
            user=reception, gym=self.gym, role="reception", is_active=True
        )
        self.client.force_login(reception)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

        reponse = self.client.post(
            reverse("access:device_update", args=[self.device.id]),
            data=json.dumps({"host": "pirate.example.com"}),
            content_type="application/json",
        )

        self.assertIn(reponse.status_code, (302, 403))
        self.device.refresh_from_db()
        self.assertEqual(self.device.host, "192.168.1.188")


class TunnelClientSignatureTests(TestCase):
    """
    Le tunnel inspecte la signature du client avant de transmettre.

    Observe en production : Cloudflare renvoyait "HTTP 403 error code: 1010"
    sur la seule signature par defaut de Python, et l'appel n'atteignait
    jamais le lecteur.
    """

    def _entetes(self, appel):
        return {nom.lower(): valeur for nom, valeur in appel.header_items()}

    def test_every_call_announces_a_browser_signature(self):
        client = hikvision.HikvisionClient("10.0.0.9", "admin", "x")

        with patch.object(hikvision.HikvisionClient, "_opener") as ouvreur:
            ouvreur.return_value.open.return_value.read.return_value = b"<x/>"
            client.request("/ISAPI/System/deviceInfo")

        appel = ouvreur.return_value.open.call_args[0][0]
        self.assertIn("mozilla", self._entetes(appel)["user-agent"].lower())

    def test_the_binary_call_announces_it_too(self):
        # Celui qui rapporte les images passe par un autre chemin : il etait
        # reste sans signature.
        client = hikvision.HikvisionClient("10.0.0.9", "admin", "x")

        with patch.object(hikvision.HikvisionClient, "_opener") as ouvreur:
            ouvreur.return_value.open.return_value.read.return_value = b"donnees-image"
            client.request_raw("/ISAPI/Intelligent/FDLib/FDSetUp")

        appel = ouvreur.return_value.open.call_args[0][0]
        self.assertIn("mozilla", self._entetes(appel)["user-agent"].lower())

    def test_the_tunnel_token_still_travels(self):
        # La signature ne doit pas avoir chasse les en-tetes du tunnel.
        device = AccessDevice(
            host="salle.exemple.com", username="admin", password="x",
            tunnel_client_id="identifiant.access",
            tunnel_client_secret="secret",
        )
        client = hikvision.HikvisionClient.from_device(device)

        with patch.object(hikvision.HikvisionClient, "_opener") as ouvreur:
            ouvreur.return_value.open.return_value.read.return_value = b"<x/>"
            client.request("/ISAPI/System/deviceInfo")

        entetes = self._entetes(ouvreur.return_value.open.call_args[0][0])
        self.assertEqual(entetes["cf-access-client-id"], "identifiant.access")

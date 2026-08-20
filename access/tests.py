import json
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from io import BytesIO

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
from . import enrollment, hikvision
from .device_views import UNKNOWN_CREDENTIAL_REASON
from .hikvision import parse_event_payload
from .models import AccessDevice, AccessLog
from .views import DOUBLE_SCAN_REASON, EXPIRED_QR_REASON, NO_SUBSCRIPTION_REASON


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

    def test_manual_access_denies_second_entry_same_day(self):
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
        self.assertEqual(payload["reason"], DOUBLE_SCAN_REASON)
        self.assertEqual(payload["log"]["status"], "denied")
        self.assertEqual(payload["log"]["reason"], DOUBLE_SCAN_REASON)
        self.assertEqual(payload["stats"]["entries"], 1)
        self.assertEqual(payload["stats"]["denied"], 1)

        logs = AccessLog.objects.filter(member=self.member_a).order_by("id")
        self.assertEqual(logs.count(), 2)
        self.assertTrue(logs[0].access_granted)
        self.assertFalse(logs[1].access_granted)
        self.assertEqual(logs[1].denial_reason, DOUBLE_SCAN_REASON)

    def test_qr_access_denies_second_scan_same_day(self):
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
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], DOUBLE_SCAN_REASON)
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

    def test_second_scan_same_day_is_refused(self):
        self._post_scan(self.member.qr_code)
        response = self._post_scan(self.member.qr_code)

        payload = response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], DOUBLE_SCAN_REASON)

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

    def test_second_scan_same_day_leaves_the_door_closed(self):
        with patch("access.hikvision.HikvisionClient.open_door"):
            self._scan(self.member.qr_code)

        with patch("access.hikvision.HikvisionClient.open_door") as open_door:
            response = self._scan(self.member.qr_code)

        open_door.assert_not_called()
        payload = response.json()
        self.assertFalse(payload["access"])
        self.assertEqual(payload["reason"], DOUBLE_SCAN_REASON)

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
        self.assertEqual(payload["reason"], DOUBLE_SCAN_REASON)

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

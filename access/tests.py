import json
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from compte.models import User, UserGymRole
from members.models import Member
from organizations.models import Gym, GymModule, Module, Organization
from subscriptions.models import MemberSubscription, SubscriptionPlan
from .device_views import UNKNOWN_CREDENTIAL_REASON
from .hikvision import parse_event_payload
from .models import AccessDevice, AccessLog
from .views import DOUBLE_SCAN_REASON, EXPIRED_QR_REASON


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
        self.assertEqual(payload["reason"], "Aucun abonnement actif")
        self.assertEqual(payload["log"]["reason"], "Aucun abonnement actif")
        self.assertEqual(payload["log"]["status"], "denied")

        log = AccessLog.objects.get(member=member)
        self.assertFalse(log.access_granted)
        self.assertEqual(log.denial_reason, "Aucun abonnement actif")

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
        self.assertEqual(payload["reason"], "Aucun abonnement actif")

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

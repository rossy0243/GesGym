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
from . import door, enrollment, hikvision, relectures
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


def _vieillir_les_passages(minutes=5):
    """
    Recule les passages deja enregistres.

    Le lecteur regroupe les lectures d'une meme personne faites dans la minute :
    deux lignes a la meme seconde racontent une relecture, pas deux visites. Un
    vrai retour dans la salle, lui, arrive plus tard - c'est ce que ces tests
    veulent dire quand ils enchainent deux passages.
    """
    from datetime import timedelta as _timedelta

    from access.models import AccessLog

    for log in AccessLog.objects.all():
        AccessLog.objects.filter(pk=log.pk).update(
            check_in_time=log.check_in_time - _timedelta(minutes=minutes)
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
        _vieillir_les_passages()
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
        _vieillir_les_passages()
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

    def test_the_desk_does_not_see_network_discovery(self):
        # L'accueil se sert des lecteurs sans les administrer : balayer le
        # reseau appartient a l'installation, pas au comptoir.
        response = self.client.get(reverse("access:acces_dashboard"))

        self.assertNotContains(response, "Détecter un lecteur sur le réseau")

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
        _vieillir_les_passages()
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
        _vieillir_les_passages()
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
        _vieillir_les_passages()
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

    def test_a_receptionist_can_enrol_faces(self):
        # C'est l'accueil qui inscrit les membres : lui refuser l'enrolement
        # obligeait a deranger un gerant pour chaque nouveau visage.
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

        self.assertEqual(response.status_code, 200)

    def test_a_coach_still_cannot_enrol_faces(self):
        # L'elargissement s'arrete a l'accueil et a la caisse.
        coach = User.objects.create_user(
            username="coach-visage", password="pass12345"
        )
        UserGymRole.objects.create(
            user=coach, gym=self.gym, role="coach", is_active=True
        )
        self._connecter(coach)

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
        # petit numero. Il ne doit jamais etre confondu avec un membre - mais
        # son passage est desormais journalise comme fiche du terminal, au
        # lieu de disparaitre sans trace.
        self._pousser("2")

        self.assertFalse(AccessLog.objects.filter(member__isnull=False).exists())
        self.assertEqual(AccessLog.objects.get().terminal_label, "Fiche 2")

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
        _vieillir_les_passages()
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
        _vieillir_les_passages()
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
        _vieillir_les_passages()
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

    def _avec_jeton(self):
        self.device.tunnel_client_id = "identifiant.access"
        self.device.tunnel_client_secret = "secret-du-tunnel"
        self.device.use_https = True
        self.device.save(update_fields=[
            "tunnel_client_id", "tunnel_client_secret", "use_https",
        ])

    def test_editing_something_else_keeps_the_tunnel_pair(self):
        # Les identifiants ne quittent jamais le serveur : le formulaire les
        # renvoie donc vides. Sans cette garde, changer l'adresse du lecteur
        # les effacait, et l'application cessait de s'authentifier en silence.
        self._avec_jeton()

        self._modifier(host="autre.trycloudflare.com",
                       tunnel_client_id="", tunnel_client_secret="")

        self.device.refresh_from_db()
        self.assertEqual(self.device.tunnel_client_id, "identifiant.access")
        self.assertEqual(self.device.tunnel_client_secret, "secret-du-tunnel")

    def test_the_identifier_is_never_sent_back_either(self):
        # Le secret seul ne suffit pas : les deux moities restent au serveur.
        self._avec_jeton()

        self.assertNotIn("tunnel_client_id", _serialize_device(self.device))

    def test_unchecking_the_tunnel_clears_the_pair(self):
        # Le geste explicite pour retirer un jeton, puisqu'un champ vide
        # signifie desormais "ne change pas".
        self._avec_jeton()

        self._modifier(use_https=False)

        self.device.refresh_from_db()
        self.assertEqual(self.device.tunnel_client_id, "")
        self.assertEqual(self.device.tunnel_client_secret, "")

    def test_a_new_identifier_still_replaces_the_old_one(self):
        self._avec_jeton()

        self._modifier(tunnel_client_id="nouvel.identifiant")

        self.device.refresh_from_db()
        self.assertEqual(self.device.tunnel_client_id, "nouvel.identifiant")

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


class DeviceRoleSplitTests(TestCase):
    """
    Se servir d'un lecteur et l'administrer sont deux droits distincts.

    L'accueil et la caisse enrolent des visages et ouvrent la porte ; ils n'ont
    aucune raison de pouvoir supprimer un lecteur ou changer son adresse.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Roles", slug="org-roles"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Roles",
            slug="gym-roles", subdomain="gym-roles",
        )
        module, _ = Module.objects.get_or_create(
            code="ACCESS", defaults={"name": "Access"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="Entree", host="10.0.0.9", password="secret"
        )
        self.member = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243880000001",
        )

    def _connecter(self, role):
        utilisateur = User.objects.create_user(
            username=f"agent-{role}", password="pass12345"
        )
        UserGymRole.objects.create(
            user=utilisateur, gym=self.gym, role=role, is_active=True
        )
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()
        return utilisateur

    def _refuse(self, reponse):
        return reponse.status_code in (302, 403)

    # --- Ce que l'accueil et la caisse peuvent faire --------------------------

    def test_reception_and_cashier_reach_the_access_page(self):
        for role in ("reception", "cashier"):
            with self.subTest(role=role):
                self._connecter(role)
                reponse = self.client.get(reverse("access:acces_dashboard"))
                self.assertEqual(reponse.status_code, 200)

    def test_reception_and_cashier_see_the_readers(self):
        for role in ("reception", "cashier"):
            with self.subTest(role=role):
                self._connecter(role)
                reponse = self.client.get(reverse("access:device_list"))
                self.assertEqual(reponse.status_code, 200)

    def test_reception_and_cashier_can_enrol_a_face(self):
        for role in ("reception", "cashier"):
            with self.subTest(role=role):
                self._connecter(role)
                reponse = self.client.get(
                    reverse("access:face_enrollment", args=[self.member.id])
                )
                self.assertEqual(reponse.status_code, 200)

    def test_reception_and_cashier_can_open_the_door(self):
        for role in ("reception", "cashier"):
            with self.subTest(role=role):
                self._connecter(role)
                with patch.object(hikvision.HikvisionClient, "open_door"):
                    reponse = self.client.post(
                        reverse("access:device_open_door", args=[self.device.id])
                    )
                self.assertEqual(reponse.status_code, 200)

    # --- Ce qui leur reste ferme ----------------------------------------------

    def test_they_cannot_delete_a_reader(self):
        for role in ("reception", "cashier"):
            with self.subTest(role=role):
                self._connecter(role)
                reponse = self.client.post(
                    reverse("access:device_delete", args=[self.device.id])
                )
                self.assertTrue(self._refuse(reponse))
        self.assertTrue(AccessDevice.objects.filter(pk=self.device.pk).exists())

    def test_they_cannot_move_a_reader(self):
        for role in ("reception", "cashier"):
            with self.subTest(role=role):
                self._connecter(role)
                reponse = self.client.post(
                    reverse("access:device_update", args=[self.device.id]),
                    data=json.dumps({"host": "pirate.example.com"}),
                    content_type="application/json",
                )
                self.assertTrue(self._refuse(reponse))
        self.device.refresh_from_db()
        self.assertEqual(self.device.host, "10.0.0.9")

    def test_they_cannot_register_a_new_reader(self):
        self._connecter("reception")

        reponse = self.client.post(
            reverse("access:device_create"),
            data=json.dumps({"host": "10.0.0.7", "password": "x"}),
            content_type="application/json",
        )

        self.assertTrue(self._refuse(reponse))

    def test_they_cannot_change_the_screen_messages(self):
        self._connecter("cashier")

        reponse = self.client.get(
            reverse("access:device_messages", args=[self.device.id])
        )

        self.assertTrue(self._refuse(reponse))

    def test_a_coach_still_has_no_access_at_all(self):
        # L'elargissement ne doit pas deborder sur les autres roles.
        self._connecter("coach")

        self.assertTrue(self._refuse(self.client.get(reverse("access:device_list"))))

    # --- Ce que l'ecran propose ------------------------------------------------

    def test_the_page_hides_administration_from_the_desk(self):
        self._connecter("reception")

        html = self.client.get(reverse("access:acces_dashboard")).content.decode()

        self.assertIn("PEUT_ADMINISTRER_LECTEURS = false", html)
        self.assertNotIn("Ajouter manuellement", html)

    def test_the_page_offers_administration_to_the_manager(self):
        self._connecter("manager")

        html = self.client.get(reverse("access:acces_dashboard")).content.decode()

        self.assertIn("PEUT_ADMINISTRER_LECTEURS = true", html)
        self.assertIn("Ajouter manuellement", html)


class ManualDoorOpeningTraceTests(TestCase):
    """
    Ouvrir la porte depuis l'application doit laisser une trace visible.

    Le geste donne acces a la salle sans que personne se presente. Sans ligne
    au journal, ouvrir a un ami ne se voit nulle part.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Trace", slug="org-trace"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Trace",
            slug="gym-trace", subdomain="gym-trace",
        )
        module, _ = Module.objects.get_or_create(
            code="ACCESS", defaults={"name": "Access"}
        )
        GymModule.objects.get_or_create(
            gym=self.gym, module=module, defaults={"is_active": True}
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="Entree", host="10.0.0.9", password="secret"
        )
        self.agent = User.objects.create_user(
            username="hotesse", password="pass12345", first_name="Sarah",
        )
        UserGymRole.objects.create(
            user=self.agent, gym=self.gym, role="reception", is_active=True
        )
        self.client.force_login(self.agent)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _ouvrir(self):
        with patch.object(hikvision.HikvisionClient, "open_door"):
            return self.client.post(
                reverse("access:device_open_door", args=[self.device.id])
            )

    def test_the_opening_creates_a_journal_line(self):
        self._ouvrir()

        self.assertEqual(AccessLog.objects.filter(gym=self.gym).count(), 1)

    def test_the_line_names_who_opened(self):
        # C'est tout l'interet : rattacher le geste a quelqu'un.
        self._ouvrir()

        log = AccessLog.objects.get(gym=self.gym)
        self.assertEqual(log.scanned_by, self.agent)
        self.assertIsNone(log.member)

    def test_the_line_says_it_was_a_manual_opening(self):
        self._ouvrir()

        log = AccessLog.objects.get(gym=self.gym)
        self.assertIn("ouverture manuelle", log.device_used.lower())

    def test_a_failed_opening_leaves_no_line(self):
        # Rien ne s'est ouvert : journaliser tromperait la lecture.
        with patch.object(
            hikvision.HikvisionClient,
            "open_door",
            side_effect=hikvision.HikvisionUnreachable("hors de portee"),
        ):
            self.client.post(reverse("access:device_open_door", args=[self.device.id]))

        self.assertFalse(AccessLog.objects.filter(gym=self.gym).exists())

    def test_it_does_not_inflate_the_attendance_count(self):
        # Personne ne s'est presente : compter cette ouverture comme une
        # entree fausserait la frequentation du jour.
        self._ouvrir()

        reponse = self.client.get(reverse("access:acces_dashboard"))
        self.assertEqual(reponse.context["today_entries"], 0)

    def test_the_journal_shows_it_without_a_member(self):
        self._ouvrir()

        html = self.client.get(reverse("access:acces_dashboard")).content.decode()

        self.assertIn("Ouverture manuelle", html)

    def test_the_realtime_feed_survives_a_line_without_a_member(self):
        # Le flux temps reel lisait le nom du membre sans precaution.
        self._ouvrir()

        reponse = self.client.get("/access/access/realtime/")

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()[0]["member"], "Ouverture manuelle")


class ReaderLogVolumeTests(TestCase):
    """
    Ce que le lecteur ecrit dans les journaux du serveur.

    Il bat toutes les trente secondes. Journaliser la charge complete a chaque
    fois produisait cinq megaoctets par jour et par lecteur, ou les vrais
    passages devenaient introuvables - c'est arrive.
    """

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Org Volume", slug="org-volume"
        )
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Volume",
            slug="gym-volume", subdomain="gym-volume",
        )
        self.device = AccessDevice.objects.create(
            gym=self.gym, name="L1", host="10.0.0.9", password="secret"
        )
        self.member = Member.objects.create(
            gym=self.gym, first_name="Ada", last_name="Mbala",
            phone="+243870000101",
        )
        self.url = reverse("access:device_webhook", args=[self.device.webhook_token])

    def _pousser(self, charge):
        return self.client.post(
            self.url, data=json.dumps(charge), content_type="application/json"
        )

    def test_a_heartbeat_writes_nothing(self):
        # Deux mille huit cents fois par jour : le silence est la seule option
        # tenable.
        with self.assertNoLogs("access", level="INFO"):
            self._pousser({"eventType": "heartBeat", "AccessControllerEvent": {}})

    def test_a_passage_is_logged_without_its_payload(self):
        with self.assertLogs("access", level="INFO") as journal:
            self._pousser({
                "AccessControllerEvent": {
                    "employeeNoString": enrollment.employee_no(self.member),
                    "serialNo": 1,
                    "minor": 75,
                }
            })

        trace = chr(10).join(journal.output)
        self.assertIn("identifiant=", trace)
        self.assertNotIn("brut=", trace)

    def test_an_unrecognised_event_keeps_its_payload(self):
        # Le seul cas ou la trace integrale sert : le materiel a parle et nous
        # n'avons rien reconnu.
        with self.assertLogs("access", level="INFO") as journal:
            self._pousser({
                "AccessControllerEvent": {"minor": 217, "quelqueChose": "inconnu"}
            })

        trace = chr(10).join(journal.output)
        self.assertIn("non reconnu", trace)
        self.assertIn("brut=", trace)


class StaffAndTerminalPassageTests(TestCase):
    """
    Le journal accueille le personnel et les fiches du terminal ; les
    statistiques des membres les ignorent.

    Rien de ce qui existait ne doit changer : les ouvertures manuelles et les
    invites gardent leur definition, et les chiffres d'hier restent ceux
    d'aujourd'hui tant qu'aucun employe n'est passe.
    """

    def setUp(self):
        from decimal import Decimal

        from rh.models import Employee

        self.organization = Organization.objects.create(name="Org Personnel", slug="org-personnel")
        self.gym = Gym.objects.create(
            organization=self.organization, name="Gym Personnel",
            slug="gym-personnel", subdomain="gym-personnel",
        )
        self.voisine = Gym.objects.create(
            organization=self.organization, name="Voisine",
            slug="gym-personnel-voisine", subdomain="gym-personnel-voisine",
        )
        for code in ("MEMBERS", "ACCESS"):
            module, _ = Module.objects.get_or_create(code=code, defaults={"name": code})
            GymModule.objects.get_or_create(gym=self.gym, module=module, defaults={"is_active": True})

        self.device = AccessDevice.objects.create(
            gym=self.gym, name="Terminal", host="10.0.0.9", password="secret"
        )
        self.url = reverse("access:device_webhook", args=[self.device.webhook_token])
        self.member = Member.objects.create(
            gym=self.gym, first_name="Alice", last_name="Nzuzi", phone="+243860000011",
        )
        plan = SubscriptionPlan.objects.create(gym=self.gym, name="Mensuel", price=30, duration_days=30)
        today = timezone.localdate()
        MemberSubscription.objects.create(
            gym=self.gym, member=self.member, plan=plan,
            start_date=today - timedelta(days=1), end_date=today + timedelta(days=29),
            is_active=True,
        )
        self.employe = Employee.objects.create(
            gym=self.gym, name="Paul Gardien", role="cleaner", phone="+243860000099",
            compensation_type="daily", daily_salary=Decimal("5000"),
        )
        self.employe_voisin = Employee.objects.create(
            gym=self.voisine, name="Zoe Ailleurs", role="cleaner",
            compensation_type="daily", daily_salary=Decimal("5000"),
        )

        patcher = patch("access.hikvision.HikvisionClient.open_door")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _envoyer(self, **evenement):
        charge = {"AccessControllerEvent": {"majorEventType": 5, "subEventType": 75, **evenement}}
        return self.client.post(self.url, data=json.dumps(charge), content_type="application/json")

    def _passages_typiques(self):
        """Un membre, une ouverture manuelle, un employe et une fiche du terminal."""
        AccessLog.objects.create(gym=self.gym, member=self.member, access_granted=True)
        AccessLog.objects.create(gym=self.gym, access_granted=True)
        AccessLog.objects.create(gym=self.gym, employee=self.employe, access_granted=True)
        AccessLog.objects.create(gym=self.gym, employee=self.employe, access_granted=False)
        AccessLog.objects.create(gym=self.gym, terminal_label="Fiche 3", access_granted=True, is_return=True)

    # --- La fiche du terminal au journal ---------------------------------------------

    def test_a_terminal_record_is_journaled_without_a_member(self):
        self._envoyer(employeeNoString="2")

        log = AccessLog.objects.get()
        self.assertIsNone(log.member)
        self.assertTrue(log.access_granted)
        self.assertEqual(log.terminal_label, "Fiche 2")

    def test_the_name_sent_by_the_reader_is_kept(self):
        self._envoyer(employeeNoString="2", name="Paul Gardien")

        log = AccessLog.objects.get()
        self.assertEqual(log.terminal_label, "Paul Gardien")
        self.assertEqual(log.nom_affiche, "Paul Gardien (fiche du terminal)")

    def test_a_passage_refused_by_the_reader_is_journaled_as_refused(self):
        # Fiche expiree sur le terminal : le lecteur n'a pas ouvert, le journal
        # ne doit pas pretendre le contraire.
        self._envoyer(employeeNoString="2", subEventType=9)

        log = AccessLog.objects.get()
        self.assertFalse(log.access_granted)
        self.assertFalse(log.is_return)

    def test_a_repeated_notification_is_not_journaled_twice(self):
        # Le lecteur reemet tant qu'il ne s'estime pas acquitte.
        self._envoyer(employeeNoString="2", serialNo="777")
        self._envoyer(employeeNoString="2", serialNo="777")

        self.assertEqual(AccessLog.objects.count(), 1)

    def test_a_second_passage_the_same_day_is_a_return(self):
        self._envoyer(employeeNoString="2", serialNo="1")
        _vieillir_les_passages()
        self._envoyer(employeeNoString="2", serialNo="2")

        self.assertEqual(AccessLog.objects.filter(is_return=True).count(), 1)

    def test_random_text_is_still_refused_without_trace(self):
        # Seul un numero hors plage est une fiche du terminal : un texte
        # quelconque lu par le lecteur reste refuse, comme avant.
        reponse = self._envoyer(employeeNoString="bonjour")

        self.assertFalse(reponse.json()["access"])
        self.assertFalse(AccessLog.objects.exists())

    def test_a_member_passage_is_unchanged(self):
        self._envoyer(employeeNoString=enrollment.employee_no(self.member))

        log = AccessLog.objects.get()
        self.assertEqual(log.member, self.member)
        self.assertEqual(log.terminal_label, "")

    # --- Les statistiques des membres ----------------------------------------------------

    def test_todays_counters_ignore_staff_and_terminal_passages(self):
        from .views import _today_stats

        self._passages_typiques()

        stats = _today_stats(self.gym)

        self.assertEqual(stats["entries"], 1)
        self.assertEqual(stats["returns"], 0)
        self.assertEqual(stats["denied"], 0)

    def test_the_dashboard_counts_what_it_counted_before(self):
        # Le membre et l'ouverture manuelle comptaient deja : ils comptent
        # toujours. L'employe et la fiche du terminal n'entrent nulle part.
        gerant = User.objects.create_user(username="gerant-personnel", password="pass12345")
        UserGymRole.objects.create(user=gerant, gym=self.gym, role="manager", is_active=True)
        self.client.force_login(gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()
        self._passages_typiques()

        contexte = self.client.get(reverse("core:gym_dashboard", args=[self.gym.id])).context

        self.assertEqual(contexte["today_checkins"], 2)
        self.assertEqual(contexte["today_unique_visitors"], 1)
        self.assertEqual(contexte["denied_today"], 0)
        self.assertEqual(contexte["visits_period"], 2)

    def test_the_filter_keeps_manual_openings(self):
        AccessLog.objects.create(gym=self.gym, access_granted=True)
        AccessLog.objects.create(gym=self.gym, employee=self.employe, access_granted=True)

        self.assertEqual(AccessLog.objects.filter(gym=self.gym).hors_personnel().count(), 1)

    # --- Les libelles ----------------------------------------------------------------------

    def test_every_kind_of_passage_has_a_name(self):
        membre = AccessLog.objects.create(gym=self.gym, member=self.member)
        employe = AccessLog.objects.create(gym=self.gym, employee=self.employe)
        fiche = AccessLog.objects.create(gym=self.gym, terminal_label="Fiche 8")
        manuelle = AccessLog.objects.create(gym=self.gym)

        self.assertEqual(membre.nom_affiche, "Alice Nzuzi")
        self.assertEqual(employe.nom_affiche, "Paul Gardien (personnel)")
        self.assertEqual(fiche.nom_affiche, "Fiche 8 (fiche du terminal)")
        self.assertEqual(manuelle.nom_affiche, "Ouverture manuelle")

    def test_the_access_screen_names_an_employee(self):
        from .views import _serialize_log

        log = AccessLog.objects.create(gym=self.gym, employee=self.employe)

        ligne = _serialize_log(log)

        self.assertEqual(ligne["member"], "Paul Gardien (personnel)")
        self.assertEqual(ligne["phone"], "+243860000099")

    def test_the_export_names_staff_and_leaves_manual_openings_blank(self):
        from core.accounting_reports import build_access_rows
        from core.views import _get_period_window

        AccessLog.objects.create(gym=self.gym, employee=self.employe)
        AccessLog.objects.create(gym=self.gym)

        lignes = build_access_rows(self.gym, _get_period_window("day", timezone.localdate()))

        clients = sorted(ligne["client"] for ligne in lignes)
        self.assertEqual(clients, ["", "Paul Gardien (personnel)"])

    def test_an_employee_of_another_gym_is_refused(self):
        with self.assertRaises(ValidationError):
            AccessLog.objects.create(gym=self.gym, employee=self.employe_voisin)

    # --- Le rattrapage ------------------------------------------------------------------------

    def test_the_catch_up_recreates_a_terminal_passage(self):
        from django.core.management import call_command

        from .management.commands.rattraper_passages import Command

        evenements = [{
            "employeeNoString": "5",
            "name": "Gardien de nuit",
            "minor": 75,
            "serialNo": "900",
            "time": timezone.localtime().replace(microsecond=0).isoformat(),
        }]
        with patch.object(Command, "_lire_evenements", return_value=evenements):
            call_command("rattraper_passages", stdout=__import__("io").StringIO())

        log = AccessLog.objects.get(device_event_id="900")
        self.assertEqual(log.terminal_label, "Gardien de nuit")
        self.assertIsNone(log.member)
        self.assertTrue(log.access_granted)

    def test_the_catch_up_keeps_a_refused_terminal_passage_refused(self):
        from django.core.management import call_command

        from .management.commands.rattraper_passages import Command

        evenements = [{
            "employeeNoString": "5",
            "minor": 21,
            "serialNo": "901",
            "time": timezone.localtime().replace(microsecond=0).isoformat(),
        }]
        with patch.object(Command, "_lire_evenements", return_value=evenements):
            call_command("rattraper_passages", stdout=__import__("io").StringIO())

        self.assertFalse(AccessLog.objects.get(device_event_id="901").access_granted)



def _salle_avec_personnel(suffixe):
    """Une salle avec lecteur, modules actifs, un membre et deux employes."""
    from decimal import Decimal

    from rh.models import Employee

    organisation = Organization.objects.create(name=f"Org {suffixe}", slug=f"org-{suffixe}")
    salle = Gym.objects.create(
        organization=organisation, name=f"Gym {suffixe}", slug=f"gym-{suffixe}",
        subdomain=f"gym-{suffixe}",
    )
    voisine = Gym.objects.create(
        organization=organisation, name=f"Voisine {suffixe}", slug=f"voisine-{suffixe}",
        subdomain=f"voisine-{suffixe}",
    )
    for code in ("MEMBERS", "ACCESS", "RH"):
        module, _ = Module.objects.get_or_create(code=code, defaults={"name": code})
        GymModule.objects.get_or_create(gym=salle, module=module, defaults={"is_active": True})
    lecteur = AccessDevice.objects.create(
        gym=salle, name="Terminal", host="10.0.0.9", password="secret"
    )
    membre = Member.objects.create(
        gym=salle, first_name="Alice", last_name="Nzuzi", phone="+243860000021",
    )
    employe = Employee.objects.create(
        gym=salle, name="Paul Gardien", role="cleaner", phone="+243860000098",
        compensation_type="daily", daily_salary=Decimal("5000"),
    )
    employe_voisin = Employee.objects.create(
        gym=voisine, name="Zoe Ailleurs", role="cleaner",
        compensation_type="daily", daily_salary=Decimal("5000"),
    )
    return salle, lecteur, membre, employe, employe_voisin


def _lecteur_sans_reste(test):
    """
    Le lecteur ne dit rien de plus que ce que le test simule.

    Retirer une fiche enleve d'abord le visage, puis verifie que la fiche a
    bien disparu. Ces deux appels-la n'apprennent rien aux tests qui portent
    sur autre chose : on les fait taire.
    """
    for methode, valeur in (("delete_face", None), ("user_exists", False)):
        patcher = patch.object(hikvision.HikvisionClient, methode, return_value=valeur)
        patcher.start()
        test.addCleanup(patcher.stop)


def _image_jpeg():
    tampon = BytesIO()
    Image.new("RGB", (352, 432), (90, 90, 90)).save(tampon, format="JPEG")
    return tampon.getvalue()


class StaffFaceNumberingTests(TestCase):
    """Les employes ont leur plage de numeros, distincte de celle des membres."""

    def setUp(self):
        self.gym, self.device, self.member, self.employe, _ = _salle_avec_personnel("numeros")
        _lecteur_sans_reste(self)

    def test_an_employee_number_is_in_the_staff_range(self):
        self.assertEqual(
            enrollment.numero_personnel(self.employe),
            str(enrollment.PLAGE_PERSONNEL + self.employe.id),
        )

    def test_an_employee_number_maps_back_to_the_employee(self):
        numero = enrollment.numero_personnel(self.employe)

        self.assertEqual(enrollment.employee_id_depuis(numero), self.employe.id)

    def test_an_employee_is_never_taken_for_a_member(self):
        # Sans borne, le numero d'un employe designait un membre inexistant :
        # la purge l'aurait retire du lecteur.
        self.assertIsNone(enrollment.member_id_depuis(enrollment.numero_personnel(self.employe)))

    def test_a_member_is_never_taken_for_an_employee(self):
        self.assertIsNone(enrollment.employee_id_depuis(enrollment.employee_no(self.member)))

    def test_the_ranges_meet_without_overlap(self):
        self.assertEqual(
            enrollment.member_id_depuis(str(enrollment.PLAGE_PERSONNEL)),
            enrollment.PLAGE_PERSONNEL - enrollment.PLAGE_APPLICATION,
        )
        self.assertIsNone(enrollment.employee_id_depuis(str(enrollment.PLAGE_PERSONNEL)))
        self.assertIsNone(enrollment.member_id_depuis(str(enrollment.PLAGE_PERSONNEL + 1)))

    def test_manual_records_belong_to_nobody(self):
        for brut in ("2", "badge", None, ""):
            with self.subTest(brut=brut):
                self.assertIsNone(enrollment.employee_id_depuis(brut))
                self.assertIsNone(enrollment.member_id_depuis(brut))

    def test_an_employee_record_is_open_at_all_times(self):
        with patch.object(hikvision.HikvisionClient, "upsert_user") as pose:
            enrollment.inscrire_employe(self.device, self.employe)

        args = pose.mock_calls[0].args
        self.assertEqual(args[0], enrollment.numero_personnel(self.employe))
        self.assertEqual(args[1], "Paul Gardien")
        self.assertEqual(args[2], enrollment.DEBUT_PAR_DEFAUT)
        self.assertEqual(args[3], enrollment.FIN_PAR_DEFAUT)

    def test_a_deactivated_employee_is_never_enrolled(self):
        self.employe.is_active = False
        self.employe.save()

        with patch.object(hikvision.HikvisionClient, "upsert_user") as pose:
            with self.assertRaises(enrollment.EnrollmentError):
                enrollment.inscrire_employe(self.device, self.employe)

        pose.assert_not_called()

    def test_a_refused_face_still_says_the_record_exists(self):
        with patch.object(hikvision.HikvisionClient, "upsert_user"), patch.object(
            hikvision.HikvisionClient, "set_face",
            side_effect=hikvision.HikvisionError('{"subStatusCode": "alreadyExistThisFace"}'),
        ):
            with self.assertRaises(enrollment.EnrollmentError) as capture:
                enrollment.inscrire_employe(self.device, self.employe, _image_jpeg())

        self.assertIn("fiche est enregistree", str(capture.exception))
        self.assertIn("deja enregistre sous une autre fiche", str(capture.exception))

    def test_removing_an_employee_deletes_the_staff_number(self):
        with patch.object(hikvision.HikvisionClient, "delete_user") as retrait:
            enrollment.retirer_employe(self.device, self.employe)

        retrait.assert_called_once_with(enrollment.numero_personnel(self.employe))


class StaffFaceWebhookTests(TestCase):
    """Le lecteur reconnait un employe : le passage est journalise a son nom."""

    def setUp(self):
        (self.gym, self.device, self.member, self.employe,
         self.employe_voisin) = _salle_avec_personnel("webhook-personnel")
        self.url = reverse("access:device_webhook", args=[self.device.webhook_token])
        patcher = patch("access.hikvision.HikvisionClient.open_door")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _envoyer(self, **evenement):
        charge = {"AccessControllerEvent": {"majorEventType": 5, "subEventType": 75, **evenement}}
        return self.client.post(self.url, data=json.dumps(charge), content_type="application/json")

    def test_an_employee_enters_without_subscription_and_is_journaled(self):
        reponse = self._envoyer(employeeNoString=enrollment.numero_personnel(self.employe))

        self.assertTrue(reponse.json()["access"])
        self.assertEqual(reponse.json()["member"], "Paul Gardien (personnel)")
        log = AccessLog.objects.get()
        self.assertEqual(log.employee, self.employe)
        self.assertIsNone(log.member)
        self.assertEqual(log.terminal_label, "")

    def test_an_employee_passage_is_not_counted_as_attendance(self):
        from .views import _today_stats

        self._envoyer(employeeNoString=enrollment.numero_personnel(self.employe))

        self.assertEqual(_today_stats(self.gym)["entries"], 0)

    def test_a_second_passage_the_same_day_is_a_return(self):
        numero = enrollment.numero_personnel(self.employe)
        self._envoyer(employeeNoString=numero, serialNo="11")
        _vieillir_les_passages()
        self._envoyer(employeeNoString=numero, serialNo="12")

        self.assertEqual(AccessLog.objects.filter(employee=self.employe, is_return=True).count(), 1)

    def test_a_repeated_notification_is_journaled_once(self):
        numero = enrollment.numero_personnel(self.employe)
        self._envoyer(employeeNoString=numero, serialNo="21")
        self._envoyer(employeeNoString=numero, serialNo="21")

        self.assertEqual(AccessLog.objects.count(), 1)

    def test_an_employee_of_another_gym_is_not_named(self):
        # Le numero est dans la plage, mais pas dans cette salle : on ne nomme
        # personne, et le passage reste trace comme fiche du terminal.
        self._envoyer(employeeNoString=enrollment.numero_personnel(self.employe_voisin))

        log = AccessLog.objects.get()
        self.assertIsNone(log.employee)
        self.assertTrue(log.terminal_label.startswith("Fiche "))

    def test_a_member_is_still_recognised_as_a_member(self):
        self._envoyer(employeeNoString=enrollment.employee_no(self.member))

        log = AccessLog.objects.get()
        self.assertEqual(log.member, self.member)
        self.assertIsNone(log.employee)

    def test_the_catch_up_recreates_an_employee_passage(self):
        import io

        from django.core.management import call_command

        from .management.commands.rattraper_passages import Command

        evenements = [{
            "employeeNoString": enrollment.numero_personnel(self.employe),
            "minor": 75,
            "serialNo": "950",
            "time": timezone.localtime().replace(microsecond=0).isoformat(),
        }]
        with patch.object(Command, "_lire_evenements", return_value=evenements):
            call_command("rattraper_passages", stdout=io.StringIO())

        log = AccessLog.objects.get(device_event_id="950")
        self.assertEqual(log.employee, self.employe)
        self.assertEqual(log.terminal_label, "")


class StaffFaceSyncTests(TestCase):
    """La synchronisation tient le personnel a jour et ne le purge jamais."""

    def setUp(self):
        self.gym, self.device, self.member, self.employe, _ = _salle_avec_personnel("sync-personnel")

    def _synchroniser(self, fiches, *options):
        import io

        from django.core.management import call_command

        with patch.object(
            hikvision.HikvisionClient, "user_count", return_value={"users": len(fiches), "faces": len(fiches)}
        ), patch.object(
            hikvision.HikvisionClient, "list_users", return_value=fiches
        ), patch.object(
            hikvision.HikvisionClient, "upsert_user"
        ) as pose, patch.object(
            hikvision.HikvisionClient, "delete_user"
        ) as retrait:
            call_command("synchroniser_lecteurs", *options, stdout=io.StringIO())
        return pose, retrait

    def test_an_enrolled_employee_is_refreshed(self):
        numero = enrollment.numero_personnel(self.employe)

        pose, _ = self._synchroniser([{"employeeNo": numero}])

        self.assertIn(numero, [appel.args[0] for appel in pose.mock_calls])

    def test_a_deactivated_employee_is_not_reopened(self):
        self.employe.is_active = False
        self.employe.save()
        numero = enrollment.numero_personnel(self.employe)

        pose, _ = self._synchroniser([{"employeeNo": numero}])

        self.assertNotIn(numero, [appel.args[0] for appel in pose.mock_calls])

    def test_the_purge_never_removes_an_employee(self):
        numero_employe = enrollment.numero_personnel(self.employe)
        membre_disparu = str(enrollment.PLAGE_APPLICATION + 999_999)

        _, retrait = self._synchroniser(
            [{"employeeNo": numero_employe}, {"employeeNo": membre_disparu}], "--purger"
        )

        retires = [appel.args[0] for appel in retrait.mock_calls]
        self.assertEqual(retires, [membre_disparu])

    def test_members_are_still_refreshed(self):
        numero_membre = enrollment.employee_no(self.member)

        pose, _ = self._synchroniser([{"employeeNo": numero_membre}])

        self.assertIn(numero_membre, [appel.args[0] for appel in pose.mock_calls])


class StaffFaceScreenTests(TestCase):
    """Le parcours d'enrolement d'un employe, depuis sa fiche RH."""

    def setUp(self):
        (self.gym, self.device, self.member, self.employe,
         self.employe_voisin) = _salle_avec_personnel("ecran-personnel")
        self.gerant = self._utilisateur("gerant-ecran-personnel", "manager")
        self._connecter(self.gerant)
        _lecteur_sans_reste(self)

    def _utilisateur(self, nom, role):
        utilisateur = User.objects.create_user(username=nom, password="pass12345")
        UserGymRole.objects.create(user=utilisateur, gym=self.gym, role=role, is_active=True)
        return utilisateur

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _capturer(self):
        with patch.object(hikvision.HikvisionClient, "capture_face", return_value=_image_jpeg()):
            return self.client.post(
                reverse("access:staff_face_capture", args=[self.employe.id]),
                {"device_id": self.device.id},
            )

    def test_the_manager_sees_the_three_steps(self):
        reponse = self.client.get(reverse("access:staff_face_enrollment", args=[self.employe.id]))

        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Paul Gardien")
        self.assertContains(reponse, "devant le lecteur")
        self.assertContains(reponse, "Lancez la capture")
        self.assertContains(reponse, reverse("access:staff_face_capture", args=[self.employe.id]))
        self.assertContains(reponse, enrollment.numero_personnel(self.employe))

    def test_a_receptionist_cannot_enrol_staff(self):
        # L'accueil enrole les membres, pas quelqu'un qui entre sans abonnement.
        self._connecter(self._utilisateur("accueil-ecran-personnel", "reception"))

        reponse = self.client.get(reverse("access:staff_face_enrollment", args=[self.employe.id]))

        self.assertIn(reponse.status_code, (302, 403))

    def test_an_employee_of_another_gym_is_out_of_reach(self):
        reponse = self.client.get(
            reverse("access:staff_face_enrollment", args=[self.employe_voisin.id])
        )

        self.assertEqual(reponse.status_code, 404)

    def test_capture_then_validation_enrols_the_employee(self):
        self.assertTrue(self._capturer().json()["ok"])

        with patch.object(hikvision.HikvisionClient, "upsert_user") as pose, patch.object(
            hikvision.HikvisionClient, "set_face"
        ) as visage:
            reponse = self.client.post(
                reverse("access:staff_face_confirm", args=[self.employe.id]), follow=True
            )

        self.assertEqual(reponse.status_code, 200)
        numero = enrollment.numero_personnel(self.employe)
        self.assertEqual(pose.mock_calls[0].args[0], numero)
        visage.assert_called_once()
        self.assertEqual(visage.mock_calls[0].args[0], numero)
        trace = SensitiveActivityLog.objects.get(action="access.staff_face_enrolled")
        self.assertEqual(trace.actor, self.gerant)
        self.assertEqual(trace.metadata["employee_id"], self.employe.id)

    def test_a_member_capture_cannot_enrol_an_employee(self):
        # Les deux parcours ont chacun leur capture : l'image d'un membre ne
        # doit jamais finir sur la fiche d'un employe.
        with patch.object(hikvision.HikvisionClient, "capture_face", return_value=_image_jpeg()):
            self.client.post(
                reverse("access:face_capture", args=[self.member.id]),
                {"device_id": self.device.id},
            )

        with patch.object(hikvision.HikvisionClient, "upsert_user") as pose:
            reponse = self.client.post(
                reverse("access:staff_face_confirm", args=[self.employe.id]), follow=True
            )

        self.assertContains(reponse, "Aucune capture en attente")
        pose.assert_not_called()

    def test_a_deactivated_employee_cannot_be_captured(self):
        self.employe.is_active = False
        self.employe.save()

        reponse = self._capturer()

        self.assertEqual(reponse.status_code, 400)
        self.assertIn("desactive", reponse.json()["error"])

    def test_removal_takes_the_employee_off_the_readers(self):
        with patch.object(hikvision.HikvisionClient, "delete_user") as retrait:
            self.client.post(
                reverse("access:staff_face_remove", args=[self.employe.id]), follow=True
            )

        retrait.assert_called_once_with(enrollment.numero_personnel(self.employe))

    def test_the_member_screen_is_unchanged(self):
        reponse = self.client.get(reverse("access:face_enrollment", args=[self.member.id]))

        self.assertContains(reponse, "Placez le membre devant le lecteur")
        self.assertContains(reponse, reverse("access:face_capture", args=[self.member.id]))
        self.assertContains(reponse, reverse("access:face_confirm", args=[self.member.id]))

    def test_the_rh_sheet_offers_the_enrolment(self):
        reponse = self.client.get(reverse("rh:detail", args=[self.employe.id]))

        self.assertContains(reponse, reverse("access:staff_face_enrollment", args=[self.employe.id]))

    def test_the_rh_sheet_hides_it_without_the_access_module(self):
        GymModule.objects.filter(gym=self.gym, module__code="ACCESS").update(is_active=False)

        reponse = self.client.get(reverse("rh:detail", args=[self.employe.id]))

        self.assertEqual(reponse.status_code, 200)
        self.assertNotContains(reponse, reverse("access:staff_face_enrollment", args=[self.employe.id]))



class StaffDepartureTests(TestCase):
    """Au depart d'un employe, son visage quitte le lecteur - ou l'alerte reste."""

    def setUp(self):
        from .models import StaffReaderRecord

        (self.gym, self.device, self.member, self.employe,
         self.employe_voisin) = _salle_avec_personnel("depart")
        self.gerant = User.objects.create_user(username="gerant-depart", password="pass12345")
        UserGymRole.objects.create(user=self.gerant, gym=self.gym, role="manager", is_active=True)
        self._connecter(self.gerant)
        self.numero = enrollment.numero_personnel(self.employe)
        self.Fiche = StaffReaderRecord
        _lecteur_sans_reste(self)

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _inscrire(self):
        from . import personnel

        return personnel.noter_inscription(self.device, self.employe)

    def _desactiver(self, **patch_retrait):
        with patch.object(hikvision.HikvisionClient, "delete_user", **patch_retrait) as retrait:
            reponse = self.client.post(reverse("rh:delete", args=[self.employe.id]), follow=True)
        return reponse, retrait

    def _lecteur_injoignable(self):
        return {"side_effect": hikvision.HikvisionUnreachable("cable arrache")}

    def _alertes(self):
        return self.client.get(reverse("core:gym_dashboard", args=[self.gym.id])).context["alertes_urgentes"]

    # --- L'inscription est retenue -------------------------------------------------------

    def test_an_enrolment_remembers_the_reader(self):
        with patch.object(hikvision.HikvisionClient, "capture_face", return_value=_image_jpeg()):
            self.client.post(
                reverse("access:staff_face_capture", args=[self.employe.id]),
                {"device_id": self.device.id},
            )
        with patch.object(hikvision.HikvisionClient, "upsert_user"), patch.object(
            hikvision.HikvisionClient, "set_face"
        ):
            self.client.post(reverse("access:staff_face_confirm", args=[self.employe.id]))

        fiche = self.Fiche.objects.get()
        self.assertEqual(fiche.device, self.device)
        self.assertEqual(fiche.employee_no, self.numero)
        self.assertIsNone(fiche.retrait_demande_le)

    # --- La desactivation retire le visage ---------------------------------------------------

    def test_deactivating_removes_the_face_from_the_reader(self):
        self._inscrire()

        reponse, retrait = self._desactiver()

        retrait.assert_called_once_with(self.numero)
        self.assertFalse(self.Fiche.objects.exists())
        self.assertContains(reponse, "a ete retire du lecteur")

    def test_deactivating_through_the_form_removes_it_too(self):
        self._inscrire()

        with patch.object(hikvision.HikvisionClient, "delete_user") as retrait:
            self.client.post(
                reverse("rh:update", args=[self.employe.id]),
                {
                    "name": "Paul Gardien", "role": "cleaner", "phone": "+243860000098",
                    "email": "", "compensation_type": "daily",
                    "daily_salary": "5000", "monthly_salary": "0",
                },
            )

        retrait.assert_called_once_with(self.numero)
        self.assertFalse(self.Fiche.objects.exists())

    def test_editing_an_active_employee_never_calls_the_reader(self):
        self._inscrire()

        with patch.object(hikvision.HikvisionClient, "delete_user") as retrait:
            self.client.post(
                reverse("rh:update", args=[self.employe.id]),
                {
                    "name": "Paul Gardien", "role": "cleaner", "phone": "+243860000077",
                    "email": "", "compensation_type": "daily",
                    "daily_salary": "5000", "monthly_salary": "0", "is_active": "on",
                },
            )

        retrait.assert_not_called()
        self.assertIsNone(self.Fiche.objects.get().retrait_demande_le)

    def test_an_employee_never_enrolled_never_calls_the_reader(self):
        _, retrait = self._desactiver()

        retrait.assert_not_called()

    # --- Le lecteur ne confirme pas ------------------------------------------------------------

    def test_an_unconfirmed_removal_stays_pending_and_warns(self):
        self._inscrire()

        reponse, _ = self._desactiver(**self._lecteur_injoignable())

        self.employe.refresh_from_db()
        self.assertFalse(self.employe.is_active)
        fiche = self.Fiche.objects.get()
        self.assertIsNotNone(fiche.retrait_demande_le)
        self.assertIn("injoignable", fiche.derniere_erreur)
        self.assertContains(reponse, "peut encore entrer")

    def test_the_dashboard_raises_an_urgent_alert_with_a_retry(self):
        self._inscrire()
        self._desactiver(**self._lecteur_injoignable())

        alertes = [a for a in self._alertes() if a.get("reessayer_url")]

        self.assertEqual(len(alertes), 1)
        self.assertEqual(alertes[0]["ton"], "urgent")
        self.assertIn("Paul Gardien", alertes[0]["titre"])
        page = self.client.get(reverse("core:gym_dashboard", args=[self.gym.id]))
        self.assertContains(page, "Réessayer")
        self.assertContains(page, alertes[0]["reessayer_url"])

    def test_no_alert_once_the_removal_is_confirmed(self):
        self._inscrire()
        self._desactiver()

        self.assertFalse([a for a in self._alertes() if a.get("reessayer_url")])

    def test_retry_confirms_the_removal(self):
        fiche = self._inscrire()
        self._desactiver(**self._lecteur_injoignable())

        with patch.object(hikvision.HikvisionClient, "delete_user") as retrait:
            reponse = self.client.post(
                reverse("access:staff_removal_retry", args=[fiche.id]), follow=True
            )

        retrait.assert_called_once_with(self.numero)
        self.assertFalse(self.Fiche.objects.exists())
        self.assertEqual(reponse.status_code, 200)
        trace = SensitiveActivityLog.objects.get(action="access.staff_face_removal_retried")
        self.assertTrue(trace.metadata["confirme"])

    def test_a_failed_retry_keeps_the_alert(self):
        fiche = self._inscrire()
        self._desactiver(**self._lecteur_injoignable())

        with patch.object(hikvision.HikvisionClient, "delete_user", **self._lecteur_injoignable()):
            self.client.post(reverse("access:staff_removal_retry", args=[fiche.id]))

        self.assertTrue(self.Fiche.objects.filter(retrait_demande_le__isnull=False).exists())

    def test_a_receptionist_cannot_retry(self):
        fiche = self._inscrire()
        self._desactiver(**self._lecteur_injoignable())
        accueil = User.objects.create_user(username="accueil-depart", password="pass12345")
        UserGymRole.objects.create(user=accueil, gym=self.gym, role="reception", is_active=True)
        self._connecter(accueil)

        with patch.object(hikvision.HikvisionClient, "delete_user") as retrait:
            reponse = self.client.post(reverse("access:staff_removal_retry", args=[fiche.id]))

        self.assertIn(reponse.status_code, (302, 403))
        retrait.assert_not_called()

    def test_another_gym_record_is_out_of_reach(self):
        from .models import StaffReaderRecord

        voisin = AccessDevice.objects.create(
            gym=self.employe_voisin.gym, name="Voisin", host="10.0.0.8", password="secret"
        )
        fiche = StaffReaderRecord.objects.create(
            gym=voisin.gym, device=voisin, employee=self.employe_voisin,
            employee_no=enrollment.numero_personnel(self.employe_voisin),
            nom="Zoe Ailleurs", retrait_demande_le=timezone.now(),
        )

        reponse = self.client.post(reverse("access:staff_removal_retry", args=[fiche.id]))

        self.assertEqual(reponse.status_code, 404)

    def test_a_retry_only_redirects_inside_the_site(self):
        fiche = self._inscrire()
        self._desactiver(**self._lecteur_injoignable())

        with patch.object(hikvision.HikvisionClient, "delete_user"):
            reponse = self.client.post(
                reverse("access:staff_removal_retry", args=[fiche.id]),
                {"next": "https://ailleurs.example/piege"},
            )

        self.assertEqual(reponse["Location"], reverse("core:gym_dashboard", args=[self.gym.id]))

    # --- Les autres chemins de depart ----------------------------------------------------------

    def test_any_deactivation_requests_the_removal(self):
        # Administration, script : sans passer par l'ecran RH, l'alerte existe.
        self._inscrire()

        self.employe.is_active = False
        self.employe.save()

        self.assertIsNotNone(self.Fiche.objects.get().retrait_demande_le)

    def test_a_deleted_employee_leaves_a_named_alert(self):
        self._inscrire()

        self.employe.delete()

        fiche = self.Fiche.objects.get()
        self.assertIsNone(fiche.employee)
        self.assertIsNotNone(fiche.retrait_demande_le)
        self.assertTrue(any("Paul Gardien" in a["titre"] for a in self._alertes()))

    def test_a_failed_manual_removal_is_not_cancelled_by_an_edit(self):
        with patch.object(hikvision.HikvisionClient, "delete_user", **self._lecteur_injoignable()):
            self.client.post(reverse("access:staff_face_remove", args=[self.employe.id]))

        self.employe.phone = "+243860000055"
        self.employe.save()

        self.assertIsNotNone(self.Fiche.objects.get().retrait_demande_le)

    def test_no_alert_without_the_access_module(self):
        self._inscrire()
        self._desactiver(**self._lecteur_injoignable())
        GymModule.objects.filter(gym=self.gym, module__code="ACCESS").update(is_active=False)

        self.assertFalse([a for a in self._alertes() if a.get("reessayer_url")])

    # --- La synchronisation acheve le travail ----------------------------------------------------

    def _synchroniser(self, fiches):
        import io

        from django.core.management import call_command

        with patch.object(
            hikvision.HikvisionClient, "user_count", return_value={"users": len(fiches), "faces": 0}
        ), patch.object(
            hikvision.HikvisionClient, "list_users", return_value=fiches
        ), patch.object(
            hikvision.HikvisionClient, "upsert_user"
        ) as pose, patch.object(
            hikvision.HikvisionClient, "delete_user"
        ) as retrait:
            call_command("synchroniser_lecteurs", stdout=io.StringIO())
        return pose, retrait

    def test_sync_confirms_a_removal_already_done_on_the_reader(self):
        self._inscrire()
        self.employe.is_active = False
        self.employe.save()

        _, retrait = self._synchroniser([])

        retrait.assert_not_called()
        self.assertFalse(self.Fiche.objects.exists())

    def test_sync_retries_a_pending_removal(self):
        self._inscrire()
        self.employe.is_active = False
        self.employe.save()

        _, retrait = self._synchroniser([{"employeeNo": self.numero}])

        retrait.assert_called_once_with(self.numero)
        self.assertFalse(self.Fiche.objects.exists())

    def test_sync_removes_a_deactivated_employee_it_did_not_know(self):
        self.employe.is_active = False
        self.employe.save()

        _, retrait = self._synchroniser([{"employeeNo": self.numero}])

        retrait.assert_called_once_with(self.numero)

    def test_sync_notes_an_active_employee_found_on_the_reader(self):
        pose, retrait = self._synchroniser([{"employeeNo": self.numero}])

        retrait.assert_not_called()
        self.assertIn(self.numero, [appel.args[0] for appel in pose.mock_calls])
        self.assertEqual(self.Fiche.objects.get().employee, self.employe)



class StaffSwitchFromMemberTests(TestCase):
    """Un employe inscrit comme membre passe au personnel, historique intact."""

    def setUp(self):
        from django.core.files.base import ContentFile

        (self.gym, self.device, self.membre_normal, self.employe,
         self.employe_voisin) = _salle_avec_personnel("bascule")
        # La fiche membre de l'employe : meme nom, meme telephone, visage du lecteur.
        self.faux_membre = Member.objects.create(
            gym=self.gym, first_name="Paul", last_name="Gardien", phone="+243860000098",
        )
        self.faux_membre.photo.save(
            f"visage_membre_{self.faux_membre.id}.jpg", ContentFile(_image_jpeg()), save=True
        )
        plan = SubscriptionPlan.objects.create(gym=self.gym, name="Mensuel", price=30, duration_days=30)
        today = timezone.localdate()
        MemberSubscription.objects.create(
            gym=self.gym, member=self.faux_membre, plan=plan,
            start_date=today - timedelta(days=1), end_date=today + timedelta(days=29),
            is_active=True,
        )
        self.passage = AccessLog.objects.create(
            gym=self.gym, member=self.faux_membre, access_granted=True
        )
        self.gerant = User.objects.create_user(username="gerant-bascule", password="pass12345")
        UserGymRole.objects.create(user=self.gerant, gym=self.gym, role="manager", is_active=True)
        self._connecter(self.gerant)

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _basculer(self, membre=None, **retrait):
        from . import personnel

        appels = []
        with patch.object(
            hikvision.HikvisionClient, "delete_user",
            side_effect=retrait.get("side_effect") or (lambda n: appels.append(("retrait", n))),
        ), patch.object(
            hikvision.HikvisionClient, "upsert_user",
            side_effect=lambda n, *a, **k: appels.append(("fiche", n)),
        ), patch.object(
            hikvision.HikvisionClient, "set_face",
            side_effect=lambda n, *a, **k: appels.append(("visage", n)),
        ):
            resultat = personnel.basculer_membre(self.employe, membre or self.faux_membre)
        return resultat, appels

    # --- Le service --------------------------------------------------------------------------

    def test_the_member_record_leaves_the_reader_before_the_face_is_set(self):
        # Le lecteur refuse un meme visage sur deux fiches : l'ordre est vital.
        _, appels = self._basculer()

        numero_membre = enrollment.employee_no(self.faux_membre)
        numero_employe = enrollment.numero_personnel(self.employe)
        self.assertEqual(
            appels,
            [("retrait", numero_membre), ("fiche", numero_employe), ("visage", numero_employe)],
        )

    def test_the_member_record_is_deactivated_and_its_history_kept(self):
        resultat, _ = self._basculer()

        self.faux_membre.refresh_from_db()
        self.assertFalse(self.faux_membre.is_active)
        self.assertTrue(resultat["photo"])
        self.passage.refresh_from_db()
        self.assertEqual(self.passage.member, self.faux_membre)
        self.assertTrue(self.faux_membre.subscriptions.filter(is_active=True).exists())

    def test_the_employee_is_remembered_on_the_reader(self):
        from .models import StaffReaderRecord

        self._basculer()

        self.assertEqual(StaffReaderRecord.objects.get().employee, self.employe)

    def test_a_photo_not_taken_by_the_reader_is_not_reused(self):
        from django.core.files.base import ContentFile

        self.faux_membre.photo.save("portrait_telephone.jpg", ContentFile(_image_jpeg()), save=True)

        resultat, appels = self._basculer()

        self.assertFalse(resultat["photo"])
        self.assertNotIn("visage", [genre for genre, _ in appels])
        self.faux_membre.refresh_from_db()
        self.assertFalse(self.faux_membre.is_active)

    def test_another_members_reader_photo_is_not_taken_for_this_one(self):
        from . import personnel

        self.faux_membre.photo.name = f"members/visage_membre_{self.faux_membre.id}7.jpg"

        self.assertFalse(personnel.photo_reprise_possible(self.faux_membre))

    def test_an_unreachable_reader_changes_nothing(self):
        with self.assertRaises(enrollment.EnrollmentError):
            _, appels = self._basculer(side_effect=hikvision.HikvisionUnreachable("coupure"))

        self.faux_membre.refresh_from_db()
        self.assertTrue(self.faux_membre.is_active)
        from .models import StaffReaderRecord
        self.assertFalse(StaffReaderRecord.objects.exists())

    def test_a_record_already_absent_from_the_reader_does_not_block(self):
        resultat, appels = self._basculer(side_effect=hikvision.HikvisionError("fiche inconnue"))

        self.faux_membre.refresh_from_db()
        self.assertFalse(self.faux_membre.is_active)
        self.assertIn(("visage", enrollment.numero_personnel(self.employe)), appels)

    def test_a_member_of_another_gym_is_refused(self):
        etranger = Member.objects.create(
            gym=self.employe_voisin.gym, first_name="X", last_name="Y", phone="+243860000031",
        )

        with self.assertRaises(enrollment.EnrollmentError):
            self._basculer(membre=etranger)

    def test_a_deactivated_employee_cannot_take_a_member_record(self):
        self.employe.is_active = False
        self.employe.save()

        with self.assertRaises(enrollment.EnrollmentError):
            self._basculer()
        self.faux_membre.refresh_from_db()
        self.assertTrue(self.faux_membre.is_active)

    def test_a_deactivated_member_no_longer_opens_the_reader(self):
        self.faux_membre.is_active = False
        self.faux_membre.save()

        with patch.object(hikvision.HikvisionClient, "upsert_user") as pose:
            enrollment.inscrire_membre(self.device, self.faux_membre)

        self.assertEqual(pose.mock_calls[0].args[3], timezone.localdate().strftime("%Y-%m-%dT00:00:00"))

    # --- Les candidats ---------------------------------------------------------------------------

    def test_a_member_with_the_same_phone_or_name_is_suggested(self):
        from . import personnel

        candidats = [c["membre"] for c in personnel.membres_candidats(self.employe)]

        self.assertEqual(candidats, [self.faux_membre])

    def test_a_deactivated_member_is_not_suggested(self):
        from . import personnel

        self.faux_membre.is_active = False
        self.faux_membre.save()

        self.assertEqual(personnel.membres_candidats(self.employe), [])

    def test_the_search_finds_other_members(self):
        from . import personnel

        candidats = [c["membre"] for c in personnel.membres_candidats(self.employe, "Nzuzi")]

        self.assertEqual(candidats, [self.membre_normal])

    # --- L'ecran -----------------------------------------------------------------------------------

    def test_the_screen_offers_the_matching_member(self):
        reponse = self.client.get(reverse("access:staff_face_enrollment", args=[self.employe.id]))

        self.assertContains(reponse, reverse("access:staff_switch_from_member", args=[self.employe.id]))
        self.assertContains(reponse, f'name="member_id" value="{self.faux_membre.id}"')
        self.assertContains(reponse, "visage pris par le lecteur")

    def test_switching_from_the_screen_is_traced(self):
        with patch.object(hikvision.HikvisionClient, "delete_user"), patch.object(
            hikvision.HikvisionClient, "upsert_user"
        ), patch.object(hikvision.HikvisionClient, "set_face"):
            reponse = self.client.post(
                reverse("access:staff_switch_from_member", args=[self.employe.id]),
                {"member_id": self.faux_membre.id},
                follow=True,
            )

        self.assertContains(reponse, "historique est conserve")
        self.faux_membre.refresh_from_db()
        self.assertFalse(self.faux_membre.is_active)
        trace = SensitiveActivityLog.objects.get(action="access.member_switched_to_staff")
        self.assertEqual(trace.metadata["member_id"], self.faux_membre.id)
        self.assertTrue(trace.metadata["visage_repris"])

    def test_a_receptionist_cannot_switch(self):
        accueil = User.objects.create_user(username="accueil-bascule", password="pass12345")
        UserGymRole.objects.create(user=accueil, gym=self.gym, role="reception", is_active=True)
        self._connecter(accueil)

        with patch.object(hikvision.HikvisionClient, "delete_user") as retrait:
            reponse = self.client.post(
                reverse("access:staff_switch_from_member", args=[self.employe.id]),
                {"member_id": self.faux_membre.id},
            )

        self.assertIn(reponse.status_code, (302, 403))
        retrait.assert_not_called()
        self.faux_membre.refresh_from_db()
        self.assertTrue(self.faux_membre.is_active)

    def test_an_unreadable_member_id_is_not_found(self):
        reponse = self.client.post(
            reverse("access:staff_switch_from_member", args=[self.employe.id]),
            {"member_id": "abc"},
        )

        self.assertEqual(reponse.status_code, 404)

    # --- Le membre desactive, ailleurs dans l'application ---------------------------------------

    def test_the_dashboard_no_longer_counts_the_member(self):
        url = reverse("core:gym_dashboard", args=[self.gym.id])
        avant = self.client.get(url).context

        self.faux_membre.is_active = False
        self.faux_membre.save()
        apres = self.client.get(url).context

        self.assertEqual(apres["total_members"], avant["total_members"] - 1)
        self.assertEqual(apres["active_members"], avant["active_members"] - 1)

    def test_the_member_list_marks_it_inactive(self):
        self.faux_membre.is_active = False
        self.faux_membre.save()

        reponse = self.client.get(reverse("members:member_list"))

        self.assertContains(reponse, 'badge bg-secondary px-3 py-2">Inactif')

    def test_the_active_filter_leaves_it_out(self):
        self.faux_membre.is_active = False
        self.faux_membre.save()

        reponse = self.client.get(reverse("members:member_list"), {"status": "active"})

        self.assertNotContains(reponse, "Gardien")

    def test_the_member_sheet_says_inactive(self):
        self.faux_membre.is_active = False
        self.faux_membre.save()

        reponse = self.client.get(reverse("members:member_detail", args=[self.faux_membre.id]))

        self.assertEqual(reponse.json()["status"], "inactive")



class StaffTodayOnDashboardTests(TestCase):
    """Le personnel passe aujourd'hui a sa ligne, hors des chiffres des membres."""

    def setUp(self):
        from decimal import Decimal

        from rh.models import Employee

        (self.gym, self.device, self.member, self.employe,
         _) = _salle_avec_personnel("tableau-personnel")
        self.collegue = Employee.objects.create(
            gym=self.gym, name="Rita Accueil", role="reception",
            compensation_type="daily", daily_salary=Decimal("5000"),
        )
        gerant = User.objects.create_user(username="gerant-tableau-personnel", password="pass12345")
        UserGymRole.objects.create(user=gerant, gym=self.gym, role="manager", is_active=True)
        self.client.force_login(gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()
        self.url = reverse("core:gym_dashboard", args=[self.gym.id])

    def _passage(self, **champs):
        return AccessLog.objects.create(gym=self.gym, access_granted=True, **champs)

    def test_each_staff_person_counts_once(self):
        self._passage(employee=self.employe)
        self._passage(employee=self.employe, is_return=True)
        self._passage(employee=self.collegue)
        self._passage(terminal_label="Gardien de nuit")
        self._passage(terminal_label="Gardien de nuit", is_return=True)

        self.assertEqual(self.client.get(self.url).context["personnel_today"], 3)

    def test_member_numbers_do_not_move(self):
        self._passage(member=self.member)
        self._passage(employee=self.employe)
        self._passage(terminal_label="Fiche 4")

        contexte = self.client.get(self.url).context

        self.assertEqual(contexte["today_checkins"], 1)
        self.assertEqual(contexte["personnel_today"], 2)

    def test_a_refusal_is_not_an_entry(self):
        self._passage(employee=self.employe)
        AccessLog.objects.create(gym=self.gym, employee=self.collegue, access_granted=False)

        self.assertEqual(self.client.get(self.url).context["personnel_today"], 1)

    def test_yesterday_is_not_today(self):
        hier = self._passage(employee=self.employe)
        AccessLog.objects.filter(pk=hier.pk).update(check_in_time=timezone.now() - timedelta(days=1))

        self.assertEqual(self.client.get(self.url).context["personnel_today"], 0)

    def test_members_and_manual_openings_are_not_staff(self):
        self._passage(member=self.member)
        self._passage()

        self.assertEqual(self.client.get(self.url).context["personnel_today"], 0)

    def test_the_line_appears_in_the_activity_block(self):
        # La ligne vit desormais dans la carte du detail des passages, avec les
        # invites et les ouvertures manuelles.
        self._passage(employee=self.employe)

        self.assertContains(self.client.get(self.url), "Passages du personnel : 1")

    def test_no_line_without_the_access_module(self):
        GymModule.objects.filter(gym=self.gym, module__code="ACCESS").update(is_active=False)
        self._passage(employee=self.employe)

        reponse = self.client.get(self.url)

        self.assertIsNone(reponse.context["personnel_today"])
        self.assertNotContains(reponse, "Personnel passe")



class StaffTerminalAdoptionTests(TestCase):
    """Un employe cree a la main sur le terminal garde son visage, a son nom."""

    def setUp(self):
        from .models import StaffReaderRecord

        (self.gym, self.device, self.member, self.employe,
         self.employe_voisin) = _salle_avec_personnel("adoption")
        self.Fiche = StaffReaderRecord
        self.gerant = User.objects.create_user(username="gerant-adoption", password="pass12345")
        UserGymRole.objects.create(user=self.gerant, gym=self.gym, role="manager", is_active=True)
        self._connecter(self.gerant)
        self.url_ecran = reverse("access:staff_face_enrollment", args=[self.employe.id])
        self.url_adopter = reverse("access:staff_adopt_terminal_record", args=[self.employe.id])
        _lecteur_sans_reste(self)

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _adopter(self, numero="5", employe=None, device=None):
        from . import personnel

        return personnel.adopter_fiche(device or self.device, employe or self.employe, numero)

    def _synchroniser(self, fiches):
        import io

        from django.core.management import call_command

        with patch.object(
            hikvision.HikvisionClient, "user_count", return_value={"users": len(fiches), "faces": 0}
        ), patch.object(
            hikvision.HikvisionClient, "list_users", return_value=fiches
        ), patch.object(
            hikvision.HikvisionClient, "upsert_user"
        ) as pose, patch.object(
            hikvision.HikvisionClient, "delete_user"
        ) as retrait:
            call_command("synchroniser_lecteurs", stdout=io.StringIO())
        return pose, retrait

    # --- Le service --------------------------------------------------------------------------

    def test_an_adopted_record_designates_the_employee(self):
        from . import personnel

        self._adopter("5")

        self.assertEqual(personnel.employe_de_la_fiche(self.device, "5"), self.employe)

    def test_the_link_holds_for_that_reader_only(self):
        from . import personnel

        autre = AccessDevice.objects.create(
            gym=self.gym, name="Terminal 2", host="10.0.0.10", password="secret"
        )
        self._adopter("5")

        self.assertIsNone(personnel.employe_de_la_fiche(autre, "5"))

    def test_only_a_manual_record_can_be_adopted(self):
        for numero in (
            enrollment.employee_no(self.member),
            enrollment.numero_personnel(self.employe),
            "badge",
            "",
        ):
            with self.subTest(numero=numero):
                with self.assertRaises(enrollment.EnrollmentError):
                    self._adopter(numero)
        self.assertFalse(self.Fiche.objects.exists())

    def test_a_record_already_adopted_by_someone_else_is_refused(self):
        from decimal import Decimal

        from rh.models import Employee

        collegue = Employee.objects.create(
            gym=self.gym, name="Rita Accueil", role="reception",
            compensation_type="daily", daily_salary=Decimal("5000"),
        )
        self._adopter("5", employe=collegue)

        with self.assertRaises(enrollment.EnrollmentError):
            self._adopter("5")

    def test_adopting_twice_for_the_same_employee_is_harmless(self):
        self._adopter("5")
        self._adopter("5")

        self.assertEqual(self.Fiche.objects.count(), 1)

    def test_a_deactivated_employee_cannot_adopt(self):
        self.employe.is_active = False
        self.employe.save()

        with self.assertRaises(enrollment.EnrollmentError):
            self._adopter("5")

    def test_a_reader_of_another_gym_is_refused(self):
        voisin = AccessDevice.objects.create(
            gym=self.employe_voisin.gym, name="Voisin", host="10.0.0.8", password="secret"
        )

        with self.assertRaises(enrollment.EnrollmentError):
            self._adopter("5", device=voisin)

    def test_the_listing_keeps_only_free_manual_records(self):
        from . import personnel

        self._adopter("7")
        lues = [
            {"employeeNo": "5", "name": "Paul G"},
            {"employeeNo": "7", "name": "Deja rattache"},
            {"employeeNo": enrollment.employee_no(self.member), "name": "Alice"},
            {"employeeNo": enrollment.numero_personnel(self.employe), "name": "Paul"},
        ]
        with patch.object(hikvision.HikvisionClient, "list_users", return_value=lues):
            resultat = personnel.fiches_du_terminal(self.gym)

        self.assertEqual([f["numero"] for f in resultat["fiches"]], ["5"])
        self.assertEqual(resultat["erreurs"], [])

    def test_the_listing_can_be_filtered(self):
        from . import personnel

        lues = [{"employeeNo": "5", "name": "Paul G"}, {"employeeNo": "6", "name": "Rita"}]
        with patch.object(hikvision.HikvisionClient, "list_users", return_value=lues):
            resultat = personnel.fiches_du_terminal(self.gym, "rita")

        self.assertEqual([f["numero"] for f in resultat["fiches"]], ["6"])

    def test_an_unreachable_reader_is_reported(self):
        from . import personnel

        with patch.object(
            hikvision.HikvisionClient, "list_users",
            side_effect=hikvision.HikvisionUnreachable("coupure"),
        ):
            resultat = personnel.fiches_du_terminal(self.gym)

        self.assertEqual(resultat["fiches"], [])
        self.assertEqual(len(resultat["erreurs"]), 1)

    # --- La porte et le rattrapage ------------------------------------------------------------

    def _envoyer(self, **evenement):
        charge = {"AccessControllerEvent": {"majorEventType": 5, "subEventType": 75, **evenement}}
        url = reverse("access:device_webhook", args=[self.device.webhook_token])
        with patch("access.hikvision.HikvisionClient.open_door"):
            return self.client.post(url, data=json.dumps(charge), content_type="application/json")

    def test_a_passage_on_an_adopted_record_is_the_employees(self):
        self._adopter("5")

        self._envoyer(employeeNoString="5", name="Paul G")

        log = AccessLog.objects.get()
        self.assertEqual(log.employee, self.employe)
        self.assertEqual(log.terminal_label, "")

    def test_a_record_not_adopted_stays_a_terminal_record(self):
        self._envoyer(employeeNoString="5", name="Paul G")

        log = AccessLog.objects.get()
        self.assertIsNone(log.employee)
        self.assertEqual(log.terminal_label, "Paul G")

    def test_the_catch_up_names_the_adopting_employee(self):
        import io

        from django.core.management import call_command

        from .management.commands.rattraper_passages import Command

        self._adopter("5")
        evenements = [{
            "employeeNoString": "5", "name": "Paul G", "minor": 75, "serialNo": "960",
            "time": timezone.localtime().replace(microsecond=0).isoformat(),
        }]
        with patch.object(Command, "_lire_evenements", return_value=evenements):
            call_command("rattraper_passages", stdout=io.StringIO())

        self.assertEqual(AccessLog.objects.get(device_event_id="960").employee, self.employe)

    # --- Le depart ---------------------------------------------------------------------------------

    def test_deactivating_removes_the_adopted_record(self):
        self._adopter("5")

        with patch.object(hikvision.HikvisionClient, "delete_user") as retrait:
            self.client.post(reverse("rh:delete", args=[self.employe.id]))

        retrait.assert_called_once_with("5")
        self.assertFalse(self.Fiche.objects.exists())

    def test_manual_removal_targets_the_adopted_number_only(self):
        self._adopter("5")

        with patch.object(hikvision.HikvisionClient, "delete_user") as retrait:
            self.client.post(reverse("access:staff_face_remove", args=[self.employe.id]))

        retrait.assert_called_once_with("5")

    def test_sync_does_not_confirm_an_adopted_removal_still_on_the_reader(self):
        self._adopter("5")
        self.employe.is_active = False
        self.employe.save()

        with patch.object(hikvision.HikvisionClient, "delete_user", side_effect=hikvision.HikvisionUnreachable("coupure")):
            import io

            from django.core.management import call_command

            with patch.object(
                hikvision.HikvisionClient, "user_count", return_value={"users": 1, "faces": 0}
            ), patch.object(hikvision.HikvisionClient, "list_users", return_value=[{"employeeNo": "5"}]):
                call_command("synchroniser_lecteurs", stdout=io.StringIO())

        self.assertTrue(self.Fiche.objects.filter(retrait_demande_le__isnull=False).exists())

    def test_sync_removes_an_adopted_record_of_a_deactivated_employee(self):
        from rh.models import Employee

        self._adopter("5")
        # Desactivation hors application, sans signal.
        Employee.objects.filter(pk=self.employe.pk).update(is_active=False)

        _, retrait = self._synchroniser([{"employeeNo": "5"}])

        retrait.assert_called_once_with("5")
        self.assertFalse(self.Fiche.objects.exists())

    def test_sync_leaves_an_active_adopted_record_alone(self):
        self._adopter("5")

        pose, retrait = self._synchroniser([{"employeeNo": "5"}])

        pose.assert_not_called()
        retrait.assert_not_called()
        self.assertTrue(self.Fiche.objects.exists())

    # --- L'ecran -----------------------------------------------------------------------------------

    def test_the_screen_does_not_read_the_reader_unasked(self):
        with patch.object(hikvision.HikvisionClient, "list_users") as lecture:
            reponse = self.client.get(self.url_ecran)

        lecture.assert_not_called()
        self.assertContains(reponse, "Lire les fiches du lecteur")

    def test_the_screen_lists_terminal_records_on_demand(self):
        with patch.object(
            hikvision.HikvisionClient, "list_users",
            return_value=[{"employeeNo": "5", "name": "Paul G"}],
        ):
            reponse = self.client.get(self.url_ecran, {"fiches": "1"})

        self.assertContains(reponse, "Paul G")
        self.assertContains(reponse, 'name="employee_no" value="5"')
        self.assertContains(reponse, self.url_adopter)

    def test_adopting_from_the_screen_is_traced(self):
        reponse = self.client.post(
            self.url_adopter,
            {"device_id": self.device.id, "employee_no": "5", "nom": "Paul G"},
            follow=True,
        )

        self.assertEqual(self.Fiche.objects.get().employee_no, "5")
        trace = SensitiveActivityLog.objects.get(action="access.staff_terminal_record_adopted")
        self.assertEqual(trace.metadata["employee_no"], "5")
        self.assertContains(reponse, "Fiche du terminal rattach")
        self.assertContains(reponse, "n° 5 sur Terminal")

    def test_a_receptionist_cannot_adopt(self):
        accueil = User.objects.create_user(username="accueil-adoption", password="pass12345")
        UserGymRole.objects.create(user=accueil, gym=self.gym, role="reception", is_active=True)
        self._connecter(accueil)

        reponse = self.client.post(
            self.url_adopter, {"device_id": self.device.id, "employee_no": "5"}
        )

        self.assertIn(reponse.status_code, (302, 403))
        self.assertFalse(self.Fiche.objects.exists())

    def test_a_reader_of_another_gym_is_out_of_reach_on_screen(self):
        voisin = AccessDevice.objects.create(
            gym=self.employe_voisin.gym, name="Voisin", host="10.0.0.8", password="secret"
        )

        reponse = self.client.post(
            self.url_adopter, {"device_id": voisin.id, "employee_no": "5"}
        )

        self.assertEqual(reponse.status_code, 404)
        self.assertFalse(self.Fiche.objects.exists())



class TerminalRecordLastPassageTests(TestCase):
    """Une fiche du terminal sans nom se reconnait a son dernier passage."""

    def setUp(self):
        (self.gym, self.device, self.member, self.employe,
         _) = _salle_avec_personnel("dernier-passage")
        gerant = User.objects.create_user(username="gerant-dernier-passage", password="pass12345")
        UserGymRole.objects.create(user=gerant, gym=self.gym, role="manager", is_active=True)
        self.client.force_login(gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _lire(self, lues, recherche=""):
        from . import personnel

        with patch.object(hikvision.HikvisionClient, "list_users", return_value=lues):
            return personnel.fiches_du_terminal(self.gym, recherche)["fiches"]

    def _passage(self, libelle, device=None, il_y_a=None):
        log = AccessLog.objects.create(
            gym=self.gym, device=device or self.device, terminal_label=libelle, access_granted=True
        )
        if il_y_a is not None:
            AccessLog.objects.filter(pk=log.pk).update(check_in_time=timezone.now() - il_y_a)
        return log

    def test_a_nameless_record_shows_its_last_passage(self):
        self._passage("Fiche 6")

        fiches = {f["numero"]: f for f in self._lire([{"employeeNo": "6", "name": ""}])}

        self.assertIsNotNone(fiches["6"]["dernier_passage"])
        self.assertTrue(fiches["6"]["passe_aujourdhui"])

    def test_a_named_record_is_found_under_its_name(self):
        self._passage("Paul G")

        fiches = {f["numero"]: f for f in self._lire([{"employeeNo": "5", "name": "Paul G"}])}

        self.assertIsNotNone(fiches["5"]["dernier_passage"])

    def test_the_record_that_just_passed_comes_first(self):
        self._passage("Fiche 9", il_y_a=timedelta(days=3))
        self._passage("Fiche 6")

        fiches = self._lire([
            {"employeeNo": "5", "name": "Jamais vu"},
            {"employeeNo": "9", "name": ""},
            {"employeeNo": "6", "name": ""},
        ])

        self.assertEqual([f["numero"] for f in fiches], ["6", "9", "5"])
        self.assertFalse(fiches[1]["passe_aujourdhui"])
        self.assertIsNone(fiches[2]["dernier_passage"])

    def test_a_passage_on_another_reader_is_not_this_records(self):
        autre = AccessDevice.objects.create(
            gym=self.gym, name="Terminal 2", host="10.0.0.10", password="secret"
        )
        self._passage("Fiche 6", device=autre)

        with patch.object(
            hikvision.HikvisionClient, "list_users", return_value=[{"employeeNo": "6", "name": ""}]
        ):
            from . import personnel

            fiches = personnel.fiches_du_terminal(self.gym)["fiches"]

        premiere = [f for f in fiches if f["device"] == self.device][0]
        self.assertIsNone(premiere["dernier_passage"])

    def test_the_door_and_the_listing_use_the_same_name(self):
        # Sans la meme regle des deux cotes, un passage reel resterait "jamais vu".
        charge = {"AccessControllerEvent": {
            "majorEventType": 5, "subEventType": 75, "employeeNoString": "6",
        }}
        url = reverse("access:device_webhook", args=[self.device.webhook_token])
        with patch("access.hikvision.HikvisionClient.open_door"):
            self.client.post(url, data=json.dumps(charge), content_type="application/json")

        fiches = self._lire([{"employeeNo": "6"}])

        self.assertTrue(fiches[0]["passe_aujourdhui"])

    def test_the_screen_says_when_each_record_last_passed(self):
        self._passage("Fiche 6")
        self._passage("Fiche 9", il_y_a=timedelta(days=3))
        lues = [
            {"employeeNo": "6", "name": ""},
            {"employeeNo": "9", "name": ""},
            {"employeeNo": "5", "name": "Jamais vu"},
        ]

        with patch.object(hikvision.HikvisionClient, "list_users", return_value=lues):
            reponse = self.client.get(
                reverse("access:staff_face_enrollment", args=[self.employe.id]), {"fiches": "1"}
            )

        self.assertContains(reponse, "passé aujourd'hui à")
        self.assertContains(reponse, "dernier passage le")
        self.assertContains(reponse, "jamais vu passer")
        self.assertContains(reponse, "Fiche sans nom ?")



class RelecturesTests(TestCase):
    """
    Deux lectures de la meme personne dans la minute font un seul passage.

    Le lecteur lit parfois plusieurs fois de suite : la frequentation du jour
    doublait sans que personne ne soit entre deux fois.
    """

    def setUp(self):
        (self.gym, self.device, self.member, self.employe,
         _) = _salle_avec_personnel("relectures")
        plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Mensuel", price=30, duration_days=30
        )
        today = timezone.localdate()
        MemberSubscription.objects.create(
            gym=self.gym, member=self.member, plan=plan,
            start_date=today - timedelta(days=1), end_date=today + timedelta(days=29),
            is_active=True,
        )
        self.url = reverse("access:device_webhook", args=[self.device.webhook_token])
        patcher = patch("access.hikvision.HikvisionClient.open_door")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _envoyer(self, **evenement):
        charge = {"AccessControllerEvent": {
            "majorEventType": 5, "subEventType": 75,
            "currentVerifyMode": "face", **evenement,
        }}
        return self.client.post(self.url, data=json.dumps(charge), content_type="application/json")

    def _numero_membre(self):
        return enrollment.employee_no(self.member)

    # --- Le membre ------------------------------------------------------------------------

    def test_two_readings_in_the_same_minute_make_one_passage(self):
        self._envoyer(employeeNoString=self._numero_membre(), serialNo="1")
        self._envoyer(employeeNoString=self._numero_membre(), serialNo="2")

        self.assertEqual(AccessLog.objects.filter(member=self.member).count(), 1)

    def test_the_door_still_opens_on_the_repeated_reading(self):
        self._envoyer(employeeNoString=self._numero_membre(), serialNo="1")

        reponse = self._envoyer(employeeNoString=self._numero_membre(), serialNo="2")

        self.assertTrue(reponse.json()["access"])
        self.assertEqual(reponse.json()["reason"], relectures.RELECTURE_REASON)

    def test_the_daily_attendance_counts_one(self):
        from .views import _today_stats

        self._envoyer(employeeNoString=self._numero_membre(), serialNo="1")
        self._envoyer(employeeNoString=self._numero_membre(), serialNo="2")

        self.assertEqual(_today_stats(self.gym)["entries"], 1)

    def test_a_later_passage_is_a_real_return(self):
        self._envoyer(employeeNoString=self._numero_membre(), serialNo="1")
        _vieillir_les_passages()

        self._envoyer(employeeNoString=self._numero_membre(), serialNo="2")

        self.assertEqual(AccessLog.objects.filter(member=self.member).count(), 2)
        self.assertTrue(AccessLog.objects.filter(member=self.member, is_return=True).exists())

    def test_two_different_people_are_two_passages(self):
        # La regle regroupe une personne, pas la porte.
        autre = Member.objects.create(
            gym=self.gym, first_name="Bob", last_name="Kasa", phone="+243860000077",
        )
        plan = SubscriptionPlan.objects.get(gym=self.gym)
        today = timezone.localdate()
        MemberSubscription.objects.create(
            gym=self.gym, member=autre, plan=plan, start_date=today,
            end_date=today + timedelta(days=30), is_active=True,
        )

        self._envoyer(employeeNoString=self._numero_membre(), serialNo="1")
        self._envoyer(employeeNoString=enrollment.employee_no(autre), serialNo="2")

        self.assertEqual(AccessLog.objects.count(), 2)

    def test_repeated_refusals_are_all_kept(self):
        # Quelqu'un qui insiste doit se voir : c'est l'alerte "refuse 3 fois".
        sans_droit = Member.objects.create(
            gym=self.gym, first_name="Sans", last_name="Abonnement", phone="+243860000088",
        )

        self._envoyer(employeeNoString=enrollment.employee_no(sans_droit), serialNo="1")
        self._envoyer(employeeNoString=enrollment.employee_no(sans_droit), serialNo="2")

        self.assertEqual(AccessLog.objects.filter(member=sans_droit, access_granted=False).count(), 2)

    # --- Le personnel et les fiches du terminal -------------------------------------------------

    def test_an_employee_read_twice_passes_once(self):
        numero = enrollment.numero_personnel(self.employe)

        self._envoyer(employeeNoString=numero, serialNo="1")
        self._envoyer(employeeNoString=numero, serialNo="2")

        self.assertEqual(AccessLog.objects.filter(employee=self.employe).count(), 1)

    def test_a_terminal_record_read_twice_passes_once(self):
        self._envoyer(employeeNoString="7", name="Gardien", serialNo="1")
        self._envoyer(employeeNoString="7", name="Gardien", serialNo="2")

        self.assertEqual(AccessLog.objects.filter(terminal_label="Gardien").count(), 1)

    # --- L'ouverture manuelle --------------------------------------------------------------------

    def test_manual_openings_are_never_grouped(self):
        # Une ouverture manuelle ne designe personne : deux gestes, deux lignes.
        AccessLog.objects.create(gym=self.gym, access_granted=True)
        AccessLog.objects.create(gym=self.gym, access_granted=True)

        self.assertEqual(AccessLog.objects.filter(member__isnull=True, terminal_label="").count(), 2)

    # --- Le rattrapage ------------------------------------------------------------------------------

    def test_the_catch_up_does_not_recreate_a_reading(self):
        import io

        from django.core.management import call_command

        from .management.commands.rattraper_passages import Command

        maintenant = timezone.localtime().replace(microsecond=0)
        evenements = [
            {"employeeNoString": self._numero_membre(), "minor": 75, "serialNo": "801",
             "time": maintenant.isoformat()},
            {"employeeNoString": self._numero_membre(), "minor": 75, "serialNo": "802",
             "time": (maintenant + timedelta(seconds=20)).isoformat()},
        ]
        with patch.object(Command, "_lire_evenements", return_value=evenements):
            call_command("rattraper_passages", stdout=io.StringIO())

        self.assertEqual(AccessLog.objects.filter(member=self.member).count(), 1)



class DetailDesPassagesTests(TestCase):
    """
    "Personnes differentes : 0 sur 1 passage" laissait croire a une erreur.

    Chaque categorie est desormais nommee : membres, invites, personnel,
    ouvertures manuelles.
    """

    def setUp(self):
        from members.models import GuestPass

        (self.gym, self.device, self.member, self.employe,
         _) = _salle_avec_personnel("detail-passages")
        self.GuestPass = GuestPass
        self.gerant = User.objects.create_user(username="gerant-detail", password="pass12345")
        UserGymRole.objects.create(user=self.gerant, gym=self.gym, role="manager", is_active=True)
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()
        self.url = reverse("core:gym_dashboard", args=[self.gym.id])

    def _carnet(self):
        from members import invitations

        plan = SubscriptionPlan.objects.create(
            gym=self.gym, name="Premium", price=50, duration_days=30,
            guest_invites_per_month=2, guest_sessions_per_invite=2,
        )
        MemberSubscription.objects.create(
            gym=self.gym, member=self.member, plan=plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30), is_active=True,
        )
        return invitations.emettre(self.member, "Paul Kabeya", "0820000001")

    def _detail(self):
        return self.client.get(self.url).context["passages_detail"]

    def test_each_kind_of_passage_is_named(self):
        carnet = self._carnet()
        AccessLog.objects.create(gym=self.gym, member=self.member, access_granted=True)
        AccessLog.objects.create(gym=self.gym, guest_pass=carnet, access_granted=True)
        AccessLog.objects.create(gym=self.gym, employee=self.employe, access_granted=True)
        AccessLog.objects.create(gym=self.gym, access_granted=True)

        detail = self._detail()

        self.assertEqual(detail["membres"], 1)
        self.assertEqual(detail["invites"], 1)
        self.assertEqual(detail["personnel"], 1)
        self.assertEqual(detail["ouvertures"], 1)

    def test_a_return_adds_nobody(self):
        AccessLog.objects.create(gym=self.gym, member=self.member, access_granted=True)
        AccessLog.objects.create(gym=self.gym, member=self.member, access_granted=True, is_return=True)

        self.assertEqual(self._detail()["membres"], 1)

    def test_a_refusal_is_not_an_entry(self):
        AccessLog.objects.create(gym=self.gym, member=self.member, access_granted=False)

        self.assertEqual(self._detail()["membres"], 0)

    def test_a_quiet_day_says_so(self):
        detail = self._detail()

        self.assertEqual(detail["membres"], 0)
        self.assertFalse(detail["autres"])
        self.assertContains(self.client.get(self.url), "Aucun autre passage aujourd'hui")

    def test_the_card_names_the_staff_passage(self):
        # Le cas du client : un seul passage, celui d'un employe.
        AccessLog.objects.create(gym=self.gym, employee=self.employe, access_granted=True)

        reponse = self.client.get(self.url)

        self.assertContains(reponse, "Membres différents")
        self.assertContains(reponse, "Passages du personnel : 1")
        self.assertNotContains(reponse, "Personnel passe :")

    def test_the_card_names_guests_and_manual_openings(self):
        carnet = self._carnet()
        AccessLog.objects.create(gym=self.gym, guest_pass=carnet, access_granted=True)
        AccessLog.objects.create(gym=self.gym, access_granted=True)

        reponse = self.client.get(self.url)

        self.assertContains(reponse, "Invités : 1")
        self.assertContains(reponse, "Ouvertures manuelles : 1")



class PointageAuPassageTests(TestCase):
    """Le passage d'un employe a la porte le pointe present, sans rien saisir."""

    def setUp(self):
        from rh.models import Attendance

        self.Attendance = Attendance
        (self.gym, self.device, self.member, self.employe,
         _) = _salle_avec_personnel("pointage")
        self.url = reverse("access:device_webhook", args=[self.device.webhook_token])
        patcher = patch("access.hikvision.HikvisionClient.open_door")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _envoyer(self, **evenement):
        charge = {"AccessControllerEvent": {"majorEventType": 5, "subEventType": 75, **evenement}}
        return self.client.post(self.url, data=json.dumps(charge), content_type="application/json")

    def test_a_staff_passage_writes_the_attendance(self):
        self._envoyer(employeeNoString=enrollment.numero_personnel(self.employe))

        pointage = self.Attendance.objects.get(employee=self.employe)
        self.assertEqual(pointage.status, "present")
        self.assertEqual(pointage.source, self.Attendance.SOURCE_LECTEUR)
        self.assertIsNotNone(pointage.heure_arrivee)

    def test_a_refused_passage_points_nobody(self):
        self._envoyer(employeeNoString=enrollment.numero_personnel(self.employe), subEventType=9)

        self.assertFalse(self.Attendance.objects.exists())

    def test_a_member_passage_points_nobody(self):
        self._envoyer(employeeNoString=enrollment.employee_no(self.member))

        self.assertFalse(self.Attendance.objects.exists())

    def test_the_catch_up_points_too(self):
        import io

        from django.core.management import call_command

        from .management.commands.rattraper_passages import Command

        evenements = [{
            "employeeNoString": enrollment.numero_personnel(self.employe),
            "minor": 75, "serialNo": "970",
            "time": timezone.localtime().replace(microsecond=0).isoformat(),
        }]
        with patch.object(Command, "_lire_evenements", return_value=evenements):
            call_command("rattraper_passages", stdout=io.StringIO())

        self.assertTrue(self.Attendance.objects.filter(employee=self.employe).exists())



class SensDuPassageTests(TestCase):
    """
    Un passage porte un sens : entree ou sortie.

    Tant qu'aucun lecteur de sortie n'existe et qu'aucune touche n'est pressee
    au terminal, tout reste une entree - c'est-a-dire ce que la salle vit
    aujourd'hui.
    """

    def setUp(self):
        from rh.models import Attendance

        self.Attendance = Attendance
        (self.gym, self.device, self.member, self.employe,
         _) = _salle_avec_personnel("sens")
        self.url = reverse("access:device_webhook", args=[self.device.webhook_token])
        patcher = patch("access.hikvision.HikvisionClient.open_door")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _envoyer(self, **evenement):
        charge = {"AccessControllerEvent": {"majorEventType": 5, "subEventType": 75, **evenement}}
        return self.client.post(self.url, data=json.dumps(charge), content_type="application/json")

    # --- Le sens lu ---------------------------------------------------------------------------

    def test_a_passage_is_an_entry_by_default(self):
        self._envoyer(employeeNoString=enrollment.numero_personnel(self.employe))

        self.assertEqual(AccessLog.objects.get().sens, AccessLog.SENS_ENTREE)

    def test_a_reader_declared_as_an_exit_records_exits(self):
        self.device.sens = AccessDevice.SENS_SORTIE
        self.device.save()

        self._envoyer(employeeNoString=enrollment.numero_personnel(self.employe))

        self.assertEqual(AccessLog.objects.get().sens, AccessLog.SENS_SORTIE)

    def test_the_terminal_key_decides_when_it_speaks(self):
        # Une touche pressee au terminal l'emporte sur le role du lecteur.
        self._envoyer(
            employeeNoString=enrollment.numero_personnel(self.employe),
            attendanceStatus="checkOut",
        )

        self.assertEqual(AccessLog.objects.get().sens, AccessLog.SENS_SORTIE)

    def test_an_unknown_key_leaves_the_reader_decide(self):
        self._envoyer(
            employeeNoString=enrollment.numero_personnel(self.employe),
            attendanceStatus="quelqueChose",
        )

        self.assertEqual(AccessLog.objects.get().sens, AccessLog.SENS_ENTREE)

    def test_a_member_passage_carries_the_direction_too(self):
        self.device.sens = AccessDevice.SENS_SORTIE
        self.device.save()
        plan = SubscriptionPlan.objects.create(gym=self.gym, name="Mensuel", price=30, duration_days=30)
        MemberSubscription.objects.create(
            gym=self.gym, member=self.member, plan=plan,
            start_date=timezone.localdate(), end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )

        self._envoyer(employeeNoString=enrollment.employee_no(self.member))

        self.assertEqual(AccessLog.objects.get(member=self.member).sens, AccessLog.SENS_SORTIE)

    # --- Les statistiques ------------------------------------------------------------------------

    def test_an_exit_is_not_a_visit(self):
        from .views import _today_stats

        AccessLog.objects.create(gym=self.gym, member=self.member, access_granted=True)
        AccessLog.objects.create(
            gym=self.gym, member=self.member, access_granted=True, sens=AccessLog.SENS_SORTIE
        )

        self.assertEqual(_today_stats(self.gym)["entries"], 1)

    def test_an_exit_does_not_count_as_staff_passage(self):
        from core.views import _personnel_passe

        AccessLog.objects.create(
            gym=self.gym, employee=self.employe, access_granted=True, sens=AccessLog.SENS_SORTIE
        )

        self.assertEqual(_personnel_passe(self.gym, timezone.localdate()), 0)

    def test_entering_then_leaving_within_the_minute_is_kept(self):
        # Deux lectures de sens contraire ne sont pas une relecture.
        numero = enrollment.numero_personnel(self.employe)
        self._envoyer(employeeNoString=numero, serialNo="1")
        self._envoyer(employeeNoString=numero, serialNo="2", attendanceStatus="checkOut")

        self.assertEqual(AccessLog.objects.count(), 2)

    # --- Le pointage --------------------------------------------------------------------------------

    def test_an_exit_fills_the_departure_hour(self):
        numero = enrollment.numero_personnel(self.employe)
        self._envoyer(employeeNoString=numero, serialNo="1")
        self._envoyer(employeeNoString=numero, serialNo="2", attendanceStatus="checkOut")

        pointage = self.Attendance.objects.get(employee=self.employe)
        self.assertIsNotNone(pointage.heure_arrivee)
        self.assertIsNotNone(pointage.heure_depart)


class VerificationDuPointageTests(TestCase):
    """La commande qui demande au terminal s'il sait marquer les sorties."""

    def setUp(self):
        (self.gym, self.device, _, _, _) = _salle_avec_personnel("verif-pointage")

    def _lancer(self, **patch_reponse):
        import io

        from django.core.management import call_command

        sortie = io.StringIO()
        with patch.object(hikvision.HikvisionClient, "request", **patch_reponse):
            call_command("verifier_pointage", stdout=sortie)
        return sortie.getvalue()

    def test_a_terminal_that_can_mark_exits_says_so(self):
        texte = self._lancer(return_value='{"AttendanceMode": {"mode": "manual"}}')

        self.assertIn("manual", texte)
        self.assertIn("marquer leur depart", texte)

    def test_a_disabled_function_is_named_as_such(self):
        texte = self._lancer(return_value='{"AttendanceMode": {"mode": "disable"}}')

        self.assertIn("desactivee", texte)

    def test_a_terminal_without_the_function_points_to_a_second_reader(self):
        texte = self._lancer(side_effect=hikvision.HikvisionError("404"))

        self.assertIn("second lecteur", texte)

    def test_the_declared_role_is_recalled(self):
        texte = self._lancer(return_value='{"AttendanceMode": {"mode": "manual"}}')

        self.assertIn("role declare dans l'application", texte)



class HistoriqueDesPassagesTests(TestCase):
    """
    L'historique se lit par periode, et se tourne.

    Il portait les 200 derniers passages sans le dire : la page annoncait
    "200 entrees" comme s'il n'y en avait que 200, et l'avant-veille etait
    hors d'atteinte.
    """

    def setUp(self):
        (self.gym, self.device, self.member, self.employe,
         _) = _salle_avec_personnel("historique")
        self.gerant = User.objects.create_user(username="gerant-historique", password="pass12345")
        UserGymRole.objects.create(user=self.gerant, gym=self.gym, role="manager", is_active=True)
        self.client.force_login(self.gerant)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()
        self.url = reverse("access:acces_dashboard")
        self.today = timezone.localdate()

    def _passages(self, combien, il_y_a_jours=0):
        crees = []
        for _ in range(combien):
            log = AccessLog.objects.create(
                gym=self.gym, member=self.member, access_granted=True
            )
            if il_y_a_jours:
                AccessLog.objects.filter(pk=log.pk).update(
                    check_in_time=timezone.now() - timedelta(days=il_y_a_jours)
                )
            crees.append(log)
        return crees

    def test_the_week_is_shown_by_default(self):
        self._passages(3)
        self._passages(2, il_y_a_jours=30)

        reponse = self.client.get(self.url)

        self.assertEqual(reponse.context["history_total"], 3)
        self.assertEqual(reponse.context["history_depuis"],
                         (self.today - timedelta(days=6)).isoformat())

    def test_an_older_period_can_be_asked_for(self):
        self._passages(2, il_y_a_jours=30)
        jour = (self.today - timedelta(days=30)).isoformat()

        reponse = self.client.get(self.url, {"date_from": jour, "date_to": jour})

        self.assertEqual(reponse.context["history_total"], 2)

    def test_a_long_day_is_cut_into_pages(self):
        self._passages(120)

        reponse = self.client.get(self.url)

        self.assertEqual(len(reponse.context["history_logs"]), 100)
        self.assertEqual(reponse.context["history_total"], 120)
        self.assertContains(reponse, "Suivante")

    def test_the_next_page_shows_the_rest(self):
        self._passages(120)

        reponse = self.client.get(self.url, {"page": "2"})

        self.assertEqual(len(reponse.context["history_logs"]), 20)

    def test_the_period_is_kept_when_turning_the_page(self):
        self._passages(120)
        jour = self.today.isoformat()

        reponse = self.client.get(self.url, {"date_from": jour, "date_to": jour})

        self.assertIn(f"date_from={jour}", reponse.context["filtres_conserves"])
        self.assertNotIn("page=", reponse.context["filtres_conserves"])

    def test_an_unreadable_date_falls_back_on_the_week(self):
        # L'adresse se modifie a la main : une date illisible ne doit pas
        # casser la page.
        self._passages(3)

        reponse = self.client.get(self.url, {"date_from": "hier", "date_to": ""})

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.context["history_total"], 3)

    def test_a_reversed_period_is_put_back_in_order(self):
        self._passages(2, il_y_a_jours=3)

        reponse = self.client.get(self.url, {
            "date_from": self.today.isoformat(),
            "date_to": (self.today - timedelta(days=5)).isoformat(),
        })

        self.assertEqual(reponse.context["history_total"], 2)

    def test_the_agents_come_from_the_accounts_not_the_journal(self):
        agent = User.objects.create_user(username="agent-historique", password="pass12345")
        UserGymRole.objects.create(user=agent, gym=self.gym, role="reception", is_active=True)
        for _ in range(5):
            AccessLog.objects.create(
                gym=self.gym, member=self.member, access_granted=True, scanned_by=agent
            )

        reponse = self.client.get(self.url)

        agents = list(reponse.context["history_agents"])
        self.assertEqual([a.username for a in agents], ["agent-historique"])



class InventaireDuLecteurTests(TestCase):
    """
    L'ecran dit ce que porte chaque fiche du lecteur, et permet de la liberer.

    Le lecteur ne connait que des numeros. Un visage refuse - "ce visage
    existe deja" - ne se retrouvait nulle part : les fiches membres etaient
    ecartees de la liste, et la fiche du membre n'apparait pas sur cet ecran.
    """

    def setUp(self):
        from .models import StaffReaderRecord

        self.Fiche = StaffReaderRecord
        (self.gym, self.device, self.member, self.employe,
         self.employe_voisin) = _salle_avec_personnel("inventaire")
        self.gerant = User.objects.create_user(username="gerant-inventaire", password="pass12345")
        UserGymRole.objects.create(user=self.gerant, gym=self.gym, role="manager", is_active=True)
        # Liberer un visage retire une fiche a quelqu'un d'autre : geste du
        # proprietaire. Le reste de l'ecran reste au gerant.
        self.proprietaire = User.objects.create_user(
            username="proprio-inventaire", password="pass12345"
        )
        UserGymRole.objects.create(
            user=self.proprietaire, gym=self.gym, role="owner", is_active=True
        )
        self._connecter(self.gerant)
        self.url = reverse("access:staff_face_enrollment", args=[self.employe.id])
        self.numero_membre = enrollment.employee_no(self.member)
        self.numero_employe = enrollment.numero_personnel(self.employe)
        _lecteur_sans_reste(self)

    def _connecter(self, utilisateur):
        self.client.force_login(utilisateur)
        session = self.client.session
        session["current_gym_id"] = self.gym.id
        session.save()

    def _lues(self):
        return [
            {"employeeNo": self.numero_membre, "name": "Kevin Tassa"},
            {"employeeNo": self.numero_employe, "name": "Paul Gardien"},
            {"employeeNo": "5", "name": "Gardien de nuit"},
        ]

    def _inventaire(self, recherche=""):
        from . import personnel

        with patch.object(hikvision.HikvisionClient, "list_users", return_value=self._lues()):
            return personnel.fiches_du_lecteur(self.gym, recherche)["fiches"]

    # --- Ce que porte chaque fiche ------------------------------------------------------------

    def test_every_record_says_what_it_holds(self):
        fiches = {fiche["numero"]: fiche for fiche in self._inventaire()}

        self.assertEqual(fiches[self.numero_membre]["nature"], "membre")
        self.assertIn("Alice", fiches[self.numero_membre]["porteur"])
        self.assertEqual(fiches[self.numero_employe]["nature"], "personnel")
        self.assertEqual(fiches[self.numero_employe]["porteur"], "Paul Gardien")
        self.assertEqual(fiches["5"]["nature"], "manuelle")

    def test_only_a_manual_record_can_be_attached(self):
        fiches = {fiche["numero"]: fiche for fiche in self._inventaire()}

        self.assertTrue(fiches["5"]["adoptable"])
        self.assertFalse(fiches[self.numero_membre]["adoptable"])
        self.assertFalse(fiches[self.numero_employe]["adoptable"])

    def test_a_deactivated_member_is_named_as_such(self):
        self.member.is_active = False
        self.member.save()

        fiches = {fiche["numero"]: fiche for fiche in self._inventaire()}

        self.assertIn("desactivee", fiches[self.numero_membre]["porteur"])

    def test_a_record_of_a_deleted_member_is_still_shown(self):
        # Le cas qui bloque un visage sans qu'on sache pourquoi.
        numero = str(enrollment.PLAGE_APPLICATION + 999_999)
        with patch.object(
            hikvision.HikvisionClient, "list_users",
            return_value=[{"employeeNo": numero, "name": "Inconnu"}],
        ):
            from . import personnel

            fiches = personnel.fiches_du_lecteur(self.gym)["fiches"]

        self.assertEqual(fiches[0]["nature"], "membre")
        self.assertIn("supprime", fiches[0]["porteur"])

    def test_the_attachable_list_keeps_only_manual_records(self):
        from . import personnel

        with patch.object(hikvision.HikvisionClient, "list_users", return_value=self._lues()):
            adoptables = personnel.fiches_du_terminal(self.gym)["fiches"]

        self.assertEqual([fiche["numero"] for fiche in adoptables], ["5"])

    def test_the_search_finds_a_member_record(self):
        fiches = self._inventaire("kevin")

        self.assertEqual([fiche["numero"] for fiche in fiches], [self.numero_membre])

    # --- L'ecran ---------------------------------------------------------------------------------

    def test_the_screen_shows_every_record_on_demand(self):
        self._connecter(self.proprietaire)

        with patch.object(hikvision.HikvisionClient, "list_users", return_value=self._lues()):
            reponse = self.client.get(self.url, {"fiches": "1"})

        self.assertContains(reponse, "Kevin Tassa")
        self.assertContains(reponse, "Fiche membre")
        self.assertContains(reponse, "Libérer")
        self.assertContains(reponse, reverse("access:staff_release_face", args=[self.employe.id]))

    # --- La commande ---------------------------------------------------------------------------------

    def _inspecter(self, lues=None, **options):
        import io

        from django.core.management import call_command

        sortie = io.StringIO()
        with patch.object(
            hikvision.HikvisionClient, "list_users",
            return_value=self._lues() if lues is None else lues,
        ):
            call_command("inspecter_lecteur", stdout=sortie, **options)
        return sortie.getvalue()

    def test_the_command_says_what_each_record_holds(self):
        texte = self._inspecter()

        self.assertIn("fiche membre", texte)
        self.assertIn("Alice", texte)
        self.assertIn("fiche du personnel", texte)
        self.assertIn("creee a la main", texte)

    def test_the_command_can_look_for_one_name(self):
        texte = self._inspecter(chercher="kevin")

        self.assertIn(self.numero_membre, texte)
        self.assertNotIn("Gardien de nuit", texte)

    def test_an_unreachable_reader_is_reported_by_the_command(self):
        import io

        from django.core.management import call_command

        sortie = io.StringIO()
        with patch.object(
            hikvision.HikvisionClient, "list_users",
            side_effect=hikvision.HikvisionUnreachable("cable arrache"),
        ):
            call_command("inspecter_lecteur", stdout=sortie)

        self.assertIn("injoignable", sortie.getvalue())

    # --- Liberer un visage --------------------------------------------------------------------------

    def test_releasing_a_record_removes_it_from_the_reader(self):
        self._connecter(self.proprietaire)

        with patch.object(hikvision.HikvisionClient, "delete_user") as retrait:
            reponse = self.client.post(
                reverse("access:staff_release_face", args=[self.employe.id]),
                {"device_id": self.device.id, "employee_no": self.numero_membre,
                 "porteur": "Kevin Tassa"},
                follow=True,
            )

        retrait.assert_called_once_with(self.numero_membre)
        self.assertContains(reponse, "Le visage est libere")
        trace = SensitiveActivityLog.objects.get(action="access.reader_record_released")
        self.assertEqual(trace.metadata["employee_no"], self.numero_membre)

    def test_releasing_also_forgets_an_attached_record(self):
        from . import personnel

        personnel.adopter_fiche(self.device, self.employe, "5")
        self._connecter(self.proprietaire)

        with patch.object(hikvision.HikvisionClient, "delete_user"):
            self.client.post(
                reverse("access:staff_release_face", args=[self.employe.id]),
                {"device_id": self.device.id, "employee_no": "5"},
            )

        self.assertFalse(self.Fiche.objects.filter(employee_no="5").exists())

    def test_an_unreachable_reader_says_so(self):
        self._connecter(self.proprietaire)

        with patch.object(
            hikvision.HikvisionClient, "delete_user",
            side_effect=hikvision.HikvisionUnreachable("cable"),
        ):
            reponse = self.client.post(
                reverse("access:staff_release_face", args=[self.employe.id]),
                {"device_id": self.device.id, "employee_no": "5"},
                follow=True,
            )

        self.assertContains(reponse, "injoignable")

    # --- Le refus du lecteur --------------------------------------------------------------------

    def _capturer_puis_valider(self, refus):
        with patch.object(
            hikvision.HikvisionClient, "capture_face", return_value=_image_jpeg()
        ):
            self.client.post(
                reverse("access:staff_face_capture", args=[self.employe.id]),
                {"device_id": self.device.id},
            )

        with patch.object(hikvision.HikvisionClient, "upsert_user"), patch.object(
            hikvision.HikvisionClient, "set_face", side_effect=hikvision.HikvisionError(refus)
        ):
            return self.client.post(
                reverse("access:staff_face_confirm", args=[self.employe.id]), follow=True
            )

    def test_a_face_already_taken_says_where_to_free_it(self):
        # Le message disait pourquoi le lecteur refusait, jamais ou aller.
        reponse = self._capturer_puis_valider(
            '{"subStatusCode": "alreadyExistThisFace"}'
        )

        self.assertContains(reponse, "deja enregistre sous une autre fiche")
        self.assertContains(reponse, "puis recommencez la capture")

    def test_another_refusal_keeps_its_own_message(self):
        reponse = self._capturer_puis_valider(
            '{"subStatusCode": "lowScoreOfFaceQuality"}'
        )

        self.assertContains(reponse, "contre-jour")
        # Le titre de la carte et le mot "reprenez-la" vivent deja sur la page :
        # on verifie la phrase propre au conseil.
        self.assertNotContains(reponse, "puis recommencez la capture")

    def test_a_manager_reads_the_records_but_cannot_release(self):
        # Le gerant garde la lecture, le rattachement et la bascule ; seule la
        # suppression d'une fiche lui echappe.
        with patch.object(hikvision.HikvisionClient, "list_users", return_value=self._lues()):
            reponse = self.client.get(self.url, {"fiches": "1"})

        self.assertContains(reponse, "Kevin Tassa")
        self.assertNotContains(reponse, "Libérer")

        with patch.object(hikvision.HikvisionClient, "delete_user") as retrait:
            refus = self.client.post(
                reverse("access:staff_release_face", args=[self.employe.id]),
                {"device_id": self.device.id, "employee_no": "5"},
            )

        self.assertIn(refus.status_code, (302, 403))
        retrait.assert_not_called()

    def test_a_receptionist_cannot_release(self):
        accueil = User.objects.create_user(username="accueil-inventaire", password="pass12345")
        UserGymRole.objects.create(user=accueil, gym=self.gym, role="reception", is_active=True)
        self._connecter(accueil)

        with patch.object(hikvision.HikvisionClient, "delete_user") as retrait:
            reponse = self.client.post(
                reverse("access:staff_release_face", args=[self.employe.id]),
                {"device_id": self.device.id, "employee_no": "5"},
            )

        self.assertIn(reponse.status_code, (302, 403))
        retrait.assert_not_called()

    def test_a_reader_of_another_gym_is_out_of_reach(self):
        self._connecter(self.proprietaire)
        ailleurs = AccessDevice.objects.create(
            gym=self.employe_voisin.gym, name="Ailleurs", host="10.0.0.8", password="secret"
        )

        reponse = self.client.post(
            reverse("access:staff_release_face", args=[self.employe.id]),
            {"device_id": ailleurs.id, "employee_no": "5"},
        )

        self.assertEqual(reponse.status_code, 404)

    # --- La bascule le dit ----------------------------------------------------------------------------

    def test_a_switch_warns_when_the_old_record_was_not_removed(self):
        from django.core.files.base import ContentFile

        membre = Member.objects.create(
            gym=self.gym, first_name="Kevin", last_name="Tassa", phone="+243821331784",
        )
        membre.photo.save(f"visage_membre_{membre.id}.jpg", ContentFile(_image_jpeg()), save=True)

        with patch.object(
            hikvision.HikvisionClient, "delete_user",
            side_effect=hikvision.HikvisionError("fiche verrouillee"),
        ), patch.object(hikvision.HikvisionClient, "upsert_user"), patch.object(
            hikvision.HikvisionClient, "set_face"
        ):
            reponse = self.client.post(
                reverse("access:staff_switch_from_member", args=[self.employe.id]),
                {"member_id": membre.id},
                follow=True,
            )

        self.assertContains(reponse, "n&#x27;a pas confirme la suppression")
        self.assertContains(reponse, "liberez la fiche")



class RetraitCompletDuneFicheTests(TestCase):
    """
    Supprimer une fiche du lecteur, vraiment.

    Trois pieges vus sur ce materiel : le visage survit a sa fiche dans la
    bibliotheque du lecteur ; l'ancienne commande repond "ok" sans rien
    effacer ; la commande recente travaille en tache de fond.
    """

    def setUp(self):
        (self.gym, self.device, self.member, self.employe,
         _) = _salle_avec_personnel("retrait-complet")
        self.numero = enrollment.employee_no(self.member)

    def _retirer(self, **patches):
        defauts = {
            "delete_face": {"return_value": None},
            "delete_user": {"return_value": None},
            "user_exists": {"return_value": False},
            "delete_user_detail": {"return_value": None},
        }
        defauts.update(patches)

        with patch.object(hikvision.HikvisionClient, "delete_face", **defauts["delete_face"]) as visage, \
             patch.object(hikvision.HikvisionClient, "delete_user", **defauts["delete_user"]) as fiche, \
             patch.object(hikvision.HikvisionClient, "user_exists", **defauts["user_exists"]) as presence, \
             patch.object(hikvision.HikvisionClient, "delete_user_detail", **defauts["delete_user_detail"]) as seconde:
            enrollment.retirer_fiche(self.device, self.numero)
        return visage, fiche, presence, seconde

    def test_the_face_is_removed_before_the_record(self):
        # Le visage vit dans une bibliotheque a part : le laisser la ferait
        # refuser tout nouvel enrolement, sans fiche pour l'expliquer.
        visage, fiche, _, _ = self._retirer()

        visage.assert_called_once_with(self.numero)
        fiche.assert_called_once_with(self.numero)

    def test_a_missing_face_does_not_stop_the_removal(self):
        visage, fiche, _, _ = self._retirer(
            delete_face={"side_effect": hikvision.HikvisionError("FDID introuvable")}
        )

        fiche.assert_called_once_with(self.numero)

    def test_a_record_that_survives_is_deleted_the_other_way(self):
        # L'ancienne commande repond "ok" sans rien faire : la fiche est
        # toujours la, on passe a la commande recente.
        _, _, _, seconde = self._retirer(user_exists={"side_effect": [True, False]})

        seconde.assert_called_once_with(self.numero)

    def test_a_record_that_never_leaves_is_said_plainly(self):
        with patch.object(hikvision.HikvisionClient, "delete_face"), patch.object(
            hikvision.HikvisionClient, "delete_user"
        ), patch.object(
            hikvision.HikvisionClient, "user_exists", return_value=True
        ), patch.object(hikvision.HikvisionClient, "delete_user_detail"):
            with self.assertRaises(enrollment.EnrollmentError) as capture:
                enrollment.retirer_fiche(self.device, self.numero)

        message = str(capture.exception)
        self.assertIn("toujours presente", message)
        self.assertIn("ecran", message)

    def test_an_unreachable_reader_is_named_as_such(self):
        with patch.object(
            hikvision.HikvisionClient, "delete_face",
            side_effect=hikvision.HikvisionUnreachable("cable arrache"),
        ):
            with self.assertRaises(enrollment.EnrollmentError) as capture:
                enrollment.retirer_fiche(self.device, self.numero)

        self.assertIn("injoignable", str(capture.exception))

    def test_the_reader_is_asked_whether_the_record_is_still_there(self):
        _, _, presence, _ = self._retirer()

        presence.assert_called_with(self.numero)



class ErreurDePasserelleTests(TestCase):
    """
    Un 502 rendu par le tunnel ne dit rien du lecteur.

    L'appel n'a jamais atteint le terminal. L'annoncer comme un refus faisait
    lire "le lecteur a refuse la fiche" pour un terminal simplement eteint, et
    laissait continuer des gestes qui n'avaient rien change.
    """

    def setUp(self):
        (self.gym, self.device, self.member, self.employe,
         _) = _salle_avec_personnel("passerelle")

    def _reponse_http(self, code, corps=b"error code: 502"):
        import io
        from unittest.mock import Mock
        from urllib.error import HTTPError

        erreur = HTTPError(
            url="https://tunnel.example/ISAPI/AccessControl/UserInfo/Modify?format=json",
            code=code, msg="Bad Gateway", hdrs=None, fp=io.BytesIO(corps),
        )
        return patch.object(
            hikvision.HikvisionClient, "_opener",
            return_value=Mock(open=Mock(side_effect=erreur)),
        )

    def _appeler(self, code):
        client = hikvision.HikvisionClient.from_device(self.device, timeout=1)
        with self._reponse_http(code):
            client.request("/ISAPI/AccessControl/UserInfo/Modify?format=json")

    # --- Le classement ---------------------------------------------------------------------

    def test_a_gateway_error_says_the_reader_never_answered(self):
        with self.assertRaises(hikvision.HikvisionUnreachable) as capture:
            self._appeler(502)

        message = str(capture.exception)
        self.assertIn("n'a pas repondu", message)
        self.assertIn("tunnel", message)

    def test_every_gateway_code_is_treated_the_same(self):
        for code in (502, 503, 504, 521, 524):
            with self.subTest(code=code):
                with self.assertRaises(hikvision.HikvisionUnreachable):
                    self._appeler(code)

    def test_a_real_refusal_stays_a_refusal(self):
        with self.assertRaises(hikvision.HikvisionError) as capture:
            self._appeler(400)

        self.assertNotIsInstance(capture.exception, hikvision.HikvisionUnreachable)
        self.assertIn("HTTP 400", str(capture.exception))

    # --- Ce que l'equipe lit ------------------------------------------------------------------

    def test_an_enrolment_says_the_reader_is_unreachable(self):
        with self._reponse_http(502):
            with self.assertRaises(enrollment.EnrollmentError) as capture:
                enrollment.inscrire_employe(self.device, self.employe)

        message = str(capture.exception)
        self.assertIn("injoignable", message)
        self.assertNotIn("a refuse la fiche", message)

    # --- Ce que l'application decide ---------------------------------------------------------------

    def test_a_switch_changes_nothing_when_the_tunnel_is_down(self):
        # Le retrait n'est pas passe : desactiver la fiche membre laisserait
        # un membre sans acces et un visage toujours sur le lecteur.
        from . import personnel

        with self._reponse_http(502):
            with self.assertRaises(enrollment.EnrollmentError):
                personnel.basculer_membre(self.employe, self.member)

        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)

    def test_a_departure_keeps_the_removal_pending(self):
        from . import personnel

        personnel.noter_inscription(self.device, self.employe)

        with self._reponse_http(502):
            resultat = personnel.retirer_des_lecteurs(self.employe)

        self.assertEqual(resultat["confirmees"], 0)
        self.assertEqual(len(resultat["restantes"]), 1)
        self.assertIn("injoignable", resultat["restantes"][0].derniere_erreur)

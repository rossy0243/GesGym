"""
Determine si un lecteur d'acces sait lire les QR codes.

    python manage.py verifier_qr

Interroge le lecteur enregistre, liste les modes d'authentification qu'il
declare reellement supporter, teste les endpoints ISAPI propres au QR, puis
conclut. Ne modifie rien sur l'appareil.
"""

import re

from django.core.management.base import BaseCommand, CommandError

from access import hikvision
from access.models import AccessDevice

# Endpoints connus pour exposer la configuration QR selon les gammes/firmwares.
QR_ENDPOINTS = (
    "/ISAPI/AccessControl/QRCodeConfig/capabilities?format=json",
    "/ISAPI/AccessControl/QRCodeCfg/capabilities?format=json",
    "/ISAPI/AccessControl/qrCodeCfg/capabilities?format=json",
    "/ISAPI/AccessControl/CodeConfig/capabilities?format=json",
)

VERIFY_MODE_PATTERN = re.compile(
    r'"(?:userVerifyMode|currentVerifyMode)"\s*:\s*\{\s*"@opt"\s*:\s*"([^"]+)"'
)

SEPARATOR = "=" * 62


class Command(BaseCommand):
    help = "Verifie si le lecteur d'acces sait lire les QR codes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--device",
            type=int,
            help="Identifiant du lecteur a interroger (le premier par defaut).",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=10,
            help="Delai d'attente reseau en secondes (10 par defaut).",
        )

    def handle(self, *args, **options):
        device = self._get_device(options.get("device"))
        client = hikvision.HikvisionClient.from_device(device, timeout=options["timeout"])

        self._device_info(client, device)

        modes = self._verify_modes(client)
        endpoints = self._qr_endpoints(client)

        self._verdict(modes, endpoints)

    # -- etapes -------------------------------------------------------------

    def _get_device(self, device_id):
        queryset = AccessDevice.objects.all()
        device = queryset.filter(id=device_id).first() if device_id else queryset.first()

        if device is None:
            raise CommandError(
                "Aucun lecteur enregistre dans l'application. "
                "Ajoute-le d'abord depuis Controle d'acces > Lecteurs."
            )
        return device

    def _device_info(self, client, device):
        try:
            info = client.device_info()
        except hikvision.HikvisionError as exc:
            raise CommandError(
                f"Lecteur {device.host} injoignable : {exc}\n"
                "Verifie qu'il est alimente, cable, et qu'aucun VPN ne bloque "
                "le reseau local."
            ) from exc

        self.stdout.write(f"Lecteur  : {device.name} ({device.host})")
        self.stdout.write(f"Modele   : {info['model']}")
        self.stdout.write(self.style.MIGRATE_HEADING(f"Firmware : {info['firmware']}"))
        self.stdout.write("")
        return info

    def _verify_modes(self, client):
        modes = ""
        for path in (
            "/ISAPI/AccessControl/UserInfo/capabilities?format=json",
            "/ISAPI/AccessControl/AcsEvent/capabilities?format=json",
        ):
            try:
                payload = client.request(path)
            except hikvision.HikvisionError:
                continue

            match = VERIFY_MODE_PATTERN.search(payload)
            if match:
                modes = match.group(1)
                break

        self.stdout.write("MODES D'AUTHENTIFICATION DECLARES PAR LE LECTEUR")
        self.stdout.write("-" * 62)
        if not modes:
            self.stdout.write("  (aucun mode lisible dans la reponse du lecteur)")
        for mode in sorted({item.strip() for item in modes.split(",") if item.strip()}):
            self.stdout.write(f"  {mode}")
        self.stdout.write("")
        return modes

    def _qr_endpoints(self, client):
        self.stdout.write("ENDPOINTS SPECIFIQUES AU QR CODE")
        self.stdout.write("-" * 62)

        available = []
        for path in QR_ENDPOINTS:
            try:
                client.request(path)
            except hikvision.HikvisionError as exc:
                self.stdout.write(f"  absent      {path}  ({exc})")
                continue
            self.stdout.write(self.style.SUCCESS(f"  DISPONIBLE  {path}"))
            available.append(path)

        self.stdout.write("")
        return available

    def _verdict(self, modes, endpoints):
        supported = "qr" in modes.lower() or bool(endpoints)

        self.stdout.write(SEPARATOR)
        if supported:
            self.stdout.write(
                self.style.SUCCESS("VERDICT : le lecteur SAIT lire les QR codes.")
            )
            self.stdout.write(
                "On peut lui faire lire directement le QR des membres, en plus"
            )
            self.stdout.write("du scan deja en place cote application.")
        else:
            self.stdout.write(
                self.style.WARNING(
                    "VERDICT : ce lecteur NE SAIT PAS lire les QR codes."
                )
            )
            self.stdout.write(
                "Le scan reste cote GesGym (webcam, telephone ou douchette) et"
            )
            self.stdout.write(
                "l'application commande l'ouverture - ce qui fonctionne deja."
            )
        self.stdout.write(SEPARATOR)

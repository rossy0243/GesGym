"""
Dit si un lecteur sait marquer les sorties.

Suivre les departs demande de distinguer une entree d'une sortie. Deux voies
existent : une touche sur le terminal avant le visage, quand le firmware
l'expose, ou un second lecteur pose a la sortie. Cette commande interroge le
materiel pour trancher, plutot que de commander un terminal pour rien.

    python manage.py verifier_pointage
"""

import json

from django.core.management.base import BaseCommand, CommandError

from access import hikvision
from access.models import AccessDevice

CHEMIN_POINTAGE = "/ISAPI/AccessControl/Configuration/attendanceMode?format=json"


class Command(BaseCommand):
    help = "Dit si les lecteurs savent marquer une sortie (pointage entree/sortie)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--lecteur", type=int, help="Ne verifier qu'un lecteur, par son identifiant."
        )

    def handle(self, *args, **options):
        lecteurs = AccessDevice.objects.filter(is_active=True).select_related("gym")
        if options["lecteur"]:
            lecteurs = lecteurs.filter(id=options["lecteur"])

        lecteurs = list(lecteurs)
        if not lecteurs:
            raise CommandError("Aucun lecteur actif.")

        for device in lecteurs:
            self._verifier(device)

    def _verifier(self, device):
        self.stdout.write(self.style.MIGRATE_HEADING(f"--- {device.name} ({device.host})"))
        self.stdout.write(f"    role declare dans l'application : {device.get_sens_display()}")

        try:
            client = hikvision.HikvisionClient.from_device(device, timeout=20)
            brut = client.request(CHEMIN_POINTAGE)
        except hikvision.HikvisionError as exc:
            self.stdout.write(
                self.style.WARNING(
                    f"    ce lecteur ne repond pas sur le pointage : {exc}\n"
                    "    Sans cette fonction, les departs demandent un second "
                    "lecteur pose a la sortie."
                )
            )
            return

        try:
            reglage = json.loads(brut)
        except (TypeError, ValueError):
            reglage = {}

        mode = str(
            (reglage.get("AttendanceMode") or reglage).get("mode", "") or ""
        ).strip()
        if not mode:
            self.stdout.write(
                self.style.WARNING(
                    "    le lecteur repond, mais n'annonce aucun mode de pointage. "
                    "Reponse brute :\n" f"    {brut[:300]}"
                )
            )
            return

        self.stdout.write(self.style.SUCCESS(f"    mode de pointage du terminal : {mode}"))
        if mode.lower() in {"disable", "disabled", "close"}:
            self.stdout.write(
                "    Le materiel sait marquer les sorties, mais la fonction est "
                "desactivee. A activer sur le terminal, puis relancer cette commande."
            )
        else:
            self.stdout.write(
                "    Les employes peuvent marquer leur depart au terminal : "
                "l'application le lira et remplira l'heure de sortie."
            )

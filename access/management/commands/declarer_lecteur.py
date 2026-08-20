"""
Apprend a un lecteur ou pousser ses evenements.

Sans cette declaration, un visage reconnu ouvre bien la porte mais n'apparait
nulle part : ni journal d'acces, ni frequentation, ni "dernier acces" sur la
fiche du membre. Le lecteur decide seul, l'application ne sait rien.

L'adresse annoncee doit etre joignable **depuis le lecteur** : celle du
serveur sur le reseau local, jamais 127.0.0.1. Elle est deduite de la route
reelle vers le lecteur, ce qui evite d'annoncer l'adresse d'un tunnel VPN.

A relancer a chaque changement d'adresse du serveur.
"""

from django.core.management.base import BaseCommand, CommandError

from access import enrollment, hikvision
from access.models import AccessDevice


class Command(BaseCommand):
    help = "Declare l'adresse de l'application aupres d'un lecteur."

    def add_arguments(self, parser):
        parser.add_argument(
            "--lecteur",
            type=int,
            help="Identifiant du lecteur. Par defaut : tous les lecteurs actifs.",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=8000,
            help="Port sur lequel le serveur ecoute (defaut : 8000).",
        )
        parser.add_argument(
            "--adresse",
            help=(
                "Force l'adresse annoncee au lecteur. A n'utiliser que si la "
                "detection automatique se trompe."
            ),
        )
        parser.add_argument(
            "--verifier",
            action="store_true",
            help="Affiche ce que le lecteur porte deja, sans rien modifier.",
        )

    def handle(self, *args, **options):
        lecteurs = AccessDevice.objects.filter(is_active=True).select_related("gym")
        if options["lecteur"]:
            lecteurs = lecteurs.filter(id=options["lecteur"])

        lecteurs = list(lecteurs)
        if not lecteurs:
            raise CommandError("Aucun lecteur actif enregistre.")

        for device in lecteurs:
            self.stdout.write(
                self.style.MIGRATE_HEADING(f"--- {device.name} ({device.host})")
            )
            try:
                self._traiter(device, options)
            except enrollment.EnrollmentError as exc:
                self.stdout.write(self.style.ERROR(f"    {exc}"))

    def _traiter(self, device, options):
        client = hikvision.HikvisionClient.from_device(device, timeout=25)

        try:
            actuel = client.get_event_notification(1)
        except hikvision.HikvisionUnreachable as exc:
            raise enrollment.EnrollmentError(
                f"Lecteur injoignable ({device.host}) : {exc}"
            ) from exc

        self.stdout.write(
            "    declaration actuelle : "
            + (
                f"{actuel['ip']}:{actuel['port']}{actuel['url']}"
                if actuel["url"]
                else self.style.WARNING("aucune")
            )
        )

        if options["verifier"]:
            return

        url = enrollment.declarer_application(
            device, options["port"], options["adresse"]
        )
        self.stdout.write(self.style.SUCCESS(f"    declaree : {url}"))

        relu = client.get_event_notification(1)
        self.stdout.write(
            f"    relue du lecteur : {relu['ip']}:{relu['port']}{relu['url']} "
            f"({relu['protocole']}, {relu['format']})"
        )
        self.stdout.write("")
        self.stdout.write(
            "    Le serveur doit ecouter sur cette adresse, pas seulement sur "
            "127.0.0.1.\n"
            "    Lancez-le avec .\\runserver_lan.ps1"
        )

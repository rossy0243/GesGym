"""
Apprend a un lecteur ou pousser ses evenements.

Sans cette declaration, un visage reconnu ouvre bien la porte mais n'apparait
nulle part : ni journal d'acces, ni frequentation, ni "dernier acces" sur la
fiche du membre. Le lecteur decide seul, l'application ne sait rien.

Le lecteur retient **deux destinations**, et les deux servent :

1. le serveur du reseau local, deduit de la route reelle vers le lecteur, ce
   qui evite d'annoncer l'adresse d'un tunnel VPN. A relancer a chaque
   changement d'adresse du serveur ;
2. le serveur public (``--public``), que le lecteur atteint tout seul en
   sortant vers internet. Cette destination-la ne bouge jamais, et fonctionne
   meme quand aucune machine de la salle n'est allumee.
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
            help="Port sur lequel le serveur local ecoute (defaut : 8000).",
        )
        parser.add_argument(
            "--adresse",
            help=(
                "Force l'adresse locale annoncee au lecteur. A n'utiliser que "
                "si la detection automatique se trompe."
            ),
        )
        parser.add_argument(
            "--public",
            help=(
                "URL complete du webhook sur le serveur public, copiee depuis "
                "la fiche du lecteur de l'application en ligne. Ecrite dans la "
                "seconde destination, sans toucher a la premiere."
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
            self._afficher(client, enrollment.EMPLACEMENT_LOCAL, "local")
            self._afficher(client, enrollment.EMPLACEMENT_PUBLIC, "public")
        except hikvision.HikvisionUnreachable as exc:
            raise enrollment.EnrollmentError(
                f"Lecteur injoignable ({device.host}) : {exc}"
            ) from exc

        if options["verifier"]:
            return

        if options["public"]:
            self._declarer_public(device, client, options["public"])
        else:
            self._declarer_local(device, client, options)

    # --- Les deux destinations ------------------------------------------------

    def _declarer_local(self, device, client, options):
        url = enrollment.declarer_application(
            device, options["port"], options["adresse"]
        )
        self.stdout.write(self.style.SUCCESS(f"    destination locale : {url}"))
        self._afficher(client, enrollment.EMPLACEMENT_LOCAL, "relue")
        self.stdout.write("")
        self.stdout.write(
            "    Le serveur doit ecouter sur cette adresse, pas seulement sur "
            "127.0.0.1.\n"
            "    Lancez-le avec .\runserver_lan.ps1"
        )

    def _declarer_public(self, device, client, url):
        # Le jeton de production differe de celui de la base locale : l'URL est
        # donnee telle quelle plutot que reconstruite, pour ne pas viser une
        # fiche qui n'existe que sur cette machine.
        if "/access/devices/webhook/" not in url:
            raise enrollment.EnrollmentError(
                "L'URL publique doit etre celle du webhook du lecteur, copiee "
                "depuis sa fiche dans l'application en ligne."
            )

        enrollment.declarer_url(device, url, emplacement=enrollment.EMPLACEMENT_PUBLIC)
        self.stdout.write(self.style.SUCCESS(f"    destination publique : {url}"))
        self._afficher(client, enrollment.EMPLACEMENT_PUBLIC, "relue")
        self.stdout.write("")
        self.stdout.write(
            "    La destination locale n'a pas ete touchee : le lecteur pousse\n"
            "    desormais vers les deux."
        )

    def _afficher(self, client, emplacement, etiquette):
        actuel = client.get_event_notification(emplacement)
        if actuel["url"]:
            detail = (
                f"{actuel['protocole'].lower()}://{actuel['hote']}:"
                f"{actuel['port']}{actuel['url']}"
            )
        else:
            detail = self.style.WARNING("aucune")
        self.stdout.write(f"    [{emplacement}] {etiquette:<7} : {detail}")

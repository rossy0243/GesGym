"""
Interroge un lecteur sur ce qu'il sait faire, avant d'ecrire du code pour lui.

Les terminaux Hikvision partagent le protocole ISAPI mais pas les memes
fonctions : selon le modele et le firmware, la bibliotheque de visages,
l'enrolement par photo ou la remontee d'evenements n'existent pas au meme
endroit, voire pas du tout. Deviner mene a du code qui echoue sur site.

Cette commande ne modifie rien sur le materiel : elle ne fait que lire.
"""

from django.core.management.base import BaseCommand, CommandError

from access import hikvision
from access.models import AccessDevice


# Chemins interroges. Un 404 est une reponse utile : il dit que la fonction
# n'existe pas sur ce firmware.
SONDAGES = (
    ("Identite", "/ISAPI/System/deviceInfo", "GET", None),
    ("Capacites de controle d'acces", "/ISAPI/AccessControl/capabilities", "GET", None),
    ("Capacites des fiches utilisateur", "/ISAPI/AccessControl/UserInfo/capabilities?format=json", "GET", None),
    ("Nombre de fiches enregistrees", "/ISAPI/AccessControl/UserInfo/Count?format=json", "GET", None),
    ("Bibliotheque de visages", "/ISAPI/Intelligent/FDLib?format=json", "GET", None),
    ("Capacites de la bibliotheque de visages", "/ISAPI/Intelligent/FDLib/capabilities?format=json", "GET", None),
    ("Capacites d'enrolement du visage", "/ISAPI/AccessControl/CaptureFaceData/capabilities?format=json", "GET", None),
    ("Notification HTTP declaree", "/ISAPI/Event/notification/httpHosts", "GET", None),
    ("Capacites de notification", "/ISAPI/Event/notification/httpHosts/capabilities", "GET", None),
    ("Modes de verification", "/ISAPI/AccessControl/Door/param/1", "GET", None),
)


class Command(BaseCommand):
    help = "Lit les capacites d'un lecteur enregistre, sans rien y modifier."

    def add_arguments(self, parser):
        parser.add_argument(
            "--lecteur",
            type=int,
            help="Identifiant du lecteur. Par defaut : le seul lecteur actif.",
        )
        parser.add_argument(
            "--complet",
            action="store_true",
            help="Affiche la reponse entiere au lieu des 600 premiers caracteres.",
        )

    def handle(self, *args, **options):
        device = self._lecteur(options.get("lecteur"))

        self.stdout.write(f"Lecteur : {device.name}")
        self.stdout.write(f"Adresse : {device.host}:{device.port}")
        self.stdout.write(f"Salle   : {device.gym.name}")
        self.stdout.write("")

        client = hikvision.HikvisionClient.from_device(device)
        limite = None if options["complet"] else 600

        for libelle, chemin, methode, corps in SONDAGES:
            self.stdout.write(self.style.MIGRATE_HEADING(f"--- {libelle}"))
            self.stdout.write(f"    {methode} {chemin}")
            try:
                reponse = client.request(chemin, method=methode, body=corps)
            except hikvision.HikvisionAuthError as exc:
                self.stdout.write(self.style.ERROR(f"    identifiants refuses : {exc}"))
                raise CommandError("Mot de passe du lecteur incorrect : rien d'autre ne marchera.")
            except hikvision.HikvisionUnreachable as exc:
                self.stdout.write(self.style.ERROR(f"    injoignable : {exc}"))
                raise CommandError(
                    "Lecteur injoignable. Si Proton VPN tourne, quittez-le : "
                    "son filtrage bloque le reseau local."
                )
            except hikvision.HikvisionError as exc:
                # Un 403 ou 404 renseigne autant qu'un succes.
                self.stdout.write(self.style.WARNING(f"    non disponible : {exc}"))
                continue

            texte = " ".join(reponse.split())
            if limite and len(texte) > limite:
                texte = texte[:limite] + f"... (+{len(texte) - limite} caracteres)"
            self.stdout.write(f"    {texte}")
            self.stdout.write("")

    def _lecteur(self, identifiant):
        queryset = AccessDevice.objects.select_related("gym")

        if identifiant:
            try:
                return queryset.get(id=identifiant)
            except AccessDevice.DoesNotExist:
                raise CommandError(f"Aucun lecteur numero {identifiant}.")

        actifs = list(queryset.filter(is_active=True))
        if not actifs:
            raise CommandError("Aucun lecteur actif enregistre.")
        if len(actifs) > 1:
            noms = ", ".join(f"{d.id}={d.name}" for d in actifs)
            raise CommandError(f"Plusieurs lecteurs actifs, precisez --lecteur : {noms}")
        return actifs[0]

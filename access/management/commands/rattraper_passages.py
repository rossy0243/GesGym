"""
Recupere les passages que le lecteur n'a pas pu remonter.

Le lecteur decide seul a la porte et pousse ensuite l'evenement a
l'application. Quand le lien est coupe — panne de courant, tunnel tombe,
Internet absent — la porte continue de s'ouvrir mais plus rien n'arrive au
journal. La frequentation de la journee serait perdue.

Le materiel garde pourtant ses evenements dans sa propre memoire. Cette
commande les relit et recree ce qui manque.

Elle ne cree jamais deux fois le meme passage : chaque evenement porte un
numero, conserve sur la ligne du journal. A lancer apres une coupure, ou
chaque nuit par precaution.
"""

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from access import enrollment, hikvision
from access.models import AccessDevice, AccessLog
from members.models import Member

# Codes d'evenement correspondant a une authentification acceptee.
MINORS_ACCES_ACCORDE = frozenset({1, 8, 38, 75})


class Command(BaseCommand):
    help = "Recupere dans le lecteur les passages absents du journal."

    def add_arguments(self, parser):
        parser.add_argument(
            "--lecteur",
            type=int,
            help="Identifiant du lecteur. Par defaut : tous les lecteurs actifs.",
        )
        parser.add_argument(
            "--jours",
            type=int,
            default=2,
            help="Profondeur de relecture, en jours (defaut : 2).",
        )
        parser.add_argument(
            "--simulation",
            action="store_true",
            help="Montre ce qui serait recree, sans rien ecrire.",
        )

    def handle(self, *args, **options):
        lecteurs = AccessDevice.objects.filter(is_active=True).select_related("gym")
        if options["lecteur"]:
            lecteurs = lecteurs.filter(id=options["lecteur"])

        lecteurs = list(lecteurs)
        if not lecteurs:
            raise CommandError("Aucun lecteur actif.")

        if options["simulation"]:
            self.stdout.write(self.style.WARNING("Simulation : rien ne sera ecrit.\n"))

        for device in lecteurs:
            self._traiter(device, options["jours"], options["simulation"])

    def _traiter(self, device, jours, simulation):
        self.stdout.write(self.style.MIGRATE_HEADING(f"--- {device.name} ({device.host})"))

        try:
            evenements = self._lire_evenements(device, jours)
        except hikvision.HikvisionError as exc:
            self.stdout.write(self.style.ERROR(f"    injoignable : {exc}"))
            return

        self.stdout.write(f"    {len(evenements)} evenement(s) nominatif(s) dans le lecteur")

        # Numeros deja journalises : on ne recree pas ce qui existe.
        connus = set(
            AccessLog.objects.filter(device=device)
            .exclude(device_event_id="")
            .values_list("device_event_id", flat=True)
        )

        recrees = 0
        ignores = 0
        inconnus = 0

        for evenement in evenements:
            numero = str(evenement.get("serialNo") or "")
            if not numero or numero in connus:
                ignores += 1
                continue

            member_id = enrollment.member_id_depuis(evenement.get("employeeNoString"))
            if member_id is None:
                # Badge du personnel, fiche creee a la main : pas un membre.
                inconnus += 1
                continue

            member = Member.objects.filter(id=member_id, gym=device.gym).first()
            if member is None:
                inconnus += 1
                continue

            horodatage = self._horodatage(evenement.get("time"))
            if horodatage is None:
                ignores += 1
                continue

            if simulation:
                self.stdout.write(
                    f"    [simulation] {horodatage:%d/%m %H:%M} "
                    f"{member.first_name} {member.last_name}"
                )
                recrees += 1
                continue

            self._recreer(device, member, evenement, numero, horodatage)
            recrees += 1

        self.stdout.write(
            f"    {recrees} passage(s) recupere(s), {ignores} deja connu(s), "
            f"{inconnus} hors membres"
        )

    def _lire_evenements(self, device, jours):
        """Evenements nominatifs de la memoire du lecteur, du plus ancien au plus recent."""
        import json

        client = hikvision.HikvisionClient.from_device(device, timeout=25)
        fin = timezone.localtime()
        debut = fin - timedelta(days=jours)

        corps = {
            "AcsEventCond": {
                "searchID": "rattrapage",
                "searchResultPosition": 0,
                "maxResults": 200,
                "major": 5,
                "minor": 0,
                "startTime": debut.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "endTime": fin.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
        }
        brut = client.request(
            "/ISAPI/AccessControl/AcsEvent?format=json",
            method="POST",
            body=json.dumps(corps),
            content_type="application/json",
        )
        liste = json.loads(brut).get("AcsEvent", {}).get("InfoList", []) or []

        return [e for e in liste if e.get("employeeNoString")]

    def _horodatage(self, valeur):
        """Date de l'evenement, telle que le lecteur l'a datee."""
        if not valeur:
            return None
        try:
            return datetime.fromisoformat(str(valeur))
        except ValueError:
            return None

    def _recreer(self, device, member, evenement, numero, horodatage):
        """
        Recree la ligne de journal telle que le passage s'est produit.

        On enregistre ce qui a eu lieu a la porte, pas ce que l'application
        aurait decide : le lecteur a ouvert, la personne est entree.
        """
        par_le_visage = hikvision.est_un_visage(evenement)
        methode = f"{device.name} (visage)" if par_le_visage else f"{device.name} (badge)"

        deja_entre = AccessLog.objects.filter(
            gym=device.gym,
            member=member,
            access_granted=True,
            is_return=False,
            check_in_time__date=horodatage.date(),
        ).exists()

        log = AccessLog.objects.create(
            gym=device.gym,
            member=member,
            device=device,
            device_used=f"{methode} - rattrapage",
            device_event_id=numero,
            access_granted=True,
            is_return=deja_entre,
            denial_reason="Retour dans la salle" if deja_entre else "",
        )

        # check_in_time est auto_now_add : il faut le corriger apres coup pour
        # que le passage apparaisse a l'heure ou il a reellement eu lieu.
        AccessLog.objects.filter(pk=log.pk).update(check_in_time=horodatage)
        return log

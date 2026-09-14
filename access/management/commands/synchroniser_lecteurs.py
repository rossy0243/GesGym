"""
Reporte l'etat des membres sur les lecteurs a reconnaissance faciale.

Le lecteur decide seul a la porte, a partir des dates de validite qu'il porte.
L'application les lui pousse a chaque encaissement ou suspension, mais un
lecteur eteint ou hors reseau a ce moment-la reste sur l'etat precedent.

Cette commande rattrape l'ecart. A lancer periodiquement, par exemple chaque
nuit, et apres toute coupure reseau.

Elle ne touche qu'aux fiches posees par l'application : les fiches saisies a
la main sur le terminal (badges du personnel, visiteurs) ne sont jamais
modifiees ni supprimees.
"""

from django.core.management.base import BaseCommand, CommandError

from access import enrollment, hikvision
from access.models import AccessDevice
from members.models import Member


class Command(BaseCommand):
    help = "Met a jour les fiches membres sur les lecteurs de controle d'acces."

    def add_arguments(self, parser):
        parser.add_argument(
            "--lecteur",
            type=int,
            help="Ne traiter qu'un lecteur, par son identifiant.",
        )
        parser.add_argument(
            "--simulation",
            action="store_true",
            help="Montre ce qui serait fait, sans rien modifier.",
        )
        parser.add_argument(
            "--purger",
            action="store_true",
            help=(
                "Retire aussi du lecteur les fiches applicatives dont le membre "
                "n'existe plus en base."
            ),
        )

    def handle(self, *args, **options):
        lecteurs = AccessDevice.objects.filter(is_active=True).select_related("gym")
        if options["lecteur"]:
            lecteurs = lecteurs.filter(id=options["lecteur"])

        lecteurs = list(lecteurs)
        if not lecteurs:
            raise CommandError("Aucun lecteur actif a synchroniser.")

        simulation = options["simulation"]
        if simulation:
            self.stdout.write(self.style.WARNING("Simulation : rien ne sera modifie.\n"))

        for device in lecteurs:
            self._traiter(device, simulation, options["purger"])

    def _traiter(self, device, simulation, purger):
        self.stdout.write(self.style.MIGRATE_HEADING(f"--- {device.name} ({device.host})"))

        try:
            client = hikvision.HikvisionClient.from_device(device, timeout=25)
            avant = client.user_count()
            fiches = client.list_users()
        except hikvision.HikvisionError as exc:
            self.stdout.write(self.style.ERROR(f"    injoignable : {exc}"))
            device.last_error = str(exc)[:255]
            device.save(update_fields=["last_error", "updated_at"])
            return

        self.stdout.write(
            f"    etat du lecteur : {avant['users']} fiche(s), {avant['faces']} visage(s)"
        )

        # Fiches posees par l'application, reconnues a leur plage d'identifiants.
        posees = {}
        for fiche in fiches:
            member_id = enrollment.member_id_depuis(fiche.get("employeeNo"))
            if member_id is not None:
                posees[member_id] = fiche

        membres = Member.objects.filter(gym=device.gym).select_related("gym")

        mis_a_jour = 0
        echecs = 0
        ignores = 0

        for member in membres:
            # Sans visage sur le lecteur, il n'y a rien a tenir a jour : le
            # membre n'a jamais ete enrole.
            if member.id not in posees:
                ignores += 1
                continue

            if simulation:
                sub = member.active_subscription
                echeance = sub.end_date.strftime("%d/%m/%Y") if sub else "aucun abonnement"
                self.stdout.write(f"    [simulation] {member.first_name} {member.last_name} -> {echeance}")
                mis_a_jour += 1
                continue

            try:
                enrollment.inscrire_membre(device, member)
                mis_a_jour += 1
            except enrollment.EnrollmentError as exc:
                echecs += 1
                self.stdout.write(
                    self.style.ERROR(f"    {member.first_name} {member.last_name} : {exc}")
                )

        self.stdout.write(
            f"    {mis_a_jour} fiche(s) rafraichie(s), {ignores} membre(s) sans visage enrole"
        )
        if echecs:
            self.stdout.write(self.style.ERROR(f"    {echecs} echec(s)"))

        self._rafraichir_personnel(device, fiches, simulation)

        if purger:
            self._purger(device, client, posees, membres, simulation)

        if not simulation:
            device.last_error = ""
            device.save(update_fields=["last_error", "updated_at"])

    def _rafraichir_personnel(self, device, fiches, simulation):
        """
        Tient a jour les fiches du personnel et acheve les retraits demandes.

        * un retrait en attente dont la fiche a disparu du lecteur est confirme ;
        * un retrait en attente dont la fiche est encore la est retente ;
        * un employe desactive encore present est retire ;
        * un employe actif present est rafraichi, et note s'il ne l'etait pas.

        La synchronisation n'inscrit personne de nouveau.
        """
        from django.utils import timezone

        from access import personnel
        from access.models import StaffReaderRecord
        from rh.models import Employee

        # Tous les numeros du lecteur : une fiche adoptee garde son petit numero,
        # et la croire absente confirmerait a tort son retrait.
        presents = {
            str(fiche.get("employeeNo") or "").strip()
            for fiche in fiches
        } - {""}

        # Une fiche adoptee suit la regle commune : employe desactive, retrait
        # demande - meme si la desactivation n'est pas passee par l'ecran RH.
        if not simulation:
            StaffReaderRecord.objects.filter(
                device=device, retrait_demande_le__isnull=True, employee__is_active=False
            ).update(retrait_demande_le=timezone.now())

        confirmes = 0
        retires = 0
        echecs = 0
        traites = set()

        for fiche in StaffReaderRecord.objects.filter(
            device=device, retrait_demande_le__isnull=False
        ).select_related("device"):
            traites.add(fiche.employee_no)
            if simulation:
                self.stdout.write(f"    [simulation] retrait en attente : {fiche.nom or fiche.employee_no}")
                continue
            if fiche.employee_no not in presents:
                fiche.delete()
                confirmes += 1
            elif personnel.tenter(fiche):
                retires += 1
            else:
                echecs += 1
                self.stdout.write(self.style.ERROR(f"    retrait de {fiche.nom} : {fiche.derniere_erreur}"))

        identifiants = {enrollment.employee_id_depuis(numero) for numero in presents} - {None}
        rafraichis = 0
        for employe in Employee.objects.filter(gym=device.gym, id__in=identifiants):
            numero = enrollment.numero_personnel(employe)
            if numero in traites:
                continue

            if not employe.is_active:
                if simulation:
                    self.stdout.write(f"    [simulation] retrait de {employe.name} (desactive)")
                    continue
                fiche = StaffReaderRecord(
                    gym=device.gym, device=device, employee=employe,
                    employee_no=numero, nom=(employe.name or "")[:255],
                )
                if personnel.tenter(fiche):
                    retires += 1
                else:
                    echecs += 1
                    self.stdout.write(self.style.ERROR(f"    retrait de {employe.name} : {fiche.derniere_erreur}"))
                continue

            if simulation:
                self.stdout.write(f"    [simulation] personnel : {employe.name}")
                rafraichis += 1
                continue
            try:
                enrollment.inscrire_employe(device, employe)
                personnel.noter_inscription(device, employe)
                rafraichis += 1
            except enrollment.EnrollmentError as exc:
                echecs += 1
                self.stdout.write(self.style.ERROR(f"    {employe.name} : {exc}"))

        if rafraichis or retires or confirmes or echecs:
            self.stdout.write(
                f"    personnel : {rafraichis} rafraichi(s), {retires + confirmes} retrait(s) "
                f"confirme(s), {echecs} echec(s)"
            )

    def _purger(self, device, client, posees, membres, simulation):
        """Retire les fiches applicatives dont le membre a disparu de la base."""
        vivants = set(membres.values_list("id", flat=True))
        orphelines = [mid for mid in posees if mid not in vivants]

        if not orphelines:
            self.stdout.write("    aucune fiche orpheline")
            return

        for member_id in orphelines:
            numero = str(enrollment.PLAGE_APPLICATION + member_id)
            if simulation:
                self.stdout.write(f"    [simulation] retrait de la fiche {numero}")
                continue
            try:
                client.delete_user(numero)
                self.stdout.write(f"    fiche orpheline {numero} retiree")
            except hikvision.HikvisionError as exc:
                self.stdout.write(self.style.ERROR(f"    retrait de {numero} impossible : {exc}"))

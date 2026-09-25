"""
Dit ce que chaque lecteur porte, et a qui chaque fiche correspond.

Le lecteur ne connait que des numeros. Quand il refuse un visage - "ce visage
existe deja" - cette commande dit ou ce visage se trouve : sur une fiche
membre, sur une fiche du personnel, ou sur une fiche creee a la main. C'est la
meme lecture que l'ecran d'enrolement, utilisable quand l'ecran n'est pas a
portee.

    python manage.py inspecter_lecteur
    python manage.py inspecter_lecteur --chercher kevin
"""

from django.core.management.base import BaseCommand, CommandError

from access import personnel
from organizations.models import Gym

LIBELLES = {
    "membre": "fiche membre",
    "personnel": "fiche du personnel",
    "manuelle": "creee a la main",
}


class Command(BaseCommand):
    help = "Liste les fiches presentes sur les lecteurs et dit a qui elles correspondent."

    def add_arguments(self, parser):
        parser.add_argument("--salle", type=int, help="Identifiant de la salle.")
        parser.add_argument(
            "--chercher", default="", help="Nom ou numero a retrouver dans les fiches."
        )

    def handle(self, *args, **options):
        salles = Gym.objects.filter(is_active=True)
        if options["salle"]:
            salles = salles.filter(id=options["salle"])

        salles = list(salles)
        if not salles:
            raise CommandError("Aucune salle active.")

        for gym in salles:
            inventaire = personnel.fiches_du_lecteur(gym, options["chercher"])
            if not inventaire["fiches"] and not inventaire["erreurs"]:
                continue

            self.stdout.write(self.style.MIGRATE_HEADING(f"--- {gym.name}"))
            for erreur in inventaire["erreurs"]:
                self.stdout.write(self.style.ERROR(f"    injoignable : {erreur}"))

            for fiche in inventaire["fiches"]:
                nature = LIBELLES.get(fiche["nature"], fiche["nature"])
                porteur = f" - {fiche['porteur']}" if fiche["porteur"] else ""
                self.stdout.write(
                    f"    n {fiche['numero']:<10} {fiche['nom'][:30]:<32} {nature}{porteur}"
                )

            self.stdout.write(f"    {len(inventaire['fiches'])} fiche(s) lue(s)")

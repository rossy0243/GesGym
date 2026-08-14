"""
Rassemble tout ce qu'il faut savoir sur un module pour en ecrire la formation.

Le but n'est pas de generer le document : une doc produite mecaniquement a
partir du code donne un catalogue de fonctions, pas une formation. Cette
commande produit le *dossier* que Claude lira ensuite pour rediger : les
parcours, les regles metier, les droits, les messages vus par l'utilisateur,
les garde-fous et les cas limites deja couverts par les tests.

    python manage.py dossier_module membres
    python manage.py dossier_module --tous --dossier docs/formation
"""

import ast
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Un module tel que le voit un utilisateur ne correspond pas toujours a une
# application Django : on nomme les choses comme dans l'interface.
MODULES = {
    "membres": {
        "titre": "Membres",
        "apps": ["members"],
        "resume": "Fiches membres, preinscriptions, cartes, portail du membre.",
    },
    "abonnements": {
        "titre": "Abonnements",
        "apps": ["subscriptions"],
        "resume": "Formules, offres, souscriptions et renouvellements.",
    },
    "caisse": {
        "titre": "Caisse et paiements",
        "apps": ["pos"],
        "resume": "Ouverture et cloture de caisse, encaissements, depenses.",
    },
    "acces": {
        "titre": "Controle d'acces",
        "apps": ["access"],
        "resume": "Scan QR, pointage manuel, lecteurs physiques, journal d'entrees.",
    },
    "coaching": {
        "titre": "Coaching",
        "apps": ["coaching"],
        "resume": "Coachs, affectations, programmes de groupe, portail coach.",
    },
    "machines": {
        "titre": "Machines",
        "apps": ["machines"],
        "resume": "Parc de machines, maintenances et couts associes.",
    },
    "produits": {
        "titre": "Produits et stock",
        "apps": ["products"],
        "resume": "Catalogue, mouvements de stock, ventes au comptoir.",
    },
    "rh": {
        "titre": "Ressources humaines",
        "apps": ["rh"],
        "resume": "Employes, pointage, paie et circuit de validation.",
    },
    "messages": {
        "titre": "Messages membres",
        "apps": ["notifications"],
        "resume": "Envois groupes vers l'espace membre, annulation, suppression.",
    },
    "rapports": {
        "titre": "Rapports comptables",
        "apps": ["core"],
        "fichiers": ["accounting_reports.py"],
        "resume": "Journal comptable, periodes, exports CSV et XLSX.",
    },
    "parametres": {
        "titre": "Parametres et journal sensible",
        "apps": ["core"],
        "fichiers": ["views.py", "forms.py", "activity_log.py", "audit.py"],
        "resume": "Organisation, employes internes, specialites, journal d'audit.",
    },
    "compte": {
        "titre": "Comptes et connexion",
        "apps": ["compte"],
        "resume": "Connexion, profil, changement de mot de passe, roles.",
    },
}

GARDES = {
    "login_required": "connexion obligatoire",
    "require_POST": "envoi de formulaire uniquement",
    "csrf_exempt": "hors protection CSRF (appel machine)",
    "role_required": "roles autorises",
    "module_required": "module actif requis",
}


class Command(BaseCommand):
    help = (
        "Rassemble le materiau d'un module (parcours, regles, droits, messages) "
        "afin d'en rediger la formation."
    )

    def add_arguments(self, parser):
        parser.add_argument("module", nargs="?", help=f"Un parmi : {', '.join(MODULES)}")
        parser.add_argument("--tous", action="store_true", help="Traite tous les modules.")
        parser.add_argument(
            "--dossier",
            help="Ecrit un fichier Markdown par module dans ce repertoire.",
        )
        parser.add_argument(
            "--liste", action="store_true", help="Affiche les modules disponibles."
        )

    def handle(self, *args, **options):
        if options["liste"]:
            for cle, config in MODULES.items():
                self.stdout.write(f"  {cle:<14} {config['titre']} - {config['resume']}")
            return

        if options["tous"]:
            cibles = list(MODULES)
        elif options["module"]:
            if options["module"] not in MODULES:
                raise CommandError(
                    f"Module inconnu : {options['module']}. "
                    f"Disponibles : {', '.join(MODULES)}"
                )
            cibles = [options["module"]]
        else:
            raise CommandError("Indiquez un module, ou --tous, ou --liste.")

        destination = Path(options["dossier"]) if options["dossier"] else None
        if destination:
            destination.mkdir(parents=True, exist_ok=True)

        for cle in cibles:
            contenu = self._dossier(cle)
            if destination:
                chemin = destination / f"dossier-{cle}.md"
                chemin.write_text(contenu, encoding="utf-8")
                self.stdout.write(self.style.SUCCESS(f"Ecrit : {chemin}"))
            else:
                self.stdout.write(contenu)

    # -- Assemblage -----------------------------------------------------------

    def _dossier(self, cle):
        config = MODULES[cle]
        racine = Path(settings.BASE_DIR)
        fichiers = self._fichiers_python(racine, config)

        lignes = [
            f"# Dossier de formation - {config['titre']}",
            "",
            f"> {config['resume']}",
            "",
            "Ce dossier rassemble la matiere brute du module. Il sert a rediger la",
            "formation : il n'en est pas une. Les intitules proviennent du code, donc",
            "de ce que le logiciel fait reellement, pas de ce qu'on croit qu'il fait.",
            "",
        ]

        lignes += self._section_parcours(racine, config)
        lignes += self._section_donnees(fichiers)
        lignes += self._section_droits(fichiers)
        lignes += self._section_regles(fichiers)
        lignes += self._section_messages(fichiers)
        lignes += self._section_audit(fichiers)
        lignes += self._section_ecrans(racine, config)
        lignes += self._section_comportements(racine, config)
        lignes += self._section_questions()

        return "\n".join(lignes) + "\n"

    def _fichiers_python(self, racine, config):
        fichiers = []
        for app in config["apps"]:
            dossier = racine / app
            if not dossier.exists():
                continue
            noms = config.get("fichiers")
            if noms:
                fichiers += [dossier / nom for nom in noms if (dossier / nom).exists()]
            else:
                fichiers += [
                    chemin
                    for chemin in dossier.glob("*.py")
                    if chemin.name not in {"__init__.py", "tests.py"}
                ]
                fichiers += list((dossier / "management" / "commands").glob("*.py"))
        return [chemin for chemin in fichiers if chemin.exists()]

    def _arbre(self, chemin):
        try:
            return ast.parse(chemin.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            return None

    # -- Sections --------------------------------------------------------------

    def _section_parcours(self, racine, config):
        lignes = ["## Parcours accessibles", ""]
        trouve = False

        for app in config["apps"]:
            urls = racine / app / "urls.py"
            if not urls.exists():
                continue
            arbre = self._arbre(urls)
            if arbre is None:
                continue

            entrees = []
            for noeud in ast.walk(arbre):
                if not (isinstance(noeud, ast.Call) and getattr(noeud.func, "id", "") == "path"):
                    continue
                route = self._valeur(noeud.args[0]) if noeud.args else ""
                vue = ast.unparse(noeud.args[1]) if len(noeud.args) > 1 else ""
                nom = next(
                    (self._valeur(mc.value) for mc in noeud.keywords if mc.arg == "name"),
                    "",
                )
                entrees.append((route, vue, nom))

            if entrees:
                trouve = True
                lignes.append(f"### Application `{app}`")
                lignes.append("")
                lignes.append("| Adresse | Vue | Nom interne |")
                lignes.append("|---|---|---|")
                for route, vue, nom in entrees:
                    lignes.append(f"| `{route}` | `{vue}` | `{nom}` |")
                lignes.append("")

        if not trouve:
            lignes += ["Aucune route propre a ce module.", ""]
        return lignes

    def _section_donnees(self, fichiers):
        lignes = ["## Donnees manipulees", ""]
        trouve = False

        for chemin in fichiers:
            if chemin.name != "models.py":
                continue
            arbre = self._arbre(chemin)
            if arbre is None:
                continue

            for noeud in arbre.body:
                if not isinstance(noeud, ast.ClassDef):
                    continue
                champs, choix = [], []
                for element in noeud.body:
                    if isinstance(element, ast.Assign) and isinstance(element.value, ast.Call):
                        appel = ast.unparse(element.value.func)
                        if appel.startswith("models."):
                            nom = element.targets[0].id if isinstance(element.targets[0], ast.Name) else "?"
                            champs.append((nom, appel.replace("models.", "")))
                    elif isinstance(element, ast.Assign) and isinstance(
                        element.value, (ast.Tuple, ast.List)
                    ):
                        nom = element.targets[0].id if isinstance(element.targets[0], ast.Name) else ""
                        if nom.endswith("CHOICES") or nom.endswith("STATUS"):
                            choix.append((nom, ast.unparse(element.value)))

                if not champs and not choix:
                    continue
                trouve = True
                lignes.append(f"### `{noeud.name}`")
                doc = ast.get_docstring(noeud)
                if doc:
                    lignes += ["", *[f"> {l}" for l in doc.strip().splitlines()], ""]
                if champs:
                    lignes.append("")
                    lignes.append("| Champ | Type |")
                    lignes.append("|---|---|")
                    for nom, type_ in champs:
                        lignes.append(f"| `{nom}` | {type_} |")
                for nom, valeur in choix:
                    lignes += ["", f"Valeurs possibles `{nom}` :", "", "```python", valeur, "```"]
                lignes.append("")

        if not trouve:
            lignes += ["Ce module ne definit pas de donnees propres.", ""]
        return lignes

    def _section_droits(self, fichiers):
        lignes = [
            "## Qui a le droit de faire quoi",
            "",
            "Garde-fous poses sur chaque vue. A traduire en langage metier dans la",
            "formation : « la reception peut pointer mais pas consulter les salaires ».",
            "",
            "| Action | Protections |",
            "|---|---|",
        ]
        trouve = False

        for chemin in fichiers:
            arbre = self._arbre(chemin)
            if arbre is None:
                continue
            for noeud in arbre.body:
                if not isinstance(noeud, ast.FunctionDef) or noeud.name.startswith("_"):
                    continue
                gardes = []
                for decorateur in noeud.decorator_list:
                    texte = ast.unparse(decorateur)
                    racine_deco = texte.split("(")[0]
                    if racine_deco in GARDES:
                        gardes.append(f"`{texte}`")
                if gardes:
                    trouve = True
                    lignes.append(f"| `{noeud.name}` | {'<br>'.join(gardes)} |")

        if not trouve:
            lignes.append("| _(aucune vue protegee detectee)_ | |")
        lignes.append("")
        return lignes

    def _section_regles(self, fichiers):
        lignes = [
            "## Regles metier appliquees",
            "",
            "Refus opposes par le logiciel. Chacun merite une explication dans la",
            "formation : pourquoi la regle existe, et que faire quand on la rencontre.",
            "",
        ]
        vues = set()

        for chemin in fichiers:
            arbre = self._arbre(chemin)
            if arbre is None:
                continue
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.Call):
                    continue
                appel = ast.unparse(noeud.func)
                if appel.split(".")[-1] not in {"ValidationError", "CommandError"} and appel not in {
                    "forms.ValidationError"
                }:
                    continue
                for argument in noeud.args:
                    texte = self._valeur(argument)
                    if texte and len(texte) > 12:
                        vues.add(texte)

        for texte in sorted(vues):
            lignes.append(f"- {texte}")
        if not vues:
            lignes.append("_Aucun refus explicite detecte._")
        lignes.append("")
        return lignes

    def _section_messages(self, fichiers):
        lignes = [
            "## Ce que l'utilisateur lit a l'ecran",
            "",
            "Messages affiches apres une action. Ils donnent le vocabulaire exact a",
            "employer dans la formation : l'apprenant doit reconnaitre ce qu'il verra.",
            "",
        ]
        par_niveau = {"success": set(), "warning": set(), "error": set(), "info": set()}

        for chemin in fichiers:
            arbre = self._arbre(chemin)
            if arbre is None:
                continue
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.Call):
                    continue
                appel = ast.unparse(noeud.func)
                if not appel.startswith("messages."):
                    continue
                niveau = appel.split(".")[-1]
                if niveau not in par_niveau:
                    continue
                for argument in noeud.args[1:]:
                    texte = self._valeur(argument)
                    if texte:
                        par_niveau[niveau].add(texte)

        etiquettes = {
            "success": "Confirmations",
            "warning": "Avertissements",
            "error": "Refus et erreurs",
            "info": "Informations",
        }
        for niveau, titre in etiquettes.items():
            if par_niveau[niveau]:
                lignes += [f"### {titre}", ""]
                lignes += [f"- {texte}" for texte in sorted(par_niveau[niveau])]
                lignes.append("")
        return lignes

    def _section_audit(self, fichiers):
        lignes = [
            "## Traces laissees dans le journal sensible",
            "",
            "Actions consignees. Utile pour expliquer aux equipes ce qui est trace,",
            "et rassurer sur ce qui ne l'est pas.",
            "",
        ]
        actions = set()

        for chemin in fichiers:
            arbre = self._arbre(chemin)
            if arbre is None:
                continue
            for noeud in ast.walk(arbre):
                if isinstance(noeud, ast.Call) and ast.unparse(noeud.func).endswith(
                    "log_sensitive_action"
                ):
                    for argument in noeud.args[1:2]:
                        texte = self._valeur(argument)
                        if texte:
                            actions.add(texte)

        lignes += [f"- `{action}`" for action in sorted(actions)] or [
            "_Aucune action de ce module n'est journalisee._"
        ]
        lignes.append("")
        return lignes

    def _section_ecrans(self, racine, config):
        lignes = ["## Ecrans concernes", ""]
        trouve = False
        for app in config["apps"]:
            dossier = racine / app / "templates"
            if not dossier.exists():
                continue
            gabarits = sorted(dossier.rglob("*.html"))
            if gabarits:
                trouve = True
                lignes += [f"- `{chemin.relative_to(racine)}`" for chemin in gabarits]
        if not trouve:
            lignes.append("_Aucun ecran propre a ce module._")
        lignes.append("")
        return lignes

    def _section_comportements(self, racine, config):
        lignes = [
            "## Comportements garantis par les tests",
            "",
            "Chaque intitule decrit une promesse verifiee automatiquement. C'est la",
            "meilleure source pour les cas limites a montrer en formation.",
            "",
        ]
        trouve = False

        for app in config["apps"]:
            chemin = racine / app / "tests.py"
            if not chemin.exists():
                continue
            arbre = self._arbre(chemin)
            if arbre is None:
                continue

            for classe in arbre.body:
                if not isinstance(classe, ast.ClassDef):
                    continue
                methodes = [
                    element
                    for element in classe.body
                    if isinstance(element, ast.FunctionDef)
                    and element.name.startswith("test_")
                ]
                if not methodes:
                    continue
                trouve = True
                doc_classe = ast.get_docstring(classe)
                lignes.append(f"### {classe.name}")
                if doc_classe:
                    lignes += ["", f"> {doc_classe.strip().splitlines()[0]}", ""]
                for methode in methodes:
                    phrase = methode.name[5:].replace("_", " ")
                    doc = ast.get_docstring(methode)
                    lignes.append(f"- {phrase}" + (f" — _{doc.strip().splitlines()[0]}_" if doc else ""))
                lignes.append("")

        if not trouve:
            lignes += ["_Aucun test ne couvre ce module._", ""]
        return lignes

    def _section_questions(self):
        return [
            "## A completer par un humain",
            "",
            "Le code ne dit pas tout. Avant de rediger, il faut trancher :",
            "",
            "- Qui suit cette formation : reception, caisse, gerant, proprietaire ?",
            "- Quelles taches quotidiennes reelles doit-on savoir faire a la fin ?",
            "- Quels incidents arrivent souvent et doivent etre traites en exercice ?",
            "- Quelles habitudes de la salle different de ce que propose le logiciel ?",
            "",
        ]

    # -- Utilitaires ------------------------------------------------------------

    @staticmethod
    def _valeur(noeud):
        """Texte d'un litteral, y compris les f-strings et concatenations."""
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
            return noeud.value.strip()
        if isinstance(noeud, ast.JoinedStr):
            morceaux = []
            for partie in noeud.values:
                if isinstance(partie, ast.Constant) and isinstance(partie.value, str):
                    morceaux.append(partie.value)
                else:
                    morceaux.append("{valeur}")
            return re.sub(r"\s+", " ", "".join(morceaux)).strip()
        if isinstance(noeud, ast.BinOp):
            gauche = Command._valeur(noeud.left) or ""
            droite = Command._valeur(noeud.right) or ""
            return f"{gauche}{droite}".strip()
        return ""

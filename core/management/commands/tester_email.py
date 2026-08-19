"""
Verifie qu'un e-mail part reellement, et dit pourquoi quand ce n'est pas le cas.

Un e-mail qui ne part pas ne provoque aucune erreur visible : en
developpement Django ecrit le message dans la console et l'application croit
l'avoir envoye. Cette commande separe les deux cas.
"""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.management.base import BaseCommand, CommandError


BACKEND_CONSOLE = "django.core.mail.backends.console.EmailBackend"
BACKEND_LOCMEM = "django.core.mail.backends.locmem.EmailBackend"
BACKEND_DUMMY = "django.core.mail.backends.dummy.EmailBackend"

BACKENDS_SANS_ENVOI = {
    BACKEND_CONSOLE: "les messages sont ecrits dans la console du serveur",
    BACKEND_LOCMEM: "les messages sont gardes en memoire pour les tests",
    BACKEND_DUMMY: "les messages sont jetes",
}


class Command(BaseCommand):
    help = "Envoie un e-mail de controle et rapporte la configuration utilisee."

    def add_arguments(self, parser):
        parser.add_argument(
            "destinataire",
            nargs="?",
            help="Adresse a qui envoyer le message de controle.",
        )
        parser.add_argument(
            "--diagnostic-seul",
            action="store_true",
            help="Affiche la configuration sans rien envoyer.",
        )

    def handle(self, *args, **options):
        self._afficher_configuration()

        if options["diagnostic_seul"]:
            return

        destinataire = options["destinataire"]
        if not destinataire:
            raise CommandError(
                "Indiquez une adresse destinataire, ou utilisez --diagnostic-seul."
            )

        backend = settings.EMAIL_BACKEND
        if backend in BACKENDS_SANS_ENVOI:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Aucun envoi reel : {BACKENDS_SANS_ENVOI[backend]}.\n"
                    "Renseignez DJANGO_EMAIL_BACKEND dans le fichier .env pour envoyer "
                    "vraiment."
                )
            )

        self.stdout.write("")
        self.stdout.write(f"Envoi vers {destinataire}...")

        message = EmailMultiAlternatives(
            subject="Controle d'envoi SmartClub",
            body=(
                "Ce message confirme que la configuration d'envoi fonctionne.\n\n"
                f"Backend  : {settings.EMAIL_BACKEND}\n"
                f"Serveur  : {settings.EMAIL_HOST}:{settings.EMAIL_PORT}\n"
                f"Expediteur : {settings.DEFAULT_FROM_EMAIL}\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[destinataire],
        )

        try:
            # fail_silently=False : une panne doit se voir ici, pas se taire.
            envoyes = message.send(fail_silently=False)
        except Exception as exc:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(f"Echec : {exc.__class__.__name__} : {exc}"))
            self.stdout.write("")
            self.stdout.write(self._piste(exc))
            raise CommandError("L'e-mail n'est pas parti.")

        self.stdout.write("")
        if envoyes and backend not in BACKENDS_SANS_ENVOI:
            self.stdout.write(self.style.SUCCESS(f"Message accepte par {settings.EMAIL_HOST}."))
            self.stdout.write(
                "Verifiez la boite de reception, et les indesirables : un domaine "
                "sans SPF ni DKIM y atterrit souvent."
            )
        elif envoyes:
            self.stdout.write(
                self.style.WARNING("Message traite par un backend qui n'envoie rien.")
            )
        else:
            self.stdout.write(self.style.ERROR("Aucun message accepte."))

    # --- Details ------------------------------------------------------------

    def _afficher_configuration(self):
        backend = settings.EMAIL_BACKEND
        cle_brevo = settings.ANYMAIL.get("BREVO_API_KEY", "") if hasattr(settings, "ANYMAIL") else ""

        self.stdout.write("Configuration d'envoi")
        self.stdout.write(f"  DEBUG             : {settings.DEBUG}")
        self.stdout.write(f"  EMAIL_BACKEND     : {backend}")
        self.stdout.write(f"  EMAIL_HOST        : {settings.EMAIL_HOST}:{settings.EMAIL_PORT}")
        self.stdout.write(f"  EMAIL_HOST_USER   : {settings.EMAIL_HOST_USER or '(vide)'}")
        self.stdout.write(
            f"  EMAIL_HOST_PASSWORD : {'(renseigne)' if settings.EMAIL_HOST_PASSWORD else '(vide)'}"
        )
        self.stdout.write(f"  EMAIL_USE_TLS     : {settings.EMAIL_USE_TLS}")
        self.stdout.write(f"  EMAIL_USE_SSL     : {settings.EMAIL_USE_SSL}")
        self.stdout.write(f"  DEFAULT_FROM_EMAIL: {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write(f"  BREVO_API_KEY     : {'(renseignee)' if cle_brevo else '(vide)'}")

        self.stdout.write("")
        for probleme in self._problemes(backend, cle_brevo):
            self.stdout.write(self.style.WARNING(f"  - {probleme}"))

    def _problemes(self, backend, cle_brevo):
        soucis = []

        if backend in BACKENDS_SANS_ENVOI:
            soucis.append(
                f"Le backend actuel n'envoie rien : {BACKENDS_SANS_ENVOI[backend]}."
            )

        if backend.endswith("smtp.EmailBackend"):
            if settings.EMAIL_HOST in {"localhost", "127.0.0.1", ""}:
                soucis.append(
                    "EMAIL_HOST vaut localhost : aucun serveur SMTP n'ecoute ici."
                )
            if not settings.EMAIL_HOST_USER:
                soucis.append("EMAIL_HOST_USER est vide.")
            if not settings.EMAIL_HOST_PASSWORD:
                soucis.append("EMAIL_HOST_PASSWORD est vide.")
            if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
                soucis.append(
                    "EMAIL_USE_TLS et EMAIL_USE_SSL sont actifs tous les deux : "
                    "choisissez-en un (465 = SSL, 587 = TLS)."
                )
            if settings.EMAIL_PORT == 465 and not settings.EMAIL_USE_SSL:
                soucis.append("Le port 465 demande EMAIL_USE_SSL=True.")
            if settings.EMAIL_PORT == 587 and not settings.EMAIL_USE_TLS:
                soucis.append("Le port 587 demande EMAIL_USE_TLS=True.")

        if "brevo" in backend.lower() and not cle_brevo:
            soucis.append("Le backend Brevo est choisi mais BREVO_API_KEY est vide.")

        if not soucis:
            soucis.append("Rien d'anormal dans la configuration.")
        return soucis

    def _piste(self, exc):
        nom = exc.__class__.__name__
        texte = str(exc).lower()

        if "authentication" in texte or nom == "SMTPAuthenticationError":
            return (
                "Piste : identifiants refuses. Avec Gmail, un mot de passe de compte "
                "ne suffit pas : il faut un mot de passe d'application."
            )
        if "timed out" in texte or nom == "timeout":
            return (
                "Piste : le port sortant est probablement bloque par le reseau ou "
                "l'hebergeur. Un envoi par API (Brevo, port 443) contourne ce blocage."
            )
        if "connection refused" in texte or "getaddrinfo" in texte:
            return "Piste : serveur SMTP injoignable. Verifiez EMAIL_HOST et EMAIL_PORT."
        if "ssl" in texte or "wrong version" in texte:
            return (
                "Piste : desaccord de chiffrement. Port 465 avec EMAIL_USE_SSL=True, "
                "port 587 avec EMAIL_USE_TLS=True."
            )
        return "Piste : relisez les avertissements ci-dessus."

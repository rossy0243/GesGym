from django.core.management.base import BaseCommand

from members.models import MemberPreRegistration


class Command(BaseCommand):
    help = (
        "Bascule vers le statut 'expiree' les preinscriptions en attente dont "
        "la validite est depassee. Elles restent consultables pour le suivi "
        "commercial au lieu d'etre supprimees."
    )

    def handle(self, *args, **options):
        expired_count = MemberPreRegistration.mark_expired_pending()
        self.stdout.write(
            self.style.SUCCESS(
                f"{expired_count} preinscription(s) marquee(s) comme expiree(s)."
            )
        )

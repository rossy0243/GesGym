from django.core.management.base import BaseCommand

from members.models import MemberPreRegistration


class Command(BaseCommand):
    help = "Supprime les preinscriptions membres en attente dont la validite a expire."

    def handle(self, *args, **options):
        deleted_count, _ = MemberPreRegistration.delete_expired_pending()
        self.stdout.write(
            self.style.SUCCESS(
                f"{deleted_count} preinscription(s) expiree(s) supprimee(s)."
            )
        )

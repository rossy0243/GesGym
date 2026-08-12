from django.core.management.base import BaseCommand
from django.utils import timezone

from members.models import Member


class Command(BaseCommand):
    help = (
        "Regenere les QR codes membres expires. --all force la rotation de "
        "tous les membres actifs.\n"
        "ATTENTION : les QR sont imprimes sur les cartes membres. Toute "
        "rotation rend caduque la carte physique correspondante. A ne pas "
        "planifier automatiquement : reservez cette commande a un incident "
        "(fuite de codes, reimpression complete du parc de cartes)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Force regeneration for every active member QR code.",
        )
        parser.add_argument(
            "--gym-id",
            type=int,
            help="Limit regeneration to a specific gym id.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many QR codes would be regenerated without saving.",
        )

    def handle(self, *args, **options):
        queryset = Member.objects.select_related("gym").filter(is_active=True)
        if options["gym_id"]:
            queryset = queryset.filter(gym_id=options["gym_id"])
        if not options["all"]:
            queryset = queryset.filter(qr_code_expires_at__lte=timezone.now())

        count = queryset.count()
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(f"{count} QR code(s) a regenerer."))
            return

        for member in queryset.iterator():
            member.rotate_qr_code()

        self.stdout.write(self.style.SUCCESS(f"{count} QR code(s) regenere(s)."))

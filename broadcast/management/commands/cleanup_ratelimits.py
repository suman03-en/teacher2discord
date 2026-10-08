"""Management command to clean up expired rate-limit records."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from broadcast.models import RateLimit


class Command(BaseCommand):
    help = "Remove expired rate-limit records to keep the database clean."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many records would be deleted without actually deleting them.",
        )

    def handle(self, *args, **options):
        stale = RateLimit.objects.filter(reset_at__lt=timezone.now())
        count = stale.count()

        if options["dry_run"]:
            self.stdout.write(f"Would delete {count} expired rate-limit record(s).")
        else:
            stale.delete()
            self.stdout.write(
                self.style.SUCCESS(f"Deleted {count} expired rate-limit record(s).")
            )

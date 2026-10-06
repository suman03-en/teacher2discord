from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from broadcast.models import LoginToken


class Command(BaseCommand):
    help = 'Remove expired and used login tokens to keep the database clean.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show how many tokens would be deleted without actually deleting them.',
        )

    def handle(self, *args, **options):
        stale = LoginToken.objects.filter(
            Q(expires_at__lt=timezone.now()) | Q(used=True)
        )
        count = stale.count()

        if options['dry_run']:
            self.stdout.write(f"Would delete {count} expired/used token(s).")
        else:
            stale.delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {count} expired/used token(s)."))

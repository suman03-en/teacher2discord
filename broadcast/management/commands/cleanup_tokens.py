from django.core.management.base import BaseCommand
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
        expired_or_used = LoginToken.objects.filter(
            expires_at__lt=timezone.now()
        ) | LoginToken.objects.filter(used=True)

        count = expired_or_used.count()

        if options['dry_run']:
            self.stdout.write(f"Would delete {count} expired/used token(s).")
        else:
            expired_or_used.delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {count} expired/used token(s)."))

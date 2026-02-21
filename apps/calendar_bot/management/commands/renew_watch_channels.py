"""
Management command: renew_watch_channels

Re-registers Google Calendar push notification watch channels for all connected
CalendarToken rows. Can be run manually via:

    python manage.py renew_watch_channels

This is useful for:
- Manually renewing channels when Celery beat is not running.
- Debugging: verify WEBHOOK_BASE_URL is set and Google accepts the registration.
- One-off channel renewal after deployment.

Channels that fail to renew (e.g. due to revoked credentials or missing
WEBHOOK_BASE_URL) are logged as errors but do not abort the run for other tokens.
"""
import logging

from django.core.management.base import BaseCommand
from django.conf import settings

# Imported at module level so tests can patch
# apps.calendar_bot.management.commands.renew_watch_channels.register_watch_channel
from apps.calendar_bot.sync import register_watch_channel

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Re-register Google Calendar push notification watch channels for all '
        'connected CalendarToken rows.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--phone',
            type=str,
            default=None,
            help='Only renew watch channel for this phone number (optional).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Print what would be done without actually calling the Google API.',
        )

    def handle(self, *args, **options):
        from apps.calendar_bot.models import CalendarToken

        phone_filter = options.get('phone')
        dry_run = options.get('dry_run')

        webhook_base_url = getattr(settings, 'WEBHOOK_BASE_URL', None)
        if not webhook_base_url:
            self.stderr.write(
                self.style.ERROR(
                    'WEBHOOK_BASE_URL is not set. Watch channel registration will be skipped. '
                    'Set WEBHOOK_BASE_URL to your public HTTPS base URL (e.g. '
                    'https://your-app.railway.app) and retry.'
                )
            )
            return

        self.stdout.write(f'WEBHOOK_BASE_URL: {webhook_base_url}')

        qs = CalendarToken.objects.exclude(access_token='').order_by('phone_number', 'created_at')
        if phone_filter:
            qs = qs.filter(phone_number=phone_filter)
            self.stdout.write(f'Filtering to phone: {phone_filter}')

        tokens = list(qs)
        total = len(tokens)

        if total == 0:
            self.stdout.write('No CalendarToken rows found. Nothing to do.')
            return

        self.stdout.write(f'Found {total} token(s) to process.')

        success_count = 0
        skip_count = 0
        error_count = 0

        for token in tokens:
            label = f'phone={token.phone_number} email={token.account_email or "(none)"}'

            if dry_run:
                self.stdout.write(f'[dry-run] Would renew watch channel for {label}')
                skip_count += 1
                continue

            self.stdout.write(f'Renewing watch channel for {label} ...')
            try:
                channel = register_watch_channel(token)
                if channel is None:
                    # register_watch_channel returns None when WEBHOOK_BASE_URL is missing;
                    # the guard already logged the error.
                    skip_count += 1
                    self.stdout.write(
                        self.style.WARNING(f'  Skipped (WEBHOOK_BASE_URL guard triggered): {label}')
                    )
                else:
                    success_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  OK: channel_id={channel.channel_id} expiry={channel.expiry}'
                        )
                    )
            except Exception as exc:
                error_count += 1
                logger.exception(
                    'renew_watch_channels: failed to renew channel for %s: %s', label, exc
                )
                self.stderr.write(
                    self.style.ERROR(f'  ERROR for {label}: {type(exc).__name__}: {exc}')
                )

        self.stdout.write(
            f'\nDone. success={success_count} skipped={skip_count} errors={error_count}'
        )

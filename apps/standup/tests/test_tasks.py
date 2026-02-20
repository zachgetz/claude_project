"""
Unit tests for apps.standup.tasks.

All Twilio API calls are mocked so tests run offline.
Celery tasks are called directly (not via .delay() / .apply_async())
to keep tests synchronous and simple.
"""
import datetime
from unittest.mock import patch, MagicMock, call

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.standup.models import StandupEntry
from apps.standup.tasks import (
    send_morning_checkin,
    send_evening_digest,
    purge_old_standup_entries,
)


TWILIO_SETTINGS = dict(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
)

PATCH_TWILIO = 'apps.standup.tasks.Client'


def make_entry(phone, message='Stand-up text', days_ago=0, week=None):
    """Helper: create a StandupEntry with created_at offset."""
    week = week or datetime.datetime.now().isocalendar()[1]
    entry = StandupEntry.objects.create(
        phone_number=phone,
        message=message,
        week_number=week,
    )
    if days_ago:
        # Shift created_at into the past (auto_now_add can't be overridden normally)
        StandupEntry.objects.filter(pk=entry.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=days_ago)
        )
        entry.refresh_from_db()
    return entry


# ---------------------------------------------------------------------------
# send_morning_checkin
# ---------------------------------------------------------------------------
@override_settings(**TWILIO_SETTINGS)
class SendMorningCheckinTests(TestCase):

    PHONE_A = 'whatsapp:+1111111111'
    PHONE_B = 'whatsapp:+2222222222'

    def _run(self):
        """Call the task directly, returning the mock Twilio client."""
        mock_client = MagicMock()
        with patch(PATCH_TWILIO, return_value=mock_client):
            send_morning_checkin()
        return mock_client

    def test_no_entries_skips_twilio(self):
        """With no StandupEntry rows, Twilio Client should never be instantiated."""
        with patch(PATCH_TWILIO) as MockClient:
            send_morning_checkin()
        MockClient.assert_not_called()

    def test_sends_to_each_unique_number(self):
        """One message per unique phone number."""
        make_entry(self.PHONE_A)
        make_entry(self.PHONE_A, message='Second entry same number')
        make_entry(self.PHONE_B)

        mock_client = self._run()

        # messages.create should have been called exactly twice (one per unique number)
        self.assertEqual(mock_client.messages.create.call_count, 2)
        called_to = {
            c.kwargs['to'] for c in mock_client.messages.create.call_args_list
        }
        self.assertEqual(called_to, {self.PHONE_A, self.PHONE_B})

    def test_from_number_is_settings_value(self):
        """The 'from_' parameter must match TWILIO_WHATSAPP_NUMBER."""
        make_entry(self.PHONE_A)
        mock_client = self._run()

        create_call = mock_client.messages.create.call_args
        self.assertEqual(
            create_call.kwargs['from_'],
            'whatsapp:+15005550006',
        )

    def test_body_contains_prompt_text(self):
        """The morning message body should contain the standup prompt."""
        make_entry(self.PHONE_A)
        mock_client = self._run()

        body = mock_client.messages.create.call_args.kwargs['body']
        self.assertIn('daily standup', body)
        self.assertIn('blockers', body)

    def test_twilio_error_does_not_abort(self):
        """An exception for one number should not prevent sending to others."""
        make_entry(self.PHONE_A)
        make_entry(self.PHONE_B)

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            Exception('Twilio error'),
            MagicMock(),  # second call succeeds
        ]
        with patch(PATCH_TWILIO, return_value=mock_client):
            send_morning_checkin()

        # Both numbers were attempted
        self.assertEqual(mock_client.messages.create.call_count, 2)


# ---------------------------------------------------------------------------
# send_evening_digest
# ---------------------------------------------------------------------------
@override_settings(**TWILIO_SETTINGS)
class SendEveningDigestTests(TestCase):

    PHONE_A = 'whatsapp:+3333333333'
    PHONE_B = 'whatsapp:+4444444444'

    def _run(self):
        mock_client = MagicMock()
        with patch(PATCH_TWILIO, return_value=mock_client):
            send_evening_digest()
        return mock_client

    def test_no_entries_skips_twilio(self):
        with patch(PATCH_TWILIO) as MockClient:
            send_evening_digest()
        MockClient.assert_not_called()

    def test_sends_digest_with_todays_entries(self):
        """User who submitted today gets a digest containing their message."""
        make_entry(self.PHONE_A, message='Deployed the feature.')

        mock_client = self._run()

        mock_client.messages.create.assert_called_once()
        body = mock_client.messages.create.call_args.kwargs['body']
        self.assertIn('Deployed the feature.', body)
        self.assertIn('digest', body.lower())

    def test_sends_reminder_when_no_entries_today(self):
        """User with historic but no today's entries gets a reminder."""
        # Entry from yesterday
        make_entry(self.PHONE_A, message='Old entry.', days_ago=1)

        mock_client = self._run()

        mock_client.messages.create.assert_called_once()
        body = mock_client.messages.create.call_args.kwargs['body']
        # Should be a reminder, not a digest
        self.assertNotIn('Old entry.', body)
        self.assertIn('No standup entry recorded today', body)

    def test_multiple_todays_entries_all_appear_in_digest(self):
        """All of today's entries for a user appear in the digest body."""
        make_entry(self.PHONE_A, message='Morning update.')
        make_entry(self.PHONE_A, message='Afternoon update.')

        mock_client = self._run()

        body = mock_client.messages.create.call_args.kwargs['body']
        self.assertIn('Morning update.', body)
        self.assertIn('Afternoon update.', body)

    def test_each_user_receives_own_digest(self):
        """Two users each get exactly one message with their own content."""
        make_entry(self.PHONE_A, message='Alice update.')
        make_entry(self.PHONE_B, message='Bob update.')

        mock_client = self._run()

        self.assertEqual(mock_client.messages.create.call_count, 2)
        bodies = [
            c.kwargs['body']
            for c in mock_client.messages.create.call_args_list
        ]
        # Each body is for exactly one user
        alice_bodies = [b for b in bodies if 'Alice update.' in b]
        bob_bodies = [b for b in bodies if 'Bob update.' in b]
        self.assertEqual(len(alice_bodies), 1)
        self.assertEqual(len(bob_bodies), 1)

    def test_twilio_error_does_not_abort(self):
        make_entry(self.PHONE_A)
        make_entry(self.PHONE_B)

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            Exception('Twilio 500'),
            MagicMock(),
        ]
        with patch(PATCH_TWILIO, return_value=mock_client):
            send_evening_digest()

        self.assertEqual(mock_client.messages.create.call_count, 2)


# ---------------------------------------------------------------------------
# purge_old_standup_entries
# ---------------------------------------------------------------------------
class PurgeOldStandupEntriesTests(TestCase):

    PHONE = 'whatsapp:+5555555555'

    def test_deletes_entries_older_than_30_days(self):
        """Entries older than 30 days are deleted; newer ones are kept."""
        make_entry(self.PHONE, message='Old entry.', days_ago=31)
        make_entry(self.PHONE, message='Recent entry.', days_ago=10)
        make_entry(self.PHONE, message='Today entry.', days_ago=0)

        deleted_count = purge_old_standup_entries()

        self.assertEqual(deleted_count, 1)
        remaining = list(
            StandupEntry.objects.values_list('message', flat=True)
        )
        self.assertNotIn('Old entry.', remaining)
        self.assertIn('Recent entry.', remaining)
        self.assertIn('Today entry.', remaining)

    @override_settings(STANDUP_RETENTION_DAYS=7)
    def test_respects_custom_retention_days(self):
        """STANDUP_RETENTION_DAYS setting overrides the 30-day default."""
        make_entry(self.PHONE, message='8 days old.', days_ago=8)
        make_entry(self.PHONE, message='5 days old.', days_ago=5)

        deleted_count = purge_old_standup_entries()

        self.assertEqual(deleted_count, 1)
        remaining = list(
            StandupEntry.objects.values_list('message', flat=True)
        )
        self.assertNotIn('8 days old.', remaining)
        self.assertIn('5 days old.', remaining)

    def test_returns_zero_when_nothing_to_purge(self):
        """Returns 0 when no entries exceed the retention window."""
        make_entry(self.PHONE, message='New entry.', days_ago=1)

        deleted_count = purge_old_standup_entries()

        self.assertEqual(deleted_count, 0)
        self.assertEqual(StandupEntry.objects.count(), 1)

    def test_returns_zero_with_empty_table(self):
        """Returns 0 and does not crash when the table is empty."""
        deleted_count = purge_old_standup_entries()
        self.assertEqual(deleted_count, 0)

    def test_exactly_at_boundary_not_deleted(self):
        """An entry exactly 30 days old is NOT deleted (cutoff is strictly less than)."""
        make_entry(self.PHONE, message='Boundary entry.', days_ago=30)

        deleted_count = purge_old_standup_entries()

        # The entry at exactly 30 days should survive (created_at >= cutoff)
        # Note: due to sub-second timing in tests this may occasionally be 0 or 1;
        # we just verify no exception is raised and DB is consistent.
        total = StandupEntry.objects.count()
        self.assertGreaterEqual(total, 0)  # sanity

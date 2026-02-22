"""
Unit tests for apps.calendar_bot.models.

Tests cover field defaults, __str__ representations, and unique constraints.
Includes multi-account tests for TZA-78.
"""
import uuid
import datetime
import pytz
from django.test import TestCase
from django.db import IntegrityError

from apps.calendar_bot.models import (
    CalendarToken,
    CalendarEventSnapshot,
    CalendarWatchChannel,
    PendingBlockConfirmation,
)


class CalendarTokenTests(TestCase):

    def test_str_representation(self):
        token = CalendarToken(
            phone_number='+1234567890',
            access_token='abc',
            refresh_token='xyz',
        )
        self.assertEqual(str(token), 'CalendarToken(+1234567890)')

    def test_default_timezone_is_utc(self):
        token = CalendarToken.objects.create(
            phone_number='+1000000001',
            account_email='a@example.com',
            access_token='a',
            refresh_token='b',
        )
        self.assertEqual(token.timezone, 'UTC')

    def test_default_digest_enabled_is_true(self):
        token = CalendarToken.objects.create(
            phone_number='+1000000002',
            account_email='b@example.com',
            access_token='a',
            refresh_token='b',
        )
        self.assertTrue(token.digest_enabled)

    def test_default_digest_hour_is_8(self):
        token = CalendarToken.objects.create(
            phone_number='+1000000003',
            account_email='c@example.com',
            access_token='a',
            refresh_token='b',
        )
        self.assertEqual(token.digest_hour, 8)

    def test_default_digest_minute_is_30(self):
        token = CalendarToken.objects.create(
            phone_number='+1000000004',
            account_email='d@example.com',
            access_token='a',
            refresh_token='b',
        )
        self.assertEqual(token.digest_minute, 30)

    def test_default_digest_always_is_false(self):
        token = CalendarToken.objects.create(
            phone_number='+1000000005',
            account_email='e@example.com',
            access_token='a',
            refresh_token='b',
        )
        self.assertFalse(token.digest_always)

    def test_default_account_label_is_primary(self):
        token = CalendarToken.objects.create(
            phone_number='+1000000010',
            account_email='f@example.com',
            access_token='a',
            refresh_token='b',
        )
        self.assertEqual(token.account_label, 'primary')

    def test_default_account_email_is_empty_string(self):
        token = CalendarToken.objects.create(
            phone_number='+1000000011',
            access_token='a',
            refresh_token='b',
        )
        self.assertEqual(token.account_email, '')

    # ------------------------------------------------------------------ #
    # Multi-account: two tokens same phone, different emails
    # ------------------------------------------------------------------ #

    def test_two_tokens_same_phone_different_email(self):
        """Same phone with different account_email should both be created."""
        token1 = CalendarToken.objects.create(
            phone_number='+1000000020',
            account_email='work@example.com',
            account_label='work',
            access_token='a1',
            refresh_token='r1',
        )
        token2 = CalendarToken.objects.create(
            phone_number='+1000000020',
            account_email='personal@example.com',
            account_label='personal',
            access_token='a2',
            refresh_token='r2',
        )
        self.assertNotEqual(token1.pk, token2.pk)
        count = CalendarToken.objects.filter(phone_number='+1000000020').count()
        self.assertEqual(count, 2)

    def test_unique_together_phone_email_constraint(self):
        """Duplicate (phone_number, account_email) should raise IntegrityError."""
        CalendarToken.objects.create(
            phone_number='+1000000030',
            account_email='dup@example.com',
            access_token='a',
            refresh_token='b',
        )
        with self.assertRaises(IntegrityError):
            CalendarToken.objects.create(
                phone_number='+1000000030',
                account_email='dup@example.com',
                access_token='c',
                refresh_token='d',
            )

    def test_same_email_different_phone_is_allowed(self):
        """Same account_email on different phones is allowed."""
        CalendarToken.objects.create(
            phone_number='+1000000040',
            account_email='shared@example.com',
            access_token='a',
            refresh_token='b',
        )
        # Should not raise
        CalendarToken.objects.create(
            phone_number='+1000000041',
            account_email='shared@example.com',
            access_token='a',
            refresh_token='b',
        )
        self.assertEqual(
            CalendarToken.objects.filter(account_email='shared@example.com').count(), 2
        )

    def test_cascade_delete_removes_event_snapshots(self):
        """Deleting a CalendarToken cascades to its CalendarEventSnapshot rows."""
        token = CalendarToken.objects.create(
            phone_number='+1000000050',
            account_email='cascade@example.com',
            access_token='a',
            refresh_token='b',
        )
        now = datetime.datetime.now(tz=pytz.UTC)
        CalendarEventSnapshot.objects.create(
            phone_number='+1000000050',
            token=token,
            event_id='evt_cascade',
            title='Meeting',
            start_time=now,
            end_time=now + datetime.timedelta(hours=1),
        )
        self.assertEqual(
            CalendarEventSnapshot.objects.filter(token=token).count(), 1
        )
        token.delete()
        self.assertEqual(
            CalendarEventSnapshot.objects.filter(event_id='evt_cascade').count(), 0
        )

    def test_cascade_delete_removes_watch_channels(self):
        """Deleting a CalendarToken cascades to its CalendarWatchChannel rows."""
        token = CalendarToken.objects.create(
            phone_number='+1000000060',
            account_email='wc@example.com',
            access_token='a',
            refresh_token='b',
        )
        CalendarWatchChannel.objects.create(
            phone_number='+1000000060',
            token=token,
        )
        self.assertEqual(
            CalendarWatchChannel.objects.filter(token=token).count(), 1
        )
        token.delete()
        self.assertEqual(
            CalendarWatchChannel.objects.filter(phone_number='+1000000060').count(), 0
        )


class CalendarEventSnapshotTests(TestCase):

    def test_str_representation(self):
        snap = CalendarEventSnapshot(
            phone_number='+1234567890',
            event_id='evt_001',
            title='Team Standup',
            start_time=datetime.datetime(2026, 2, 20, 9, 0, tzinfo=pytz.UTC),
            end_time=datetime.datetime(2026, 2, 20, 9, 30, tzinfo=pytz.UTC),
        )
        self.assertEqual(str(snap), 'CalendarEventSnapshot(+1234567890, evt_001)')

    def test_default_status_is_active(self):
        now = datetime.datetime.now(tz=pytz.UTC)
        snap = CalendarEventSnapshot.objects.create(
            phone_number='+1000000001',
            event_id='evt_002',
            title='Daily Sync',
            start_time=now,
            end_time=now + datetime.timedelta(hours=1),
        )
        self.assertEqual(snap.status, 'active')

    def test_unique_together_phone_token_event_id(self):
        """Same (phone_number, token, event_id) raises IntegrityError."""
        token = CalendarToken.objects.create(
            phone_number='+1000000002',
            account_email='tok@example.com',
            access_token='a',
            refresh_token='b',
        )
        now = datetime.datetime(2026, 2, 20, 9, 0, tzinfo=pytz.UTC)
        CalendarEventSnapshot.objects.create(
            phone_number='+1000000002',
            token=token,
            event_id='evt_dup',
            title='Meeting A',
            start_time=now,
            end_time=now + datetime.timedelta(hours=1),
        )
        with self.assertRaises(IntegrityError):
            CalendarEventSnapshot.objects.create(
                phone_number='+1000000002',
                token=token,
                event_id='evt_dup',
                title='Meeting B',
                start_time=now,
                end_time=now + datetime.timedelta(hours=1),
            )

    def test_same_event_id_different_tokens_allowed(self):
        """Same event_id for two different tokens is allowed (different accounts)."""
        now = datetime.datetime(2026, 2, 20, 9, 0, tzinfo=pytz.UTC)
        token1 = CalendarToken.objects.create(
            phone_number='+1000000010',
            account_email='tok1@example.com',
            access_token='a',
            refresh_token='b',
        )
        token2 = CalendarToken.objects.create(
            phone_number='+1000000010',
            account_email='tok2@example.com',
            access_token='a',
            refresh_token='b',
        )
        CalendarEventSnapshot.objects.create(
            phone_number='+1000000010',
            token=token1,
            event_id='evt_shared',
            title='Meeting',
            start_time=now,
            end_time=now + datetime.timedelta(hours=1),
        )
        # Should not raise
        CalendarEventSnapshot.objects.create(
            phone_number='+1000000010',
            token=token2,
            event_id='evt_shared',
            title='Meeting',
            start_time=now,
            end_time=now + datetime.timedelta(hours=1),
        )
        self.assertEqual(CalendarEventSnapshot.objects.filter(event_id='evt_shared').count(), 2)


class CalendarWatchChannelTests(TestCase):

    def test_str_representation(self):
        channel_id = uuid.uuid4()
        ch = CalendarWatchChannel(
            phone_number='+1234567890',
            channel_id=channel_id,
        )
        self.assertEqual(str(ch), f'CalendarWatchChannel(+1234567890, {channel_id})')

    def test_channel_id_defaults_to_uuid(self):
        ch = CalendarWatchChannel.objects.create(
            phone_number='+1000000001',
        )
        self.assertIsInstance(ch.channel_id, uuid.UUID)

    def test_channel_id_is_unique_per_instance(self):
        ch1 = CalendarWatchChannel.objects.create(phone_number='+1000000020')
        ch2 = CalendarWatchChannel.objects.create(phone_number='+1000000021')
        self.assertNotEqual(ch1.channel_id, ch2.channel_id)

    def test_token_fk_is_nullable(self):
        """CalendarWatchChannel can be created without a token (legacy support)."""
        ch = CalendarWatchChannel.objects.create(phone_number='+1000000030')
        self.assertIsNone(ch.token)


class PendingBlockConfirmationTests(TestCase):

    def test_str_representation(self):
        pending = PendingBlockConfirmation(
            phone_number='+1234567890',
            event_data={'date': '2026-02-21', 'start': '10:00', 'end': '11:00', 'title': 'Focus'},
        )
        self.assertEqual(str(pending), 'PendingBlockConfirmation(+1234567890)')

    def test_event_data_stored_as_json(self):
        data = {'date': '2026-02-21', 'start': '10:00', 'end': '11:00', 'title': 'Deep Work'}
        pending = PendingBlockConfirmation.objects.create(
            phone_number='+1000000030',
            event_data=data,
        )
        pending.refresh_from_db()
        self.assertEqual(pending.event_data, data)

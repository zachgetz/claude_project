"""
Unit tests for apps.calendar_bot.models.

Tests cover field defaults, __str__ representations, and unique constraints.
"""
import uuid
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
            access_token='a',
            refresh_token='b',
        )
        self.assertEqual(token.timezone, 'UTC')

    def test_default_digest_enabled_is_true(self):
        token = CalendarToken.objects.create(
            phone_number='+1000000002',
            access_token='a',
            refresh_token='b',
        )
        self.assertTrue(token.digest_enabled)

    def test_default_digest_hour_is_8(self):
        token = CalendarToken.objects.create(
            phone_number='+1000000003',
            access_token='a',
            refresh_token='b',
        )
        self.assertEqual(token.digest_hour, 8)

    def test_default_digest_minute_is_0(self):
        token = CalendarToken.objects.create(
            phone_number='+1000000004',
            access_token='a',
            refresh_token='b',
        )
        self.assertEqual(token.digest_minute, 0)

    def test_default_digest_always_is_false(self):
        token = CalendarToken.objects.create(
            phone_number='+1000000005',
            access_token='a',
            refresh_token='b',
        )
        self.assertFalse(token.digest_always)

    def test_phone_number_unique_constraint(self):
        CalendarToken.objects.create(
            phone_number='+1000000006',
            access_token='a',
            refresh_token='b',
        )
        with self.assertRaises(IntegrityError):
            CalendarToken.objects.create(
                phone_number='+1000000006',
                access_token='c',
                refresh_token='d',
            )


class CalendarEventSnapshotTests(TestCase):

    def test_str_representation(self):
        import datetime, pytz
        snap = CalendarEventSnapshot(
            phone_number='+1234567890',
            event_id='evt_001',
            title='Team Standup',
            start_time=datetime.datetime(2026, 2, 20, 9, 0, tzinfo=pytz.UTC),
            end_time=datetime.datetime(2026, 2, 20, 9, 30, tzinfo=pytz.UTC),
        )
        self.assertEqual(str(snap), 'CalendarEventSnapshot(+1234567890, evt_001)')

    def test_default_status_is_active(self):
        import datetime, pytz
        snap = CalendarEventSnapshot.objects.create(
            phone_number='+1000000001',
            event_id='evt_002',
            title='Daily Sync',
            start_time=datetime.datetime(2026, 2, 20, 9, 0, tzinfo=pytz.UTC),
            end_time=datetime.datetime(2026, 2, 20, 9, 30, tzinfo=pytz.UTC),
        )
        self.assertEqual(snap.status, 'active')

    def test_unique_together_phone_event_id(self):
        import datetime, pytz
        now = datetime.datetime(2026, 2, 20, 9, 0, tzinfo=pytz.UTC)
        CalendarEventSnapshot.objects.create(
            phone_number='+1000000002',
            event_id='evt_dup',
            title='Meeting A',
            start_time=now,
            end_time=now + datetime.timedelta(hours=1),
        )
        with self.assertRaises(IntegrityError):
            CalendarEventSnapshot.objects.create(
                phone_number='+1000000002',
                event_id='evt_dup',
                title='Meeting B',
                start_time=now,
                end_time=now + datetime.timedelta(hours=1),
            )

    def test_different_phones_can_share_event_id(self):
        """Same event_id for two different phones is allowed."""
        import datetime, pytz
        now = datetime.datetime(2026, 2, 20, 9, 0, tzinfo=pytz.UTC)
        CalendarEventSnapshot.objects.create(
            phone_number='+1000000010',
            event_id='evt_shared',
            title='Meeting',
            start_time=now,
            end_time=now + datetime.timedelta(hours=1),
        )
        # Should not raise
        CalendarEventSnapshot.objects.create(
            phone_number='+1000000011',
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

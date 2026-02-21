"""
Tests for multi-account calendar service behavior (TZA-78).

Covers:
- get_user_tz with multiple tokens (no error, uses first token)
- get_events_for_date merges events from multiple tokens
- get_events_for_date partial failure (one token fails, others succeed)
- sync_calendar_snapshot scoped to specific token
"""
import datetime
from unittest.mock import patch, MagicMock, call

import pytz
from django.test import TestCase, override_settings

from apps.calendar_bot.models import CalendarToken, CalendarEventSnapshot


@override_settings(
    GOOGLE_CLIENT_ID='fake_client_id',
    GOOGLE_CLIENT_SECRET='fake_secret',
)
class GetUserTzMultiTokenTests(TestCase):

    def test_get_user_tz_with_multiple_tokens_uses_first_created(self):
        """
        With two tokens for the same phone, get_user_tz should use the
        first token (ordered by created_at) without raising an error.
        """
        from apps.calendar_bot.calendar_service import get_user_tz

        token1 = CalendarToken.objects.create(
            phone_number='+1999000001',
            account_email='first@example.com',
            access_token='a',
            refresh_token='b',
            timezone='America/New_York',
        )
        CalendarToken.objects.create(
            phone_number='+1999000001',
            account_email='second@example.com',
            access_token='a',
            refresh_token='b',
            timezone='Europe/London',
        )
        # Should not raise MultipleObjectsReturned
        tz = get_user_tz('+1999000001')
        # Returns timezone from first-created token
        self.assertEqual(str(tz), 'America/New_York')

    def test_get_user_tz_no_tokens_returns_utc(self):
        from apps.calendar_bot.calendar_service import get_user_tz
        tz = get_user_tz('+9999000000')
        self.assertEqual(tz, pytz.UTC)


@override_settings(
    GOOGLE_CLIENT_ID='fake_client_id',
    GOOGLE_CLIENT_SECRET='fake_secret',
)
class GetEventsForDateMultiTokenTests(TestCase):
    """
    Tests for get_events_for_date with multiple tokens.
    """

    PHONE = '+1777000001'

    def _make_service_mock(self, events):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {'items': events}
        return mock_service

    def _make_event(self, title, hours_from_now):
        now = datetime.datetime.now(tz=pytz.UTC)
        start = now + datetime.timedelta(hours=hours_from_now)
        end = start + datetime.timedelta(hours=1)
        return {
            'id': f'evt_{title.replace(" ", "_")}',
            'summary': title,
            'start': {'dateTime': start.isoformat()},
            'end': {'dateTime': end.isoformat()},
        }

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_events_merged_from_two_tokens(self, mock_get_svc):
        from apps.calendar_bot.calendar_service import get_events_for_date

        token1 = CalendarToken.objects.create(
            phone_number=self.PHONE,
            account_email='t1@example.com',
            access_token='a1',
            refresh_token='r1',
        )
        token2 = CalendarToken.objects.create(
            phone_number=self.PHONE,
            account_email='t2@example.com',
            access_token='a2',
            refresh_token='r2',
        )

        event1 = self._make_event('Work Meeting', 1)
        event2 = self._make_event('Personal Event', 2)

        # Return different events for each token call
        mock_get_svc.side_effect = [
            self._make_service_mock([event1]),
            self._make_service_mock([event2]),
        ]

        today = datetime.datetime.now(tz=pytz.UTC).date()
        events = get_events_for_date(self.PHONE, today)

        # Both events should appear
        titles = [ev['summary'] for ev in events]
        self.assertIn('Work Meeting', titles)
        self.assertIn('Personal Event', titles)

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_partial_failure_continues_with_other_tokens(self, mock_get_svc):
        """
        If one token's API call fails, the function should continue
        with the remaining tokens and return their events.
        """
        from apps.calendar_bot.calendar_service import get_events_for_date

        CalendarToken.objects.create(
            phone_number=self.PHONE,
            account_email='fail@example.com',
            access_token='a_fail',
            refresh_token='r_fail',
        )
        CalendarToken.objects.create(
            phone_number=self.PHONE,
            account_email='ok@example.com',
            access_token='a_ok',
            refresh_token='r_ok',
        )

        event_ok = self._make_event('OK Meeting', 2)

        # First token raises, second succeeds
        mock_get_svc.side_effect = [
            Exception('Auth error'),
            self._make_service_mock([event_ok]),
        ]

        today = datetime.datetime.now(tz=pytz.UTC).date()
        events = get_events_for_date(self.PHONE, today)

        titles = [ev['summary'] for ev in events]
        self.assertIn('OK Meeting', titles)

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_no_tokens_returns_empty_list(self, mock_get_svc):
        from apps.calendar_bot.calendar_service import get_events_for_date

        today = datetime.datetime.now(tz=pytz.UTC).date()
        events = get_events_for_date('+9000000000', today)

        self.assertEqual(events, [])
        mock_get_svc.assert_not_called()


@override_settings(
    GOOGLE_CLIENT_ID='fake_client_id',
    GOOGLE_CLIENT_SECRET='fake_secret',
)
class SyncCalendarSnapshotMultiTokenTests(TestCase):
    """
    Tests that sync_calendar_snapshot is scoped to a specific token.
    Events from other tokens do not contaminate this token's snapshots.
    """

    PHONE = '+1888000001'

    def _make_service_mock(self, events):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {'items': events}
        return mock_service

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_snapshots_scoped_to_token(self, mock_get_svc):
        """
        Two tokens for same phone; snapshot for token1 should not appear
        when syncing token2.
        """
        from apps.calendar_bot.calendar_service import sync_calendar_snapshot

        now = datetime.datetime.now(tz=pytz.UTC)
        token1 = CalendarToken.objects.create(
            phone_number=self.PHONE,
            account_email='tok1@example.com',
            access_token='a1',
            refresh_token='r1',
        )
        token2 = CalendarToken.objects.create(
            phone_number=self.PHONE,
            account_email='tok2@example.com',
            access_token='a2',
            refresh_token='r2',
        )

        event1 = {
            'id': 'evt_t1',
            'summary': 'Token1 Meeting',
            'start': {'dateTime': (now + datetime.timedelta(hours=1)).isoformat()},
            'end': {'dateTime': (now + datetime.timedelta(hours=2)).isoformat()},
        }

        mock_get_svc.return_value = self._make_service_mock([event1])

        # Sync token1
        changes = sync_calendar_snapshot(token1)
        new_changes = [c for c in changes if c['type'] == 'new']
        self.assertEqual(len(new_changes), 1)
        self.assertEqual(new_changes[0]['event_id'], 'evt_t1')

        # Snapshot should be scoped to token1
        snap = CalendarEventSnapshot.objects.get(event_id='evt_t1')
        self.assertEqual(snap.token, token1)

        # Now sync token2 with no events — should not report evt_t1 as cancelled
        mock_get_svc.return_value = self._make_service_mock([])
        changes2 = sync_calendar_snapshot(token2)
        cancelled = [c for c in changes2 if c['type'] == 'cancelled']
        self.assertEqual(len(cancelled), 0)

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_sync_detects_new_event(self, mock_get_svc):
        from apps.calendar_bot.calendar_service import sync_calendar_snapshot

        now = datetime.datetime.now(tz=pytz.UTC)
        token = CalendarToken.objects.create(
            phone_number=self.PHONE,
            account_email='new@example.com',
            access_token='a',
            refresh_token='r',
        )
        event = {
            'id': 'evt_new_multi',
            'summary': 'New Multi Meeting',
            'start': {'dateTime': (now + datetime.timedelta(hours=1)).isoformat()},
            'end': {'dateTime': (now + datetime.timedelta(hours=2)).isoformat()},
        }
        mock_get_svc.return_value = self._make_service_mock([event])

        changes = sync_calendar_snapshot(token)
        new_changes = [c for c in changes if c['type'] == 'new']
        self.assertEqual(len(new_changes), 1)
        self.assertEqual(new_changes[0]['event_id'], 'evt_new_multi')

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_sync_send_alerts_false_no_changes_returned(self, mock_get_svc):
        from apps.calendar_bot.calendar_service import sync_calendar_snapshot

        now = datetime.datetime.now(tz=pytz.UTC)
        token = CalendarToken.objects.create(
            phone_number=self.PHONE,
            account_email='silent@example.com',
            access_token='a',
            refresh_token='r',
        )
        event = {
            'id': 'evt_silent',
            'summary': 'Silent Meeting',
            'start': {'dateTime': (now + datetime.timedelta(hours=1)).isoformat()},
            'end': {'dateTime': (now + datetime.timedelta(hours=2)).isoformat()},
        }
        mock_get_svc.return_value = self._make_service_mock([event])

        changes = sync_calendar_snapshot(token, send_alerts=False)
        self.assertEqual(changes, [])
        # But snapshot should still be created
        self.assertTrue(CalendarEventSnapshot.objects.filter(event_id='evt_silent').exists())

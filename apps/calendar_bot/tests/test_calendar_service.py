"""
Unit tests for apps.calendar_bot.calendar_service.

All Google API and credential calls are mocked; no real HTTP is made.
Updated for TZA-78 multi-account: sync_calendar_snapshot now takes a token object.
"""
import datetime
from unittest.mock import patch, MagicMock

import pytz
from django.test import TestCase, override_settings

from apps.calendar_bot.models import CalendarToken, CalendarEventSnapshot


def _make_token(phone='+1234567890', tz='UTC', email='test@example.com'):
    return CalendarToken.objects.create(
        phone_number=phone,
        account_email=email,
        access_token='access_abc',
        refresh_token='refresh_xyz',
        timezone=tz,
    )


def make_event(event_id, title, start_dt, end_dt, status='confirmed'):
    """Build a fake Google Calendar API event dict."""
    return {
        'id': event_id,
        'summary': title,
        'start': {'dateTime': start_dt.isoformat()},
        'end': {'dateTime': end_dt.isoformat()},
        'status': status,
    }


# -------------------------------------------------------------------------
# get_user_tz
# -------------------------------------------------------------------------
class GetUserTzTests(TestCase):

    def test_returns_utc_when_no_token(self):
        from apps.calendar_bot.calendar_service import get_user_tz
        tz = get_user_tz('+9999999999')
        self.assertEqual(tz, pytz.UTC)

    def test_returns_user_timezone(self):
        from apps.calendar_bot.calendar_service import get_user_tz
        _make_token(phone='+1000000001', tz='America/New_York', email='tz1@example.com')
        tz = get_user_tz('+1000000001')
        self.assertEqual(str(tz), 'America/New_York')

    def test_returns_utc_for_invalid_stored_timezone(self):
        from apps.calendar_bot.calendar_service import get_user_tz
        _make_token(phone='+1000000002', tz='Not/AValidTZ', email='tz2@example.com')
        tz = get_user_tz('+1000000002')
        self.assertEqual(tz, pytz.UTC)


# -------------------------------------------------------------------------
# sync_calendar_snapshot
# -------------------------------------------------------------------------
@override_settings(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
    GOOGLE_CLIENT_ID='fake_client_id',
    GOOGLE_CLIENT_SECRET='fake_secret',
)
class SyncCalendarSnapshotTests(TestCase):

    PHONE = '+1234567890'

    def setUp(self):
        self.token = _make_token(phone=self.PHONE, email='sync@example.com')

    def _make_service_mock(self, events):
        """Return a mock Google Calendar service whose events().list().execute() returns events."""
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {'items': events}
        return mock_service

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_detects_new_event(self, mock_get_svc):
        from apps.calendar_bot.calendar_service import sync_calendar_snapshot

        now = datetime.datetime.now(tz=pytz.UTC)
        event = make_event('evt_1', 'New Meeting', now + datetime.timedelta(hours=1), now + datetime.timedelta(hours=2))
        mock_get_svc.return_value = self._make_service_mock([event])

        changes = sync_calendar_snapshot(self.token)

        new_changes = [c for c in changes if c['type'] == 'new']
        self.assertEqual(len(new_changes), 1)
        self.assertEqual(new_changes[0]['event_id'], 'evt_1')
        self.assertEqual(new_changes[0]['title'], 'New Meeting')
        # Snapshot should now exist in DB
        self.assertTrue(CalendarEventSnapshot.objects.filter(event_id='evt_1').exists())

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_detects_rescheduled_event(self, mock_get_svc):
        from apps.calendar_bot.calendar_service import sync_calendar_snapshot

        now = datetime.datetime.now(tz=pytz.UTC)
        original_start = now + datetime.timedelta(hours=1)
        new_start = now + datetime.timedelta(hours=3)

        snap = CalendarEventSnapshot.objects.create(
            phone_number=self.PHONE,
            token=self.token,
            event_id='evt_reschedule',
            title='Team Meeting',
            start_time=original_start,
            end_time=original_start + datetime.timedelta(hours=1),
            status='active',
        )
        CalendarEventSnapshot.objects.filter(pk=snap.pk).update(
            updated_at=now - datetime.timedelta(minutes=10)
        )

        event = make_event(
            'evt_reschedule', 'Team Meeting',
            new_start, new_start + datetime.timedelta(hours=1)
        )
        mock_get_svc.return_value = self._make_service_mock([event])

        changes = sync_calendar_snapshot(self.token)

        rescheduled = [c for c in changes if c['type'] == 'rescheduled']
        self.assertEqual(len(rescheduled), 1)
        self.assertEqual(rescheduled[0]['event_id'], 'evt_reschedule')
        self.assertEqual(rescheduled[0]['old_start'], original_start)

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_detects_cancelled_event(self, mock_get_svc):
        from apps.calendar_bot.calendar_service import sync_calendar_snapshot

        now = datetime.datetime.now(tz=pytz.UTC)
        old_start = now + datetime.timedelta(hours=1)

        snap = CalendarEventSnapshot.objects.create(
            phone_number=self.PHONE,
            token=self.token,
            event_id='evt_cancelled',
            title='Gone Meeting',
            start_time=old_start,
            end_time=old_start + datetime.timedelta(hours=1),
            status='active',
        )
        CalendarEventSnapshot.objects.filter(pk=snap.pk).update(
            updated_at=now - datetime.timedelta(minutes=10)
        )

        mock_get_svc.return_value = self._make_service_mock([])  # no events returned

        changes = sync_calendar_snapshot(self.token)

        cancelled = [c for c in changes if c['type'] == 'cancelled']
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(cancelled[0]['event_id'], 'evt_cancelled')

        snap.refresh_from_db()
        self.assertEqual(snap.status, 'cancelled')

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_no_changes_when_event_unchanged(self, mock_get_svc):
        from apps.calendar_bot.calendar_service import sync_calendar_snapshot

        now = datetime.datetime.now(tz=pytz.UTC)
        start_time = now + datetime.timedelta(hours=2)

        CalendarEventSnapshot.objects.create(
            phone_number=self.PHONE,
            token=self.token,
            event_id='evt_same',
            title='Stable Meeting',
            start_time=start_time,
            end_time=start_time + datetime.timedelta(hours=1),
            status='active',
        )

        event = make_event('evt_same', 'Stable Meeting', start_time, start_time + datetime.timedelta(hours=1))
        mock_get_svc.return_value = self._make_service_mock([event])

        changes = sync_calendar_snapshot(self.token)
        self.assertEqual(changes, [])

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_debounce_skips_recent_reschedule(self, mock_get_svc):
        from apps.calendar_bot.calendar_service import sync_calendar_snapshot

        now = datetime.datetime.now(tz=pytz.UTC)
        original_start = now + datetime.timedelta(hours=1)
        new_start = now + datetime.timedelta(hours=3)

        CalendarEventSnapshot.objects.create(
            phone_number=self.PHONE,
            token=self.token,
            event_id='evt_debounce',
            title='Debounced Meeting',
            start_time=original_start,
            end_time=original_start + datetime.timedelta(hours=1),
            status='active',
        )

        event = make_event('evt_debounce', 'Debounced Meeting', new_start, new_start + datetime.timedelta(hours=1))
        mock_get_svc.return_value = self._make_service_mock([event])

        changes = sync_calendar_snapshot(self.token)

        rescheduled = [c for c in changes if c['type'] == 'rescheduled']
        self.assertEqual(len(rescheduled), 0)

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_all_day_events_skipped_in_snapshot(self, mock_get_svc):
        """All-day events (no dateTime) should not appear in snapshot tracking."""
        from apps.calendar_bot.calendar_service import sync_calendar_snapshot

        all_day_event = {
            'id': 'evt_allday',
            'summary': 'Company Holiday',
            'start': {'date': '2026-02-20'},
            'end': {'date': '2026-02-21'},
        }
        mock_get_svc.return_value = self._make_service_mock([all_day_event])

        changes = sync_calendar_snapshot(self.token)
        self.assertEqual(changes, [])
        self.assertFalse(CalendarEventSnapshot.objects.filter(event_id='evt_allday').exists())

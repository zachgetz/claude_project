"""
Unit tests for TZA-107: Fix birthday calendar detection in get_birthdays_next_week.

Covers:
- Detection by case-insensitive summary match ("birthdays", "Birthdays", "BIRTHDAYS")
- Detection by Google's known birthday calendar ID (#contacts@group.v.calendar.google.com)
- No birthday calendar in calendarList -> returns empty list
- Birthday events are returned correctly when calendar is found
- Deduplication across multiple tokens (seen_ids set)
- calendarList API failure is handled gracefully (skip token, try next)

All Google API and credential calls are mocked; no real HTTP is made.
"""
import datetime
from unittest.mock import patch, MagicMock, call

import pytz
from django.test import TestCase, override_settings

from apps.calendar_bot.models import CalendarToken

GOOGLE_BIRTHDAY_CAL_ID = '#contacts@group.v.calendar.google.com'


def _make_token(phone, email='test@example.com', tz='UTC'):
    return CalendarToken.objects.create(
        phone_number=phone,
        account_email=email,
        access_token='access_token',
        refresh_token='refresh_token',
        timezone=tz,
    )


def _birthday_event(event_id, summary, date_str):
    """Build a fake birthday event dict (all-day, uses 'date' not 'dateTime')."""
    return {
        'id': event_id,
        'summary': summary,
        'start': {'date': date_str},
        'end': {'date': date_str},
    }


def _make_service_mock(cal_list_items, birthday_events):
    """
    Build a MagicMock Google Calendar service that:
    - Returns cal_list_items from calendarList().list().execute()
    - Returns birthday_events from events().list().execute()
    """
    mock_service = MagicMock()
    mock_service.calendarList().list().execute.return_value = {'items': cal_list_items}
    mock_service.events().list().execute.return_value = {'items': birthday_events}
    return mock_service


@override_settings(
    GOOGLE_CLIENT_ID='fake_id',
    GOOGLE_CLIENT_SECRET='fake_secret',
)
class BirthdayCalendarDetectionTests(TestCase):
    """
    Tests for birthday calendar lookup logic in get_birthdays_next_week.
    """

    PHONE = '+15550001111'

    def setUp(self):
        self.token = _make_token(self.PHONE, email='birthday_test@example.com', tz='UTC')

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_detects_birthday_calendar_by_exact_name(self, mock_get_svc):
        """Calendar with summary 'Birthdays' (exact) should be found."""
        from apps.calendar_bot.calendar_service import get_birthdays_next_week

        cal_list = [{'id': 'bday_cal_id', 'summary': 'Birthdays'}]
        event = _birthday_event('evt1', "Alice's Birthday", '2026-02-25')
        mock_get_svc.return_value = _make_service_mock(cal_list, [event])

        results = get_birthdays_next_week(self.PHONE)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['summary'], "Alice's Birthday")

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_detects_birthday_calendar_case_insensitive_lower(self, mock_get_svc):
        """Calendar with summary 'birthdays' (lowercase) should be found."""
        from apps.calendar_bot.calendar_service import get_birthdays_next_week

        cal_list = [{'id': 'bday_lower', 'summary': 'birthdays'}]
        event = _birthday_event('evt2', "Bob's Birthday", '2026-02-26')
        mock_get_svc.return_value = _make_service_mock(cal_list, [event])

        results = get_birthdays_next_week(self.PHONE)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['summary'], "Bob's Birthday")

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_detects_birthday_calendar_case_insensitive_upper(self, mock_get_svc):
        """Calendar with summary 'BIRTHDAYS' (uppercase) should be found."""
        from apps.calendar_bot.calendar_service import get_birthdays_next_week

        cal_list = [{'id': 'bday_upper', 'summary': 'BIRTHDAYS'}]
        event = _birthday_event('evt3', "Carol's Birthday", '2026-02-27')
        mock_get_svc.return_value = _make_service_mock(cal_list, [event])

        results = get_birthdays_next_week(self.PHONE)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['summary'], "Carol's Birthday")

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_detects_birthday_calendar_by_google_id(self, mock_get_svc):
        """
        Calendar with the known Google birthday ID should be found even when
        its summary is in a non-English locale (e.g. Hebrew 'ימי הולדת').
        """
        from apps.calendar_bot.calendar_service import get_birthdays_next_week

        cal_list = [
            {'id': GOOGLE_BIRTHDAY_CAL_ID, 'summary': '\u05d9\u05de\u05d9 \u05d4\u05d5\u05dc\u05d3\u05ea'},  # 'ימי הולדת' in Hebrew
        ]
        event = _birthday_event('evt4', "Dave's Birthday", '2026-02-28')
        mock_get_svc.return_value = _make_service_mock(cal_list, [event])

        results = get_birthdays_next_week(self.PHONE)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['summary'], "Dave's Birthday")

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_returns_empty_when_no_birthday_calendar(self, mock_get_svc):
        """If calendarList has no 'Birthdays' calendar, return empty list."""
        from apps.calendar_bot.calendar_service import get_birthdays_next_week

        cal_list = [
            {'id': 'primary', 'summary': 'My Calendar'},
            {'id': 'work', 'summary': 'Work'},
        ]
        mock_get_svc.return_value = _make_service_mock(cal_list, [])

        results = get_birthdays_next_week(self.PHONE)
        self.assertEqual(results, [])

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_returns_empty_when_no_token(self, mock_get_svc):
        """If no CalendarToken exists for the phone, return empty list immediately."""
        from apps.calendar_bot.calendar_service import get_birthdays_next_week

        results = get_birthdays_next_week('+99999999999')  # phone with no token
        self.assertEqual(results, [])
        mock_get_svc.assert_not_called()

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_birthday_events_sorted_by_date(self, mock_get_svc):
        """Multiple birthday events should be returned sorted by raw_date."""
        from apps.calendar_bot.calendar_service import get_birthdays_next_week

        cal_list = [{'id': 'bday_id', 'summary': 'Birthdays'}]
        events = [
            _birthday_event('evt_c', 'Charlie', '2026-02-28'),
            _birthday_event('evt_a', 'Alice', '2026-02-22'),
            _birthday_event('evt_b', 'Bob', '2026-02-25'),
        ]
        mock_get_svc.return_value = _make_service_mock(cal_list, events)

        results = get_birthdays_next_week(self.PHONE)
        self.assertEqual(len(results), 3)
        # Should be sorted by date ascending
        self.assertEqual(results[0]['summary'], 'Alice')
        self.assertEqual(results[1]['summary'], 'Bob')
        self.assertEqual(results[2]['summary'], 'Charlie')

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_deduplicates_events_across_multiple_tokens(self, mock_get_svc):
        """Same event_id from two tokens should only appear once in results."""
        from apps.calendar_bot.calendar_service import get_birthdays_next_week

        # Create a second token for same phone
        _make_token(self.PHONE, email='second@example.com', tz='UTC')

        cal_list = [{'id': GOOGLE_BIRTHDAY_CAL_ID, 'summary': 'Birthdays'}]
        shared_event = _birthday_event('shared_evt', "Eve's Birthday", '2026-02-23')

        mock_service = _make_service_mock(cal_list, [shared_event])
        mock_get_svc.return_value = mock_service

        results = get_birthdays_next_week(self.PHONE)
        # Even though we have 2 tokens (2 calls), the event should appear only once
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['summary'], "Eve's Birthday")

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_calendarlist_api_failure_skips_token_gracefully(self, mock_get_svc):
        """
        If calendarList().list().execute() raises an exception for one token,
        that token is skipped and an empty list is returned (not an error).
        """
        from apps.calendar_bot.calendar_service import get_birthdays_next_week

        mock_service = MagicMock()
        mock_service.calendarList().list().execute.side_effect = Exception('API error')
        mock_get_svc.return_value = mock_service

        # Should not raise, just return empty
        results = get_birthdays_next_week(self.PHONE)
        self.assertEqual(results, [])

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_calendarlist_logged_for_debugging(self, mock_get_svc):
        """
        Verify that the calendar list is logged when birthdays lookup is performed.
        This tests the logging requirement of TZA-107.
        """
        import logging
        from apps.calendar_bot.calendar_service import get_birthdays_next_week

        cal_list = [
            {'id': 'primary', 'summary': 'Primary'},
            {'id': GOOGLE_BIRTHDAY_CAL_ID, 'summary': 'Birthdays'},
        ]
        mock_get_svc.return_value = _make_service_mock(cal_list, [])

        with self.assertLogs('apps.calendar_bot.calendar_service', level='INFO') as log_cm:
            get_birthdays_next_week(self.PHONE)

        # Verify that at least one log line mentions calendars_found or similar
        log_output = '\n'.join(log_cm.output)
        self.assertIn('calendars_found', log_output)
        # Verify the birthday calendar was logged as found
        self.assertIn('Birthday calendar found', log_output)

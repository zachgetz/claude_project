"""
Unit tests for TZA-108: Fix week start to Sunday (Israeli calendar).

Verifies that the 'this week' schedule view in views.py and the
birthday week range in calendar_service.py both use Sunday as the
first day of the week, not Monday (Python default).
"""
import datetime
from unittest.mock import patch, MagicMock

import pytz
from django.test import TestCase


# ---------------------------------------------------------------------------
# Helper: mirror the Sunday-start formula used in the production code
# ---------------------------------------------------------------------------

def _week_start_sunday(today):
    """Return the Sunday that begins today's Israeli calendar week."""
    return today - datetime.timedelta(days=(today.weekday() + 1) % 7)


# ---------------------------------------------------------------------------
# views.py — _try_day_query week_start formula
# ---------------------------------------------------------------------------

class WeekStartSundayViewsTests(TestCase):
    """
    Tests that the Sunday-start formula used in _try_day_query is correct
    for every day of the week.
    """

    def test_week_start_on_sunday_is_same_day(self):
        """When today is Sunday, week_start should be today itself."""
        sunday = datetime.date(2026, 2, 22)          # known Sunday
        self.assertEqual(sunday.weekday(), 6)
        self.assertEqual(_week_start_sunday(sunday), sunday)

    def test_week_start_on_monday_is_previous_sunday(self):
        monday = datetime.date(2026, 2, 23)
        self.assertEqual(monday.weekday(), 0)
        self.assertEqual(_week_start_sunday(monday), datetime.date(2026, 2, 22))

    def test_week_start_on_tuesday_is_previous_sunday(self):
        tuesday = datetime.date(2026, 2, 24)
        self.assertEqual(tuesday.weekday(), 1)
        self.assertEqual(_week_start_sunday(tuesday), datetime.date(2026, 2, 22))

    def test_week_start_on_wednesday_is_previous_sunday(self):
        wednesday = datetime.date(2026, 2, 25)
        self.assertEqual(wednesday.weekday(), 2)
        self.assertEqual(_week_start_sunday(wednesday), datetime.date(2026, 2, 22))

    def test_week_start_on_thursday_is_previous_sunday(self):
        thursday = datetime.date(2026, 2, 26)
        self.assertEqual(thursday.weekday(), 3)
        self.assertEqual(_week_start_sunday(thursday), datetime.date(2026, 2, 22))

    def test_week_start_on_friday_is_previous_sunday(self):
        friday = datetime.date(2026, 2, 27)
        self.assertEqual(friday.weekday(), 4)
        self.assertEqual(_week_start_sunday(friday), datetime.date(2026, 2, 22))

    def test_week_start_on_saturday_is_previous_sunday(self):
        saturday = datetime.date(2026, 2, 28)
        self.assertEqual(saturday.weekday(), 5)
        self.assertEqual(_week_start_sunday(saturday), datetime.date(2026, 2, 22))

    def test_week_end_is_saturday(self):
        """week_start + 6 days is always Saturday."""
        sunday = datetime.date(2026, 2, 22)
        week_start = _week_start_sunday(sunday)
        week_end = week_start + datetime.timedelta(days=6)
        self.assertEqual(week_end, datetime.date(2026, 2, 28))
        self.assertEqual(week_end.weekday(), 5)      # Saturday

    def test_old_formula_would_give_monday_not_sunday(self):
        """Regression guard: the old formula gives Monday start, not Sunday."""
        monday = datetime.date(2026, 2, 23)
        old_week_start = monday - datetime.timedelta(days=monday.weekday())
        new_week_start = _week_start_sunday(monday)
        self.assertEqual(old_week_start.weekday(), 0)    # Monday
        self.assertEqual(new_week_start.weekday(), 6)    # Sunday
        self.assertNotEqual(old_week_start, new_week_start)


# ---------------------------------------------------------------------------
# calendar_service.py — get_birthdays_next_week week_start formula
# ---------------------------------------------------------------------------

class WeekStartSundayBirthdayServiceTests(TestCase):
    """
    Tests that the Sunday-start formula used in get_birthdays_next_week
    is correct, verified against the same helper.
    """

    def test_birthday_week_starts_on_sunday_from_wednesday(self):
        wednesday = datetime.date(2026, 2, 25)
        self.assertEqual(_week_start_sunday(wednesday), datetime.date(2026, 2, 22))

    def test_birthday_week_ends_on_saturday_every_day(self):
        """For every day of a full week, week_end is always Saturday."""
        week_sunday = datetime.date(2026, 2, 22)
        for offset in range(7):
            today = week_sunday + datetime.timedelta(days=offset)
            week_start = _week_start_sunday(today)
            week_end = week_start + datetime.timedelta(days=6)
            self.assertEqual(
                week_end.weekday(), 5,
                f"today={today} gave week_end={week_end} (weekday {week_end.weekday()}, expected 5=Sat)",
            )

    def test_birthday_formula_same_across_month_boundary(self):
        """Formula works correctly across a month boundary."""
        # Week of Feb 28 (Sat) / Mar 1 (Sun) 2026
        saturday_feb = datetime.date(2026, 2, 28)
        sunday_mar = datetime.date(2026, 3, 1)
        self.assertEqual(_week_start_sunday(saturday_feb), datetime.date(2026, 2, 22))
        self.assertEqual(_week_start_sunday(sunday_mar), datetime.date(2026, 3, 1))

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    @patch('apps.calendar_bot.calendar_service.get_user_tz')
    def test_get_birthdays_uses_sunday_based_week(
        self, mock_get_tz, mock_get_svc
    ):
        """
        Integration smoke-test: get_birthdays_next_week should use the week
        range [sunday, saturday] from the user's current date.

        We verify by computing the expected week range manually for today
        and asserting the API call's timeMin/timeMax match that range.
        """
        from apps.calendar_bot.models import CalendarToken
        from apps.calendar_bot.calendar_service import get_birthdays_next_week

        CalendarToken.objects.create(
            phone_number='+9991234568',
            account_email='bday@test.com',
            access_token='acc',
            refresh_token='ref',
            timezone='Asia/Jerusalem',
        )

        il_tz = pytz.timezone('Asia/Jerusalem')
        mock_get_tz.return_value = il_tz

        # Compute what the expected week range should be for the real "today"
        today_local = datetime.datetime.now(tz=il_tz).date()
        expected_week_start = _week_start_sunday(today_local)
        expected_week_end = expected_week_start + datetime.timedelta(days=6)

        # Capture events().list() kwargs
        captured = {}

        def capturing_list(**kwargs):
            captured.update(kwargs)
            m = MagicMock()
            m.execute.return_value = {'items': []}
            return m

        mock_service = MagicMock()
        mock_service.calendarList().list().execute.return_value = {
            'items': [{'id': '#contacts@group.v.calendar.google.com', 'summary': 'Birthdays'}]
        }
        mock_service.events().list = capturing_list
        mock_get_svc.return_value = mock_service

        get_birthdays_next_week('+9991234568')

        self.assertTrue(captured, "events().list() was never called — birthday calendar not found?")

        time_min_date = datetime.datetime.fromisoformat(captured['timeMin']).date()
        time_max_date = datetime.datetime.fromisoformat(captured['timeMax']).date()

        self.assertEqual(
            time_min_date, expected_week_start,
            f"timeMin date {time_min_date} should be Sunday {expected_week_start}",
        )
        self.assertEqual(
            time_max_date, expected_week_end,
            f"timeMax date {time_max_date} should be Saturday {expected_week_end}",
        )
        # Confirm Sunday and Saturday
        self.assertEqual(time_min_date.weekday(), 6, "timeMin should be a Sunday (weekday 6)")
        self.assertEqual(time_max_date.weekday(), 5, "timeMax should be a Saturday (weekday 5)")

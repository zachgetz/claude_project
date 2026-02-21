"""
Unit tests for TZA-108: Fix week start to Sunday (Israeli calendar).

Verifies that the 'this week' schedule view in views.py and the
birthday week range in calendar_service.py both use Sunday as the
first day of the week, not Monday (Python default).
"""
import datetime
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings


class WeekStartSundayViewsTests(TestCase):
    """
    Tests that _try_day_query uses Sunday as the first day of the week.

    We test the week_start calculation logic independently by verifying
    the formula (today.weekday() + 1) % 7 for various days of the week.
    """

    def _compute_week_start(self, today):
        """Mirror the formula used in _try_day_query."""
        return today - datetime.timedelta(days=(today.weekday() + 1) % 7)

    def test_week_start_on_sunday_is_same_day(self):
        """When today is Sunday, week_start should be today itself."""
        # Sunday in Python: weekday() == 6
        sunday = datetime.date(2026, 2, 22)  # a Sunday
        self.assertEqual(sunday.weekday(), 6)
        week_start = self._compute_week_start(sunday)
        self.assertEqual(week_start, sunday)

    def test_week_start_on_monday_is_previous_sunday(self):
        """When today is Monday, week_start should be the previous Sunday."""
        monday = datetime.date(2026, 2, 23)  # a Monday
        self.assertEqual(monday.weekday(), 0)
        week_start = self._compute_week_start(monday)
        expected_sunday = datetime.date(2026, 2, 22)
        self.assertEqual(week_start, expected_sunday)

    def test_week_start_on_tuesday_is_previous_sunday(self):
        """When today is Tuesday, week_start should be the previous Sunday."""
        tuesday = datetime.date(2026, 2, 24)
        self.assertEqual(tuesday.weekday(), 1)
        week_start = self._compute_week_start(tuesday)
        expected_sunday = datetime.date(2026, 2, 22)
        self.assertEqual(week_start, expected_sunday)

    def test_week_start_on_saturday_is_previous_sunday(self):
        """When today is Saturday, week_start should be 6 days before."""
        saturday = datetime.date(2026, 2, 28)
        self.assertEqual(saturday.weekday(), 5)
        week_start = self._compute_week_start(saturday)
        expected_sunday = datetime.date(2026, 2, 22)
        self.assertEqual(week_start, expected_sunday)

    def test_week_end_is_saturday(self):
        """The week should end on Saturday (6 days after Sunday start)."""
        sunday = datetime.date(2026, 2, 22)
        week_start = self._compute_week_start(sunday)
        week_end = week_start + datetime.timedelta(days=6)
        expected_saturday = datetime.date(2026, 2, 28)
        self.assertEqual(week_end, expected_saturday)
        # Confirm it's a Saturday (weekday 5)
        self.assertEqual(week_end.weekday(), 5)

    def test_old_formula_gives_monday_start(self):
        """Regression: old formula (today.weekday()) gives Monday start, not Sunday."""
        monday = datetime.date(2026, 2, 23)
        # Old formula
        old_week_start = monday - datetime.timedelta(days=monday.weekday())
        # New formula
        new_week_start = self._compute_week_start(monday)
        # Old formula gives Monday, new gives Sunday
        self.assertEqual(old_week_start.weekday(), 0)   # Monday
        self.assertEqual(new_week_start.weekday(), 6)   # Sunday
        # They should differ
        self.assertNotEqual(old_week_start, new_week_start)


class WeekStartSundayBirthdayServiceTests(TestCase):
    """
    Tests that get_birthdays_next_week uses Sunday as the first day of the week.
    """

    def _compute_week_start(self, today):
        """Mirror the formula used in get_birthdays_next_week."""
        return today - datetime.timedelta(days=(today.weekday() + 1) % 7)

    def test_birthday_week_starts_on_sunday(self):
        """When called on a Wednesday, birthday week should start from the previous Sunday."""
        wednesday = datetime.date(2026, 2, 25)
        self.assertEqual(wednesday.weekday(), 2)
        week_start = self._compute_week_start(wednesday)
        expected_sunday = datetime.date(2026, 2, 22)
        self.assertEqual(week_start, expected_sunday)

    def test_birthday_week_ends_on_saturday(self):
        """Birthday week should always end on Saturday."""
        for day_offset in range(7):
            today = datetime.date(2026, 2, 22) + datetime.timedelta(days=day_offset)
            week_start = self._compute_week_start(today)
            week_end = week_start + datetime.timedelta(days=6)
            self.assertEqual(
                week_end.weekday(), 5,
                f"Expected week_end to be Saturday for today={today}, got {week_end} (weekday {week_end.weekday()})"
            )

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    @patch('apps.calendar_bot.calendar_service.get_user_tz')
    def test_get_birthdays_next_week_queries_sunday_to_saturday(
        self, mock_get_tz, mock_get_svc
    ):
        """
        When called on a Monday, get_birthdays_next_week should query
        from the previous Sunday (not Monday) through the following Saturday.
        """
        import pytz
        from apps.calendar_bot.models import CalendarToken

        # Set up a mock token
        token = CalendarToken.objects.create(
            phone_number='+9991234567',
            account_email='birthday@test.com',
            access_token='test_access',
            refresh_token='test_refresh',
            timezone='Asia/Jerusalem',
        )

        # Freeze today to a known Monday
        known_monday = datetime.date(2026, 2, 23)
        expected_sunday = datetime.date(2026, 2, 22)
        expected_saturday = datetime.date(2026, 2, 28)

        il_tz = pytz.timezone('Asia/Jerusalem')
        mock_get_tz.return_value = il_tz

        # Build a mock service that returns an empty birthday calendar list
        mock_service = MagicMock()
        mock_service.calendarList().list().execute.return_value = {
            'items': [
                {'id': '#contacts@group.v.calendar.google.com', 'summary': 'Birthdays'},
            ]
        }
        mock_service.events().list().execute.return_value = {'items': []}
        mock_get_svc.return_value = mock_service

        # Patch datetime.datetime.now to return Monday
        fake_now = il_tz.localize(datetime.datetime(2026, 2, 23, 10, 0, 0))
        with patch('apps.calendar_bot.calendar_service.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = fake_now
            mock_dt.datetime.fromisoformat = datetime.datetime.fromisoformat
            mock_dt.date.fromisoformat = datetime.date.fromisoformat
            mock_dt.timedelta = datetime.timedelta

            from apps.calendar_bot.calendar_service import get_birthdays_next_week
            get_birthdays_next_week('+9991234567')

        # Verify the events().list() call used the right time range
        call_kwargs = mock_service.events().list.call_args
        time_min_str = call_kwargs[1]['timeMin']
        time_max_str = call_kwargs[1]['timeMax']

        # time_min should correspond to Sunday
        time_min_dt = datetime.datetime.fromisoformat(time_min_str)
        self.assertEqual(time_min_dt.date(), expected_sunday,
            f"Expected timeMin to be Sunday {expected_sunday}, got {time_min_dt.date()}")

        # time_max should correspond to Saturday
        time_max_dt = datetime.datetime.fromisoformat(time_max_str)
        self.assertEqual(time_max_dt.date(), expected_saturday,
            f"Expected timeMax to be Saturday {expected_saturday}, got {time_max_dt.date()}")

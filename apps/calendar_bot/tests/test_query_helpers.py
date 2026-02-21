"""
Unit tests for apps.calendar_bot.query_helpers.

Tests resolve_day() edge cases and format_events_for_day() output.
"""
import datetime
from django.test import TestCase

from apps.calendar_bot.query_helpers import resolve_day, format_events_for_day, format_week_view


class ResolveDayTests(TestCase):
    """resolve_day(text, today) -> (date_or_sentinel, label_or_None)"""

    def _wednesday(self):
        """Return a fixed Wednesday date: 2026-02-18."""
        return datetime.date(2026, 2, 18)  # weekday 2 = Wednesday

    def _monday(self):
        """Return a fixed Monday date: 2026-02-16."""
        return datetime.date(2026, 2, 16)  # weekday 0 = Monday

    def _friday(self):
        """Return a fixed Friday date: 2026-02-20."""
        return datetime.date(2026, 2, 20)  # weekday 4 = Friday

    # -- today / tomorrow --------------------------------------------------

    def test_today_returns_today(self):
        today = self._wednesday()
        date, label = resolve_day('today', today)
        self.assertEqual(date, today)
        self.assertIsNotNone(label)

    def test_meetings_alias_returns_today(self):
        today = self._wednesday()
        date, label = resolve_day('meetings', today)
        self.assertEqual(date, today)

    def test_empty_string_returns_today(self):
        today = self._wednesday()
        date, label = resolve_day('', today)
        self.assertEqual(date, today)

    def test_tomorrow_returns_next_day(self):
        today = self._wednesday()
        date, label = resolve_day('tomorrow', today)
        self.assertEqual(date, today + datetime.timedelta(days=1))

    # -- plain day names ---------------------------------------------------

    def test_this_friday_when_today_is_wednesday(self):
        """'friday' when today=Wednesday -> this Friday (2 days ahead)."""
        today = self._wednesday()  # Wed Feb 18
        date, label = resolve_day('friday', today)
        self.assertEqual(date, datetime.date(2026, 2, 20))  # same week Friday

    def test_this_friday_when_today_is_friday(self):
        """'friday' when today=Friday -> today itself (days_ahead == 0)."""
        today = self._friday()  # Fri Feb 20
        date, label = resolve_day('friday', today)
        self.assertEqual(date, today)

    def test_this_monday_when_today_is_wednesday(self):
        """'monday' when today=Wednesday -> NEXT Monday (days_ahead negative, +7)."""
        today = self._wednesday()  # Wed Feb 18
        date, label = resolve_day('monday', today)
        # Monday already passed this week, so jump forward
        self.assertGreater(date, today)
        self.assertEqual(date.weekday(), 0)  # must be a Monday

    def test_plain_saturday_when_today_is_friday(self):
        """'saturday' when today=Friday -> tomorrow (days_ahead == 1)."""
        today = self._friday()  # Fri Feb 20
        date, label = resolve_day('saturday', today)
        self.assertEqual(date, today + datetime.timedelta(days=1))

    def test_plain_sunday_when_today_is_friday(self):
        """'sunday' when today=Friday -> this Sunday."""
        today = self._friday()  # Fri Feb 20
        date, label = resolve_day('sunday', today)
        self.assertEqual(date, today + datetime.timedelta(days=2))

    # -- 'next <day>' ------------------------------------------------------

    def test_next_friday_when_today_is_wednesday(self):
        """'next friday' from Wednesday -> Friday of NEXT week."""
        today = self._wednesday()  # Wed Feb 18
        date, label = resolve_day('next friday', today)
        # next week Friday
        self.assertEqual(date.weekday(), 4)  # Friday
        self.assertGreater(date, today + datetime.timedelta(days=7))

    def test_next_monday_when_today_is_monday(self):
        """'next monday' from Monday -> always goes to the following Monday."""
        today = self._monday()  # Mon Feb 16
        date, label = resolve_day('next monday', today)
        self.assertEqual(date.weekday(), 0)  # Monday
        self.assertGreater(date, today)
        # Should be exactly 7 days ahead (same weekday, same week offset logic)
        self.assertEqual(date, today + datetime.timedelta(days=7))

    def test_next_saturday_when_today_is_friday(self):
        """'next saturday' from Friday -> NEXT week's Saturday (not tomorrow)."""
        today = self._friday()  # Fri Feb 20
        date, label = resolve_day('next saturday', today)
        self.assertEqual(date.weekday(), 5)  # Saturday
        # Must be more than 1 day away
        self.assertGreater(date, today + datetime.timedelta(days=1))

    # -- 'this week' -------------------------------------------------------

    def test_this_week_returns_week_sentinel(self):
        today = self._wednesday()
        result, label = resolve_day('this week', today)
        self.assertEqual(result, 'week')
        # label is None for week
        self.assertIsNone(label)

    # -- no match ----------------------------------------------------------

    def test_unknown_text_returns_none(self):
        today = self._wednesday()
        result, label = resolve_day('bananas', today)
        self.assertIsNone(result)
        self.assertIsNone(label)

    # -- text variations ---------------------------------------------------

    def test_whats_on_prefix_stripped(self):
        today = self._friday()
        date, label = resolve_day("what's on friday", today)
        self.assertEqual(date, today)

    def test_meetings_prefix_stripped(self):
        today = self._friday()
        date, label = resolve_day('meetings friday', today)
        self.assertEqual(date, today)

    def test_abbreviated_day_names(self):
        today = self._wednesday()
        date, label = resolve_day('fri', today)
        self.assertEqual(date.weekday(), 4)


class FormatEventsForDayTests(TestCase):

    def test_empty_events_returns_free_day_message(self):
        result = format_events_for_day([], 'Wednesday, Feb 18')
        self.assertIn('Nothing scheduled', result)
        self.assertIn('Wednesday, Feb 18', result)
        self.assertIn('Free day', result)

    def test_single_event_formatted(self):
        events = [{'start_str': '09:00', 'summary': 'Team Standup'}]
        result = format_events_for_day(events, 'Wednesday, Feb 18')
        self.assertIn('09:00', result)
        self.assertIn('Team Standup', result)
        self.assertIn('1 meeting', result)

    def test_multiple_events_formatted(self):
        events = [
            {'start_str': '09:00', 'summary': 'Standup'},
            {'start_str': '14:00', 'summary': 'Design Review'},
        ]
        result = format_events_for_day(events, 'Wednesday, Feb 18')
        self.assertIn('Standup', result)
        self.assertIn('Design Review', result)
        self.assertIn('2 meetings', result)

    def test_header_contains_date_label(self):
        events = [{'start_str': '10:00', 'summary': 'Sprint Planning'}]
        result = format_events_for_day(events, 'Thursday, Feb 19')
        self.assertIn('Thursday, Feb 19', result)

    def test_all_day_event_uses_all_day_str(self):
        events = [{'start_str': 'All day', 'summary': 'Company Holiday'}]
        result = format_events_for_day(events, 'Friday, Feb 20')
        self.assertIn('All day', result)
        self.assertIn('Company Holiday', result)


class FormatWeekViewTests(TestCase):

    def test_week_header_contains_date_range(self):
        week_start = datetime.date(2026, 2, 16)  # Monday
        week_end = datetime.date(2026, 2, 22)    # Sunday
        result = format_week_view({}, week_start, week_end)
        self.assertIn('Feb 16', result)
        self.assertIn('Feb 22', result)

    def test_free_day_shown_for_empty_events(self):
        week_start = datetime.date(2026, 2, 16)
        week_end = datetime.date(2026, 2, 22)
        result = format_week_view({}, week_start, week_end)
        self.assertIn('Free', result)

    def test_events_shown_per_day(self):
        week_start = datetime.date(2026, 2, 16)
        week_end = datetime.date(2026, 2, 22)
        week_events = {
            datetime.date(2026, 2, 17): [{'start_str': '09:00', 'summary': 'Standup'}],
        }
        result = format_week_view(week_events, week_start, week_end)
        self.assertIn('Standup', result)
        self.assertIn('09:00', result)

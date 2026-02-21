"""
Helpers for natural-language day resolution used by the WhatsApp webhook.
"""
import datetime
import pytz

DAY_NAMES = {
    'monday': 0,
    'tuesday': 1,
    'wednesday': 2,
    'thursday': 3,
    'friday': 4,
    'saturday': 5,
    'sunday': 6,
    'mon': 0,
    'tue': 1,
    'wed': 2,
    'thu': 3,
    'fri': 4,
    'sat': 5,
    'sun': 6,
}


def resolve_day(text, today):
    """
    Resolve a natural-language day string to a datetime.date.
    Returns (date, label_str) or (None, None) if no match.

    Recognises:
    - 'today', 'meetings', 'meetings today'
    - 'tomorrow'
    - 'monday' ... 'sunday' (nearest upcoming, today counts)
    - 'next monday' ... 'next sunday' (always the FOLLOWING Mon-Sun calendar week)
    - 'meetings friday', 'friday meetings', "what's on thursday"
    - 'this week' -> returns ('week', week_label)

    "next <day>" semantics: always the X of the following calendar week (Mon-Sun),
    never the X that is just 1 day away (e.g. "next tuesday" on a Monday jumps
    to the Tuesday of next week, not tomorrow).
    """
    text = text.strip().lower()
    text = text.replace("what's on ", '').replace("whats on ", '')
    text = text.replace('meetings ', '').replace(' meetings', '')
    text = text.strip()

    # this week
    if text == 'this week':
        return 'week', None

    # today / meetings
    if text in ('today', 'meetings', ''):
        return today, _date_label(today)

    # tomorrow
    if text == 'tomorrow':
        d = today + datetime.timedelta(days=1)
        return d, _date_label(d)

    # 'next <day>': jump to the following Mon-Sun calendar week, then find the
    # target weekday within that week.
    if text.startswith('next '):
        day_word = text[5:].strip()
        if day_word in DAY_NAMES:
            target_weekday = DAY_NAMES[day_word]
            # Compute days until next Monday; if today is Monday, that is 7 days
            # (not 0) so we always land in the *following* week.
            days_until_next_monday = (7 - today.weekday()) % 7 or 7
            next_monday = today + datetime.timedelta(days=days_until_next_monday)
            days_ahead = (target_weekday - next_monday.weekday()) % 7
            d = next_monday + datetime.timedelta(days=days_ahead)
            return d, _date_label(d)

    # plain day name: nearest upcoming occurrence (today counts as 0 days ahead)
    if text in DAY_NAMES:
        target_weekday = DAY_NAMES[text]
        days_ahead = target_weekday - today.weekday()
        if days_ahead < 0:  # day already passed this week
            days_ahead += 7
        # today counts (days_ahead == 0 is valid)
        d = today + datetime.timedelta(days=days_ahead)
        return d, _date_label(d)

    return None, None


def _date_label(d):
    return d.strftime('%A, %b %-d')


def format_events_for_day(events, date_label):
    """
    Format a list of event dicts (from get_events_for_date) into a WhatsApp message.
    """
    if not events:
        return f'Nothing scheduled for {date_label}. Free day.'

    lines = [f'Your meetings on {date_label}:']
    for ev in events:
        lines.append(f'\u2022 {ev["start_str"]} \u2014 {ev["summary"]}')
    count = len(events)
    noun = 'meeting' if count == 1 else 'meetings'
    lines.append(f'{count} {noun}')
    return '\n'.join(lines)


def format_week_view(week_events, week_start, week_end):
    """
    Format a condensed week view. Weeks run Mon-Sun.
    week_events: dict of date -> list of event dicts
    """
    start_label = week_start.strftime('%b %-d')
    end_label = week_end.strftime('%b %-d')
    lines = [f'This week (Mon {start_label} \u2013 Sun {end_label}):']

    current = week_start
    while current <= week_end:
        day_name = current.strftime('%a')
        evs = week_events.get(current, [])
        if not evs:
            lines.append(f'{day_name}: Free')
        else:
            parts = []
            for ev in evs:
                parts.append(f'{ev["start_str"]} {ev["summary"]}')
            lines.append(f'{day_name}: {chr(44).join(parts)}')
        current += datetime.timedelta(days=1)

    return '\n'.join(lines)
